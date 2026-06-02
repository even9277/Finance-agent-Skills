from __future__ import annotations

from backend.integrations.agent_runtime.env import agent_root, ensure_agent_env_loaded

_AGENT_ROOT = ensure_agent_env_loaded()

from src.utils.logging_config import setup_logger  # noqa: E402
from src.tools.skill_trace import flush_trace_exporters, initialize_trace_runtime  # noqa: E402


async def init_mem0_client_runtime():
    from src.memory.mem0_client import init_mem0_client  # noqa: E402

    await init_mem0_client()


def ltm_worker_loop_runtime():
    from src.memory.ltm_worker import ltm_worker_loop  # noqa: E402

    return ltm_worker_loop


__all__ = [
    "agent_root",
    "flush_trace_exporters",
    "initialize_trace_runtime",
    "init_mem0_client_runtime",
    "ltm_worker_loop_runtime",
    "setup_logger",
]
