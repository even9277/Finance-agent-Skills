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
    BigInteger,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


_JSON_STORAGE = JSON().with_variant(JSONB, "postgresql")


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
    running_summary_state: Mapped[dict | None] = mapped_column(_JSON_STORAGE)
    working_state: Mapped[dict | None] = mapped_column(_JSON_STORAGE)
    working_state_version: Mapped[int] = mapped_column(Integer, default=0)
    working_state_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    running_summary_mode: Mapped[str | None] = mapped_column(String(32))
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
    working_state_events: Mapped[list["WorkingStateEvent"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class WorkingStateEvent(Base):
    __tablename__ = "working_state_events"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    message_id: Mapped[int | None] = mapped_column(Integer)
    field_name: Mapped[str] = mapped_column(String(32), nullable=False)
    old_value: Mapped[dict | list | str | None] = mapped_column(_JSON_STORAGE)
    new_value: Mapped[dict | list | str | None] = mapped_column(_JSON_STORAGE)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    summary_version: Mapped[int] = mapped_column(Integer, default=0)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    session: Mapped["Session"] = relationship(back_populates="working_state_events")


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
    route_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # FIX-8: user-facing route summary
    plan_artifact_json: Mapped[dict | None] = mapped_column(_JSON_STORAGE, nullable=True)
    skill_artifact_json: Mapped[dict | None] = mapped_column(_JSON_STORAGE, nullable=True)
    verification_json: Mapped[dict | None] = mapped_column(_JSON_STORAGE, nullable=True)
    allowed_claim_level: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    session: Mapped["Session"] = relationship(back_populates="messages")


class WebSearchCache(Base):
    """Web Search v2 缓存表：只保存摘要级结果，不保存网页正文。"""

    __tablename__ = "web_search_cache"

    key: Mapped[str] = mapped_column(String(512), primary_key=True)
    payload: Mapped[dict] = mapped_column(_JSON_STORAGE, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


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
    summary_payload: Mapped[dict | None] = mapped_column(_JSON_STORAGE)
    summary_mode: Mapped[str | None] = mapped_column(String(32))
    summary_trigger: Mapped[str | None] = mapped_column(String(64))

    # 本次压缩统计（用于前端百分比进度展示）
    compressed_message_count: Mapped[int] = mapped_column(Integer, default=0)
    total_message_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SummaryAuditLog(Base):
    __tablename__ = "summary_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    task_kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    trigger: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(128))
    source_start_message_id: Mapped[int | None] = mapped_column(Integer)
    source_end_message_id: Mapped[int | None] = mapped_column(Integer)
    source_start_created_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_end_created_at: Mapped[datetime | None] = mapped_column(DateTime)
    input_message_count: Mapped[int] = mapped_column(Integer, default=0)
    input_token_estimate: Mapped[int | None] = mapped_column(Integer)
    output_summary_id: Mapped[int | None] = mapped_column(Integer)
    output_summary_version: Mapped[int | None] = mapped_column(Integer)
    output_summary_mode: Mapped[str | None] = mapped_column(String(32))
    audit_reasons_json: Mapped[list | None] = mapped_column(_JSON_STORAGE)
    model_name: Mapped[str | None] = mapped_column(String(128))
    counting_mode: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
