"""防止 D09 迁移后重新出现多套生产实体解析策略。"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.contract
def test_production_callers_do_not_define_private_entity_resolvers() -> None:
    """报告与 CLI 只能调用共享 Adapter，不得保留私有 Prompt/正则解析器。"""
    stock_resolver = (ROOT / "backend/services/stock_resolver.py").read_text(encoding="utf-8")
    agent_service = (ROOT / "backend/services/agent_service.py").read_text(encoding="utf-8")
    cli = (ROOT / "Financial-MCP-Agent/src/main.py").read_text(encoding="utf-8")

    assert "_LLM_EXTRACT_PROMPT" not in stock_resolver
    assert "def _llm_extract(" not in stock_resolver
    assert "os.getenv(" not in stock_resolver
    assert "load_dotenv(" not in stock_resolver
    assert "def extract_stock_info(" not in agent_service
    assert "def extract_stock_info(" not in cli
