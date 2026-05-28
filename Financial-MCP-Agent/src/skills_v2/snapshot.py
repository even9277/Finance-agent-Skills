from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from types import MappingProxyType
from typing import Any, Iterable
import uuid

from src.skills_v2.lifecycle import SkillStatus


def _now_text() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class SkillSnapshotEntry:
    skill_id: str
    status: SkillStatus
    skill_version: str
    spec_hash: str
    reference_hash: str
    source: str = "workspace"
    disabled_reason: str = ""


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    registry_version: str
    created_at: str
    entries: MappingProxyType[str, SkillSnapshotEntry] = field(default_factory=lambda: MappingProxyType({}))

    def get(self, skill_id: str) -> SkillSnapshotEntry | None:
        return self.entries.get(skill_id)

    def active_skill_ids(self) -> list[str]:
        return [skill_id for skill_id, entry in self.entries.items() if entry.status == SkillStatus.ACTIVE]


def build_registry_snapshot(entries: Iterable[SkillSnapshotEntry], *, registry_version: str | None = None) -> RegistrySnapshot:
    mapping = {entry.skill_id: entry for entry in entries}
    return RegistrySnapshot(
        registry_version=registry_version or f"reg_{uuid.uuid4().hex[:12]}",
        created_at=_now_text(),
        entries=MappingProxyType(mapping),
    )


class SkillSnapshotManager:
    """用原子引用切换保护长请求：请求开始后只看入链时的 snapshot。"""

    def __init__(self, initial_snapshot: RegistrySnapshot | None = None) -> None:
        self._lock = RLock()
        self._active = initial_snapshot or build_registry_snapshot([])
        self._pending: RegistrySnapshot | None = None
        self._last_known_good = self._active

    def get_active_snapshot(self) -> RegistrySnapshot:
        with self._lock:
            return self._active

    def get_last_known_good_snapshot(self) -> RegistrySnapshot:
        with self._lock:
            return self._last_known_good

    def propose_snapshot(self, snapshot: RegistrySnapshot) -> RegistrySnapshot:
        with self._lock:
            self._pending = snapshot
            return snapshot

    def activate_snapshot(self, registry_version: str | None = None) -> RegistrySnapshot:
        with self._lock:
            if self._pending is None:
                raise ValueError("no pending skill registry snapshot")
            if registry_version and self._pending.registry_version != registry_version:
                raise ValueError("pending snapshot version mismatch")
            self._active = self._pending
            self._last_known_good = self._active
            self._pending = None
            return self._active

    def rollback_snapshot(self) -> RegistrySnapshot:
        with self._lock:
            self._pending = None
            self._active = self._last_known_good
            return self._active


__all__ = ["RegistrySnapshot", "SkillSnapshotEntry", "SkillSnapshotManager", "build_registry_snapshot"]
