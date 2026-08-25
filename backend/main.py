"""
FastAPI 应用入口 - Phase 3 更新

lifespan 管理 PostgreSQL 候选治理与 Rolling Summary 后台 Worker。
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from backend.config import settings
from backend.db.database import AsyncSessionFactory, init_db
from backend.middleware.auth import AuthMiddleware
from backend.routers import auth, chat, memory, portfolio, report, user

_AGENT_ROOT = settings.agent_root

from src.utils.logging_config import setup_logger  # noqa: E402
from src.tools.skill_trace import flush_trace_exporters, initialize_trace_runtime  # noqa: E402

logger = setup_logger("backend.main", log_dir=str(_AGENT_ROOT / "logs"))

_ltm_worker_task = None
_ltm_worker_stop_event = None
_stm_worker_task = None
_stm_worker_stop_event = None


def _load_project_env_files() -> None:
    """
    将 agent/backend 两侧 .env 注入到 os.environ。

    说明：
    - pydantic-settings 能读取 .env，但不会自动写回 os.environ
    - trace / Langfuse / Mem0 的若干底层工具仍直接依赖 os.getenv
    """
    try:
        agent_env_path = _AGENT_ROOT / ".env"
        backend_env_path = Path(__file__).resolve().parent / ".env"
        if agent_env_path.exists():
            load_dotenv(dotenv_path=agent_env_path, override=False)
        if backend_env_path.exists():
            load_dotenv(dotenv_path=backend_env_path, override=False)
    except Exception as exc:
        logger.warning(f"[backend] load project env files 失败（不影响启动）: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理：
    启动：初始化数据库与可选缓存，再按开关启动受控后台 Worker。
    关闭：停止 Worker 并清理缓存、Trace 资源。
    """
    global _ltm_worker_task, _ltm_worker_stop_event, _stm_worker_task, _stm_worker_stop_event

    # 1. 初始化数据库（创建表 + 增量字段迁移）
    await init_db()
    print("[backend] 数据库初始化完成 ✓")
    logger.info("[backend] 数据库初始化完成")

    _load_project_env_files()

    # Redis 是可选加速层：初始化失败只记录 DEGRADED，权威 PostgreSQL 仍可服务。
    try:
        from backend.infrastructure.memory.runtime import initialize_memory_cache

        cache = await initialize_memory_cache()
        if cache is None:
            logger.info("memory_cache_disabled stage=%s status=%s", "memory.cache.bootstrap", "SKIPPED")
    except Exception as exc:
        logger.warning(
            "memory_cache_bootstrap_failed stage=%s status=%s error_code=%s error_type=%s",
            "memory.cache.bootstrap",
            "DEGRADED",
            "UNAVAILABLE",
            type(exc).__name__,
        )

    try:
        initialize_trace_runtime()
        print("[backend] trace runtime 初始化完成 ✓")
        logger.info("[backend] trace runtime 初始化完成")
    except Exception as exc:
        print(f"[backend] trace runtime 初始化失败（不影响启动）: {exc}")
        logger.warning(f"[backend] trace runtime 初始化失败: {exc}")

    if settings.auth_enabled:
        try:
            from backend.services.auth_service import ensure_seed_accounts

            async with AsyncSessionFactory() as session:
                await ensure_seed_accounts(session)
            print("[backend] 预置登录账号已校准 ✓")
            logger.info("[backend] 预置登录账号已校准")
        except Exception as exc:
            print(f"[backend] 预置登录账号初始化失败: {exc}")
            logger.error(f"[backend] 预置登录账号初始化失败: {exc}", exc_info=True)

    # 2. LTM 候选治理：M5 只启动 PostgreSQL Outbox Worker；Mem0 在 M6 单独接入。
    if settings.enable_memory:
        try:
            from backend.services.ltm_governance_worker import (
                build_ltm_governance_worker,
                run_ltm_governance_worker,
            )

            _ltm_worker_stop_event = asyncio.Event()
            # Provider 在 create_task 前构造，配置错误必须在启动边界可见。
            ltm_worker = build_ltm_governance_worker()
            _ltm_worker_task = asyncio.create_task(
                run_ltm_governance_worker(ltm_worker, _ltm_worker_stop_event),
                name="ltm_governance_worker",
            )
            print("[backend] ltm_governance_worker 后台任务已启动 ✓")
            logger.info(
                "memory_governance_worker_started stage=%s status=%s provider=%s",
                "memory.candidate.govern",
                "STARTED",
                settings.ltm_candidate_provider,
            )
        except Exception as exc:
            print(f"[backend] ltm_governance_worker 启动失败（不影响主功能）: {type(exc).__name__}")
            logger.warning(
                "memory_governance_worker_failed stage=%s status=%s error_code=%s "
                "error_type=%s",
                "memory.candidate.govern",
                "DEGRADED",
                "WORKER_BOOTSTRAP_FAILED",
                type(exc).__name__,
            )
    else:
        print("[backend] ENABLE_MEMORY=false，跳过 ltm_governance_worker")
        logger.info("[backend] ENABLE_MEMORY=false，LTM 候选治理关闭")

    if settings.enable_stm:
        try:
            from backend.services.stm_compaction_worker import (
                build_stm_compaction_worker,
                run_stm_compaction_worker,
            )

            _stm_worker_stop_event = asyncio.Event()
            # Provider 在 create_task 前构造，缺失配置必须由启动边界同步感知。
            stm_worker = build_stm_compaction_worker()
            _stm_worker_task = asyncio.create_task(
                run_stm_compaction_worker(stm_worker, _stm_worker_stop_event),
                name="stm_compaction_worker",
            )
            print("[backend] stm_compaction_worker 后台任务已启动 ✓")
            logger.info("[backend] stm_compaction_worker 启动完成")
        except Exception as exc:
            print(f"[backend] stm_compaction_worker 启动失败（不影响主功能）: {exc}")
            logger.warning(f"[backend] stm_compaction_worker 启动失败: {exc}")
    else:
        print("[backend] ENABLE_STM=false，跳过 stm_compaction_worker")
        logger.info("[backend] ENABLE_STM=false，STM worker 关闭")

    print(f"[backend] {settings.app_name} v{settings.app_version} 启动完成 ✓")
    logger.info(f"[backend] 应用启动完成: {settings.app_name} v{settings.app_version}")

    yield

    # ── 关闭时清理 ─────────────────────────────────────────
    if _ltm_worker_task and not _ltm_worker_task.done():
        if _ltm_worker_stop_event:
            _ltm_worker_stop_event.set()
        _ltm_worker_task.cancel()
        try:
            await _ltm_worker_task
        except asyncio.CancelledError:
            pass
        print("[backend] ltm_governance_worker 已停止")
        logger.info("[backend] ltm_governance_worker 已停止")
    if _stm_worker_task and not _stm_worker_task.done():
        if _stm_worker_stop_event:
            _stm_worker_stop_event.set()
        _stm_worker_task.cancel()
        try:
            await _stm_worker_task
        except asyncio.CancelledError:
            pass
        print("[backend] stm_compaction_worker 已停止")
        logger.info("[backend] stm_compaction_worker 已停止")
    try:
        from backend.infrastructure.memory.runtime import close_memory_cache

        await close_memory_cache()
    except Exception as exc:
        logger.warning(
            "memory_cache_close_failed stage=%s status=%s error_code=%s error_type=%s",
            "memory.cache.close",
            "DEGRADED",
            "UNAVAILABLE",
            type(exc).__name__,
        )
    try:
        flush_trace_exporters()
    except Exception as exc:
        logger.warning(f"[backend] flush trace exporters 失败: {exc}")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Finance 智能投研助手 REST API",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)

app.include_router(auth.router, prefix="/api/auth", tags=["鉴权"])
app.include_router(report.router, prefix="/api/report", tags=["调研报告"])
app.include_router(chat.router, prefix="/api/chat", tags=["对话"])
app.include_router(memory.router, prefix="/api/memory", tags=["记忆画像"])
app.include_router(user.router, prefix="/api/user", tags=["用户"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["持仓管理"])


@app.get("/api/health")
async def health_check():
    """返回应用与可选记忆缓存的安全健康摘要。"""
    from backend.infrastructure.memory.runtime import get_memory_cache

    cache = get_memory_cache()
    cache_health = (
        await cache.health()
        if cache is not None
        else {"enabled": False, "status": "DISABLED", "error_code": None, "metrics": {}}
    )
    return {
        "status": "ok",
        "version": settings.app_version,
        "components": {"memory_cache": cache_health},
    }
