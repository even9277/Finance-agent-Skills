"""
Redis 缓存值统一结构（Envelope）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    # 统一 UTC 时间，便于跨服务对齐排障
    return datetime.now(timezone.utc).isoformat()


class CacheEnvelope(BaseModel):
    data: Any
    schema_version: int = Field(default=1, ge=1)
    payload_version: Optional[int] = Field(default=None, ge=0)
    updated_at: str = Field(default_factory=utc_now_iso)
    source: str = Field(min_length=1)
    expire_at: Optional[str] = None

