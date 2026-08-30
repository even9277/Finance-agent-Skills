"""提供金融 SOP Skill 资产及其类型化治理边界。"""

from .contracts import SkillSpec
from .lifecycle import SkillLifecycleError, SkillStatus, can_transition, transition
from .loader import LoadedSkillContext, SkillLoader
from .reference_index import ReferenceIndex, ReferenceItem
from .schema_gate import SkillValidationReport, validate_skill, validate_skill_directory
from .snapshot import RegistrySnapshot, SkillSnapshotEntry, SkillSnapshotManager
from .version import SkillVersion, stable_hash_text

__all__ = [
    "LoadedSkillContext",
    "ReferenceIndex",
    "ReferenceItem",
    "RegistrySnapshot",
    "SkillLifecycleError",
    "SkillLoader",
    "SkillSnapshotEntry",
    "SkillSnapshotManager",
    "SkillSpec",
    "SkillStatus",
    "SkillValidationReport",
    "SkillVersion",
    "can_transition",
    "stable_hash_text",
    "transition",
    "validate_skill",
    "validate_skill_directory",
]
