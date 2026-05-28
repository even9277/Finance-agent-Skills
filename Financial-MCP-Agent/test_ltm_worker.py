import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.memory import ltm_worker


class LtmWorkerCandidateGovernanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_governance_skips_auto_forget_when_pool_disabled(self):
        with patch.object(ltm_worker, "_ENABLE_MEMORY_CANDIDATE_POOL", False):
            with patch("src.memory.ltm_worker._insert_audit_log", new=AsyncMock()) as audit_mock:
                await ltm_worker._auto_forget_candidates()
        audit_mock.assert_not_awaited()

    async def test_candidate_governance_skips_metrics_when_pool_disabled(self):
        with patch.object(ltm_worker, "_ENABLE_MEMORY_CANDIDATE_POOL", False):
            with patch.object(ltm_worker.logger, "info") as info_mock:
                await ltm_worker._emit_governance_metrics()
        info_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
