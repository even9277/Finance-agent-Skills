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

from backend.config import settings
from backend.db.database import AsyncSessionFactory, init_db
from backend.middleware.auth import AuthMiddleware
from backend.routers import auth, chat, memory, portfolio, report, user

_AGENT_ROOT = Path(__file__).resolve().parent.parent / "Financial-MCP-Agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from src.utils.logging_config import setup_logger

logger = setup_logger("backend.main", log_dir=str(_AGENT_ROOT / "logs"))

_ltm_worker_task = None
_ltm_worker_stop_event = None


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
        # 重要：Mem0 初始化直接读取 os.environ（os.getenv），不会自动感知 pydantic-settings 读取的 .env。
        # 因此这里显式 load backend/.env，确保 DATABASE_URL、PG_* 等注入到进程环境变量。
        try:
            from dotenv import load_dotenv  # type: ignore

            env_path = Path(__file__).resolve().parent / ".env"
            load_dotenv(dotenv_path=env_path, override=False)

            # 同时加载 Agent 侧 .env（Mem0/LLM 模型等），避免仅配置在 Financial-MCP-Agent/.env
            agent_env_path = _AGENT_ROOT / ".env"
            if agent_env_path.exists():
                load_dotenv(dotenv_path=agent_env_path, override=False)
        except Exception as exc:
            logger.warning(f"[backend] load_dotenv 失败（不影响启动）: {exc}")

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
