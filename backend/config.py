"""
后端配置管理模块
使用 pydantic-settings 从 .env 文件读取配置，支持多层覆盖：
  1. Financial-MCP-Agent/.env  ← LLM API 配置
  2. backend/.env              ← 后端特定覆盖
"""

from pathlib import Path
from typing import List, Self

from pydantic import field_validator, model_validator
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
    database_url: str = f"sqlite+aiosqlite:///{_PROJECT_ROOT / 'backend' / 'finance.db'}"

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
    enable_stm: bool = False  # Phase 2 激活
    enable_memory: bool = False  # Phase 3 激活
    enable_redis_cache: bool = False  # 可丢弃的记忆热缓存；PostgreSQL 始终权威
    enable_chat_skills: bool = False  # Phase 1 skill-first chat
    enable_tushare_skills: bool = False  # Phase 1 tushare skill bundle
    enable_tushare_planner: bool = False
    enable_tushare_market_tools: bool = False
    enable_tushare_index_tools: bool = False
    enable_tushare_sector_tools: bool = False
    enable_fundamental_analysis: bool = False
    enable_sector_analysis: bool = False
    enable_stock_selection: bool = False
    # Web News 只作为 market-move-explain 的可选弱证据；默认不允许外部请求。
    enable_web_news: bool = False
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
    stm_context_safety_margin_tokens: int = 1000
    stm_stage_overhead_tokens: int = 600
    stm_keep_recent: int = 4
    stm_legacy_count_threshold: int = 10
    stm_worker_interval_sec: int = 3
    stm_worker_batch_size: int = 10
    stm_worker_max_retries: int = 3
    stm_summary_provider: str = "openai"
    stm_summary_timeout_sec: int = 30
    # 必须覆盖一次模型调用及提交尾延迟，避免合法调用被过早回收并重复计费。
    stm_worker_lease_sec: int = 60
    # LTM 候选治理仅消费 PostgreSQL Outbox；deterministic 是默认离线安全实现。
    ltm_candidate_provider: str = "deterministic"
    ltm_candidate_timeout_sec: int = 30
    ltm_worker_interval_sec: int = 5
    ltm_worker_batch_size: int = 10
    ltm_worker_max_retries: int = 3
    ltm_worker_lease_sec: int = 60
    # Redis 仅用于加速；连接失败不得影响应用启动或对话正确性。
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_namespace: str = "finance-agent"
    redis_cache_ttl_sec: int = 300
    redis_cache_lease_sec: int = 5
    redis_singleflight_wait_ms: int = 40
    redis_connect_timeout_sec: float = 0.25
    redis_socket_timeout_sec: float = 0.50
    redis_max_connections: int = 20

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
    # M6 派生语义索引：默认关闭，离线测试使用 deterministic provider。
    memory_semantic_provider: str = "disabled"
    memory_semantic_timeout_sec: int = 8
    memory_semantic_top_k: int = 20
    memory_semantic_min_score: float = 0.10
    memory_retrieval_top_k: int = 8
    memory_retrieval_token_budget: int = 600
    memory_index_worker_interval_sec: int = 5
    memory_index_worker_batch_size: int = 10
    memory_index_worker_max_retries: int = 3
    memory_index_worker_lease_sec: int = 60
    memory_index_schema_version: str = "memory-index-v1"
    memory_embedding_provider: str = "deterministic"
    # Skill Chat 模型分层
    chat_router_model: str = "kimi-k2.5"
    chat_resolver_model: str = "kimi-k2.5"
    chat_skill_synthesis_model: str = ""
    # Skill rerank 默认关闭；开启时只允许接收 top-K routing metadata。
    skill_rerank_provider: str = "disabled"
    skill_rerank_model: str = ""
    skill_rerank_top_k: int = 3
    skill_rerank_timeout_sec: int = 8
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
    # Tavily Web News（默认关闭，密钥只允许通过环境注入）
    tavily_api_key: str = ""
    web_news_timeout_sec: int = 5
    web_news_max_results: int = 5
    web_news_freshness_days: int = 7
    web_news_max_summary_chars: int = 280
    web_news_rate_limit_per_min: int = 10
    web_news_daily_quota: int = 100
    web_news_include_domains: List[str] = []
    web_news_exclude_domains: List[str] = []
    # Auth/JWT
    jwt_secret_key: str = "change-me-in-production-please-use-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
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

    @field_validator("stm_summary_provider")
    @classmethod
    def _validate_stm_summary_provider(cls, value: str) -> str:
        """限制摘要 Provider 为生产模型或显式离线实现。"""
        normalized = value.strip().lower()
        if normalized not in {"openai", "deterministic"}:
            raise ValueError("stm_summary_provider must be openai or deterministic")
        return normalized

    @field_validator("ltm_candidate_provider")
    @classmethod
    def _validate_ltm_candidate_provider(cls, value: str) -> str:
        """限制候选抽取 Provider 为显式在线模型或离线确定性实现。"""
        normalized = value.strip().lower()
        if normalized not in {"openai", "deterministic"}:
            raise ValueError("ltm_candidate_provider must be openai or deterministic")
        return normalized

    @field_validator("memory_semantic_provider")
    @classmethod
    def _validate_memory_semantic_provider(cls, value: str) -> str:
        """限制语义 Provider 为关闭、离线确定性或显式 Mem0。"""
        normalized = value.strip().lower()
        if normalized not in {"disabled", "deterministic", "mem0"}:
            raise ValueError("memory_semantic_provider must be disabled, deterministic or mem0")
        return normalized

    @field_validator("memory_embedding_provider")
    @classmethod
    def _validate_memory_embedding_provider(cls, value: str) -> str:
        """限制嵌入实现，避免默认配置隐式调用外部模型。"""
        normalized = value.strip().lower()
        if normalized not in {"deterministic", "openai"}:
            raise ValueError("memory_embedding_provider must be deterministic or openai")
        return normalized

    @field_validator("skill_rerank_provider")
    @classmethod
    def _validate_skill_rerank_provider(cls, value: str) -> str:
        """限制 Skill rerank 为关闭或显式 OpenAI-compatible Provider。"""
        normalized = value.strip().lower()
        if normalized not in {"disabled", "openai"}:
            raise ValueError("skill_rerank_provider must be disabled or openai")
        return normalized

    @field_validator("skill_rerank_top_k")
    @classmethod
    def _validate_skill_rerank_top_k(cls, value: int) -> int:
        """限制在线候选规模，禁止把完整 Registry 交给 Provider。"""
        if not 1 <= value <= 5:
            raise ValueError("skill_rerank_top_k must be between 1 and 5")
        return value

    @field_validator(
        "stm_context_budget_tokens",
        "stm_keep_recent",
        "stm_legacy_count_threshold",
        "stm_worker_interval_sec",
        "stm_worker_batch_size",
        "stm_worker_max_retries",
        "stm_summary_timeout_sec",
        "stm_worker_lease_sec",
        "ltm_candidate_timeout_sec",
        "ltm_worker_interval_sec",
        "ltm_worker_batch_size",
        "ltm_worker_max_retries",
        "ltm_worker_lease_sec",
        "redis_cache_ttl_sec",
        "redis_cache_lease_sec",
        "redis_singleflight_wait_ms",
        "redis_max_connections",
        "embed_dims",
        "memory_semantic_timeout_sec",
        "memory_semantic_top_k",
        "memory_retrieval_top_k",
        "memory_retrieval_token_budget",
        "memory_index_worker_interval_sec",
        "memory_index_worker_batch_size",
        "memory_index_worker_max_retries",
        "memory_index_worker_lease_sec",
        "skill_rerank_timeout_sec",
        "web_news_timeout_sec",
        "web_news_freshness_days",
        "web_news_rate_limit_per_min",
        "web_news_daily_quota",
    )
    @classmethod
    def _validate_positive_stm_integer(cls, value: int) -> int:
        """拒绝会关闭预算、轮询、重试或租约保护的非正整数。"""
        if value < 1:
            raise ValueError("STM integer settings must be positive")
        return value

    @field_validator("web_news_max_results")
    @classmethod
    def _validate_web_news_max_results(cls, value: int) -> int:
        """限制单次返回规模，避免弱证据挤占上下文和配额。"""
        if not 1 <= value <= 10:
            raise ValueError("web_news_max_results must be between 1 and 10")
        return value

    @field_validator("web_news_max_summary_chars")
    @classmethod
    def _validate_web_news_summary_chars(cls, value: int) -> int:
        """限制单条摘要长度，禁止网页正文进入模型上下文。"""
        if not 80 <= value <= 500:
            raise ValueError("web_news_max_summary_chars must be between 80 and 500")
        return value

    @field_validator("web_news_include_domains", "web_news_exclude_domains")
    @classmethod
    def _validate_web_news_domains(cls, value: List[str]) -> List[str]:
        """规范域名白黑名单并拒绝 URL、路径和带凭证的输入。"""
        normalized: list[str] = []
        for item in value:
            domain = item.strip().lower().removeprefix("www.")
            if (
                not domain
                or "://" in domain
                or "/" in domain
                or "@" in domain
                or ":" in domain
                or any(character.isspace() for character in domain)
            ):
                raise ValueError("web news domains must be bare host names")
            if domain not in normalized:
                normalized.append(domain)
        return normalized

    @field_validator("redis_connect_timeout_sec", "redis_socket_timeout_sec")
    @classmethod
    def _validate_positive_redis_timeout(cls, value: float) -> float:
        """拒绝让缓存连接无限等待或立即无效的超时配置。"""
        if value <= 0:
            raise ValueError("Redis timeout settings must be positive")
        return value

    @field_validator("redis_url")
    @classmethod
    def _validate_redis_url(cls, value: str) -> str:
        """只接受 redis-py 支持的 Redis URL，不在日志中输出其内容。"""
        normalized = value.strip()
        if not normalized.startswith(("redis://", "rediss://")):
            raise ValueError("redis_url must use redis:// or rediss://")
        return normalized

    @field_validator("redis_cache_namespace")
    @classmethod
    def _validate_redis_namespace(cls, value: str) -> str:
        """限制键空间前缀为可读且无空白的稳定标识。"""
        normalized = value.strip()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError("redis_cache_namespace must not be blank or contain spaces")
        return normalized

    @model_validator(mode="after")
    def _validate_stm_worker_timing(self) -> Self:
        """确保合法模型调用不会在正常超时前丢失任务所有权。"""
        safety_margin_sec = 5
        minimum_lease = self.stm_summary_timeout_sec + safety_margin_sec
        if self.stm_worker_lease_sec <= minimum_lease:
            raise ValueError(
                "stm_worker_lease_sec must be greater than stm_summary_timeout_sec + 5 seconds"
            )
        minimum_candidate_lease = self.ltm_candidate_timeout_sec + safety_margin_sec
        if self.ltm_worker_lease_sec <= minimum_candidate_lease:
            raise ValueError(
                "ltm_worker_lease_sec must be greater than ltm_candidate_timeout_sec + 5 seconds"
            )
        minimum_index_lease = self.memory_semantic_timeout_sec + safety_margin_sec
        if self.memory_index_worker_lease_sec <= minimum_index_lease:
            raise ValueError(
                "memory_index_worker_lease_sec must be greater than "
                "memory_semantic_timeout_sec + 5 seconds"
            )
        if self.memory_semantic_provider == "deterministic" and self.embed_dims != 1536:
            raise ValueError(
                "deterministic pgvector schema memory-index-v1 requires embed_dims=1536"
            )
        overlap = set(self.web_news_include_domains).intersection(
            self.web_news_exclude_domains
        )
        if overlap:
            raise ValueError("web news include and exclude domains must not overlap")
        return self

    model_config = {
        "env_file": [
            str(_AGENT_DIR / ".env"),  # LLM 配置优先从 agent .env 读
            str(_BACKEND_DIR / ".env"),  # 后端覆盖
        ],
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
