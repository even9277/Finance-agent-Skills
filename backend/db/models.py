"""
ORM 数据模型
所有 UUID 字段在 SQLite 中存为 String(36)，PostgreSQL 切换后改为 UUID 类型即可。
Phase 3 新增：UserInvestProfile、LtmWriteTask 表；Message 表新增 used_for_ltm 字段。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


# ─────────────────────────────────────────────────────────────
# 用户表
# ─────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    display_name: Mapped[str | None] = mapped_column(String(100))
    cold_start_done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    sessions: Mapped[list["Session"]] = relationship(back_populates="user")
    reports: Mapped[list["Report"]] = relationship(back_populates="user")
    auth_account: Mapped["AuthAccount | None"] = relationship(back_populates="user")


class AuthAccount(Base):
    __tablename__ = "auth_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped["User"] = relationship(back_populates="auth_account")


# ─────────────────────────────────────────────────────────────
# 会话表（对话模式 STM 审计 + 元数据）
# ─────────────────────────────────────────────────────────────
class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE")
    )
    mode: Mapped[str] = mapped_column(String(20), default="chat")  # 'report' | 'chat'
    title: Mapped[str | None] = mapped_column(String(200))         # 取首条消息前20字
    running_summary: Mapped[str | None] = mapped_column(Text)      # Phase 2 STM 压缩摘要
    turn_count: Mapped[int] = mapped_column(Integer, default=0)    # Phase 2 压缩阈值
    last_compress_at: Mapped[datetime | None] = mapped_column(DateTime)
    context_token_count: Mapped[int] = mapped_column(Integer, default=0)
    context_budget_tokens: Mapped[int] = mapped_column(Integer, default=0)
    summary_token_count: Mapped[int] = mapped_column(Integer, default=0)
    summary_version: Mapped[int] = mapped_column(Integer, default=0)
    compression_status: Mapped[str] = mapped_column(String(20), default="idle")
    context_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    user: Mapped["User"] = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", 
        order_by="Message.created_at",
        cascade="all, delete-orphan",  # 删除 Session 时级联删除 Message
        passive_deletes=True,          # 让 DB 的 ON DELETE CASCADE 生效，避免 ORM 尝试将 FK 置空
    )


# ─────────────────────────────────────────────────────────────
# 消息表（STM 原始审计层）
# 说明：在 SQLite 下必须使用 Integer PRIMARY KEY 才能可靠自增，
# 否则会出现 NOT NULL constraint failed: messages.id。
# ─────────────────────────────────────────────────────────────
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(20))  # 'user' | 'assistant' | 'system'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)       # Phase 2 token 估算
    is_compressed: Mapped[bool] = mapped_column(Boolean, default=False)  # Phase 2 压缩标记
    used_for_ltm: Mapped[bool] = mapped_column(Boolean, default=False)   # Phase 3 LTM 抽取标记
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    session: Mapped["Session"] = relationship(back_populates="messages")


# ─────────────────────────────────────────────────────────────
# 报告表
# ─────────────────────────────────────────────────────────────
class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="SET NULL")
    )
    task_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    stock_code: Mapped[str | None] = mapped_column(String(20))
    company_name: Mapped[str | None] = mapped_column(String(100))
    content: Mapped[str | None] = mapped_column(Text)        # Markdown 全文
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/running/completed/failed
    progress: Mapped[int] = mapped_column(Integer, default=0)           # 0-100
    error_msg: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped["User | None"] = relationship(back_populates="reports")


# ─────────────────────────────────────────────────────────────
# 持仓表（Phase 4 完整实现，Phase 1 只建表备用）
# ─────────────────────────────────────────────────────────────
class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE")
    )
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    stock_name: Mapped[str | None] = mapped_column(String(100))
    cost_price: Mapped[float | None] = mapped_column()
    quantity: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ─────────────────────────────────────────────────────────────
# 自选股表（Phase 4 行情同步，独立于 LTM watchlist）
# ─────────────────────────────────────────────────────────────
class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE")
    )
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    stock_name: Mapped[str | None] = mapped_column(String(100))
    added_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (UniqueConstraint("user_id", "stock_code"),)


# ─────────────────────────────────────────────────────────────
# 用户权威投资画像表（Phase 3）
# 前端卡片/滑块/标签的写入目标；报告和对话读取结构化画像的来源
# 与 Mem0 是"双轨"关系：此表为主数据，Mem0 为语义增强层
# ─────────────────────────────────────────────────────────────
class UserInvestProfile(Base):
    __tablename__ = "user_invest_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    # 风险偏好：conservative / moderate / balanced / aggressive / speculative / balanced_conservative
    risk_level: Mapped[str | None] = mapped_column(String(50))
    # 持有周期：ultra_short / short / swing / long
    investment_horizon: Mapped[str | None] = mapped_column(String(20))
    # 期望年化收益区间（%）
    expected_return_min: Mapped[float | None] = mapped_column(Float)
    expected_return_max: Mapped[float | None] = mapped_column(Float)
    # 关注板块列表（JSON 数组），如 ["消费/白酒","银行/金融"]
    sectors: Mapped[list | None] = mapped_column(JSON, default=list)
    # 约束列表（JSON 数组），如 ["不碰ST","不碰科创板"]
    constraints: Mapped[list | None] = mapped_column(JSON, default=list)
    # 回答偏好：concise / balanced / detailed / risk_first
    response_pref: Mapped[str] = mapped_column(String(20), default="balanced")
    # 最后更新来源：user / system / llm
    updated_by: Mapped[str] = mapped_column(String(20), default="system")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped["User"] = relationship()


# ─────────────────────────────────────────────────────────────
# LTM 异步写入 outbox 队列（Phase 3）
# 所有 Mem0 写操作通过此表中转，ltm_worker 后台异步执行，主链路不等待
# ─────────────────────────────────────────────────────────────
class LtmWriteTask(Base):
    __tablename__ = "ltm_write_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # task_type: add_conversation / explicit_update / explicit_delete / cold_start
    task_type: Mapped[str] = mapped_column(String(30))
    # 序列化的 MemoryService 调用参数（JSON）
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    # 状态：pending / processing / done / failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    # 失败时写入错误信息，不影响主进程
    error_msg: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)


# ─────────────────────────────────────────────────────────────
# 会话摘要历史表（Phase 2：查看摘要历史）
# 说明：running_summary 只有“当前摘要”，本表用于保留每次压缩后的摘要快照。
# ─────────────────────────────────────────────────────────────
class SessionSummary(Base):
    __tablename__ = "session_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    # 本次压缩统计（用于前端百分比进度展示）
    compressed_message_count: Mapped[int] = mapped_column(Integer, default=0)
    total_message_count: Mapped[int] = mapped_column(Integer, default=0)

    # Phase 2.1：更直观的压缩范围展示（用户/助手条数 + 时间轴）
    # 说明：为兼容历史数据与增量迁移，这些字段允许为空；新快照会写入完整信息
    compressed_user_count: Mapped[int | None] = mapped_column(Integer, default=0)
    compressed_assistant_count: Mapped[int | None] = mapped_column(Integer, default=0)
    start_message_id: Mapped[int | None] = mapped_column(Integer)
    end_message_id: Mapped[int | None] = mapped_column(Integer)
    start_created_at: Mapped[datetime | None] = mapped_column(DateTime)
    end_created_at: Mapped[datetime | None] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class StmCompactionTask(Base):
    __tablename__ = "stm_compaction_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    cutoff_message_id: Mapped[int | None] = mapped_column(Integer)
    summary_version_before: Mapped[int] = mapped_column(Integer, default=0)
    estimated_tokens_before: Mapped[int] = mapped_column(Integer, default=0)
    error_msg: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


# ------------------------------ 记忆权威存储 v1 ------------------------------
# 下列表由 Alembic 管理；应用启动的 legacy create_all 不直接创建它们。
ALEMBIC_MANAGED_TABLE_NAMES = frozenset(
    {
        "memory_working_states",
        "memory_state_events",
        "memory_summary_metadata",
        "memory_records",
        "memory_candidates",
        "memory_audit_events",
        "memory_outbox_tasks",
        "memory_provider_references",
    }
)


class MemoryWorkingStateRow(Base):
    """持久化每个会话唯一的版本化 Working State 快照。"""

    __tablename__ = "memory_working_states"

    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_entity: Mapped[dict[str, object] | None] = mapped_column(JSON)
    candidate_entities: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    constraints: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reply_preference_hint: Mapped[str] = mapped_column(String(220), nullable=False, default="")
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("messages.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_now,
        onupdate=_now,
        nullable=False,
    )


class MemoryStateEventRow(Base):
    """保存 Working State 的字段级审计事件。"""

    __tablename__ = "memory_state_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("messages.id", ondelete="SET NULL"),
    )
    field_name: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(24), nullable=False)
    old_value: Mapped[dict[str, object] | list[object] | str | None] = mapped_column(JSON)
    new_value: Mapped[dict[str, object] | list[object] | str | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class MemorySummaryMetadataRow(Base):
    """保存 Rolling Summary 的版本、来源边界和生成状态。"""

    __tablename__ = "memory_summary_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    summary_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("session_summaries.id", ondelete="SET NULL"),
    )
    summary_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    source_start_message_id: Mapped[int | None] = mapped_column(Integer)
    source_end_message_id: Mapped[int | None] = mapped_column(Integer)
    source_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "summary_version",
            name="uq_memory_summary_session_version",
        ),
    )


class MemoryRecordRow(Base):
    """保存用户可检查、可版本化和可删除的权威长期记忆。"""

    __tablename__ = "memory_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_field: Mapped[str | None] = mapped_column(String(40))
    value_json: Mapped[str | float | list[str] | None] = mapped_column(JSON)
    content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_ref: Mapped[str | None] = mapped_column(String(255))
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    activation_source: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_now,
        onupdate=_now,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "id",
            "user_id",
            name="uq_memory_record_id_user",
        ),
    )


class MemoryCandidateRow(Base):
    """保存尚未取得权威效力的记忆候选和治理元数据。"""

    __tablename__ = "memory_candidates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_field: Mapped[str | None] = mapped_column(String(40))
    value_json: Mapped[str | float | list[str] | None] = mapped_column(JSON)
    content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_ref: Mapped[str | None] = mapped_column(String(255))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    conflict_group_id: Mapped[str | None] = mapped_column(String(64), index=True)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_now,
        onupdate=_now,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "id",
            "user_id",
            name="uq_memory_candidate_id_user",
        ),
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_memory_candidate_user_idempotency",
        ),
    )


class MemoryAuditEventRow(Base):
    """保存权威记录和候选生命周期的安全审计元数据。"""

    __tablename__ = "memory_audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    record_id: Mapped[str | None] = mapped_column(
        String(64),
        index=True,
    )
    candidate_id: Mapped[str | None] = mapped_column(
        String(64),
        index=True,
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    before_status: Mapped[str | None] = mapped_column(String(32))
    after_status: Mapped[str | None] = mapped_column(String(32))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["record_id", "user_id"],
            ["memory_records.id", "memory_records.user_id"],
            name="fk_memory_audit_record_owner",
        ),
        ForeignKeyConstraint(
            ["candidate_id", "user_id"],
            ["memory_candidates.id", "memory_candidates.user_id"],
            name="fk_memory_audit_candidate_owner",
        ),
    )


class MemoryOutboxTaskRow(Base):
    """保存与业务状态同事务提交的幂等后台任务。"""

    __tablename__ = "memory_outbox_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        index=True,
    )
    aggregate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_now,
        onupdate=_now,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_memory_outbox_user_idempotency",
        ),
    )


class MemoryProviderReferenceRow(Base):
    """保存权威记忆到外部派生索引的版本化映射。"""

    __tablename__ = "memory_provider_references"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    memory_record_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_record_id: Mapped[str] = mapped_column(String(160), nullable=False)
    memory_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_now,
        onupdate=_now,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["memory_record_id", "user_id"],
            ["memory_records.id", "memory_records.user_id"],
            name="fk_memory_provider_record_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "user_id",
            "provider",
            "provider_record_id",
            name="uq_memory_provider_user_record",
        ),
    )

