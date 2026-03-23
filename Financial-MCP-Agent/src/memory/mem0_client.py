"""
Mem0 异步客户端封装

设计原则：
- 全程使用 AsyncMemory（异步版本），适配 FastAPI 事件循环
- 优雅降级：若 mem0ai 未安装或初始化失败，使用 NoopMem0Client，
  所有方法静默返回空结果，不影响主链路
- 单例模式：通过 get_mem0_client() 获取全局唯一实例

配置说明：
  MEM0_CONFIG 从环境变量读取，必须与 pgvector 向量库维度一致（1536维）
  collection_name = "finance_ltm"（Mem0 自动创建表）
"""

import os
from typing import Any, Optional
import asyncio
from urllib.parse import urlparse
from src.utils.logging_config import setup_logger

logger = setup_logger("mem0_client")

_mem0_client: Optional[Any] = None
_mem0_available: bool = False


class NoopMem0Client:
    """
    Mem0 不可用时的空实现（降级占位）。
    所有方法静默返回空结果，记录 DEBUG 日志，不抛异常。
    """

    async def add(self, messages, user_id: str, metadata: dict = None) -> dict:
        logger.debug(f"[Mem0-Noop] add called (user={user_id}), mem0 not available")
        return {"results": []}

    async def search(self, query: str, user_id: str, **kwargs) -> list:
        logger.debug(f"[Mem0-Noop] search called (user={user_id}), mem0 not available")
        return []

    async def get_all(self, user_id: str, **kwargs) -> dict:
        logger.debug(f"[Mem0-Noop] get_all called (user={user_id}), mem0 not available")
        return {"results": []}

    async def update(self, memory_id: str, data: str, metadata: dict = None) -> dict:
        logger.debug(f"[Mem0-Noop] update called (memory_id={memory_id}), mem0 not available")
        return {}

    async def delete(self, memory_id: str) -> dict:
        logger.debug(f"[Mem0-Noop] delete called (memory_id={memory_id}), mem0 not available")
        return {}

    async def delete_all(self, user_id: str) -> dict:
        logger.debug(f"[Mem0-Noop] delete_all called (user={user_id}), mem0 not available")
        return {}


def _build_mem0_config() -> dict:
    """从环境变量构建 Mem0 配置字典。"""
    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY", "")
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "")
    model = os.getenv("OPENAI_COMPATIBLE_MODEL", "")
    # Mem0 的 embeddings 走 OpenAI embeddings.create；必须使用“embedding 模型”，不能复用聊天模型。
    # 优先级：MEM0_EMBED_MODEL > EMBED_MODEL > text-embedding-3-small
    embed_model = (
        os.getenv("MEM0_EMBED_MODEL", "")
        or os.getenv("EMBED_MODEL", "")
        or "text-embedding-3-small"
    )

    db_url = os.getenv("DATABASE_URL", "")

    # Mem0 这里优先读 PG_*；若未注入进程环境变量（常见于仅 pydantic 读取 .env 的场景），
    # 则尝试从 DATABASE_URL 解析，以避免默认使用 postgres/postgres 造成连接失败。
    pg_host = os.getenv("PG_HOST", "")
    pg_port_raw = os.getenv("PG_PORT", "")
    pg_db = os.getenv("PG_DB", "")
    pg_user = os.getenv("PG_USER", "")
    pg_password = os.getenv("PG_PASSWORD", "")

    if (not pg_host or not pg_port_raw or not pg_db or not pg_user) and db_url:
        try:
            # 支持形如：postgresql+asyncpg://user:pass@host:5432/dbname
            parsed = urlparse(db_url.replace("postgresql+asyncpg://", "postgresql://"))
            if parsed.hostname and not pg_host:
                pg_host = parsed.hostname
            if parsed.port and not pg_port_raw:
                pg_port_raw = str(parsed.port)
            if parsed.username and not pg_user:
                pg_user = parsed.username
            if parsed.password and not pg_password:
                pg_password = parsed.password
            if parsed.path and parsed.path.strip("/") and not pg_db:
                pg_db = parsed.path.strip("/")
        except Exception:
            # 解析失败则留给下面的默认值兜底
            pass

    pg_host = pg_host or "localhost"
    pg_port = int(pg_port_raw or "5432")
    pg_db = pg_db or "finance"
    pg_user = pg_user or "postgres"
    pg_password = pg_password or "postgres"

    embed_dims = int(os.getenv("EMBED_DIMS", "1536"))

    return {
        "llm": {
            "provider": "openai",
            "config": {
                "model": model,
                "api_key": api_key,
                "openai_base_url": base_url,
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": embed_model,
                "api_key": api_key,
                "openai_base_url": base_url,
                "embedding_dims": embed_dims,
            },
        },
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "host": pg_host,
                "port": pg_port,
                "dbname": pg_db,
                "user": pg_user,
                "password": pg_password,
                "collection_name": "finance_ltm",
                "embedding_model_dims": embed_dims,
            },
        },
    }


async def init_mem0_client() -> None:
    """
    在 FastAPI lifespan 中调用，初始化 Mem0 单例。
    若初始化失败，降级为 NoopMem0Client，不阻断应用启动。
    """
    global _mem0_client, _mem0_available

    try:
        from mem0 import AsyncMemory  # type: ignore
        from src.memory.mem0_prompts import (
            FINANCE_FACT_EXTRACTION_PROMPT,
            FINANCE_UPDATE_MEMORY_PROMPT,
        )

        config = _build_mem0_config()
        config["custom_fact_extraction_prompt"] = FINANCE_FACT_EXTRACTION_PROMPT
        config["custom_update_memory_prompt"] = FINANCE_UPDATE_MEMORY_PROMPT
        try:
            logger.info(
                "[Mem0] config preview: llm_model=%s, embed_model=%s, pg=%s:%s/%s",
                config.get("llm", {}).get("config", {}).get("model"),
                config.get("embedder", {}).get("config", {}).get("model"),
                config.get("vector_store", {}).get("config", {}).get("host"),
                config.get("vector_store", {}).get("config", {}).get("port"),
                config.get("vector_store", {}).get("config", {}).get("dbname"),
            )
        except Exception:
            pass

        # 兼容 mem0 版本差异：
        # - 有的版本 from_config 返回 AsyncMemory 实例
        # - 有的版本 from_config 是 async，返回 coroutine，需要 await
        maybe_client = AsyncMemory.from_config(config)
        _mem0_client = await maybe_client if asyncio.iscoroutine(maybe_client) else maybe_client
        _mem0_available = True

        print("[Mem0] AsyncMemory 初始化成功 ✓")
        logger.info("[Mem0] AsyncMemory 初始化成功，使用 pgvector 向量库")

    except ImportError:
        _mem0_client = NoopMem0Client()
        _mem0_available = False
        print("[Mem0] mem0ai 未安装，使用 NoopMem0Client（LTM 语义层不可用，结构化画像正常）")
        logger.warning("[Mem0] mem0ai 未安装，降级为 NoopMem0Client")

    except Exception as exc:
        _mem0_client = NoopMem0Client()
        _mem0_available = False
        print(f"[Mem0] 初始化失败（{exc}），使用 NoopMem0Client（LTM 语义层不可用）")
        logger.warning(f"[Mem0] 初始化失败: {exc}，降级为 NoopMem0Client", exc_info=True)


def get_mem0_client() -> Any:
    """获取 Mem0 客户端单例（线程安全，FastAPI lifespan 保证初始化完成）。"""
    global _mem0_client
    if _mem0_client is None:
        _mem0_client = NoopMem0Client()
        logger.warning("[Mem0] get_mem0_client 在 init 前被调用，返回 NoopMem0Client")
    return _mem0_client


def is_mem0_available() -> bool:
    """返回 Mem0 是否真实可用（非 Noop）。"""
    return _mem0_available
