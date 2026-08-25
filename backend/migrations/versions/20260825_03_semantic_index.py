"""建立可重建的 pgvector 派生索引表。"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from pgvector.sqlalchemy import Vector

revision: str = "20260825_03"
down_revision: str | None = "20260825_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    """新增派生索引和向量维度约束，不改变任何权威记忆记录。"""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    embedding_type = Vector(_EMBEDDING_DIMENSIONS) if is_postgres else sa.JSON()
    op.create_table(
        "memory_semantic_index",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("memory_record_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("provider_record_id", sa.String(160), nullable=False),
        sa.Column("memory_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", embedding_type, nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_memory_semantic_index_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["memory_record_id", "user_id"],
            ["memory_records.id", "memory_records.user_id"],
            name="fk_memory_semantic_index_record_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "memory_record_id",
            "provider",
            "memory_version",
            name="uq_memory_semantic_index_record_version",
        ),
    )
    for column in ("user_id", "memory_record_id", "status", "category"):
        op.create_index(
            f"ix_memory_semantic_index_{column}", "memory_semantic_index", [column]
        )
    if is_postgres:
        op.execute(
            "CREATE INDEX ix_memory_semantic_index_embedding_hnsw "
            "ON memory_semantic_index USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    """仅允许在显式授权的隔离数据库中删除派生索引表。"""
    config_allowed = bool(
        context.config.attributes.get("allow_isolated_memory_downgrade", False)
    )
    cli_allowed = os.getenv("ALLOW_ISOLATED_MEMORY_DOWNGRADE", "").strip().lower() in {
        "1",
        "true",
    }
    if not (config_allowed or cli_allowed):
        raise RuntimeError("semantic index downgrade requires isolated-database confirmation")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_memory_semantic_index_embedding_hnsw", table_name="memory_semantic_index")
    for column in ("category", "status", "memory_record_id", "user_id"):
        op.drop_index(f"ix_memory_semantic_index_{column}", table_name="memory_semantic_index")
    op.drop_table("memory_semantic_index")
