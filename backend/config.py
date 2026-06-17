"""
后端配置管理模块
使用 pydantic-settings 从 .env 文件读取配置，支持多层覆盖：
  1. Financial-MCP-Agent/.env  ← LLM API 配置
  2. backend/.env              ← 后端特定覆盖
"""

from __future__ import annotations

from pathlib import Path
from typing import List

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
    database_url: str = (
        f"sqlite+aiosqlite:///{_PROJECT_ROOT / 'backend' / 'finance.db'}"
    )
    # ── Redis（Phase 1.5 基础设施）─────────────────────────
    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str = ""
    redis_namespace_env: str = "dev"
    redis_socket_timeout_ms: int = 500
    redis_connect_timeout_ms: int = 500
    redis_max_connections: int = 20
    redis_health_check_interval_sec: int = 30
    redis_default_ttl_sec: int = 1800
    redis_ttl_jitter_ratio: float = 0.1
    redis_debug_endpoints_enabled: bool = False
    redis_metrics_endpoint_enabled: bool = True
    redis_unavailable_recheck_sec: int = 30

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
    # A0/A阶段治理开关：默认关闭，确保与当前行为兼容
    enable_chat_ltm_extract: bool = False
    enable_summary_ltm_extract: bool = False
    enable_prewrite_dedupe: bool = False
    enable_chat_skills: bool = False  # Phase 1 skill-first chat
    # 低置信度路由时暂停执行，等待用户确认（HITL）
    enable_skill_route_hitl: bool = True
    skill_route_hitl_confidence_threshold: float = 0.8
    enable_entity_resolver_v2: bool = False
    enable_route_v2: bool = False
    enable_post_rewrite_extractors: bool = False
    enable_working_state_v2: bool = True
    entity_resolver_model: str = "kimi-k2.5"
    route_stage1_confidence_high: float = 0.85
    enable_tushare_skills: bool = False  # Phase 1 tushare skill bundle
    enable_tushare_planner: bool = False
    # Plan-and-Execute v2 flags. Defaults remain off to preserve existing chat behavior.
    enable_tushare_v2: bool = False
    enable_planner_v2: bool = False
    enable_validator_v2_semantic: bool = False
    enable_validator_v2_quality: bool = False
    enable_executor_v2: bool = False
    executor_max_concurrency: int = 6
    executor_per_api_family_limit: int = 2
    executor_min_interval_ms: int = 150
    per_tool_timeout_ms: int = 8000
    per_tool_retry_limit: int = 1
    max_steps: int = 8
    total_timeout_ms: int = 25000
    max_replans: int = 1
    enable_verifier_v2: bool = False
    verifier_sufficient_threshold: int = 80
    verifier_partial_threshold: int = 60
    enable_controller_v2: bool = False
    enable_synthesis_v2: bool = False
    enable_sop_v2: bool = False
    expose_plan_preview_to_user: bool = True
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
    enable_skill_lifecycle: bool = False
    enable_skill_loader_v2: bool = False
    enable_reference_index_v2: bool = False
    enable_web_search_v2: bool = False
    web_search_shadow_mode: bool = True
    web_search_provider: str = "duckduckgo"
    web_search_timeout_ms: int = 4000
    web_search_max_results: int = 5
    web_search_default_lookback_days: int = 7
    web_search_cache_ttl_min: int = 15
    web_search_daily_quota: int = 100
    web_search_rate_limit_per_min: int = 20
    tavily_api_key: str = ""
    tavily_include_domains: str = ""
    tavily_exclude_domains: str = ""
    skill_registry_version_source: str = "spec"
    reference_search_top_k: int = 3
    skill_loader_token_budget_per_stage: int = 2048
    skill_spec_concurrency_override: bool = True
    skill_degrade_stages_priority: str = "skill_first"
    realcall_schedule_enabled: bool = False
    tushare_points_level: int = 2000
    tushare_tool_profile: str = "points_2000"
    tushare_disable_high_tier_tools: bool = True
    tushare_probe_enabled_tools: bool = True
    langfuse_upload_prompt_reply: bool = False
    auth_enabled: bool = True
    memory_context_timeout_sec: int = 8
    # STM / rolling summary
    # 当前默认主链路保留 token 预算驱动的 preflight + overflow fallback。
    stm_keep_recent: int = 6
    # 仅用于 compress_if_needed（overflow / admin 同步应急压缩），与 preflight token 阈值解耦。
    stm_fallback_min_uncompressed_messages: int = 10
    stm_fallback_compaction_timeout_sec: int = 45
    stm_compaction_model: str = ""
    stm_compaction_api_key: str = ""
    stm_compaction_base_url: str = ""
    stm_hot_update_model: str = "tongyixiaomi-flash"
    stm_hot_update_api_key: str = ""
    stm_hot_update_base_url: str = ""
    stm_hot_recent_user_window: int = 6
    # Rolling summary / preflight compaction baseline
    chat_context_window_tokens: int = 128000
    stm_summary_preflight_enabled: bool = True
    stm_summary_reserve_tokens_floor: int = 20000
    stm_summary_soft_threshold_tokens: int = 4000
    stm_summary_overhead_tokens: int = 4096
    stm_summary_chunk_parts: int = 2
    stm_summary_min_messages_for_split: int = 4
    stm_summary_retry_attempts: int = 2
    stm_summary_max_quality_retries: int = 1
    stm_summary_strict_identifier_check: bool = True
    stm_preflight_timeout_ms: int = 1500
    stm_summary_cas_retry_limit: int = 1
    stm_summary_audit_sample_rate: float = 0.1
    stm_route_slice_max_entities: int = 4
    stm_answer_policy_max_constraints: int = 8

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
    chat_rewriter_model: str = "tongyi-xiaomi-analysis-pro"
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

    @model_validator(mode="after")
    def _merge_legacy_stm_fallback_env(self) -> Settings:
        """
        新环境变量优先；未设置 STM_FALLBACK_* 时，回退读取已废弃的
        STM_COMPRESS_THRESHOLD / STM_COMPACTION_TIMEOUT_SEC（兼容旧 .env）。
        """
        import os

        if not os.environ.get("STM_FALLBACK_MIN_UNCOMPRESSED_MESSAGES"):
            legacy = os.environ.get("STM_COMPRESS_THRESHOLD")
            if legacy not in (None, ""):
                try:
                    object.__setattr__(
                        self,
                        "stm_fallback_min_uncompressed_messages",
                        int(str(legacy).strip()),
                    )
                except ValueError:
                    pass
        if not os.environ.get("STM_FALLBACK_COMPACTION_TIMEOUT_SEC"):
            legacy = os.environ.get("STM_COMPACTION_TIMEOUT_SEC")
            if legacy not in (None, ""):
                try:
                    object.__setattr__(
                        self,
                        "stm_fallback_compaction_timeout_sec",
                        int(str(legacy).strip()),
                    )
                except ValueError:
                    pass
        return self

    model_config = {
        "env_file": [
            str(_AGENT_DIR / ".env"),   # LLM 配置优先从 agent .env 读
            str(_BACKEND_DIR / ".env"),  # 后端覆盖
        ],
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
