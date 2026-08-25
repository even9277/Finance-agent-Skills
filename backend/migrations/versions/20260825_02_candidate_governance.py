"""扩展长期记忆候选治理统计与用户证据引用。

Revision ID: 20260825_02
Revises: 20260824_01
Create Date: 2026-08-25
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20260825_02"
down_revision: str | None = "20260824_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """仅新增候选统计列和规范化证据表，不改写既有记忆内容。"""
    with op.batch_alter_table("memory_candidates") as batch:
        batch.add_column(
            sa.Column("normalized_key", sa.String(180), server_default="", nullable=False)
        )
        batch.add_column(sa.Column("decision_reason", sa.String(64)))
        batch.add_column(sa.Column("promotion_score", sa.Float()))
        batch.add_column(
            sa.Column("event_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch.add_column(
            sa.Column("unique_query_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch.add_column(
            sa.Column("unique_session_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch.add_column(
            sa.Column("active_days", sa.Integer(), server_default="0", nullable=False)
        )
        batch.add_column(
            sa.Column("contradiction_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch.add_column(sa.Column("first_seen_at", sa.DateTime()))
        batch.add_column(sa.Column("last_seen_at", sa.DateTime()))
        batch.add_column(
            sa.Column("prompt_version", sa.String(64), server_default="", nullable=False)
        )
        batch.add_column(
            sa.Column("source_summary_version", sa.Integer(), server_default="0", nullable=False)
        )
        batch.add_column(
            sa.Column("source_state_version", sa.Integer(), server_default="0", nullable=False)
        )
    op.create_index(
        "ix_memory_candidates_user_fingerprint",
        "memory_candidates",
        ["user_id", "kind", "category", "fingerprint"],
    )
    op.create_table(
        "memory_candidate_evidence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("state_event_id", sa.Integer()),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("observed_on", sa.DateTime(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("summary_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id", "user_id"],
            ["memory_candidates.id", "memory_candidates.user_id"],
            name="fk_memory_candidate_evidence_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["state_event_id"], ["memory_state_events.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id",
            "message_id",
            "state_event_id",
            name="uq_memory_candidate_evidence_source",
        ),
    )
    for column in ("candidate_id", "user_id", "session_id", "message_id"):
        op.create_index(
            f"ix_memory_candidate_evidence_{column}",
            "memory_candidate_evidence",
            [column],
        )


def downgrade() -> None:
    """仅在隔离数据库显式授权后撤销 M5 扩展。"""
    config_allowed = bool(
        context.config.attributes.get("allow_isolated_memory_downgrade", False)
    )
    cli_allowed = os.getenv("ALLOW_ISOLATED_MEMORY_DOWNGRADE", "").strip().lower() in {
        "1",
        "true",
    }
    if not (config_allowed or cli_allowed):
        raise RuntimeError(
            "memory downgrade requires explicit isolated-database confirmation"
        )
    op.drop_table("memory_candidate_evidence")
    op.drop_index("ix_memory_candidates_user_fingerprint", table_name="memory_candidates")
    with op.batch_alter_table("memory_candidates") as batch:
        for column in (
            "source_state_version",
            "source_summary_version",
            "prompt_version",
            "last_seen_at",
            "first_seen_at",
            "contradiction_count",
            "active_days",
            "unique_session_count",
            "unique_query_count",
            "event_count",
            "promotion_score",
            "decision_reason",
            "normalized_key",
        ):
            batch.drop_column(column)
