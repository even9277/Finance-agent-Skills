"""实现可选的 OpenAI-compatible Skill routing metadata 重排适配器。"""

from __future__ import annotations

import json
from typing import Protocol, cast

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from backend.config import settings
from src.conversation.contracts import (
    SkillRerankRequest,
    SkillRerankResult,
    SkillRerankScore,
)
from src.conversation.ports import SkillRerankerPort
from src.prompts.chat.registry import load_skill_rerank_prompt


class _RerankScorePayload(BaseModel):
    """约束 Provider 返回的单候选结构。"""

    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=200)


class _RerankPayload(BaseModel):
    """约束 Provider 只返回有限候选分数。"""

    model_config = ConfigDict(extra="forbid")

    scores: tuple[_RerankScorePayload, ...] = Field(min_length=1, max_length=5)


class StructuredRerankClient(Protocol):
    """隔离模型 SDK，便于离线验证序列化边界和失败回退。"""

    def invoke(self, payload: dict[str, object]) -> object:
        """同步返回可由 `_RerankPayload` 校验的对象。"""
        ...


class SkillRerankAdapter:
    """把领域 top-K 候选转换为 Provider 输入并校验 typed 输出。"""

    def __init__(self, client: StructuredRerankClient) -> None:
        self._client = client

    def rerank(self, request: SkillRerankRequest) -> SkillRerankResult:
        """仅发送当前 query 和候选 routing metadata。

        Args:
            request: Retriever 已裁剪且最多五项的 typed 候选。

        Returns:
            已验证范围和字段的候选分数。

        Raises:
            ValueError: Provider 输出候选越界、重复或结构无效。
        """
        allowed_names = {item.skill_name for item in request.candidates}
        payload: dict[str, object] = {
            "query": request.query,
            "candidates": [
                {
                    "skill_name": item.skill_name,
                    "version": item.version,
                    "description": item.description,
                    "when_to_use": list(item.when_to_use),
                    "when_not_to_use": list(item.when_not_to_use),
                    "positive_examples": list(item.positive_examples),
                    "negative_examples": list(item.negative_examples),
                    "supported_entity_types": list(item.supported_entity_types),
                    "deterministic_score": item.score,
                }
                for item in request.candidates
            ],
        }
        raw = self._client.invoke(payload)
        if isinstance(raw, BaseModel):
            raw = cast(BaseModel, raw).model_dump(mode="json")
        parsed = _RerankPayload.model_validate(raw)
        returned_names = {item.skill_name for item in parsed.scores}
        if not returned_names <= allowed_names:
            raise ValueError("rerank provider returned an unknown Skill")
        if returned_names != allowed_names:
            raise ValueError("rerank provider omitted a top-k candidate")
        return SkillRerankResult(
            scores=tuple(
                SkillRerankScore(
                    skill_name=item.skill_name,
                    score=item.score,
                    reason=item.reason,
                )
                for item in parsed.scores
            )
        )


class _OpenAICompatibleRerankClient:
    """使用现有 OpenAI-compatible 配置调用结构化 rerank。"""

    def __init__(self) -> None:
        model_name = settings.skill_rerank_model or settings.chat_router_model
        if not all(
            (
                settings.openai_compatible_api_key,
                settings.openai_compatible_base_url,
                model_name,
            )
        ):
            raise RuntimeError("Skill rerank provider configuration is incomplete")
        client = ChatOpenAI(
            model=model_name,
            api_key=SecretStr(settings.openai_compatible_api_key),
            base_url=settings.openai_compatible_base_url,
            temperature=0.0,
            timeout=settings.skill_rerank_timeout_sec,
            max_retries=0,
        )
        self._structured = client.with_structured_output(_RerankPayload)
        self._prompt = load_skill_rerank_prompt()

    def invoke(self, payload: dict[str, object]) -> object:
        """发送不含历史、正文、工具或记忆的最小结构化请求。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        return self._structured.invoke(
            (
                SystemMessage(content=self._prompt),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
            )
        )


def build_skill_reranker() -> SkillRerankerPort | None:
    """按 typed Settings 构建可选 reranker；默认关闭且不初始化模型。"""
    if settings.skill_rerank_provider == "disabled":
        return None
    return SkillRerankAdapter(_OpenAICompatibleRerankClient())


__all__ = ["SkillRerankAdapter", "StructuredRerankClient", "build_skill_reranker"]
