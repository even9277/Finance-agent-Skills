"""账号登录、JWT、预置测试账号相关服务。"""

from __future__ import annotations

import logging
import secrets
import uuid
import re
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac

import jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import AuthAccount, Report, Session, User, UserInvestProfile

logger = logging.getLogger("auth_service")

_SEED_NAMESPACE = uuid.UUID("3b6f7d1e-7c5d-4f68-a7d8-3c6bbd635b8e")
SEEDED_ACCOUNTS = {
    "test1": {
        "password": "test1",
        "user_id": str(uuid.uuid5(_SEED_NAMESPACE, "finance-auth-user:test1")),
        "display_name": "test1",
    },
    "test2": {
        "password": "test2",
        "user_id": str(uuid.uuid5(_SEED_NAMESPACE, "finance-auth-user:test2")),
        "display_name": "test2",
    },
}


class AuthError(Exception):
    """鉴权领域异常。"""


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{2,31}$")


def normalize_username(username: str) -> str:
    normalized = username.strip()
    if not normalized:
        raise AuthError("用户名不能为空")
    if not _USERNAME_RE.fullmatch(normalized):
        raise AuthError("用户名仅支持 3-32 位字母、数字、下划线或短横线")
    return normalized


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return "pbkdf2_sha256$200000${}${}".format(
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, rounds, salt_b64, digest_b64 = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(rounds),
        )
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def create_access_token(*, account_id: str, username: str, user_id: str) -> str:
    expire_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": account_id,
        "user_id": user_id,
        "username": username,
        "exp": expire_at,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise AuthError("登录状态无效或已过期") from exc

    if not payload.get("sub") or not payload.get("user_id") or not payload.get("username"):
        raise AuthError("登录状态缺少必要字段")
    return payload


async def _user_data_score(db: AsyncSession, user_id: str) -> tuple[int, int, int, int]:
    session_count = (
        await db.execute(select(func.count()).select_from(Session).where(Session.user_id == user_id))
    ).scalar_one()
    report_count = (
        await db.execute(select(func.count()).select_from(Report).where(Report.user_id == user_id))
    ).scalar_one()
    has_profile = (
        await db.execute(
            select(func.count()).select_from(UserInvestProfile).where(UserInvestProfile.user_id == user_id)
        )
    ).scalar_one()
    total = int(session_count or 0) + int(report_count or 0) + (1 if has_profile else 0)
    return total, int(report_count or 0), int(session_count or 0), 1 if has_profile else 0


async def _choose_seed_user(db: AsyncSession, username: str, stable_user_id: str) -> tuple[User | None, str]:
    result = await db.execute(
        select(User).where((User.id == stable_user_id) | (User.display_name == username))
    )
    candidates = result.scalars().all()
    if not candidates:
        return None, stable_user_id

    ranked: list[tuple[tuple[int, int, int, int, int], User]] = []
    for user in candidates:
        bound_account = (
            await db.execute(select(AuthAccount).where(AuthAccount.user_id == user.id))
        ).scalar_one_or_none()
        if bound_account is not None and bound_account.username != username:
            continue
        total, report_count, session_count, has_profile = await _user_data_score(db, user.id)
        # 排序目标：
        # 1. 优先保留已有业务数据的老 user_id
        # 2. 其次优先报告/会话更多的 user_id
        # 3. 再其次优先已有画像
        # 4. 若完全无数据，则优先稳定 UUID，避免无谓漂移
        sort_key = (
            1 if total > 0 else 0,
            report_count,
            session_count,
            has_profile,
            1 if user.id != stable_user_id else 0,
        )
        ranked.append((sort_key, user))

    if not ranked:
        return None, stable_user_id
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1], ranked[0][1].id


async def ensure_seed_accounts(db: AsyncSession) -> None:
    """
    幂等确保 test1/test2 存在。
    - 若 user 不存在则创建
    - 若 account 不存在则创建
    - 若 account 存在但密码哈希异常则修复
    - 若 account 绑定 user_id 错误，仅记录 warning，不 silent 覆盖
    """
    for username, cfg in SEEDED_ACCOUNTS.items():
        stable_user_id = cfg["user_id"]
        chosen_user, chosen_user_id = await _choose_seed_user(db, username, stable_user_id)
        user = chosen_user
        if user is None:
            user = User(
                id=stable_user_id,
                display_name=cfg["display_name"],
                cold_start_done=False,
            )
            db.add(user)
            chosen_user_id = stable_user_id

        account_result = await db.execute(select(AuthAccount).where(AuthAccount.username == username))
        account = account_result.scalar_one_or_none()

        if account is None:
            db.add(
                AuthAccount(
                    username=username,
                    password_hash=hash_password(cfg["password"]),
                    user_id=chosen_user_id,
                    is_active=True,
                )
            )
            continue

        updated = False
        if account.user_id != chosen_user_id:
            logger.info(
                "[auth] seeded account %s 重新绑定到 user_id=%s（原=%s），以继承已有历史数据",
                username,
                chosen_user_id,
                account.user_id,
            )
            account.user_id = chosen_user_id
            updated = True
        if not verify_password(cfg["password"], account.password_hash):
            account.password_hash = hash_password(cfg["password"])
            updated = True
        if not account.is_active:
            account.is_active = True
            updated = True
        if updated:
            account.updated_at = datetime.utcnow()

    await db.commit()


async def register_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    display_name: str | None = None,
) -> tuple[AuthAccount, User]:
    username = normalize_username(username)
    password = password.strip()
    if len(password) < 6:
        raise AuthError("密码长度至少需要 6 位")

    existing = (
        await db.execute(select(AuthAccount).where(AuthAccount.username == username))
    ).scalar_one_or_none()
    if existing is not None:
        raise AuthError("用户名已存在，请更换后重试")

    user = User(
        id=str(uuid.uuid4()),
        display_name=(display_name or username).strip() or username,
        cold_start_done=False,
    )
    db.add(user)
    await db.flush()

    account = AuthAccount(
        username=username,
        password_hash=hash_password(password),
        user_id=user.id,
        is_active=True,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    await db.refresh(user)

    logger.info("[auth] 新账号注册成功: username=%s user_id=%s", username, user.id)
    return account, user


async def authenticate_user(db: AsyncSession, username: str, password: str) -> tuple[AuthAccount, User]:
    username = normalize_username(username)
    result = await db.execute(select(AuthAccount).where(AuthAccount.username == username))
    account = result.scalar_one_or_none()
    if account is None or not account.is_active:
        raise AuthError("用户名或密码错误")
    if not verify_password(password, account.password_hash):
        raise AuthError("用户名或密码错误")

    user_result = await db.execute(select(User).where(User.id == account.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise AuthError("账号绑定的用户不存在")

    account.last_login_at = datetime.utcnow()
    await db.commit()
    await db.refresh(account)
    return account, user


async def get_account_and_user_by_payload(db: AsyncSession, payload: dict) -> tuple[AuthAccount, User]:
    account_result = await db.execute(select(AuthAccount).where(AuthAccount.id == payload["sub"]))
    account = account_result.scalar_one_or_none()
    if account is None or not account.is_active:
        raise AuthError("账号不存在或已禁用")

    if account.username != payload["username"] or account.user_id != payload["user_id"]:
        raise AuthError("登录状态与账号信息不一致")

    user_result = await db.execute(select(User).where(User.id == account.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise AuthError("账号绑定的用户不存在")
    return account, user
