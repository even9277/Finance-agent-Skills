"""为应用启动和隔离测试提供同一 Alembic 配置入口。"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _PROJECT_ROOT / "alembic.ini"


def build_alembic_config(database_url: str) -> Config:
    """构造不输出凭证的 Alembic 配置。

    Args:
        database_url: SQLAlchemy 异步数据库 URL，仅传给迁移 Engine。

    Returns:
        指向仓库迁移目录的 Alembic 配置。
    """
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("script_location", str(_PROJECT_ROOT / "backend" / "migrations"))
    # ConfigParser 会解释百分号；双写只用于配置传递，不改变真实连接串。
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_database(database_url: str, revision: str = "head") -> None:
    """把数据库升级到指定 revision，不记录连接串或业务数据。"""
    command.upgrade(build_alembic_config(database_url), revision)


def downgrade_database(
    database_url: str,
    revision: str = "base",
    *,
    allow_isolated: bool = False,
) -> None:
    """仅在调用方显式确认后降级隔离开发/测试数据库。

    Args:
        database_url: 已由调用方确认的隔离数据库 URL。
        revision: 目标 revision；M2 验收默认回到 base。
        allow_isolated: 必须显式为 ``True``，防止误用默认调用。

    Raises:
        ValueError: 调用方没有声明目标是可销毁的隔离数据库。
    """
    if not allow_isolated:
        raise ValueError("downgrade requires explicit isolated-database confirmation")
    config = build_alembic_config(database_url)
    # Revision 自身也检查此属性，使所有程序化入口共享同一个降级保护边界。
    config.attributes["allow_isolated_memory_downgrade"] = True
    command.downgrade(config, revision)
