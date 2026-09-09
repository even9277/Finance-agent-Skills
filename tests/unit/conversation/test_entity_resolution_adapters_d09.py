"""锁定 D09 模型与 Tushare 目录 Adapter 的边界合同。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from unittest.mock import patch

from backend.config import Settings
from backend.infrastructure.chat.entity_resolution import (
    OpenAICompatibleEntityResolutionModel,
    TushareEntityCatalog,
)
from src.conversation.contracts import EntityModelRequest, EntityType
from src.conversation.errors import EntityModelContractError, EntityModelUnavailableError


class _FakeChatModel:
    """按顺序返回模型文本并记录实际调用预算。"""

    def __init__(self, *responses: str, delay_sec: float = 0.0) -> None:
        self._responses = list(responses)
        self._delay_sec = delay_sec
        self.calls = 0

    async def ainvoke(self, input: object) -> SimpleNamespace:
        """模拟一次 Provider 调用。"""
        del input
        self.calls += 1
        if self._delay_sec:
            await asyncio.sleep(self._delay_sec)
        return SimpleNamespace(content=self._responses.pop(0))


class _FakeTushareClient:
    """返回固定股票目录行并记录外部查询次数。"""

    def __init__(self, rows: list[dict[str, str]]) -> None:
        self._rows = rows
        self.calls: list[dict[str, object]] = []

    async def stock_basic(self, **kwargs: object) -> list[dict[str, str]]:
        """模拟 Tushare `stock_basic` 只读结果。"""
        self.calls.append(kwargs)
        return list(self._rows)


def _valid_payload() -> str:
    return (
        '{"schema_version":"entity-resolution-v1","candidates":['
        '{"symbol":"601012.SH","name":"隆基绿能",'
        '"entity_type":"stock","confidence":0.96}]}'
    )


@pytest.mark.unit
def test_model_adapter_accepts_strict_schema_without_repair() -> None:
    """合法 schema 应只调用一次模型并返回 typed candidate。"""
    client = _FakeChatModel(_valid_payload())
    adapter = OpenAICompatibleEntityResolutionModel(
        client=client,
        timeout_sec=1.0,
        repair_attempts=1,
    )

    result = asyncio.run(adapter.resolve(EntityModelRequest(message="分析隆基绿能")))

    assert result.candidates[0].symbol == "601012.SH"
    assert result.model_calls == 1
    assert result.repair_count == 0
    assert client.calls == 1


@pytest.mark.unit
def test_model_adapter_preserves_canonical_sector_prefix() -> None:
    """模型大小写不得破坏领域层约定的 `sector:` canonical symbol。"""
    payload = (
        '{"schema_version":"entity-resolution-v1","candidates":['
        '{"symbol":"SECTOR:新能源","name":"新能源",'
        '"entity_type":"sector","confidence":0.91}]}'
    )
    adapter = OpenAICompatibleEntityResolutionModel(
        client=_FakeChatModel(payload),
        timeout_sec=1.0,
        repair_attempts=1,
    )

    result = asyncio.run(adapter.resolve(EntityModelRequest(message="新能源行业怎么样")))

    assert result.candidates[0].symbol == "sector:新能源"


@pytest.mark.unit
def test_model_adapter_repairs_malformed_json_once() -> None:
    """只有 JSON 语法错误允许一次修复调用。"""
    client = _FakeChatModel("not-json", _valid_payload())
    adapter = OpenAICompatibleEntityResolutionModel(
        client=client,
        timeout_sec=1.0,
        repair_attempts=1,
    )

    result = asyncio.run(adapter.resolve(EntityModelRequest(message="分析隆基绿能")))

    assert result.model_calls == 2
    assert result.repair_count == 1
    assert client.calls == 2


@pytest.mark.unit
def test_model_adapter_does_not_repair_schema_semantics() -> None:
    """可解析但多字段/错类型的合同错误不得再次调用模型。"""
    invalid = (
        '{"schema_version":"entity-resolution-v1","candidates":['
        '{"symbol":"601012.SH","name":"隆基绿能",'
        '"entity_type":"stock","confidence":0.96,"unexpected":"unsafe"}]}'
    )
    client = _FakeChatModel(invalid, _valid_payload())
    adapter = OpenAICompatibleEntityResolutionModel(
        client=client,
        timeout_sec=1.0,
        repair_attempts=1,
    )

    with pytest.raises(EntityModelContractError) as captured:
        asyncio.run(adapter.resolve(EntityModelRequest(message="分析隆基绿能")))

    assert client.calls == 1
    assert captured.value.model_calls == 1
    assert captured.value.repair_count == 0


@pytest.mark.unit
def test_model_adapter_stops_after_one_failed_syntax_repair() -> None:
    """连续语法错误必须在第二次调用后稳定失败。"""
    client = _FakeChatModel("not-json", "still-not-json")
    adapter = OpenAICompatibleEntityResolutionModel(
        client=client,
        timeout_sec=1.0,
        repair_attempts=1,
    )

    with pytest.raises(EntityModelContractError) as captured:
        asyncio.run(adapter.resolve(EntityModelRequest(message="分析隆基绿能")))

    assert client.calls == 2
    assert captured.value.model_calls == 2
    assert captured.value.repair_count == 1


@pytest.mark.unit
def test_model_adapter_counts_provider_failure_during_syntax_repair() -> None:
    """第二次调用失败也必须报告真实总调用数和 repair 次数。"""

    class _RepairProviderFailure:
        """首次返回坏 JSON，第二次模拟 Provider 失败。"""

        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, input: object) -> SimpleNamespace:
            """按调用顺序返回语法错误或抛出网络错误。"""
            del input
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(content="not-json")
            raise RuntimeError("provider unavailable")

    client = _RepairProviderFailure()
    adapter = OpenAICompatibleEntityResolutionModel(
        client=client,
        timeout_sec=1.0,
        repair_attempts=1,
    )

    with pytest.raises(EntityModelUnavailableError) as captured:
        asyncio.run(adapter.resolve(EntityModelRequest(message="分析隆基绿能")))

    assert client.calls == 2
    assert captured.value.model_calls == 2
    assert captured.value.repair_count == 1


@pytest.mark.unit
def test_model_adapter_rejects_candidate_outside_allowed_types() -> None:
    """Prompt 约束不能替代代码侧类型白名单。"""
    payload = (
        '{"schema_version":"entity-resolution-v1","candidates":['
        '{"symbol":"000300.SH","name":"沪深300",'
        '"entity_type":"index","confidence":0.91}]}'
    )
    adapter = OpenAICompatibleEntityResolutionModel(
        client=_FakeChatModel(payload),
        timeout_sec=1.0,
        repair_attempts=1,
    )

    with pytest.raises(EntityModelContractError) as captured:
        asyncio.run(
            adapter.resolve(
                EntityModelRequest(message="找股票", allowed_types=(EntityType.STOCK,))
            )
        )

    assert captured.value.model_calls == 1
    assert captured.value.repair_count == 0


@pytest.mark.unit
def test_model_adapter_timeout_is_stable_and_bounded() -> None:
    """Provider 超时应转为稳定异常且不自动追加整轮调用。"""
    client = _FakeChatModel(_valid_payload(), delay_sec=0.05)
    adapter = OpenAICompatibleEntityResolutionModel(
        client=client,
        timeout_sec=0.001,
        repair_attempts=1,
    )

    with pytest.raises(EntityModelUnavailableError) as captured:
        asyncio.run(adapter.resolve(EntityModelRequest(message="分析隆基绿能")))

    assert client.calls == 1
    assert captured.value.model_calls == 1


@pytest.mark.unit
def test_tushare_catalog_normalizes_and_caches_authoritative_stock() -> None:
    """股票目录应返回 canonical entity，并避免 TTL 内重复外呼。"""
    client = _FakeTushareClient(
        [{"ts_code": "601012.SH", "name": "隆基绿能", "list_status": "L"}]
    )
    catalog = TushareEntityCatalog(client=client, ttl_seconds=60.0)

    first = asyncio.run(catalog.lookup("601012.SH"))
    second = asyncio.run(catalog.lookup("601012.SH"))

    assert first == second
    assert first is not None
    assert first.symbol == "601012.SH"
    assert first.name == "隆基绿能"
    assert first.entity_type.value == "stock"
    assert len(client.calls) == 1


@pytest.mark.unit
def test_entity_resolution_settings_reject_unbounded_values() -> None:
    """模型修复预算和 fuzzy 门禁不得被部署配置绕过。"""
    with pytest.raises(ValidationError):
        Settings(entity_resolution_repair_attempts=2)
    with pytest.raises(ValidationError):
        Settings(entity_fuzzy_threshold=0.0)
    with pytest.raises(ValidationError):
        Settings(entity_fuzzy_margin=1.1)


@pytest.mark.unit
def test_model_adapter_does_not_build_provider_before_first_fallback_call() -> None:
    """构造共享 Resolver 时不得提前要求模型网络栈或代理依赖。"""
    with patch(
        "backend.infrastructure.chat.entity_resolution._build_entity_chat_client"
    ) as builder:
        OpenAICompatibleEntityResolutionModel(timeout_sec=1.0, repair_attempts=1)

    builder.assert_not_called()


@pytest.mark.unit
def test_model_adapter_maps_lazy_provider_build_failure_to_stable_error() -> None:
    """缺配置或代理依赖也必须遵守统一 Provider 失败语义。"""
    adapter = OpenAICompatibleEntityResolutionModel(timeout_sec=1.0, repair_attempts=1)

    with patch(
        "backend.infrastructure.chat.entity_resolution._build_entity_chat_client",
        side_effect=ImportError("optional proxy dependency unavailable"),
    ):
        with pytest.raises(EntityModelUnavailableError) as captured:
            asyncio.run(adapter.resolve(EntityModelRequest(message="分析隆基绿能")))

    assert captured.value.model_calls == 1
