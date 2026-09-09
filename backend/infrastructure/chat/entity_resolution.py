"""实现共享实体解析器使用的外部模型与权威目录 Adapter。"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Literal, Protocol, cast

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from backend.config import settings
from src.conversation.contracts import (
    Entity,
    EntityModelRequest,
    EntityModelResolution,
    EntityType,
)
from src.conversation.entity import AuthoritativeEntityResolver
from src.conversation.errors import (
    EntityCatalogUnavailableError,
    EntityModelContractError,
    EntityModelUnavailableError,
)
from src.prompts.chat.registry import (
    load_entity_resolution_prompt,
    load_entity_resolution_repair_prompt,
)
from src.tools.tushare_client import get_tushare_client

_STOCK_SYMBOL_PATTERN = re.compile(r"^(?P<digits>\d{6})[.](?P<exchange>SH|SZ)$")


@lru_cache(maxsize=1)
def get_entity_resolver() -> AuthoritativeEntityResolver:
    """返回跨聊天与报告入口共享的进程级实体解析器。

    Returns:
        已注入受控模型、Tushare 目录和集中阈值的唯一 Resolver 实例。

    Notes:
        进程级复用让 Catalog 的正/负 TTL 缓存跨请求生效。测试如需替换
        Provider，应 patch 本函数或在隔离后调用 `cache_clear()`。
    """
    return AuthoritativeEntityResolver(
        model=OpenAICompatibleEntityResolutionModel(),
        catalog=TushareEntityCatalog(
            client=get_tushare_client(settings.tushare_token),
            ttl_seconds=settings.entity_catalog_ttl_sec,
        ),
        fuzzy_threshold=settings.entity_fuzzy_threshold,
        fuzzy_margin=settings.entity_fuzzy_margin,
    )


class _AsyncChatClient(Protocol):
    """限制模型 Adapter 只依赖异步消息调用。"""

    async def ainvoke(self, input: Any) -> Any:
        """返回包含文本 `content` 的供应商响应。"""
        ...


class _EntityCandidatePayload(BaseModel):
    """模型允许提出的单个实体候选。"""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=2, max_length=64)
    entity_type: EntityType
    confidence: float = Field(ge=0.0, le=1.0)


class _EntityResolutionPayload(BaseModel):
    """`entity-resolution-v1` 的严格模型输出 envelope。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["entity-resolution-v1"]
    candidates: tuple[_EntityCandidatePayload, ...] = Field(max_length=3)


class OpenAICompatibleEntityResolutionModel:
    """调用 OpenAI-compatible 模型提出有限实体候选并严格解析。

    Args:
        client: 可选已构造异步模型客户端；测试使用 fake，生产按 Settings 创建。
        timeout_sec: 单次模型调用超时秒数。
        repair_attempts: JSON 语法错误允许的修复次数，只允许 0 或 1。

    Notes:
        该 Adapter 只保证结构，不确认证券真实性。领域 Resolver 必须再通过
        `EntityCatalogPort` 回查候选，才能形成 canonical entity。
    """

    def __init__(
        self,
        *,
        client: _AsyncChatClient | None = None,
        timeout_sec: float | None = None,
        repair_attempts: int | None = None,
    ) -> None:
        effective_timeout = (
            float(settings.entity_resolution_timeout_sec)
            if timeout_sec is None
            else float(timeout_sec)
        )
        effective_repairs = (
            settings.entity_resolution_repair_attempts
            if repair_attempts is None
            else repair_attempts
        )
        if effective_timeout <= 0:
            raise ValueError("timeout_sec must be positive")
        if effective_repairs not in {0, 1}:
            raise ValueError("repair_attempts must be zero or one")
        # 确定性命中不得因模型网络栈或代理可选依赖而失败；首次兜底时再构造客户端。
        self._client = client
        self._timeout_sec = effective_timeout
        self._repair_attempts = effective_repairs
        self._prompt = load_entity_resolution_prompt()
        self._repair_prompt = load_entity_resolution_repair_prompt()

    async def resolve(self, request: EntityModelRequest) -> EntityModelResolution:
        """提出最多三个严格候选，并仅对 JSON 语法错误修复一次。

        Args:
            request: 只包含当前轮文本和允许实体类型的最小领域请求。

        Returns:
            已通过 Pydantic 严格结构校验的领域候选和实际调用预算。

        Raises:
            EntityModelUnavailableError: Provider 超时、限流、连接或响应类型异常。
            EntityModelContractError: schema 不合法，或一次语法修复后仍无法解析。
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        request_payload = json.dumps(
            {
                "message": request.message,
                "allowed_types": [item.value for item in request.allowed_types],
            },
            ensure_ascii=False,
        )
        raw = await self._invoke(
            (
                SystemMessage(content=self._prompt),
                HumanMessage(content=request_payload),
            )
        )
        try:
            parsed = _EntityResolutionPayload.model_validate_json(raw)
            model_calls, repair_count = 1, 0
        except ValidationError as exc:
            if not _is_json_syntax_error(exc) or self._repair_attempts == 0:
                raise EntityModelContractError(
                    "entity model output violates schema",
                    model_calls=1,
                ) from exc
            repair_payload = json.dumps(
                {
                    "invalid_output": raw[:2_000],
                    "required_schema_version": "entity-resolution-v1",
                },
                ensure_ascii=False,
            )
            try:
                repaired = await self._invoke(
                    (
                        SystemMessage(content=self._repair_prompt),
                        HumanMessage(content=repair_payload),
                    )
                )
            except EntityModelUnavailableError as repair_provider_exc:
                raise EntityModelUnavailableError(
                    "entity model syntax repair provider failed",
                    model_calls=2,
                    repair_count=1,
                ) from repair_provider_exc
            try:
                parsed = _EntityResolutionPayload.model_validate_json(repaired)
            except ValidationError as repair_exc:
                raise EntityModelContractError(
                    "entity model syntax repair failed",
                    model_calls=2,
                    repair_count=1,
                ) from repair_exc
            model_calls, repair_count = 2, 1

        if any(item.entity_type not in request.allowed_types for item in parsed.candidates):
            raise EntityModelContractError(
                "entity model returned a disallowed entity type",
                model_calls=model_calls,
                repair_count=repair_count,
            )

        candidates = tuple(
            Entity(
                symbol=_normalize_model_symbol(item.symbol),
                name=item.name.strip(),
                entity_type=item.entity_type,
            )
            for item in parsed.candidates
        )
        confidence = max((item.confidence for item in parsed.candidates), default=0.0)
        return EntityModelResolution(
            candidates=candidates,
            confidence=confidence,
            model_calls=model_calls,
            repair_count=repair_count,
        )

    async def _invoke(self, messages: object) -> str:
        """执行一次无 SDK 自动重试的有界调用并只返回文本。"""
        try:
            if self._client is None:
                self._client = _build_entity_chat_client()
            response = await asyncio.wait_for(
                self._client.ainvoke(messages),
                timeout=self._timeout_sec,
            )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise EntityModelUnavailableError("entity model timed out", model_calls=1) from exc
        except Exception as exc:
            raise EntityModelUnavailableError("entity model provider failed", model_calls=1) from exc
        content = getattr(response, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise EntityModelUnavailableError("entity model returned no text", model_calls=1)
        return content.strip()


def _build_entity_chat_client() -> _AsyncChatClient:
    """按集中 Settings 构造零自动重试的生产模型客户端。"""
    model_name = settings.chat_resolver_model or settings.openai_compatible_model
    if not all(
        (
            settings.openai_compatible_api_key,
            settings.openai_compatible_base_url,
            model_name,
        )
    ):
        raise RuntimeError("entity model provider configuration is incomplete")
    return cast(
        _AsyncChatClient,
        ChatOpenAI(
            model=model_name,
            api_key=SecretStr(settings.openai_compatible_api_key),
            base_url=settings.openai_compatible_base_url,
            temperature=0.0,
            timeout=settings.entity_resolution_timeout_sec,
            max_retries=0,
        ),
    )


def _is_json_syntax_error(exc: ValidationError) -> bool:
    """仅把 JSON tokenizer/parser 错误识别为可修复语法失败。"""
    return bool(exc.errors()) and all(item.get("type") == "json_invalid" for item in exc.errors())


def _normalize_model_symbol(symbol: str) -> str:
    """规范化模型候选，同时保留领域层约定的板块前缀。"""
    normalized = symbol.strip()
    if normalized.lower().startswith("sector:"):
        return f"sector:{normalized.split(':', 1)[1].strip()}"
    return normalized.upper()


class _TushareCatalogClient(Protocol):
    """限制目录 Adapter 只依赖 Tushare 股票基础信息调用。"""

    async def stock_basic(self, **kwargs: object) -> object:
        """返回股票基础信息的 DataFrame 或记录序列。"""
        ...


class TushareEntityCatalog:
    """通过 Tushare 基础信息回查 A 股 canonical entity。

    Args:
        client: 已由基础设施装配的 Tushare 异步客户端。
        ttl_seconds: 单个代码正/负查询结果在进程内的缓存秒数。

    Notes:
        该 Adapter 只读取公开证券主数据，不记录 token、查询原文或完整响应。
        基金、指数和行业板块暂由领域层本地目录承担，后续可扩展同一 Port。
    """

    def __init__(self, *, client: _TushareCatalogClient, ttl_seconds: float = 300.0) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, Entity | None]] = {}

    async def lookup(self, symbol: str) -> Entity | None:
        """按规范代码返回已上市 A 股实体。

        Args:
            symbol: `000001.SZ` 或 `600519.SH` 形式的 canonical symbol。

        Returns:
            目录存在且字段一致时返回股票实体；无记录或已非上市状态时返回 `None`。

        Raises:
            EntityCatalogUnavailableError: Tushare 调用或响应结构无法安全解释。
        """
        normalized = symbol.strip().upper()
        if _STOCK_SYMBOL_PATTERN.fullmatch(normalized) is None:
            return None
        now = time.monotonic()
        cached = self._cache.get(normalized)
        if cached is not None and cached[0] > now:
            return cached[1]

        try:
            payload = await self._client.stock_basic(
                ts_code=normalized,
                list_status="L",
                fields="ts_code,name,list_status",
            )
            rows = _catalog_rows(payload)
        except EntityCatalogUnavailableError:
            raise
        except Exception as exc:
            raise EntityCatalogUnavailableError("entity catalog query failed") from exc

        entity = _stock_entity(normalized, rows)
        self._cache[normalized] = (now + self._ttl_seconds, entity)
        return entity


def _catalog_rows(payload: object) -> list[Mapping[str, Any]]:
    """把 DataFrame、单条 Mapping 或记录序列归一化为安全行。"""
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        return [payload]
    if isinstance(payload, list):
        if not all(isinstance(item, Mapping) for item in payload):
            raise EntityCatalogUnavailableError("entity catalog returned invalid rows")
        return list(payload)
    to_dict = getattr(payload, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
        if isinstance(records, list) and all(isinstance(item, Mapping) for item in records):
            return records
    raise EntityCatalogUnavailableError("entity catalog returned an invalid payload")


def _stock_entity(symbol: str, rows: list[Mapping[str, Any]]) -> Entity | None:
    """从目录行中选择与请求代码一致且仍上市的唯一股票。"""
    matches = [
        row
        for row in rows
        if str(row.get("ts_code") or "").strip().upper() == symbol
        and str(row.get("list_status") or "L").strip().upper() == "L"
        and str(row.get("name") or "").strip()
    ]
    if len(matches) != 1:
        return None
    return Entity(
        symbol=symbol,
        name=str(matches[0]["name"]).strip(),
        entity_type=EntityType.STOCK,
    )
