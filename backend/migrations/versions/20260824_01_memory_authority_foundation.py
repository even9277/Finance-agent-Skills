"""新增记忆权威状态、治理记录和事务 Outbox 基础表。

Revision ID: 20260824_01
Revises: None
Create Date: 2026-08-24
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20260824_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """以只新增表的方式建立 memory-v1 权威持久化结构。"""
    op.create_table(
        "memory_working_states",
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active_entity", sa.JSON(), nullable=True),
        sa.Column("candidate_entities", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("constraints", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("reply_preference_hint", sa.String(220), server_default="", nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_table(
        "memory_state_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("field_name", sa.String(40), nullable=False),
        sa.Column("operation", sa.String(24), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="1", nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_state_events_session_id", "memory_state_events", ["session_id"])
    op.create_index("ix_memory_state_events_trace_id", "memory_state_events", ["trace_id"])
    op.create_table(
        "memory_summary_metadata",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("summary_id", sa.Integer(), nullable=True),
        sa.Column("summary_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("source_start_message_id", sa.Integer(), nullable=True),
        sa.Column("source_end_message_id", sa.Integer(), nullable=True),
        sa.Column("source_message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_token_estimate", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_token_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prompt_version", sa.String(64), server_default="", nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["summary_id"], ["session_summaries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "summary_version",
            name="uq_memory_summary_session_version",
        ),
    )
    op.create_index(
        "ix_memory_summary_metadata_session_id",
        "memory_summary_metadata",
        ["session_id"],
    )
    op.create_index(
        "ix_memory_summary_metadata_status",
        "memory_summary_metadata",
        ["status"],
    )
    op.create_table(
        "memory_records",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("profile_field", sa.String(40), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("evidence_ref", sa.String(255), nullable=True),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("activation_source", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_memory_record_id_user"),
    )
    for column in ("user_id", "category", "status", "expires_at"):
        op.create_index(f"ix_memory_records_{column}", "memory_records", [column])
    op.create_table(
        "memory_candidates",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("profile_field", sa.String(40), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_ref", sa.String(255), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("conflict_group_id", sa.String(64), nullable=True),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_memory_candidate_id_user"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_memory_candidate_user_idempotency",
        ),
    )
    for column in (
        "user_id",
        "category",
        "status",
        "fingerprint",
        "conflict_group_id",
        "expires_at",
    ):
        op.create_index(f"ix_memory_candidates_{column}", "memory_candidates", [column])
    op.create_table(
        "memory_audit_events",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("record_id", sa.String(64), nullable=True),
        sa.Column("candidate_id", sa.String(64), nullable=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("actor", sa.String(32), nullable=False),
        sa.Column("before_status", sa.String(32), nullable=True),
        sa.Column("after_status", sa.String(32), nullable=True),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id", "user_id"],
            ["memory_candidates.id", "memory_candidates.user_id"],
            name="fk_memory_audit_candidate_owner",
        ),
        sa.ForeignKeyConstraint(
            ["record_id", "user_id"],
            ["memory_records.id", "memory_records.user_id"],
            name="fk_memory_audit_record_owner",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "record_id", "candidate_id", "trace_id"):
        op.create_index(f"ix_memory_audit_events_{column}", "memory_audit_events", [column])
    op.create_table(
        "memory_outbox_tasks",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=True),
        sa.Column("aggregate_type", sa.String(40), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("task_kind", sa.String(40), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_memory_outbox_user_idempotency",
        ),
    )
    for column in ("user_id", "session_id", "task_kind", "status", "trace_id"):
        op.create_index(f"ix_memory_outbox_tasks_{column}", "memory_outbox_tasks", [column])
    op.create_table(
        "memory_provider_references",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("memory_record_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("provider_record_id", sa.String(160), nullable=False),
        sa.Column("memory_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_record_id", "user_id"],
            ["memory_records.id", "memory_records.user_id"],
            name="fk_memory_provider_record_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "provider_record_id",
            name="uq_memory_provider_user_record",
        ),
    )
    for column in ("user_id", "memory_record_id", "status"):
        op.create_index(
            f"ix_memory_provider_references_{column}",
            "memory_provider_references",
            [column],
        )


def downgrade() -> None:
    """仅在显式确认隔离目标后移除本 revision 新增的表。

    Raises:
        RuntimeError: 程序化调用或直接 CLI 均未声明目标数据库可销毁。
    """
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

    for table_name in (
        "memory_provider_references",
        "memory_outbox_tasks",
        "memory_audit_events",
        "memory_candidates",
        "memory_records",
        "memory_summary_metadata",
        "memory_state_events",
        "memory_working_states",
    ):
        op.drop_table(table_name)
