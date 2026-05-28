import os

import pytest


@pytest.mark.realcall
def test_skills_realcall_requires_explicit_operator_run():
    if os.getenv("RUN_REALCALL") != "1":
        pytest.skip("realcall smoke is disabled by default; set RUN_REALCALL=1 after configuring credentials")
    # 真实联调由 scripts/dev/check_credentials.py 先保证 provider 可用。
    assert os.getenv("OPENAI_COMPATIBLE_API_KEY")
    assert os.getenv("TUSHARE_TOKEN")
