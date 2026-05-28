"""
FastAPI 应用入口 - Phase 3 更新

lifespan 新增：
1. Mem0 AsyncMemory 单例初始化（ENABLE_MEMORY=true 时）
2. ltm_worker 后台任务启动（ENABLE_MEMORY=true 时）
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from backend.config import settings
from backend.db.database import AsyncSessionFactory, init_db
from backend.middleware.auth import AuthMiddleware
from backend.routers import auth, chat, memory, portfolio, report, user

_AGENT_ROOT = Path(__file__).resolve().parent.parent / "Financial-MCP-Agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from src.utils.logging_config import setup_logger
from src.tools.skill_trace import flush_trace_exporters, initialize_trace_runtime

logger = setup_logger("backend.main", log_dir=str(_AGENT_ROOT / "logs"))

_ltm_worker_task = None
_ltm_worker_stop_event = None
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
    启动：初始化数据库 → 初始化 Mem0 → 启动 ltm_worker（ENABLE_MEMORY=true 时）
    关闭：停止 ltm_worker → 清理资源
    """
    global _ltm_worker_task, _ltm_worker_stop_event

    # 1. 初始化数据库（创建表 + 增量字段迁移）
    await init_db()
    print("[backend] 数据库初始化完成 ✓")
    logger.info("[backend] 数据库初始化完成")

    _load_project_env_files()

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

    # 2. Phase 3 LTM：初始化 Mem0 + 启动 ltm_worker
    if settings.enable_memory:
        # Mem0 / trace / Langfuse 相关底层模块大量直接读取 os.environ。
        # 因此这里沿用统一的 env 注入逻辑，保证 backend/.env 与 Agent/.env 都进入进程环境。
        _load_project_env_files()

        print(f"[backend] ENABLE_MEMORY=true，正在初始化 Mem0...")  # env reload safe
        logger.info("[backend] ENABLE_MEMORY=true，初始化 Mem0")

        try:
            from src.memory.mem0_client import init_mem0_client
            await init_mem0_client()
        except Exception as exc:
            print(f"[backend] Mem0 初始化异常（不影响启动）: {exc}")
            logger.warning(f"[backend] Mem0 初始化异常: {exc}")

        # 启动 ltm_worker 后台任务
        try:
            from src.memory.ltm_worker import ltm_worker_loop
            _ltm_worker_stop_event = asyncio.Event()
            _ltm_worker_task = asyncio.create_task(
                ltm_worker_loop(_ltm_worker_stop_event),
                name="ltm_worker",
            )
            print("[backend] ltm_worker 后台任务已启动 ✓")
            logger.info("[backend] ltm_worker 启动完成")
        except Exception as exc:
            print(f"[backend] ltm_worker 启动失败（不影响主功能）: {exc}")
            logger.warning(f"[backend] ltm_worker 启动失败: {exc}")
    else:
        print("[backend] ENABLE_MEMORY=false，跳过 Mem0 初始化和 ltm_worker")
        logger.info("[backend] ENABLE_MEMORY=false，LTM 功能关闭")

    if settings.enable_stm:
        print("[backend] ENABLE_STM=true，STM 仅保留 pre_compaction/fallback 主链路，已停用 stm_compaction_worker")
        logger.info("[backend] ENABLE_STM=true，已停用旧 stm_compaction_worker")
    else:
        print("[backend] ENABLE_STM=false，跳过 STM 初始化")
        logger.info("[backend] ENABLE_STM=false，STM 关闭")

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
        print("[backend] ltm_worker 已停止")
        logger.info("[backend] ltm_worker 已停止")
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
    return {"status": "ok", "version": settings.app_version}
