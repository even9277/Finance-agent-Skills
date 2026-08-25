"""解析并执行受控自然语言记忆命令。

本模块是聊天入口前置的应用层边界：解析器只识别明确中文句式，写入和删除全部
委托 PostgreSQL authority；Redis、向量索引和 Mem0 只通过既有 outbox 作为派生层。
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import MemoryPendingCommandRow, MemoryRecordRow
from backend.infrastructure.memory.authority_repository import SqlAlchemyAuthoritativeMemoryRepository
from src.memory.contracts import MemoryCommandAction, MemoryRecordStatus, MemorySource, ProfileField

PARSER_VERSION = "memory-command-v1"
CONFIRMATION_TTL_SECONDS = 600
MAX_PREVIEW_ITEMS = 5
logger = logging.getLogger(__name__)


class MemoryCommandKind(StrEnum):
    """聊天入口可执行的记忆动作。"""

    INSPECT = MemoryCommandAction.INSPECT.value
    UPDATE = MemoryCommandAction.UPDATE.value
    DELETE = MemoryCommandAction.DELETE.value
    FORGET = MemoryCommandAction.FORGET.value
    CONFIRM = MemoryCommandAction.CONFIRM.value
    CANCEL = MemoryCommandAction.CANCEL.value


class MemoryCommandStatus(StrEnum):
    """记忆命令对用户公开的稳定状态。"""

    PENDING = "PENDING"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class MemoryCommandScope:
    """冻结一条命令的规范化目标范围，不含原始用户文本。"""

    category: str | None = None
    profile_field: str | None = None
    record_id: str | None = None
    value: str | float | tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class MemoryCommandIntent:
    """解析后的命令意图，供应用层执行且可离线测试。"""

    kind: MemoryCommandKind
    user_id: str
    session_id: str
    scope: MemoryCommandScope = field(default_factory=MemoryCommandScope)
    requires_confirmation: bool = False
    parser_version: str = PARSER_VERSION
    fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class MemoryCommandResult:
    """REST、WebSocket 和前端共用的安全结果合同。"""

    status: MemoryCommandStatus
    command_kind: MemoryCommandKind | None = None
    command_ref: str | None = None
    affected_count: int = 0
    affected_record_ids: tuple[str, ...] = ()
    consistency_status: str = "CONSISTENT"
    pending_confirmation_id: str | None = None
    error_code: str | None = None
    user_message: str = ""
    preview_items: tuple[dict[str, object], ...] = ()


def parse_memory_command(
    message: str,
    *,
    user_id: str,
    session_id: str,
) -> MemoryCommandIntent | None:
    """以确定性规则解析明确中文记忆命令。

    Args:
        message: 用户原始消息；不会写入日志或持久化命令状态。
        user_id: 已认证用户标识。
        session_id: 当前已准备好的会话标识。

    Returns:
        明确命令的规范化意图；普通金融问题返回 ``None``。
    """
    text = re.sub(r"\s+", "", message.strip())
    if not text:
        return None
    kind: MemoryCommandKind | None = None
    scope = MemoryCommandScope()
    requires_confirmation = False
    if re.fullmatch(r"(查看|查询|检查)(我的)?记忆", text):
        kind = MemoryCommandKind.INSPECT
    elif re.fullmatch(r"(确认|确认删除|确认执行)(这个)?", text):
        kind = MemoryCommandKind.CONFIRM
    elif re.fullmatch(r"(取消|取消删除|不要删除)(这个)?", text):
        kind = MemoryCommandKind.CANCEL
    elif re.fullmatch(r"忘掉(我的)?文本记忆", text):
        kind = MemoryCommandKind.FORGET
        scope = MemoryCommandScope(category="text")
        requires_confirmation = True
    elif re.fullmatch(r"删除记忆[:：]?[A-Za-z0-9_-]{1,64}", text):
        kind = MemoryCommandKind.DELETE
        scope = MemoryCommandScope(record_id=re.split(r"[:：]", text, maxsplit=1)[-1])
    elif re.fullmatch(r"(以后)?回答(尽量)?简短(一点|些)?", text):
        kind = MemoryCommandKind.UPDATE
        scope = MemoryCommandScope(profile_field=ProfileField.RESPONSE_PREF.value, value="concise")
    elif re.fullmatch(r"(以后)?回答(尽量)?详细(一点|些)?", text):
        kind = MemoryCommandKind.UPDATE
        scope = MemoryCommandScope(profile_field=ProfileField.RESPONSE_PREF.value, value="detailed")
    else:
        return None
    fingerprint = hashlib.sha256(
        f"{PARSER_VERSION}|{user_id}|{session_id}|{kind.value}|{scope}".encode("utf-8")
    ).hexdigest()
    return MemoryCommandIntent(
        kind=kind,
        user_id=user_id,
        session_id=session_id,
        scope=scope,
        requires_confirmation=requires_confirmation,
        fingerprint=fingerprint,
    )


class MemoryCommandUseCase:
    """在聊天事务中执行命令并维护 pending confirmation 生命周期。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._authority = SqlAlchemyAuthoritativeMemoryRepository(db)

    async def execute(
        self,
        intent: MemoryCommandIntent,
        *,
        trace_id: str | None = None,
    ) -> MemoryCommandResult:
        """执行单条已解析命令；调用方负责最终 commit/rollback。"""
        logger.info(
            "memory.command stage=%s status=%s command_kind=%s",
            "memory.command.preflight",
            "STARTED",
            intent.kind.value,
        )
        if intent.kind is MemoryCommandKind.INSPECT:
            result = await self._inspect(intent)
        elif intent.kind is MemoryCommandKind.UPDATE:
            result = await self._update(intent, trace_id=trace_id)
        elif intent.kind is MemoryCommandKind.DELETE:
            result = await self._delete(intent, trace_id=trace_id)
        elif intent.kind is MemoryCommandKind.FORGET:
            result = await self._prepare_forget(intent)
        elif intent.kind is MemoryCommandKind.CONFIRM:
            result = await self._confirm(intent, trace_id=trace_id)
        else:
            result = await self._cancel(intent)
        logger.info(
            "memory.command stage=%s status=%s command_kind=%s affected_count=%s error_code=%s",
            "memory.command.execute",
            result.status.value,
            intent.kind.value,
            result.affected_count,
            result.error_code or "NONE",
        )
        return result

    async def _inspect(self, intent: MemoryCommandIntent) -> MemoryCommandResult:
        """只读取当前用户的权威有效记录并返回受限摘要。"""
        rows = list(
            (
                await self._db.execute(
                    select(MemoryRecordRow)
                    .where(
                        MemoryRecordRow.user_id == intent.user_id,
                        MemoryRecordRow.status == MemoryRecordStatus.ACTIVE.value,
                    )
                    .order_by(MemoryRecordRow.created_at.desc())
                    .limit(MAX_PREVIEW_ITEMS)
                )
            ).scalars()
        )
        return MemoryCommandResult(
            status=MemoryCommandStatus.SUCCEEDED,
            command_kind=intent.kind,
            command_ref=_command_ref(),
            affected_count=len(rows),
            affected_record_ids=tuple(row.id for row in rows),
            user_message=f"当前有 {len(rows)} 条可见记忆。",
            preview_items=tuple(_safe_preview(row) for row in rows),
        )

    async def _update(
        self,
        intent: MemoryCommandIntent,
        *,
        trace_id: str | None,
    ) -> MemoryCommandResult:
        """执行低影响显式画像更新，高影响字段不在此路径绕过确认。"""
        try:
            field = ProfileField(intent.scope.profile_field or "")
        except ValueError:
            return _rejected(intent, "INVALID_SCOPE", "无法识别要更新的记忆字段。")
        if field is not ProfileField.RESPONSE_PREF:
            return _rejected(intent, "CONFIRMATION_REQUIRED", "该画像字段需要先确认。")
        result = await self._authority.write_profile(
            user_id=intent.user_id,
            field=field,
            value=str(intent.scope.value or "balanced"),
            source=MemorySource.USER_COMMAND,
            evidence_ref=f"command:{intent.fingerprint[:16]}",
            trace_id=trace_id,
        )
        return MemoryCommandResult(
            status=MemoryCommandStatus.SUCCEEDED,
            command_kind=intent.kind,
            command_ref=_command_ref(),
            affected_count=1,
            affected_record_ids=(result.record_id,),
            consistency_status=result.consistency_status.value,
            user_message="已更新你的回答偏好。",
        )

    async def _delete(
        self,
        intent: MemoryCommandIntent,
        *,
        trace_id: str | None,
    ) -> MemoryCommandResult:
        """删除明确指定的当前用户记忆；不存在或越权时统一拒绝。"""
        record_id = intent.scope.record_id
        if not record_id:
            return _rejected(intent, "INVALID_SCOPE", "请提供明确的记忆编号。")
        result = await self._authority.delete_record(
            user_id=intent.user_id, record_id=record_id, trace_id=trace_id
        )
        if result is None:
            return _rejected(intent, "RECORD_NOT_FOUND", "没有找到属于你的有效记忆。")
        return MemoryCommandResult(
            status=MemoryCommandStatus.SUCCEEDED,
            command_kind=intent.kind,
            command_ref=_command_ref(),
            affected_count=1,
            affected_record_ids=(result.record_id,),
            consistency_status=result.consistency_status.value,
            user_message="已删除指定记忆，派生索引正在同步。",
        )

    async def _prepare_forget(self, intent: MemoryCommandIntent) -> MemoryCommandResult:
        """冻结文本记忆 ID/版本并创建 600 秒 pending confirmation。"""
        rows = list(
            (
                await self._db.execute(
                    select(MemoryRecordRow)
                    .where(
                        MemoryRecordRow.user_id == intent.user_id,
                        MemoryRecordRow.kind == "text",
                        MemoryRecordRow.status == MemoryRecordStatus.ACTIVE.value,
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        pending_id = uuid.uuid4().hex
        self._db.add(
            MemoryPendingCommandRow(
                id=pending_id,
                user_id=intent.user_id,
                session_id=intent.session_id,
                command_kind=intent.kind.value,
                normalized_scope={"category": "text"},
                target_record_ids=[row.id for row in rows],
                target_versions={row.id: int(row.version) for row in rows},
                fingerprint=intent.fingerprint,
                preview_count=len(rows),
                preview_items=[_safe_preview(row) for row in rows[:MAX_PREVIEW_ITEMS]],
                expires_at=_utc_now() + timedelta(seconds=CONFIRMATION_TTL_SECONDS),
                status="PENDING",
            )
        )
        return MemoryCommandResult(
            status=MemoryCommandStatus.CONFIRMATION_REQUIRED,
            command_kind=intent.kind,
            command_ref=pending_id,
            affected_count=len(rows),
            pending_confirmation_id=pending_id,
            user_message=f"将删除 {len(rows)} 条文本记忆，请回复“确认”继续。",
            preview_items=tuple(_safe_preview(row) for row in rows[:MAX_PREVIEW_ITEMS]),
        )

    async def _confirm(
        self,
        intent: MemoryCommandIntent,
        *,
        trace_id: str | None,
    ) -> MemoryCommandResult:
        """按当前用户/会话消费最新 pending，并检查 TTL 与冻结版本。"""
        pending = await self._latest_pending(intent)
        if pending is None:
            return _rejected(intent, "CONFIRMATION_NOT_FOUND", "没有找到当前会话可确认的操作。")
        now = _utc_now()
        if pending.expires_at <= now:
            pending.status = "EXPIRED"
            pending.consumed_at = now
            return _result_for_pending(pending, MemoryCommandStatus.EXPIRED, "确认已过期，请重新发起操作。")
        if pending.status != "PENDING":
            return _rejected(intent, "CONFIRMATION_REPLAYED", "该确认操作已经消费，不能重复执行。")
        affected: list[str] = []
        for record_id in list(pending.target_record_ids or []):
            expected = int((pending.target_versions or {}).get(record_id, 0))
            row = await self._db.scalar(
                select(MemoryRecordRow)
                .where(
                    MemoryRecordRow.id == record_id,
                    MemoryRecordRow.user_id == intent.user_id,
                    MemoryRecordRow.status == MemoryRecordStatus.ACTIVE.value,
                )
                .with_for_update()
            )
            if row is None or int(row.version) != expected:
                pending.status = "REJECTED"
                pending.consumed_at = now
                return _result_for_pending(
                    pending,
                    MemoryCommandStatus.REJECTED,
                    "记忆版本已变化，请重新预览。",
                    error_code="VERSION_CONFLICT",
                )
            result = await self._authority.delete_record(
                user_id=intent.user_id, record_id=record_id, trace_id=trace_id
            )
            if result is not None:
                affected.append(result.record_id)
        pending.status = "CONFIRMED"
        pending.consumed_at = now
        return _result_for_pending(
            pending,
            MemoryCommandStatus.SUCCEEDED,
            f"已删除 {len(affected)} 条文本记忆，派生索引正在同步。",
            affected_count=len(affected),
            affected_record_ids=tuple(affected),
        )

    async def _cancel(self, intent: MemoryCommandIntent) -> MemoryCommandResult:
        """取消当前会话最新 pending，不触碰权威记忆。"""
        pending = await self._latest_pending(intent)
        if pending is None:
            return _rejected(intent, "CONFIRMATION_NOT_FOUND", "没有找到当前会话可取消的操作。")
        if pending.status != "PENDING":
            return _rejected(intent, "CONFIRMATION_REPLAYED", "该操作已经结束。")
        pending.status = "CANCELLED"
        pending.consumed_at = _utc_now()
        return _result_for_pending(pending, MemoryCommandStatus.CANCELLED, "已取消本次记忆操作。")

    async def _latest_pending(self, intent: MemoryCommandIntent) -> MemoryPendingCommandRow | None:
        """只读取当前用户和当前会话的最新 pending，防止跨租户确认。"""
        return await self._db.scalar(
            select(MemoryPendingCommandRow)
            .where(
                MemoryPendingCommandRow.user_id == intent.user_id,
                MemoryPendingCommandRow.session_id == intent.session_id,
                MemoryPendingCommandRow.status == "PENDING",
            )
            .order_by(MemoryPendingCommandRow.created_at.desc())
            .with_for_update()
        )


def _command_ref() -> str:
    """返回不包含用户数据的短命令引用。"""
    return f"mcmd_{uuid.uuid4().hex[:16]}"


def _rejected(intent: MemoryCommandIntent, error_code: str, message: str) -> MemoryCommandResult:
    """构造统一拒绝结果。"""
    return MemoryCommandResult(
        status=MemoryCommandStatus.REJECTED,
        command_kind=intent.kind,
        command_ref=_command_ref(),
        error_code=error_code,
        user_message=message,
    )


def _result_for_pending(
    pending: MemoryPendingCommandRow,
    status: MemoryCommandStatus,
    message: str,
    *,
    error_code: str | None = None,
    affected_count: int | None = None,
    affected_record_ids: tuple[str, ...] = (),
) -> MemoryCommandResult:
    """把 pending 行映射为不暴露正文的结果。"""
    return MemoryCommandResult(
        status=status,
        command_kind=MemoryCommandKind(pending.command_kind),
        command_ref=pending.id,
        affected_count=pending.preview_count if affected_count is None else affected_count,
        affected_record_ids=affected_record_ids,
        pending_confirmation_id=pending.id,
        error_code=error_code,
        user_message=message,
        preview_items=tuple(pending.preview_items or []),
    )


def _safe_preview(row: MemoryRecordRow) -> dict[str, object]:
    """只返回类别、版本和截断片段；不写入日志或跨用户响应。"""
    content = (row.content or "").strip()
    return {
        "record_id": row.id,
        "category": row.category,
        "version": int(row.version),
        "snippet": content[:160],
    }


def _utc_now() -> datetime:
    """返回与现有无时区数据库列兼容的 UTC 时间。"""
    return datetime.now(UTC).replace(tzinfo=None)
