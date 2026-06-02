from __future__ import annotations

from backend.integrations.agent_runtime.env import ensure_agent_env_loaded

_AGENT_ROOT = ensure_agent_env_loaded()

from src.utils.logging_config import setup_logger  # noqa: E402
from src.agents.skill_executor_node import execute_skill  # noqa: E402
from src.agents.query_rewriter import (  # noqa: E402
    _load_skill_doc_sections,
    rewrite_for_fallback,
    rewrite_for_sop,
    rewrite_for_tushare,
    rewrite_for_tushare_v2,
)
from src.agents.synthesis.synthesize_fallback import build_fallback_synthesis_prompt  # noqa: E402
from src.agents.synthesis.synthesize_sop import build_sop_synthesis_prompt  # noqa: E402
from src.agents.synthesis.synthesize_tushare import build_tushare_synthesis_prompt  # noqa: E402
from src.agents.entity_resolver_v2 import resolve_authoritative_entity  # noqa: E402
from src.agents.constraints_extractor import extract_constraints  # noqa: E402
from src.agents.reply_preference_extractor import extract_reply_preference  # noqa: E402
from src.agents.rewrite_context import RewriteContextPacket  # noqa: E402
from src.agents.skill_runner_v2 import run_sop_v2_pipeline, run_tushare_v2_pipeline  # noqa: E402
from src.agents.skill_router_node import (  # noqa: E402
    _build_executor_route_trace,
    registry_execution_policy_for_skill,
    route_chat_skill,
    rewrite_query_for_skill,
    skill_route_decision_from_dict,
    user_explicit_sop_decision,
)
from src.agents.tushare_plan_executor import execute_tushare_plan  # noqa: E402
from src.skills.skill_registry import get_skill_registry  # noqa: E402
from src.tools.skill_trace import (  # noqa: E402
    log_compaction_enqueue,
    log_degrade_transition,
    log_memory_enqueue,
    log_model_stage,
    log_reply_completed,
    log_router_decision,
    log_tool_plan,
    log_trace_finished,
    log_trace_started,
    new_trace_id,
    skill_trace_context,
    trace_span,
)
from src.tools.tushare_client import TushareClient, configure_tushare_client_factory  # noqa: E402
from src.memory.memory_service import MemoryService  # noqa: E402
from src.memory.mem0_schema import MemorySource  # noqa: E402
