"""实现 PostgreSQL 词法召回、Provider 语义召回和权威后过滤。"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.memory.retrieval import (
    MemoryRetrievalRequest,
    SemanticMemoryProvider,
    SemanticSearchHit,
)
from backend.db.models import MemoryRecordRow
from src.memory.contracts import (
    MemoryErrorCode,
    MemoryRecordStatus,
    RetrievalItem,
    RetrievalResult,
    RetrievalStatus,
)


class SqlAlchemyMemoryRetrievalRepository:
    """在一个请求会话内完成候选融合、生命周期过滤和 token 打包。"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        semantic_timeout_sec: float = 8.0,
        semantic_top_k: int = 20,
        semantic_min_score: float = 0.10,
    ) -> None:
        self._db = db
        self._semantic_timeout_sec = semantic_timeout_sec
        self._semantic_top_k = semantic_top_k
        self._semantic_min_score = semantic_min_score

    async def retrieve(
        self,
        request: MemoryRetrievalRequest,
        provider: SemanticMemoryProvider | None,
    ) -> RetrievalResult:
        """执行词法/语义融合，Provider 结果必须通过数据库权威校验。"""
        now = (request.now or datetime.now(UTC)).replace(tzinfo=None)
        rows = list(
            (
                await self._db.execute(
                    select(MemoryRecordRow).where(
                        MemoryRecordRow.user_id == request.user_id,
                        MemoryRecordRow.kind == "text",
                        MemoryRecordRow.status == MemoryRecordStatus.ACTIVE.value,
                        or_(
                            MemoryRecordRow.expires_at.is_(None),
                            MemoryRecordRow.expires_at > now,
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        lexical = {row.id: _lexical_score(request.query, row.content or "") for row in rows}
        lexical = {key: value for key, value in lexical.items() if value > 0}
        semantic: tuple[SemanticSearchHit, ...] = ()
        degraded: list[str] = []
        if provider is not None:
            try:
                semantic = await asyncio.wait_for(
                    provider.search(
                        user_id=request.user_id,
                        query=request.query,
                        top_k=max(request.top_k, self._semantic_top_k),
                        min_score=self._semantic_min_score,
                    ),
                    timeout=self._semantic_timeout_sec,
                )
            except Exception:
                degraded.append(provider.name)
        by_id = {row.id: row for row in rows}
        semantic_scores: dict[str, float] = {}
        reasons: dict[str, set[str]] = {}
        for hit in semantic:
            # Provider 返回的 user/version 只作为候选；最终以当前权威行重新核验。
            row = by_id.get(hit.record_id)
            if row is None or hit.user_id != request.user_id:
                continue
            if hit.memory_version != row.version:
                continue
            semantic_scores[row.id] = max(semantic_scores.get(row.id, 0.0), hit.score)
            reasons.setdefault(row.id, set()).add("semantic")
        combined_ids = set(lexical) | set(semantic_scores)
        ranked: list[tuple[float, str]] = []
        for record_id in combined_ids:
            lexical_score = lexical.get(record_id, 0.0)
            semantic_score = semantic_scores.get(record_id, 0.0)
            if lexical_score and semantic_score:
                score = 0.55 * semantic_score + 0.45 * lexical_score
                reasons.setdefault(record_id, set()).add("lexical")
            elif semantic_score:
                score = 0.55 * semantic_score
            else:
                score = 0.45 * lexical_score
                reasons.setdefault(record_id, set()).add("lexical")
            ranked.append((min(1.0, max(0.0, score)), record_id))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        items: list[RetrievalItem] = []
        token_count = 0
        for score, record_id in ranked[: request.top_k]:
            row = by_id[record_id]
            content = (row.content or "").strip()
            item_tokens = _estimate_tokens(content)
            if not content or token_count + item_tokens > request.token_budget:
                continue
            items.append(
                RetrievalItem(
                    record_id=row.id,
                    category=row.category,
                    content=content,
                    score=round(score, 6),
                    retrieval_reasons=tuple(sorted(reasons.get(row.id, set()))),
                    memory_version=row.version,
                )
            )
            token_count += item_tokens
        if not items:
            status = RetrievalStatus.PARTIAL if degraded else RetrievalStatus.EMPTY
        elif degraded:
            status = RetrievalStatus.PARTIAL
        else:
            status = RetrievalStatus.SUCCEEDED
        return RetrievalResult(
            status=status,
            items=tuple(items),
            token_count=token_count,
            error_code=MemoryErrorCode.PROVIDER_UNAVAILABLE if degraded else None,
            degraded_providers=tuple(sorted(set(degraded))),
        )


def _lexical_score(query: str, content: str) -> float:
    """用可复现的 token 重叠计算词法相关性，避免二次模型调用。"""
    query_tokens = _tokens(query)
    content_tokens = _tokens(content)
    if not query_tokens or not content_tokens:
        return 0.0
    return min(1.0, len(query_tokens & content_tokens) / len(query_tokens))


def _tokens(value: str) -> set[str]:
    """抽取英文词、数字串和中文字符，覆盖离线金融夹具的基本查询。"""
    return set(re.findall(r"[a-z0-9_.-]+|[\u4e00-\u9fff]", value.lower()))


def _estimate_tokens(content: str) -> int:
    """提供稳定的保守 token 估算，真实模型 tokenizer 不进入检索正确性边界。"""
    return max(1, (len(content) + 3) // 4)
