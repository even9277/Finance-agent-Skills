from __future__ import annotations

import os
from pathlib import Path


SECRET_ENV_NAMES = {
    "OPENAI_COMPATIBLE_API_KEY",
    "TAVILY_API_KEY",
    "SERPER_API_KEY",
    "TUSHARE_TOKEN",
    "LANGFUSE_SECRET_KEY",
}

SCAN_DIRS = (
    Path("tests/_realcall/_runs"),
    Path("trace_artifacts"),
)


def _secret_values() -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for name in SECRET_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if len(value) >= 8:
            values.append((name, value))
    return values


def test_runtime_artifacts_do_not_contain_live_secret_values():
    secrets = _secret_values()
    if not secrets:
        return

    for directory in SCAN_DIRS:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
            for name, value in secrets:
                assert value not in content, f"{name} leaked into {path}"
