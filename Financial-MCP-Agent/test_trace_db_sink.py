"""Trace DB sink 回归：开关关闭不写库，开启后 span 可落 SQLite。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools import trace_db_sink
from src.tools.skill_trace import clear_trace_exporters, skill_trace_context, trace_span


class TraceDbSinkTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = str(Path(self._tmpdir.name) / "trace_test.db")
        os.environ["SQLITE_DB_PATH"] = self._db_path
        os.environ.pop("DATABASE_URL", None)
        trace_db_sink._TABLES_READY = False  # noqa: SLF001

    def tearDown(self):
        self._tmpdir.cleanup()
        os.environ.pop("SQLITE_DB_PATH", None)
        os.environ.pop("ENABLE_TRACE_DB_SINK", None)
        os.environ.pop("ENABLE_SKILL_TRACE", None)
        clear_trace_exporters()
        trace_db_sink._TABLES_READY = False  # noqa: SLF001

    def test_disabled_skips_db_write(self):
        os.environ["ENABLE_TRACE_DB_SINK"] = "false"
        os.environ["ENABLE_SKILL_TRACE"] = "true"
        with skill_trace_context(trace_id="tr_db_off", group_id="sess_db_off", turn_index=1):
            with trace_span("route", stage="route", data={"ok": True}):
                pass
        trace_db_sink._DB_EXECUTOR.shutdown(wait=True)
        trace_db_sink._DB_EXECUTOR = __import__(
            "concurrent.futures", fromlist=["ThreadPoolExecutor"]
        ).ThreadPoolExecutor(max_workers=1, thread_name_prefix="trace_db_sink")
        self.assertFalse(Path(self._db_path).exists())

    def test_enabled_writes_span_row(self):
        os.environ["ENABLE_TRACE_DB_SINK"] = "true"
        os.environ["ENABLE_SKILL_TRACE"] = "true"
        with skill_trace_context(trace_id="tr_db_on", group_id="sess_db_on", turn_index=1):
            with trace_span("planner", stage="executor", data={"planner_type": "test"}):
                pass
        trace_db_sink._DB_EXECUTOR.shutdown(wait=True)
        trace_db_sink._DB_EXECUTOR = __import__(
            "concurrent.futures", fromlist=["ThreadPoolExecutor"]
        ).ThreadPoolExecutor(max_workers=1, thread_name_prefix="trace_db_sink")
        import aiosqlite
        import asyncio

        async def _fetch():
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(
                    "SELECT session_id, stage_name, duration_ms FROM trace_spans ORDER BY id DESC LIMIT 1"
                )
                return await cur.fetchone()

        row = asyncio.run(_fetch())
        self.assertIsNotNone(row)
        self.assertEqual(row["session_id"], "sess_db_on")
        self.assertEqual(row["stage_name"], "executor")


if __name__ == "__main__":
    unittest.main()
