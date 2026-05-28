import asyncio
import unittest
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.db.database import Base
from backend.db.models import Session, User, WorkingStateEvent
from backend.services.working_state import (
    get_working_state,
    upsert_active_entity,
    upsert_constraints,
    upsert_reply_preference,
)


class WorkingStateStoreTests(unittest.TestCase):
    def test_round_trip_and_event_audit(self):
        async def run():
            engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
            async with SessionLocal() as db:
                user = User(id=str(uuid4()))
                session = Session(user_id=user.id)
                db.add_all([user, session])
                await db.flush()
                await upsert_active_entity(
                    db,
                    session,
                    {"entity_type": "stock", "canonical_id": "600519.SH", "display_name": "贵州茅台"},
                    confidence=0.95,
                )
                await upsert_constraints(db, session, ["只看 A 股", "只看 A 股"])
                await upsert_reply_preference(db, session, "先给结论")
                state = get_working_state(session)
                self.assertEqual(state["active_entity"]["canonical_id"], "600519.SH")
                self.assertEqual(state["constraints"], ["只看 A 股"])
                self.assertEqual(state["reply_preference_hint"], "先给结论")
                self.assertEqual(session.working_state_version, 3)
                rows = (await db.execute(WorkingStateEvent.__table__.select())).all()
                self.assertEqual(len(rows), 3)
            await engine.dispose()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
