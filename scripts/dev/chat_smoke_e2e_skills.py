#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    out_dir = ROOT / os.getenv("REALCALL_TRACE_OUT", "tests/_realcall/_runs") / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "prepared",
        "note": "真实端到端聊天调用需要后端启动和有效 LLM/Tushare/WebSearch/Langfuse 凭证；本脚本先落联调目录与预算占位。",
        "run_realcall": os.getenv("RUN_REALCALL", "0"),
        "max_cost_usd": os.getenv("REALCALL_MAX_COST_USD", "1.0"),
    }
    (out_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
