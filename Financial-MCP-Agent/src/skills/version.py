"""提供 Skill 资产的稳定哈希和语义版本规范化能力。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

from pydantic import JsonValue

_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def stable_hash_text(text: str) -> str:
    """计算忽略换行平台差异的 SHA-256 文本哈希。

    Args:
        text: 待哈希的 UTF-8 文本；首尾空白不参与版本判断。

    Returns:
        64 位小写十六进制 SHA-256。
    """
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def stable_hash_mapping(payload: Mapping[str, JsonValue]) -> str:
    """按键稳定序列化 mapping 后计算内容哈希。

    Args:
        payload: 已通过边界校验、只含 JSON 值的机器合同。

    Returns:
        与 YAML 字段顺序无关的 SHA-256。
    """
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return stable_hash_text(normalized)


def combine_hashes(*parts: str) -> str:
    """把多个具名内容哈希按稳定顺序合成为一个版本指纹。"""
    return stable_hash_text("\n".join(parts))


@dataclass(frozen=True, slots=True)
class SkillVersion:
    """规范化声明版本，同时保留非 SemVer 历史值的可追溯指纹。"""

    raw: str
    source: str = "spec"

    @property
    def normalized(self) -> str:
        """返回 SemVer；空值用初始版本，历史非 SemVer 值用哈希元数据保留。"""
        value = (self.raw or "").strip()
        if not value:
            return "0.1.0"
        return value if _SEMVER_RE.fullmatch(value) else f"0.1.0+{stable_hash_text(value)[:8]}"

    @property
    def is_semver(self) -> bool:
        """判断原始声明是否为规范 SemVer；空值不视为有效声明。"""
        return bool(_SEMVER_RE.fullmatch((self.raw or "").strip()))


__all__ = ["SkillVersion", "combine_hashes", "stable_hash_mapping", "stable_hash_text"]
