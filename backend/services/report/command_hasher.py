"""报告命令规范化与幂等 hash。"""

from __future__ import annotations

import hashlib


def normalize_command(command: str) -> str:
    """收敛空白差异；不做语义改写，避免把不同请求误判为同一报告。"""
    return " ".join((command or "").strip().split())


def compute_query_hash(command: str) -> str:
    normalized = normalize_command(command)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
