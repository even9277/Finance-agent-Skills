"""验证 M5 候选治理在真实 ORM 事务中的隔离、幂等和权威边界。"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.db.database import Base  # noqa: E402
from backend.db.models import (  # noqa: E402
    MemoryAuditEventRow,
    MemoryCandidateEvidenceRow,
    MemoryCandidateRow,
    MemoryRecordRow,
    Message,
    Session,
    User,
)
from backend.infrastructure.memory.governance_repository import (  # noqa: E402
    SqlAlchemyCandidateGovernanceRepository,
)
from src.memory.contracts import (  # noqa: E402
    CandidateDraft,
    CandidateEvidence,
    MemoryValueKind,
    ProfileField,
)


async def _factory(tmp_path: Path):
    """创建包含新候选表的隔离 SQLite 数据库。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'candidate.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_user_session(
    session_factory,
    user_id: str,
    session_id: str,
    *,
    create_user: bool = True,
) -> None:
    """写入候选表所需的用户和会话父行。"""
    async with session_factory() as db:
        if create_user:
            db.add(User(id=user_id, display_name="候选测试用户"))
        db.add(Session(id=session_id, user_id=user_id, title="候选测试会话"))
        await db.commit()


@pytest.mark.integration
def test_candidate_governance_quarantines_high_impact_and_promotes_repeat_text(
    tmp_path: Path,
) -> None:
    """重复低影响偏好可晋升，但风险推断只能停在 confirmation_required。"""

    async def run_case() -> None:
        engine, session_factory = await _factory(tmp_path)
        try:
            await _seed_user_session(session_factory, "candidate-user", "candidate-session")
            await _seed_user_session(
                session_factory,
                "candidate-user",
                "candidate-session-2",
                create_user=False,
            )
            async with session_factory() as db:
                db.add_all(
                    [
                        Message(
                            id=1,
                            session_id="candidate-session",
                            role="user",
                            content="以后先给结论，再解释主要风险",
                        ),
                        Message(
                            id=2,
                            session_id="candidate-session",
                            role="user",
                            content="我的风险偏好是稳健型",
                        ),
                        Message(
                            id=3,
                            session_id="candidate-session-2",
                            role="user",
                            content="以后先给结论，再解释主要风险",
                        ),
                        Message(
                            id=4,
                            session_id="candidate-session-2",
                            role="user",
                            content="以后先给结论，再解释主要风险",
                        ),
                    ]
                )
                await db.flush()
                text_draft = CandidateDraft(
                    kind=MemoryValueKind.TEXT,
                    category="response_preference",
                    normalized_key="response_preference:conclusion_first",
                    confidence=0.95,
                    evidence=(
                        CandidateEvidence(
                            session_id="candidate-session",
                            message_id=1,
                            source_role="user",
                            query_hash="q-1",
                            observed_on=date(2026, 8, 20),
                            confidence=0.95,
                        ),
                    ),
                    content="回答先给结论，再解释风险",
                    conflict_key="response_preference:default",
                )
                profile_draft = CandidateDraft(
                    kind=MemoryValueKind.STRUCTURED_PROFILE,
                    category="profile_suggestion",
                    normalized_key="profile:risk_level:moderate",
                    confidence=0.95,
                    evidence=(
                        CandidateEvidence(
                            session_id="candidate-session",
                            message_id=2,
                            source_role="user",
                            query_hash="q-2",
                            observed_on=date(2026, 8, 20),
                            confidence=0.95,
                        ),
                    ),
                    profile_field=ProfileField.RISK_LEVEL,
                    value="moderate",
                    conflict_key="profile:risk_level",
                )
                drafts = (text_draft, profile_draft)
                repository = SqlAlchemyCandidateGovernanceRepository(db)
                first = await repository.govern(
                    user_id="candidate-user",
                    drafts=drafts,
                    prompt_version="memory-candidate-rem-v1",
                    summary_version=1,
                    state_version=1,
                    trace_id="trace-candidate",
                )
                await db.commit()
                assert first.created_count == 2
                assert first.confirmation_required_count == 1

            async with session_factory() as db:
                repeat_draft = CandidateDraft(
                    kind=MemoryValueKind.TEXT,
                    category="response_preference",
                    normalized_key="response_preference:conclusion_first",
                    confidence=0.95,
                    evidence=(
                        CandidateEvidence(
                            session_id="candidate-session-2",
                            message_id=3,
                            source_role="user",
                            query_hash="q-3",
                            observed_on=date(2026, 8, 25),
                            confidence=0.95,
                        ),
                        CandidateEvidence(
                            session_id="candidate-session-2",
                            message_id=4,
                            source_role="user",
                            query_hash="q-4",
                            observed_on=date(2026, 8, 25),
                            confidence=0.95,
                        ),
                    ),
                    content="回答先给结论，再解释风险",
                    conflict_key="response_preference:default",
                )
                result = await SqlAlchemyCandidateGovernanceRepository(db).govern(
                    user_id="candidate-user",
                    drafts=(repeat_draft,),
                    prompt_version="memory-candidate-rem-v1",
                    summary_version=2,
                    state_version=1,
                    trace_id="trace-candidate-repeat",
                )
                await db.commit()
                assert result.extracted_count == 1
                rows = list(
                    (
                        await db.execute(
                            select(MemoryCandidateRow).where(
                                MemoryCandidateRow.user_id == "candidate-user"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(rows) == 2
                preference = next(row for row in rows if row.category == "response_preference")
                profile = next(row for row in rows if row.category == "profile_suggestion")
                assert preference.status == "PROMOTED"
                assert profile.status == "CONFIRMATION_REQUIRED"
                assert (
                    await db.scalar(
                        select(MemoryRecordRow.id).where(
                            MemoryRecordRow.user_id == "candidate-user",
                            MemoryRecordRow.kind == MemoryValueKind.TEXT.value,
                        )
                    )
                    is not None
                )
                assert await db.scalar(
                    select(MemoryCandidateEvidenceRow.id).where(
                        MemoryCandidateEvidenceRow.candidate_id == preference.id
                    )
                ) is not None
                assert await db.scalar(
                    select(MemoryAuditEventRow.id).where(
                        MemoryAuditEventRow.user_id == "candidate-user"
                    )
                ) is not None
        finally:
            await engine.dispose()

    import asyncio

    asyncio.run(run_case())
