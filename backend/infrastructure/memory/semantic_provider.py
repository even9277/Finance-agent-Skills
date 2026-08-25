"""实现确定性 pgvector Provider 与受控 Mem0 适配器。"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Float, cast, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.application.memory.retrieval import SemanticMemoryProvider, SemanticSearchHit
from backend.config import settings
from backend.db.models import MemorySemanticIndexRow

_semantic_provider: SemanticMemoryProvider | None = None


@dataclass(frozen=True, slots=True)
class SemanticProviderHealth:
    """Provider 健康状态，不包含连接串或用户内容。"""

    provider: str
    status: str
    dimensions: int


class DeterministicEmbeddingProvider:
    """使用稳定哈希向量提供零外部调用的离线嵌入。"""

    def __init__(self, dimensions: int = 1536) -> None:
        if dimensions < 8:
            raise ValueError("embedding dimensions must be at least 8")
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        """把文本 token 映射到归一化固定维度向量。"""
        vector = [0.0] * self.dimensions
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


class PgVectorSemanticProvider:
    """将记忆写入项目自有 pgvector 派生表，并支持离线 SQLite 回退计算。"""

    name = "pgvector"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        embedder: DeterministicEmbeddingProvider | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder or DeterministicEmbeddingProvider(settings.embed_dims)

    async def upsert(
        self,
        *,
        user_id: str,
        record_id: str,
        memory_version: int,
        category: str,
        content: str,
        metadata: dict[str, object],
    ) -> str:
        """按权威记录版本幂等更新派生向量行。"""
        async with self._session_factory() as db:
            row = await db.scalar(
                select(MemorySemanticIndexRow).where(
                    MemorySemanticIndexRow.user_id == user_id,
                    MemorySemanticIndexRow.memory_record_id == record_id,
                    MemorySemanticIndexRow.provider == self.name,
                    MemorySemanticIndexRow.memory_version == memory_version,
                )
            )
            if row is None:
                row = MemorySemanticIndexRow(
                    user_id=user_id,
                    memory_record_id=record_id,
                    provider=self.name,
                    provider_record_id=f"pgvector:{record_id}:{memory_version}",
                    memory_version=memory_version,
                    status="ACTIVE",
                    schema_version=settings.memory_index_schema_version,
                    category=category,
                    content=content,
                    embedding_model=settings.embed_model or settings.memory_embedding_provider,
                    embedding_dimensions=self._embedder.dimensions,
                    embedding=self._embedder.embed(content),
                    metadata_json=metadata,
                )
                db.add(row)
            else:
                row.status = "ACTIVE"
                row.category = category
                row.content = content
                row.embedding = self._embedder.embed(content)
                row.metadata_json = metadata
                row.last_error_code = None
            await db.commit()
            return row.provider_record_id

    async def delete(self, *, user_id: str, provider_record_id: str) -> None:
        """按用户和 Provider ID物理删除派生向量，权威行不受影响。"""
        async with self._session_factory() as db:
            await db.execute(
                delete(MemorySemanticIndexRow).where(
                    MemorySemanticIndexRow.user_id == user_id,
                    MemorySemanticIndexRow.provider == self.name,
                    MemorySemanticIndexRow.provider_record_id == provider_record_id,
                )
            )
            await db.commit()

    async def search(
        self,
        *,
        user_id: str,
        query: str,
        top_k: int,
        min_score: float,
    ) -> tuple[SemanticSearchHit, ...]:
        """在用户隔离和版本化索引范围内执行向量相似度召回。"""
        query_vector = self._embedder.embed(query)
        async with self._session_factory() as db:
            filters = (
                MemorySemanticIndexRow.user_id == user_id,
                MemorySemanticIndexRow.provider == self.name,
                MemorySemanticIndexRow.status == "ACTIVE",
                MemorySemanticIndexRow.embedding_dimensions == self._embedder.dimensions,
            )
            bind = db.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                # pgvector 的距离是标量；显式 cast 防止 TypeDecorator 沿用向量结果处理器。
                distance = cast(
                    MemorySemanticIndexRow.embedding.op("<=>")(query_vector),
                    Float,
                )
                result = await db.execute(
                    select(MemorySemanticIndexRow, distance.label("distance"))
                    .where(*filters)
                    .order_by(distance)
                    .limit(top_k)
                )
                rows = [(row, float(distance_value)) for row, distance_value in result.all()]
                scored = [(row, max(0.0, 1.0 - distance_value)) for row, distance_value in rows]
            else:
                rows = list(
                    (await db.execute(select(MemorySemanticIndexRow).where(*filters))).scalars()
                )
                scored = [(row, _cosine(query_vector, row.embedding)) for row in rows]
                scored.sort(key=lambda item: (-item[1], item[0].id))
                scored = scored[:top_k]
            return tuple(
                SemanticSearchHit(
                    provider_record_id=row.provider_record_id,
                    record_id=row.memory_record_id,
                    user_id=row.user_id,
                    memory_version=row.memory_version,
                    score=score,
                    provider=self.name,
                )
                for row, score in scored
                if score >= min_score
            )


class Mem0SemanticProvider:
    """把 Mem0 AsyncMemory 限定为带版本元数据的派生 Provider。"""

    name = "mem0"

    def __init__(self, client: Any) -> None:
        self._client = client

    async def upsert(
        self,
        *,
        user_id: str,
        record_id: str,
        memory_version: int,
        category: str,
        content: str,
        metadata: dict[str, object],
    ) -> str:
        """使用 ``infer=False`` 写入，禁止 Mem0 自主改变项目治理结论。"""
        response = await self._client.add(
            [{"role": "user", "content": content}],
            user_id=user_id,
            metadata={
                **metadata,
                "project_user_id": user_id,
                "memory_record_id": record_id,
                "memory_version": memory_version,
                "category": category,
                "schema_version": settings.memory_index_schema_version,
            },
            infer=False,
        )
        return _provider_id(response)

    async def delete(self, *, user_id: str, provider_record_id: str) -> None:
        """删除指定 Provider 记录；用户作用域由 Worker 预先校验。"""
        del user_id
        await self._client.delete(provider_record_id)

    async def search(
        self,
        *,
        user_id: str,
        query: str,
        top_k: int,
        min_score: float,
    ) -> tuple[SemanticSearchHit, ...]:
        """使用 Mem0 用户过滤，再把结果转换为项目安全命中合同。"""
        response = await self._client.search(
            query,
            top_k=top_k,
            threshold=min_score,
            filters={"user_id": user_id},
        )
        raw_results = response.get("results", []) if isinstance(response, dict) else response
        hits: list[SemanticSearchHit] = []
        for item in raw_results or []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") or {}
            returned_user_id = str(metadata.get("project_user_id") or item.get("user_id") or "")
            record_id = str(metadata.get("memory_record_id") or "")
            version = metadata.get("memory_version")
            if returned_user_id != user_id or not record_id or not isinstance(version, int):
                continue
            hits.append(
                SemanticSearchHit(
                    provider_record_id=str(item.get("id") or ""),
                    record_id=record_id,
                    user_id=returned_user_id,
                    memory_version=version,
                    score=float(item.get("score") or 0.0),
                    provider=self.name,
                )
            )
        return tuple(hits)


async def build_mem0_provider() -> Mem0SemanticProvider:
    """惰性初始化单进程 Mem0 AsyncMemory，避免禁用配置触发 Provider。"""
    from mem0 import AsyncMemory

    client = AsyncMemory.from_config(_mem0_config())
    return Mem0SemanticProvider(client)


def _mem0_config() -> dict[str, object]:
    """构造不输出凭据的 Mem0 pgvector 配置。"""
    return {
        "llm": {
            "provider": "openai",
            "config": {
                "model": settings.openai_compatible_model,
                "api_key": settings.openai_compatible_api_key,
                "openai_base_url": settings.openai_compatible_base_url,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": settings.embed_model or "text-embedding-3-small",
                "api_key": settings.openai_compatible_api_key,
                "openai_base_url": settings.openai_compatible_base_url,
                "embedding_dims": settings.embed_dims,
            },
        },
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "host": settings.pg_host,
                "port": settings.pg_port,
                "dbname": settings.pg_db,
                "user": settings.pg_user,
                "password": settings.pg_password,
                "collection_name": "finance_ltm_m6",
                "embedding_model_dims": settings.embed_dims,
            },
        },
    }


async def build_semantic_provider(
    session_factory: async_sessionmaker[AsyncSession],
) -> SemanticMemoryProvider | None:
    """按显式配置构造唯一语义 Provider；关闭时不导入 Mem0。"""
    if settings.memory_semantic_provider == "disabled":
        return None
    if settings.memory_semantic_provider == "deterministic":
        return PgVectorSemanticProvider(session_factory)
    return await build_mem0_provider()


async def initialize_semantic_provider(
    session_factory: async_sessionmaker[AsyncSession],
) -> SemanticMemoryProvider | None:
    """初始化并保存进程级唯一 Provider，供 Worker 与前台召回复用。"""
    global _semantic_provider
    _semantic_provider = await build_semantic_provider(session_factory)
    return _semantic_provider


def get_semantic_provider() -> SemanticMemoryProvider | None:
    """返回启动阶段创建的 Provider；未启用或启动失败时返回 ``None``。"""
    return _semantic_provider


def _provider_id(response: object) -> str:
    """从 Mem0 版本差异响应中提取稳定 Provider ID，缺失时拒绝建引用。"""
    if isinstance(response, dict):
        results = response.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            value = results[0].get("id")
            if value:
                return str(value)
        value = response.get("id")
        if value:
            return str(value)
    raise ValueError("MEM0_PROVIDER_ID_MISSING")


def _tokens(text: str) -> Iterable[str]:
    import re

    return re.findall(r"[a-z0-9_.-]+|[\u4e00-\u9fff]", text.lower())


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(0.0, min(1.0, numerator / (left_norm * right_norm)))
