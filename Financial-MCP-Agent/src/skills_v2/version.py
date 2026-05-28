from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def stable_hash_text(text: str) -> str:
    """对 Skill 文本/Spec 做稳定 hash，避免用文件 mtime 这类不可靠信号。"""
    normalized = (text or "").replace("\r\n", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SkillVersion:
    raw: str
    source: str = "spec"

    @property
    def normalized(self) -> str:
        value = (self.raw or "").strip()
        if not value:
            return "0.1.0"
        return value if _SEMVER_RE.match(value) else f"0.1.0+{stable_hash_text(value)[:8]}"

    @property
    def is_semver(self) -> bool:
        return bool(_SEMVER_RE.match(self.normalized))


__all__ = ["SkillVersion", "stable_hash_text"]
