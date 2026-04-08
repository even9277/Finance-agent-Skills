"""
后端配置管理模块
使用 pydantic-settings 从 .env 文件读取配置，支持多层覆盖：
  1. Financial-MCP-Agent/.env  ← LLM API 配置
  2. backend/.env              ← 后端特定覆盖
"""

from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings

_BACKEND_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_AGENT_DIR = _PROJECT_ROOT / "Financial-MCP-Agent"


class Settings(BaseSettings):
    # ── 应用基本信息 ──────────────────────────────────────
    app_name: str = "Finance 智能投研助手"
    app_version: str = "1.2.0"
    debug: bool = False

    # ── 服务器 ────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000

    # ── 数据库（Phase 1 SQLite，Phase 生产切 PostgreSQL）─
    database_url: str = (
        f"sqlite+aiosqlite:///{_PROJECT_ROOT / 'backend' / 'finance.db'}"
    )

    # ── CORS ──────────────────────────────────────────────
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]

    # ── LLM（从 agent .env 继承）─────────────────────────
    openai_compatible_api_key: str = ""
    openai_compatible_base_url: str = ""
    openai_compatible_model: str = ""

    # ── Feature Flags ─────────────────────────────────────
    enable_stm: bool = False    # Phase 2 激活
    enable_memory: bool = False  # Phase 3 激活
    enable_chat_skills: bool = False  # Phase 1 skill-first chat
    enable_tushare_skills: bool = False  # Phase 1 tushare skill bundle
    enable_tushare_planner: bool = False
    enable_tushare_market_tools: bool = False
    enable_tushare_index_tools: bool = False
    enable_tushare_sector_tools: bool = False
    enable_fundamental_analysis: bool = False
    enable_sector_analysis: bool = False
    enable_stock_selection: bool = False
    enable_deterministic_skill_execution: bool = True
    enable_tool_prefetch_concurrency: bool = True
    enable_trace: bool = True
    enable_evidence_lineage: bool = True
    enable_trace_artifact_refs: bool = False
    enable_trace_prompt_capture: bool = False
    enable_trace_reply_capture: bool = False
    enable_langfuse: bool = False
    auth_enabled: bool = True
    memory_context_timeout_sec: int = 8
    # STM dynamic budget / async compaction
    stm_compression_strategy: str = "dynamic_budget"
    stm_context_budget_tokens: int = 32000
    stm_context_target_ratio: float = 0.72
    stm_context_hard_ratio: float = 0.85
    stm_response_reserve_tokens: int = 1200
    stm_memory_reserve_tokens: int = 600
    stm_keep_recent: int = 4
    stm_legacy_count_threshold: int = 10
    stm_worker_interval_sec: int = 3
    stm_worker_batch_size: int = 10
    stm_worker_max_retries: int = 3

    # ── Mem0 / pgvector 配置（Phase 3）────────────────────
    # PostgreSQL 连接（Mem0 向量库使用，SQLite 环境下这些配置被忽略）
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_db: str = "finance"
    pg_user: str = "postgres"
    pg_password: str = "postgres"
    # 向量维度（与嵌入模型一致，默认 1536）
    embed_dims: int = 1536
    # 嵌入模型（留空则复用 OPENAI_COMPATIBLE_MODEL）
    embed_model: str = ""
    # Skill Chat 模型分层
    chat_router_model: str = "kimi-k2.5"
    chat_resolver_model: str = "kimi-k2.5"
    chat_skill_synthesis_model: str = ""
    # Trace / Langfuse
    trace_artifact_dir: str = str(_AGENT_DIR / "logs" / "chat_trace_artifacts")
    langfuse_base_url: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_project: str = ""
    langfuse_env: str = "dev"
    langfuse_release: str = ""
    langfuse_sample_rate: float = 1.0
    langfuse_flush_at: int = 20
    langfuse_flush_interval_sec: int = 5
    # Tushare（Phase 1）
    tushare_token: str = ""
    # Auth/JWT
    jwt_secret_key: str = "change-me-in-production-please-use-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    # LTM Worker 轮询间隔（秒）
    ltm_worker_interval_sec: int = 5
    # LTM 触发最小间隔（秒，同一会话两次 enqueue_add_conversation 的最小间隔）
    min_ltm_interval: int = 300

    # ── 路径（只读，由代码推导）──────────────────────────
    @property
    def agent_root(self) -> Path:
        return _AGENT_DIR

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT

    @field_validator("debug", mode="before")
    @classmethod
    def _normalize_debug(cls, value):
        """
        Be permissive with historical env values like DEBUG=release/debug.
        Pydantic v2 no longer treats these as booleans automatically.
        """
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"debug", "dev", "development"}:
                return True
        return value

    model_config = {
        "env_file": [
            str(_AGENT_DIR / ".env"),   # LLM 配置优先从 agent .env 读
            str(_BACKEND_DIR / ".env"),  # 后端覆盖
        ],
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
