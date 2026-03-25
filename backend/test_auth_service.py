import os
import tempfile
import unittest

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.db.database import Base
from backend.db.models import AuthAccount, Report, Session, User, UserInvestProfile
from backend.middleware.auth import AuthContext, ensure_user_access
from backend.services.auth_service import (
    AuthError,
    SEEDED_ACCOUNTS,
    authenticate_user,
    create_access_token,
    decode_access_token,
    ensure_seed_accounts,
    register_user,
)


class AuthServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.temp_db.name}")
        self.SessionFactory = async_sessionmaker(self.engine, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with self.SessionFactory() as session:
            await ensure_seed_accounts(session)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)

    async def test_seeded_accounts_exist_and_passwords_are_hashed(self):
        async with self.SessionFactory() as session:
            result = await session.execute(
                select(AuthAccount).where(AuthAccount.username.in_(["test1", "test2"]))
            )
            accounts = {account.username: account for account in result.scalars().all()}

        self.assertEqual(set(accounts.keys()), {"test1", "test2"})
        for username, account in accounts.items():
            self.assertNotEqual(account.password_hash, username)
            self.assertEqual(account.user_id, SEEDED_ACCOUNTS[username]["user_id"])

    async def test_test1_can_authenticate_and_issue_token(self):
        async with self.SessionFactory() as session:
            account, user = await authenticate_user(session, "test1", "test1")

        token = create_access_token(
            account_id=account.id,
            username=account.username,
            user_id=account.user_id,
        )
        payload = decode_access_token(token)

        self.assertEqual(account.username, "test1")
        self.assertEqual(user.id, SEEDED_ACCOUNTS["test1"]["user_id"])
        self.assertEqual(payload["username"], "test1")
        self.assertEqual(payload["user_id"], SEEDED_ACCOUNTS["test1"]["user_id"])

    async def test_test2_can_authenticate_and_issue_token(self):
        async with self.SessionFactory() as session:
            account, user = await authenticate_user(session, "test2", "test2")

        token = create_access_token(
            account_id=account.id,
            username=account.username,
            user_id=account.user_id,
        )
        payload = decode_access_token(token)

        self.assertEqual(account.username, "test2")
        self.assertEqual(user.id, SEEDED_ACCOUNTS["test2"]["user_id"])
        self.assertEqual(payload["username"], "test2")
        self.assertEqual(payload["user_id"], SEEDED_ACCOUNTS["test2"]["user_id"])

    async def test_seed_prefers_legacy_user_with_existing_data(self):
        legacy_user_id = "12e268ca-1d23-465e-b152-61af13afa7e3"
        async with self.SessionFactory() as session:
            legacy_user = User(id=legacy_user_id, display_name="test1", cold_start_done=True)
            session.add(legacy_user)
            session.add(Session(id="s-legacy", user_id=legacy_user_id, mode="chat", title="legacy"))
            session.add(
                Report(
                    id="r-legacy",
                    user_id=legacy_user_id,
                    task_id="task-legacy",
                    stock_code="600519.SH",
                    company_name="贵州茅台",
                    status="completed",
                    progress=100,
                    content="legacy report",
                )
            )
            session.add(
                UserInvestProfile(
                    id="p-legacy",
                    user_id=legacy_user_id,
                    risk_level="aggressive",
                    response_pref="risk_first",
                    updated_by="user",
                )
            )
            await session.commit()
            await ensure_seed_accounts(session)

        async with self.SessionFactory() as session:
            account = (
                await session.execute(select(AuthAccount).where(AuthAccount.username == "test1"))
            ).scalar_one()

        self.assertEqual(account.user_id, legacy_user_id)

    async def test_register_user_creates_new_account_and_user(self):
        async with self.SessionFactory() as session:
            account, user = await register_user(
                session,
                username="new_user_01",
                password="secret123",
                display_name="New User",
            )

        self.assertEqual(account.username, "new_user_01")
        self.assertEqual(account.user_id, user.id)
        self.assertEqual(user.display_name, "New User")
        self.assertFalse(user.cold_start_done)
        self.assertNotEqual(account.password_hash, "secret123")

    async def test_register_user_rejects_duplicate_username(self):
        async with self.SessionFactory() as session:
            with self.assertRaises(AuthError):
                await register_user(
                    session,
                    username="test1",
                    password="secret123",
                    display_name="Dup User",
                )

    def test_ensure_user_access_blocks_cross_user_access(self):
        auth = AuthContext(account_id="a1", username="test1", user_id=SEEDED_ACCOUNTS["test1"]["user_id"])
        with self.assertRaises(HTTPException) as ctx:
            ensure_user_access(SEEDED_ACCOUNTS["test2"]["user_id"], auth)
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
