#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import base64
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _timed(name: str, fn):
    started = time.perf_counter()
    try:
        detail = fn()
        ok = True
        error = ""
    except Exception as exc:  # noqa: BLE001 - 自检脚本需要吞掉并汇总所有失败项
        detail = {}
        ok = False
        error = str(exc)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {name:<24} {elapsed_ms:>5}ms {error}")
    return {"name": name, "ok": ok, "elapsed_ms": elapsed_ms, "detail": detail, "error": error}


def _http_json(url: str, *, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float = 4.0):
    body = None
    method = "GET"
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        method = "POST"
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - dev 自检只访问显式配置 URL
        raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def check_llm() -> dict[str, Any]:
    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "").strip().rstrip("/")
    model = os.getenv("OPENAI_COMPATIBLE_MODEL", "").strip()
    if not api_key or not base_url or not model:
        raise RuntimeError("missing OPENAI_COMPATIBLE_*")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 4,
        "temperature": 0,
    }
    data = _http_json(
        f"{base_url}/chat/completions",
        payload=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=4,
    )
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("empty LLM response")
    return {"model": model, "key": _mask(api_key)}


async def _probe_tushare_one(method_name: str, kwargs: dict[str, Any]) -> tuple[str, bool, str]:
    from src.tools.tushare_client import get_tushare_client

    client = get_tushare_client()
    method = getattr(client, method_name)
    try:
        result = await method(**kwargs)
    except Exception as exc:  # noqa: BLE001
        return method_name, False, str(exc)
    if result is None:
        return method_name, False, "empty result"
    rows = result.to_dict("records") if hasattr(result, "to_dict") else result
    if isinstance(rows, list) and not rows:
        return method_name, False, "empty rows"
    return method_name, True, ""


def check_tushare() -> dict[str, Any]:
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("missing TUSHARE_TOKEN")
    probes = {
        "stock_basic": {"limit": 1},
        "daily": {"ts_code": "600519.SH", "limit": 1},
        "pro_bar": {"ts_code": "600519.SH", "limit": 1},
        "fund_basic": {"market": "E", "limit": 1},
        "fund_nav": {"ts_code": "510300.SH", "limit": 1},
        "fund_daily": {"ts_code": "510300.SH", "limit": 1},
        "fund_share": {"ts_code": "510300.SH", "limit": 1},
        "fina_indicator": {"ts_code": "600519.SH", "limit": 1},
        "income": {"ts_code": "600519.SH", "limit": 1},
        "balancesheet": {"ts_code": "600519.SH", "limit": 1},
        "cashflow": {"ts_code": "600519.SH", "limit": 1},
        "sw_daily": {"ts_code": "801120.SI", "limit": 1},
        "index_member": {"index_code": "000300.SH", "limit": 1},
    }

    async def _run():
        results = []
        for method_name, kwargs in probes.items():
            results.append(await _probe_tushare_one(method_name, kwargs))
        return results

    results = asyncio.run(_run())
    enabled = [name for name, ok, _ in results if ok]
    disabled = {name: error for name, ok, error in results if not ok}
    if "stock_basic" not in enabled:
        raise RuntimeError(f"stock_basic probe failed: {disabled.get('stock_basic')}")
    print(f"      Tushare profile={os.getenv('TUSHARE_TOOL_PROFILE', 'points_2000')} level={os.getenv('TUSHARE_POINTS_LEVEL', '2000')}")
    print(f"      enabled_tools_by_points_level={enabled}")
    print(f"      disabled_by_points_level={list(disabled)}")
    return {"enabled_tools_by_points_level": enabled, "disabled_by_points_level": disabled}


def check_web_search() -> dict[str, Any]:
    provider = os.getenv("WEB_SEARCH_PROVIDER", "tavily").strip().lower()
    if provider == "tavily":
        key = os.getenv("TAVILY_API_KEY", "").strip()
        if not key:
            raise RuntimeError("missing TAVILY_API_KEY")
        payload = {
            "api_key": key,
            "query": "贵州茅台 公告",
            "max_results": 1,
            "search_depth": "basic",
            "topic": "finance",
            "include_answer": False,
            "include_raw_content": False,
        }
        data = _http_json(
            "https://api.tavily.com/search",
            payload=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=float(os.getenv("WEB_SEARCH_TIMEOUT_MS", "4000")) / 1000,
        )
        results = data.get("results") or []
        if not results:
            raise RuntimeError("empty Tavily results")
        return {"provider": "tavily", "result_count": len(results)}
    if provider in {"duckduckgo", "ddgs"}:
        from ddgs import DDGS

        rows = list(DDGS().text(query="贵州茅台 公告", max_results=1, region="cn-zh"))
        if not rows:
            raise RuntimeError("empty DDGS results")
        return {"provider": "duckduckgo", "result_count": len(rows)}
    raise RuntimeError(f"unsupported WEB_SEARCH_PROVIDER={provider}")


def check_langfuse() -> dict[str, Any]:
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    base_url = os.getenv("LANGFUSE_BASE_URL", os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")).strip().rstrip("/")
    if not public_key or not secret_key:
        raise RuntimeError("missing LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY")
    token = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("ascii")
    data = _http_json(f"{base_url}/api/public/projects", headers={"Authorization": f"Basic {token}"}, timeout=4)
    return {"base_url": base_url, "projects": len(data if isinstance(data, list) else data.get("data", []))}


def check_database() -> dict[str, Any]:
    database_url = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'backend' / 'finance.db'}")
    if database_url.startswith("sqlite"):
        db_path = database_url.rsplit("/", 1)[-1]
        if db_path in {"", "."}:
            db_path = str(ROOT / "backend" / "finance.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return {"kind": "sqlite", "path": db_path}
    return {"kind": "external", "note": "skipped non-sqlite DSN in stdlib checker"}


def main() -> int:
    _load_env_file(AGENT_ROOT / ".env")
    _load_env_file(ROOT / "backend" / ".env")
    optional = os.getenv("CHECK_CREDENTIALS_OPTIONAL", "0") == "1"
    if optional:
        required_fields = [
            "TAVILY_API_KEY",
            "TUSHARE_POINTS_LEVEL",
            "LANGFUSE_UPLOAD_PROMPT_REPLY",
            "WEB_SEARCH_PROVIDER",
            "REALCALL_SCHEDULE_ENABLED",
        ]
        example_text = (AGENT_ROOT / ".env.example").read_text(encoding="utf-8") + "\n" + (ROOT / "backend" / ".env.example").read_text(encoding="utf-8")
        missing = [field for field in required_fields if field not in example_text]
        if missing:
            print(f"[FAIL] env.example fields missing: {missing}")
            return 1
        print("[OK] optional credential check: env.example fields are present")
        return 0
    checks = [
        ("LLM", check_llm),
        ("Tushare", check_tushare),
        ("Web Search", check_web_search),
        ("Langfuse", check_langfuse),
        ("Database", check_database),
    ]
    results = [_timed(name, fn) for name, fn in checks]
    out_path = ROOT / "tests" / "_realcall" / "_runs" / "latest_credentials.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    required_failed = [item for item in results if not item["ok"] and item["name"] in {"LLM", "Tushare", "Web Search", "Database"}]
    if required_failed and not optional:
        print(f"credential self-check failed; report={out_path}")
        return 1
    print(f"credential self-check report={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
