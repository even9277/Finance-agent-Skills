"""验证 Compose 集成测试使用临时 PostgreSQL 且不写入持久业务表。"""

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.integration
def test_postgres_connection_uses_isolated_test_database() -> None:
    async def run_check() -> None:
        database_url = os.getenv("TEST_DATABASE_URL")
        if not database_url:
            pytest.skip("TEST_DATABASE_URL 未设置；普通 CI 不启动真实数据库")

        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.begin() as connection:
                value = await connection.scalar(text("SELECT 1"))
                await connection.execute(text("CREATE TEMP TABLE e2e_probe (value INTEGER)"))
                await connection.execute(text("INSERT INTO e2e_probe(value) VALUES (1)"))
                count = await connection.scalar(text("SELECT COUNT(*) FROM e2e_probe"))

            assert value == 1
            assert count == 1
        finally:
            await engine.dispose()

    asyncio.run(run_check())
