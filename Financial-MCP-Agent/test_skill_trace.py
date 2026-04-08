import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.skill_trace import (
    clear_trace_exporters,
    log_claim_lineage,
    log_compaction_enqueue,
    log_degrade_transition,
    log_memory_enqueue,
    log_policy_violation,
    log_trace_finished,
    register_trace_exporter,
    skill_trace_context,
    trace_span,
    write_trace_artifact,
)


class SkillTraceTests(unittest.TestCase):
    def tearDown(self):
        clear_trace_exporters()
        os.environ.pop("ENABLE_TRACE_ARTIFACT_REFS", None)
        os.environ.pop("TRACE_ARTIFACT_DIR", None)

    def test_exporter_receives_span_and_trace_records_with_metrics(self):
        captured = []
        register_trace_exporter(lambda record: captured.append(record))

        with skill_trace_context(trace_id="tr_test", group_id="sess_test", turn_index=1):
            with trace_span("planner", stage="executor", data={"planner_type": "fallback_planner"}):
                pass
            log_trace_finished(
                status="ok",
                duration_ms=123.4,
                metrics={
                    "route_confidence": 0.88,
                    "tool_batch_size": 2,
                    "tool_failure_rate": 0.0,
                    "p95_latency": 321.0,
                    "degrade_stage": "primary",
                    "policy_violation_count": 0,
                    "evidence_ok": True,
                },
                final_selected_skill="tushare-data",
                final_selected_skill_family="tushare-data",
                reply_mode="skill",
            )

        self.assertGreaterEqual(len(captured), 2)
        span_record = next(record for record in captured if record["record_type"] == "span")
        trace_record = next(record for record in captured if record["record_type"] == "trace")

        self.assertEqual(span_record["name"], "planner")
        self.assertEqual(span_record["data"]["planner_type"], "fallback_planner")
        self.assertEqual(trace_record["metrics"]["route_confidence"], 0.88)
        self.assertEqual(trace_record["metrics"]["p95_latency"], 321.0)
        self.assertEqual(trace_record["data"]["reply_mode"], "skill")

    def test_trace_supports_policy_degrade_memory_and_claim_events(self):
        captured = []
        register_trace_exporter(lambda record: captured.append(record))

        with skill_trace_context(trace_id="tr_test_events", group_id="sess_test", turn_index=2):
            log_policy_violation(skill_name="fund-compare", tool_name="get_balance_sheet", violation_type="forbidden_tool_attempt")
            log_degrade_transition(skill_name="fund-compare", stage="graceful_decline", reason="missing evidence", outcome="evidence-missing")
            log_memory_enqueue(session_id="sess_test", queued=False, enqueue_skipped_reason="memory_disabled")
            log_compaction_enqueue(session_id="sess_test", queued=False, enqueue_skipped_reason="threshold_not_met_or_budget_ok")
            log_claim_lineage(skill_name="fund-compare", claim_count=1, claim_ids=["clm_001"])

        event_names = [record["name"] for record in captured if record["record_type"] == "event"]
        self.assertIn("chat.policy_violation", event_names)
        self.assertIn("chat.degrade_transition", event_names)
        self.assertIn("chat.memory_write_enqueue", event_names)
        self.assertIn("chat.compaction_enqueue", event_names)
        self.assertIn("chat.claim_lineage", event_names)

    def test_artifact_ref_writes_file_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["ENABLE_TRACE_ARTIFACT_REFS"] = "true"
            os.environ["TRACE_ARTIFACT_DIR"] = tmpdir
            with skill_trace_context(trace_id="tr_artifact_test", group_id="sess_test", turn_index=3):
                ref = write_trace_artifact("claims", {"foo": "bar"}, file_stem="claims_test")
            self.assertIsNotNone(ref)
            self.assertTrue(Path(ref["path"]).exists())


if __name__ == "__main__":
    unittest.main()
