from __future__ import annotations

from backend.integrations.agent_runtime.env import ensure_agent_env_loaded

_AGENT_ROOT = ensure_agent_env_loaded()

from src.agents.fundamental_agent import fundamental_agent  # noqa: E402
from src.agents.news_agent import news_agent  # noqa: E402
from src.agents.summary_agent import summary_agent  # noqa: E402
from src.agents.technical_agent import technical_agent  # noqa: E402
from src.agents.value_agent import value_agent  # noqa: E402
from src.agents.stm_nodes import prepare_summary_context, maybe_summarize_state  # noqa: E402
from src.utils.execution_logger import (  # noqa: E402
    finalize_execution_logger,
    get_execution_logger,
    initialize_execution_logger,
)
from src.utils.logging_config import setup_logger  # noqa: E402
from src.utils.state_definition import AgentState, make_stm_defaults  # noqa: E402


def get_memory_nodes():
    from src.agents.memory_nodes import memory_read_node, memory_write_node  # noqa: E402

    return memory_read_node, memory_write_node
