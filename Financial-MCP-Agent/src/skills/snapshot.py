"""管理通过 Gate 的 Skill 原子快照和进程内 Last-Known-Good。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Iterable, Mapping

from .contracts import SkillSpec
from .lifecycle import SkillStatus, normalize_status
from .reference_index import ReferenceIndex
from .version import stable_hash_text


class SkillSnapshotError(RuntimeError):
    """表示快照不可用、候选不完整或激活版本不匹配。"""


def _now_text() -> str:
    """返回带时区的 ISO 时间，仅用于观测，不参与快照内容哈希。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class SkillSnapshotEntry:
    """固定一个已校验 Skill 的身份、内容、权限和 reference 索引。"""

    skill_id: str
    status: SkillStatus
    skill_version: str
    spec_hash: str
    reference_hash: str
    document_hash: str = ""
    description: str = ""
    execution_mode: str = "deterministic"
    source: str = "workspace"
    aliases: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    reference_paths: tuple[str, ...] = ()
    skill_dir: Path | None = field(default=None, repr=False)
    spec: SkillSpec | None = field(default=None, repr=False)
    markdown: str = field(default="", repr=False)
    reference_index: ReferenceIndex | None = field(default=None, repr=False)
    disabled_reason: str = ""

    def __post_init__(self) -> None:
        if not self.skill_id.strip() or not self.skill_version.strip():
            raise SkillSnapshotError("snapshot entry identity and version must not be blank")
        object.__setattr__(self, "status", normalize_status(self.status))
        object.__setattr__(self, "allowed_tools", tuple(sorted(set(self.allowed_tools))))
        object.__setattr__(self, "reference_paths", tuple(sorted(set(self.reference_paths))))

    def hash_material(self) -> str:
        """返回不含正文、路径绝对值和时间戳的稳定内容材料。"""
        return "|".join(
            (
                self.skill_id,
                self.status.value,
                self.skill_version,
                self.spec_hash,
                self.document_hash,
                self.reference_hash,
                self.description,
                self.execution_mode,
                self.source,
                ",".join(self.aliases),
                ",".join(self.allowed_tools),
                ",".join(self.reference_paths),
                self.disabled_reason,
            )
        )


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    """表示一次原子发布、可被请求固定引用的不可变 Registry。"""

    registry_version: str
    created_at: str
    snapshot_hash: str
    entries: Mapping[str, SkillSnapshotEntry]

    def get(self, skill_id: str) -> SkillSnapshotEntry | None:
        """按稳定标识读取条目；未知 Skill 返回 `None`。"""
        return self.entries.get(skill_id)

    def require(self, skill_id: str) -> SkillSnapshotEntry:
        """返回 active 条目，否则拒绝加载。

        Raises:
            SkillSnapshotError: Skill 不存在或不是 active。
        """
        entry = self.get(skill_id)
        if entry is None or entry.status is not SkillStatus.ACTIVE:
            raise SkillSnapshotError(f"active skill is absent from snapshot: {skill_id}")
        return entry

    def active_skill_ids(self) -> tuple[str, ...]:
        """返回稳定排序的 active Skill 标识。"""
        return tuple(
            skill_id
            for skill_id, entry in self.entries.items()
            if entry.status is SkillStatus.ACTIVE
        )


def build_registry_snapshot(
    entries: Iterable[SkillSnapshotEntry],
    *,
    registry_version: str | None = None,
) -> RegistrySnapshot:
    """排序、去重并构建具备稳定内容哈希的不可变快照。

    Raises:
        SkillSnapshotError: 条目重名、版本为空或没有 active Skill。
    """
    ordered = tuple(sorted(entries, key=lambda item: item.skill_id))
    names = tuple(item.skill_id for item in ordered)
    if len(names) != len(set(names)):
        raise SkillSnapshotError("registry snapshot contains duplicate skill identities")
    if not any(item.status is SkillStatus.ACTIVE for item in ordered):
        raise SkillSnapshotError("registry snapshot must contain at least one active skill")
    snapshot_hash = stable_hash_text("\n".join(item.hash_material() for item in ordered))
    version = registry_version or f"registry-v2-{snapshot_hash[:12]}"
    if not version.strip():
        raise SkillSnapshotError("registry version must not be blank")
    mapping = MappingProxyType({item.skill_id: item for item in ordered})
    return RegistrySnapshot(
        registry_version=version,
        created_at=_now_text(),
        snapshot_hash=snapshot_hash,
        entries=mapping,
    )


class SkillSnapshotManager:
    """通过锁内引用切换管理 active、pending 与 Last-Known-Good。"""

    def __init__(self, initial_snapshot: RegistrySnapshot | None = None) -> None:
        self._lock = RLock()
        self._active = initial_snapshot
        self._pending: RegistrySnapshot | None = None
        self._last_known_good = initial_snapshot

    def has_active_snapshot(self) -> bool:
        """判断进程内是否已经发布过合法快照。"""
        with self._lock:
            return self._active is not None

    def get_active_snapshot(self) -> RegistrySnapshot:
        """返回当前 active 引用；调用方可在请求开始时固定该对象。

        Raises:
            SkillSnapshotError: 首次加载尚无合法快照。
        """
        with self._lock:
            if self._active is None:
                raise SkillSnapshotError("no active skill registry snapshot")
            return self._active

    def get_last_known_good_snapshot(self) -> RegistrySnapshot:
        """返回最近一次成功激活的快照。"""
        with self._lock:
            if self._last_known_good is None:
                raise SkillSnapshotError("no last-known-good skill registry snapshot")
            return self._last_known_good

    def propose_snapshot(self, snapshot: RegistrySnapshot) -> RegistrySnapshot:
        """登记完整候选，但不改变 active 请求视图。"""
        with self._lock:
            self._pending = snapshot
            return snapshot

    def activate_snapshot(self, registry_version: str | None = None) -> RegistrySnapshot:
        """在锁内一次性激活匹配版本的 pending 快照。

        Raises:
            SkillSnapshotError: 没有候选或版本不匹配。
        """
        with self._lock:
            if self._pending is None:
                raise SkillSnapshotError("no pending skill registry snapshot")
            if registry_version and self._pending.registry_version != registry_version:
                raise SkillSnapshotError("pending snapshot version mismatch")
            self._active = self._pending
            self._last_known_good = self._pending
            self._pending = None
            return self._active

    def reject_pending(self) -> RegistrySnapshot:
        """丢弃失败候选并保持 active/LKG 不变。"""
        with self._lock:
            self._pending = None
            return self.get_active_snapshot()

    def rollback_snapshot(self) -> RegistrySnapshot:
        """清除 pending 并恢复到 LKG；不读取磁盘或构造新对象。"""
        with self._lock:
            self._pending = None
            if self._last_known_good is None:
                raise SkillSnapshotError("no last-known-good snapshot to roll back")
            self._active = self._last_known_good
            return self._active


__all__ = [
    "RegistrySnapshot",
    "SkillSnapshotEntry",
    "SkillSnapshotError",
    "SkillSnapshotManager",
    "build_registry_snapshot",
]
