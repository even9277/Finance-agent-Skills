#!/usr/bin/env python3
"""
Redis 单链路校验脚本。

目标：
1. 业务代码不得直接 import redis。
2. Redis 客户端调用只允许出现在 backend/integrations/redis 和 backend/tests。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_PREFIXES = (
    ROOT / "backend" / "integrations" / "redis",
    ROOT / "backend" / "tests",
    ROOT / "scripts",
)
SCAN_DIRS = (
    ROOT / "backend",
    ROOT / "Financial-MCP-Agent" / "src",
    ROOT / "frontend" / "src",
)
PY_SUFFIX = {".py"}
TS_SUFFIX = {".ts", ".tsx", ".js", ".jsx", ".vue"}

IMPORT_PATTERNS = [
    re.compile(r"^\s*import\s+redis\b", re.MULTILINE),
    re.compile(r"^\s*from\s+redis(\.|$)", re.MULTILINE),
]

# 只检查明显的直接客户端调用，避免误报普通文档字符串
DIRECT_CALL_PATTERNS = [
    re.compile(r"\bredis\.(set|get|delete|exists|ttl|hset|hget|lpush|rpush)\s*\("),
    re.compile(r"\bRedis\s*\("),
    re.compile(r"\bredis\.asyncio\b"),
]


def _is_allowed(path: Path) -> bool:
    resolved = path.resolve()
    return any(resolved.is_relative_to(prefix) for prefix in ALLOWED_PREFIXES)


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for path in scan_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix in PY_SUFFIX or path.suffix in TS_SUFFIX:
                files.append(path)
    return files


def main() -> int:
    violations: list[str] = []
    scanned = 0
    for path in _iter_files():
        scanned += 1
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        hit_import = any(pattern.search(content) for pattern in IMPORT_PATTERNS)
        hit_direct_call = any(pattern.search(content) for pattern in DIRECT_CALL_PATTERNS)
        if (hit_import or hit_direct_call) and not _is_allowed(path):
            violations.append(str(path.relative_to(ROOT)))

    if violations:
        print("Redis 单链路校验失败，发现非允许路径的 Redis 直接调用：")
        for item in sorted(set(violations)):
            print(f" - {item}")
        print(
            "\n允许路径仅限：backend/integrations/redis/*、backend/tests/*、scripts/*"
        )
        return 1

    print(
        f"Redis single-chain check passed. scanned_files={scanned}, violations=0"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
