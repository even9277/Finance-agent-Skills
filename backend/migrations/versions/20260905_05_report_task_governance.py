"""新增报告任务幂等与持久快照治理表。

Revision ID: 20260905_05
Revises: 20260825_04
Create Date: 2026-09-05
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20260905_05"
down_revision: str | None = "20260825_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建立用户作用域唯一、支持原子换代的报告任务治理表。"""
    op.create_table(
        "report_task_governance",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("key_digest", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("stage_states", sa.JSON(), server_default="[]", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "key_digest",
            name="uq_report_task_governance_user_key",
        ),
    )
    for column in ("user_id", "task_id", "report_id", "expires_at"):
        op.create_index(
            f"ix_report_task_governance_{column}",
            "report_task_governance",
            [column],
        )


def downgrade() -> None:
    """仅在显式确认的隔离数据库中回滚报告任务治理表。"""
    config_allowed = bool(context.config.attributes.get("allow_isolated_memory_downgrade", False))
    cli_allowed = os.getenv("ALLOW_ISOLATED_MEMORY_DOWNGRADE", "").strip().lower() in {
        "1",
        "true",
    }
    if not (config_allowed or cli_allowed):
        raise RuntimeError("report governance downgrade requires isolated-database confirmation")
    for column in ("user_id", "task_id", "report_id", "expires_at"):
        op.drop_index(
            f"ix_report_task_governance_{column}",
            table_name="report_task_governance",
        )
    op.drop_table("report_task_governance")
