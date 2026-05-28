from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml


@dataclass(slots=True)
class SourcePolicy:
    allowed_domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=list)
    official_domains: list[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path | None = None) -> "SourcePolicy":
        policy_path = path or Path(__file__).with_name("source_policy.yaml")
        if not policy_path.exists():
            return cls()
        payload = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        return cls(
            allowed_domains=[str(item) for item in payload.get("allowed_domains") or []],
            blocked_domains=[str(item) for item in payload.get("blocked_domains") or []],
            official_domains=[str(item) for item in payload.get("official_domains") or []],
        )

    def domain_allowed(self, domain: str) -> bool:
        clean = normalize_domain(domain)
        if any(clean == item or clean.endswith(f".{item}") for item in self.blocked_domains):
            return False
        if not self.allowed_domains:
            return True
        return any(clean == item or clean.endswith(f".{item}") for item in self.allowed_domains)

    def source_type(self, domain: str) -> str:
        clean = normalize_domain(domain)
        if any(clean == item or clean.endswith(f".{item}") for item in self.official_domains):
            return "official"
        if clean.endswith((".gov.cn", ".org.cn")):
            return "official"
        if clean.endswith((".com.cn", ".cn")):
            return "finance_media"
        return "web"


def normalize_domain(value: str) -> str:
    text = str(value or "").strip().lower()
    if "://" in text:
        text = urlsplit(text).netloc
    return text.split("@")[-1].split(":")[0].removeprefix("www.")


__all__ = ["SourcePolicy", "normalize_domain"]
