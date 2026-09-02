"""锁定当前记忆边界，并显式记录尚未实现的目标合同。"""

from __future__ import annotations

import asyncio
import ast
import inspect
import sys
from dataclasses import fields
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, cast, get_type_hints
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.chat.contracts import PreparedChatTurn  # noqa: E402
from backend.application.chat.use_case import ControlledChatUseCase  # noqa: E402
from backend.db.database import get_db  # noqa: E402
from backend.middleware import auth as auth_middleware  # noqa: E402
from backend.middleware.auth import AuthContext, require_auth  # noqa: E402
from backend.routers import memory as memory_router  # noqa: E402
from backend.application.memory.observability import MemoryStage  # noqa: E402
from src.memory import mem0_client  # noqa: E402
from src.memory.memory_service import MemoryService  # noqa: E402

TARGET_GAP = pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="#24：目标记忆合同尚未迁移；实现后必须移除 xfail 并补正式验收",
)


class _OwnerLookupResult:
    """模拟项目权威记录返回的归属信息，不信任 Provider metadata。"""

    def fetchone(self) -> SimpleNamespace:
        """返回属于另一名虚拟用户的权威记录。"""
        return SimpleNamespace(
            _mapping={
                "id": "memory-cross-user",
                "user_id": "fixture-user-b",
                "status": "ACTIVE",
            }
        )

    def fetchall(self) -> list[SimpleNamespace]:
        """返回用于批量后过滤的权威记录列表。"""
        return [self.fetchone()]


class _OwnerLookupSession:
    """仅用于所有权负例的最小异步数据库替身。"""

    async def execute(self, *_args: object, **_kwargs: object) -> _OwnerLookupResult:
        """返回固定的跨用户权威记录。"""
        return _OwnerLookupResult()


@pytest.mark.contract
def test_memory_access_rejects_a_different_authenticated_user() -> None:
    """确认真实记忆路由不能越过 JWT 身份读取其他用户记忆。"""
    auth = AuthContext(
        account_id="fixture-account-a",
        username="fixture-user-a",
        user_id="fixture-user-a",
    )
    app = FastAPI()
    app.include_router(memory_router.router, prefix="/api/memory")
    profile_reader = AsyncMock()
    stats_reader = AsyncMock()

    async def override_auth() -> AuthContext:
        return auth

    async def override_db() -> Any:
        yield cast(AsyncSession, _OwnerLookupSession())

    app.dependency_overrides[require_auth] = override_auth
    app.dependency_overrides[get_db] = override_db
    with (
        patch.object(auth_middleware.settings, "auth_enabled", True),
        patch.object(memory_router.memory_service, "get_user_profile", new=profile_reader),
        patch.object(memory_router.memory_service, "get_memory_stats", new=stats_reader),
    ):
        with TestClient(app) as client:
            response = client.get(
                "/api/memory/profile",
                params={"user_id": "fixture-user-b"},
            )

    assert response.status_code == 403
    profile_reader.assert_not_awaited()
    stats_reader.assert_not_awaited()


@pytest.mark.contract
def test_bulk_forget_requires_explicit_confirmation_before_service_call() -> None:
    """确认旧 API 在缺少确认参数时不会进入破坏性删除服务。"""

    async def run_case() -> None:
        deletion = AsyncMock()
        with (
            patch.object(memory_router.memory_service, "delete_all_memories", new=deletion),
            pytest.raises(HTTPException) as error,
        ):
            await memory_router.delete_all_memories(
                user_id="fixture-user-memory",
                confirm=False,
                db=cast(AsyncSession, SimpleNamespace()),
            )
        assert error.value.status_code == 400
        deletion.assert_not_awaited()

    asyncio.run(run_case())


@pytest.mark.contract
def test_prepared_turn_exposes_typed_working_state() -> None:
    """确认 Repository 合同把版本化 Working State 交给唯一聊天用例。"""
    field_names = {item.name for item in fields(PreparedChatTurn)}
    assert "working_state" in field_names
    working_state_type = get_type_hints(PreparedChatTurn)["working_state"]
    working_state_fields = {item.name for item in fields(working_state_type)}
    assert {"active_entity", "constraints", "reply_preference_hint"}.issubset(
        working_state_fields
    )
    assert {"state_version", "version"}.intersection(working_state_fields)


@pytest.mark.contract
def test_chat_use_case_enqueues_compaction_after_a_committed_turn() -> None:
    """目标触发器：公开入口委托的共享核心必须在提交后进入压缩边界。"""
    public_source = dedent(inspect.getsource(ControlledChatUseCase.execute))
    public_tree = ast.parse(public_source)
    public_awaited_calls = [
        node.value.func.attr
        for node in ast.walk(public_tree)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
    ]
    assert public_awaited_calls == ["_execute"]

    core_source = dedent(inspect.getsource(ControlledChatUseCase._execute))
    core_tree = ast.parse(core_source)
    awaited_calls = [
        node.value.func.attr
        for node in ast.walk(core_tree)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
    ]
    compaction_calls = {
        "maybe_enqueue_compaction",
        "enqueue_compaction",
        "enqueue_compaction_task",
    }

    assert compaction_calls.intersection(awaited_calls)
    commit_index = awaited_calls.index("commit")
    compaction_index = next(
        index for index, name in enumerate(awaited_calls) if name in compaction_calls
    )
    assert commit_index < compaction_index


@pytest.mark.contract
def test_model_inference_cannot_directly_write_high_impact_profile() -> None:
    """目标合同：模型推断的风险等级只能进入候选池，不能直写画像。"""

    async def run_case() -> None:
        module = sys.modules[MemoryService.__module__]
        upsert = AsyncMock()
        with patch.object(module, "_upsert_profile_field", new=upsert):
            result = await MemoryService.update_profile_field(
                user_id="fixture-user-memory",
                field="risk_level",
                value="aggressive",
                source="chat_inferred",
            )
        upsert.assert_not_awaited()
        assert result.requires_confirmation is True
        assert result.applied is False

    asyncio.run(run_case())


@pytest.mark.contract
@TARGET_GAP
def test_memory_update_authorizes_owner_before_provider_mutation() -> None:
    """目标合同：按 memory_id 更新前必须从权威记录校验所属用户。"""

    async def run_case() -> None:
        client = SimpleNamespace(update=AsyncMock(return_value={"updated": True}))
        parameters = inspect.signature(MemoryService.update_memory).parameters
        assert "db_session" in parameters
        update_memory = cast(
            Callable[..., Awaitable[bool]],
            MemoryService.update_memory,
        )
        with (
            patch.object(mem0_client, "is_mem0_available", return_value=True),
            patch.object(mem0_client, "get_mem0_client", return_value=client),
        ):
            updated = await update_memory(
                user_id="fixture-user-a",
                memory_id="memory-owned-by-fixture-user-b",
                content="不应越权更新",
                metadata={},
                db_session=cast(AsyncSession, _OwnerLookupSession()),
            )

        assert updated is False
        client.update.assert_not_awaited()

    asyncio.run(run_case())


@pytest.mark.contract
@TARGET_GAP
def test_semantic_results_are_post_filtered_by_authoritative_user_scope() -> None:
    """目标合同：Provider 即使返回跨用户结果，权威后过滤也必须丢弃。"""

    async def run_case() -> None:
        client = SimpleNamespace(
            search=AsyncMock(
                return_value=[
                    {
                        "id": "memory-cross-user",
                        "memory": "用户关注半导体",
                        "score": 0.99,
                        "metadata": {
                            "user_id": "fixture-user-b",
                            "category": "sector_focus",
                            "source": "ui",
                            "active": True,
                        },
                    }
                ]
            )
        )
        parameters = inspect.signature(MemoryService.search_semantic).parameters
        assert "db_session" in parameters
        search_semantic = cast(
            Callable[..., Awaitable[list[dict[str, object]]]],
            MemoryService.search_semantic,
        )
        with (
            patch.object(mem0_client, "is_mem0_available", return_value=True),
            patch.object(mem0_client, "get_mem0_client", return_value=client),
        ):
            results = await search_semantic(
                user_id="fixture-user-a",
                query="我关注什么板块",
                categories=["sector_focus"],
                sources=["ui"],
                db_session=cast(AsyncSession, _OwnerLookupSession()),
            )

        assert results == []

    asyncio.run(run_case())


@pytest.mark.contract
def test_natural_language_memory_command_has_an_application_owner() -> None:
    """目标触发器：聊天中的记忆指令必须有独立应用模块与公开用例。"""
    command_module = PROJECT_ROOT / "backend" / "application" / "memory" / "commands.py"
    assert command_module.is_file()
    tree = ast.parse(command_module.read_text(encoding="utf-8"))
    public_owners = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }
    assert public_owners


@pytest.mark.contract
@TARGET_GAP
def test_targeted_delete_exposes_lifecycle_and_consistency_status() -> None:
    """目标合同：删除结果必须暴露权威状态与派生索引一致性状态。"""

    async def run_case() -> None:
        enqueue = AsyncMock()
        with patch.object(MemoryService, "enqueue_explicit_delete", new=enqueue):
            result = await MemoryService.delete_memory(
                user_id="fixture-user-memory",
                memory_id="fixture-memory-delete",
                db_session=cast(AsyncSession, _OwnerLookupSession()),
            )

        enqueue.assert_awaited_once()
        assert not isinstance(result, bool)
        assert getattr(result, "status", None) in {"INACTIVE", "DELETE_PENDING"}
        assert getattr(result, "consistency_status", None) in {
            "PENDING",
            "CONSISTENT",
        }

    asyncio.run(run_case())


@pytest.mark.contract
def test_memory_trace_declares_stable_foreground_and_background_stages() -> None:
    """正式合同：所有记忆阶段必须来自唯一的低基数枚举。"""
    required_stages = {
        "memory.preflight",
        "memory.state.extract",
        "memory.state.merge",
        "memory.compact",
        "memory.candidate.extract",
        "memory.candidate.govern",
        "memory.index",
        "memory.retrieve",
        "memory.inject",
        "memory.mutate",
        "memory.delete",
        "memory.cache",
        "memory.worker",
    }
    assert {stage.value for stage in MemoryStage} == required_stages
