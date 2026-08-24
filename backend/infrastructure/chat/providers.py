"""实现受控工作流使用的真实 LLM、Tushare 和日志端口。"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, cast

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from backend.config import settings
from src.conversation.contracts import (
    EvidenceFact,
    ModelSynthesisRequest,
    ToolCall,
    ToolObservation,
    WorkflowEvent,
)
from src.conversation.errors import ToolPermanentError, ToolTimeoutError, ToolTransientError
from src.tools.chat_tushare_tools import get_tushare_toolkit

logger = logging.getLogger(__name__)


def _jsonable(value: Any) -> Any:
    """把不可变领域合同转换为仅用于模型输入的安全 JSON 值。"""
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(item) for key, item in asdict(cast(Any, value)).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


class OpenAICompatibleModelProvider:
    """通过现有 OpenAI-compatible 配置生成受证据约束的回答。"""

    def __init__(self) -> None:
        if not all(
            (
                settings.openai_compatible_api_key,
                settings.openai_compatible_base_url,
                settings.chat_skill_synthesis_model or settings.openai_compatible_model,
            )
        ):
            raise RuntimeError("LLM provider configuration is incomplete")
        self._model_name = (
            settings.chat_skill_synthesis_model or settings.openai_compatible_model
        )
        self._client = ChatOpenAI(
            model=self._model_name,
            api_key=SecretStr(settings.openai_compatible_api_key),
            base_url=settings.openai_compatible_base_url,
            temperature=0.2,
            timeout=30,
            max_retries=1,
        )

    async def synthesize(self, request: ModelSynthesisRequest) -> str:
        """只把 AnswerContextPack 中已验收内容发送给模型。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        payload = json.dumps(_jsonable(request.context), ensure_ascii=False)
        response = await self._client.ainvoke(
            [
                SystemMessage(content=request.system_prompt),
                HumanMessage(content=f"请根据以下结构化证据回答：\n{payload}"),
            ]
        )
        content = response.content
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, default=str)


class TushareToolProvider:
    """只执行治理目录允许且已由 Validator 验收的 Tushare 只读工具。"""

    def __init__(self) -> None:
        self._tools = {str(tool.name): tool for tool in get_tushare_toolkit()}

    async def execute(self, call: ToolCall) -> ToolObservation:
        """调用指定只读工具并归一化为 Evidence facts。

        Args:
            call: Executor 生成的已授权调用。

        Returns:
            不携带任意 DataFrame 或 Provider 对象的领域观察。

        Raises:
            ToolPermanentError: 工具未知或 Provider 返回不可重试错误。
            ToolTimeoutError: Provider 明确返回超时。
            ToolTransientError: Provider 明确返回限流或临时不可用。
        """
        tool = self._tools.get(call.tool_name)
        if tool is None:
            raise ToolPermanentError("tool is not registered")
        arguments = {item.name: item.value for item in call.arguments}
        payload = await tool.ainvoke(arguments)
        if not isinstance(payload, dict):
            raise ToolPermanentError("tool returned an invalid envelope")
        if not payload.get("ok"):
            error = str(payload.get("error") or "tool failed").lower()
            if "timeout" in error or "timed out" in error:
                raise ToolTimeoutError("tushare tool timeout")
            if "rate" in error or "tempor" in error or "频率" in error:
                raise ToolTransientError("tushare tool transient failure")
            raise ToolPermanentError("tushare tool execution failed")

        facts = self._facts(payload.get("payload"))
        observed_at = self._observed_at(payload.get("trade_date"))
        source_api = str(payload.get("source_api") or call.tool_name)
        return ToolObservation(
            step_id=call.step_id,
            tool_name=call.tool_name,
            symbol=call.symbol,
            evidence_dimension=call.evidence_dimension,
            facts=facts,
            source=f"tushare:{source_api}",
            observed_at=observed_at,
            attempts=1,
        )

    @staticmethod
    def _facts(payload: Any) -> tuple[EvidenceFact, ...]:
        rows = payload if isinstance(payload, list) else [payload]
        first = next((item for item in rows if isinstance(item, dict)), {})
        facts: list[EvidenceFact] = []
        for key, value in first.items():
            if value is None or isinstance(value, (dict, list, tuple, set)):
                continue
            facts.append(EvidenceFact(key=str(key), value=str(value)))
        return tuple(facts[:40])

    @staticmethod
    def _observed_at(value: Any) -> date:
        text = str(value or "").strip()
        for pattern in ("%Y%m%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, pattern).date()
            except ValueError:
                continue
        return date.today()


class StructuredLoggingTraceSink:
    """在 M7 接入完整 Trace exporter 前提供稳定低风险结构化日志。"""

    def emit(self, event: WorkflowEvent) -> None:
        """记录阶段、关联标识和耗时，不记录问题、证据或回答正文。"""
        logger.info(
            "controlled_chat.stage trace_id=%s run_id=%s session_id=%s stage=%s "
            "status=%s elapsed_ms=%.2f error_code=%s",
            event.trace_id,
            event.run_id,
            event.session_id,
            event.stage.value,
            event.status.value,
            event.elapsed_ms,
            event.error_code.value if event.error_code is not None else None,
        )
