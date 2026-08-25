"""新增受控记忆命令的一次性确认状态表。

Revision ID: 20260825_04
Revises: 20260825_03
Create Date: 2026-08-25
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20260825_04"
down_revision: str | None = "20260825_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建立绑定用户/会话、范围快照、版本和 TTL 的 pending 命令表。"""
    op.create_table(
        "memory_pending_commands",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("command_kind", sa.String(24), nullable=False),
        sa.Column("normalized_scope", sa.JSON(), nullable=False),
        sa.Column("target_record_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("target_versions", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("preview_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("preview_items", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(24), server_default="PENDING", nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "fingerprint", name="uq_memory_pending_user_fingerprint"),
    )
    for column in ("user_id", "session_id", "expires_at", "status"):
        op.create_index(
            f"ix_memory_pending_commands_{column}",
            "memory_pending_commands",
            [column],
        )


def downgrade() -> None:
    """仅在显式确认的隔离数据库中回滚 pending 命令表。"""
    config_allowed = bool(context.config.attributes.get("allow_isolated_memory_downgrade", False))
    cli_allowed = os.getenv("ALLOW_ISOLATED_MEMORY_DOWNGRADE", "").strip().lower() in {"1", "true"}
    if not (config_allowed or cli_allowed):
        raise RuntimeError("memory pending-command downgrade requires isolated-database confirmation")
    for column in ("user_id", "session_id", "expires_at", "status"):
        op.drop_index(f"ix_memory_pending_commands_{column}", table_name="memory_pending_commands")
    op.drop_table("memory_pending_commands")
