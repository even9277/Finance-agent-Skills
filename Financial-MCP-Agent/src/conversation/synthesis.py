"""只基于 AnswerContextPack 调用模型 Provider 生成受控回答。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from src.skills.loader import LoadedSkillContext, SynthesisSkillView

from src.prompts.chat.registry import SYNTHESIS_PROMPT_VERSION, load_synthesis_prompt

from .contracts import (
    AnswerContextPack,
    ClaimLevel,
    ModelSynthesisRequest,
    SkillReferenceGuidance,
    SkillSynthesisGuidance,
    TerminalStatus,
)
from .errors import ContractViolationError
from .ports import ModelPort


def build_skill_synthesis_guidance(
    loaded: LoadedSkillContext,
    *,
    reply_preference: str,
    degrade_stage: str,
) -> SkillSynthesisGuidance:
    """把 synthesis-stage 最小视图投影为模型可见的安全组织指引。

    Args:
        loaded: 同一请求固定快照加载的 synthesis 上下文。
        reply_preference: Rewrite 解析的回答偏好；只影响模板变体。
        degrade_stage: Controller 根据证据状态选定的有限降级阶段。

    Returns:
        不含工具权限、计划模板和未验收市场事实的回答指引。

    Raises:
        ContractViolationError: 上下文阶段错误或降级阶段不属于 Skill 合同。
    """
    if loaded.stage != "synthesis":
        raise ContractViolationError("Skill synthesis guidance requires synthesis context")
    view = cast("SynthesisSkillView", loaded.spec_view)
    preference = reply_preference.strip().lower()
    variant_name = (
        "risk_first"
        if "risk" in preference or "风险" in preference
        else "concise"
        if "concise" in preference or "简洁" in preference or "精简" in preference
        else ""
    )
    variant = view.output_template.response_pref_overrides.get(variant_name)
    section_order = (
        variant.section_order if variant is not None else view.output_template.default_section_order
    )
    style_variant = variant.style_variant if variant is not None else "default"
    stage_names = {item.name for item in view.degrade_policy.stages}
    if degrade_stage not in stage_names:
        raise ContractViolationError("controller degrade stage is outside the Skill contract")
    return SkillSynthesisGuidance(
        skill_name=loaded.skill_id,
        skill_version=loaded.skill_version,
        spec_hash=loaded.spec_hash,
        reference_hash=loaded.reference_hash,
        registry_snapshot_hash=loaded.registry_snapshot_hash,
        section_order=section_order,
        style_variant=style_variant,
        degrade_stage=degrade_stage,
        references=tuple(
            SkillReferenceGuidance(
                title=item.title,
                path=item.path,
                content=item.content,
                content_hash=item.content_hash,
            )
            for item in loaded.references
        ),
    )


class ControlledSynthesizer:
    """隔离 Prompt 加载和模型调用，并强制显式部分结果文案。"""

    def __init__(self, model: ModelPort) -> None:
        self._model = model

    async def stream(self, pack: AnswerContextPack) -> AsyncIterator[str]:
        """逐段生成只依赖已验收证据的安全回答。

        Args:
            pack: 只包含 accepted evidence、缺口和 claim level 的上下文。

        Yields:
            保持 Provider 原始顺序的非空文本增量；业务 PARTIAL 的缺口说明作为
            独立首段且只发送一次。

        Raises:
            ContractViolationError: 上下文包含拒绝证据或 Skill 指引不匹配。
            ModelSynthesisError: 由模型 Provider 原样传播的技术生成失败。
        """
        self._validate_pack(pack)
        if pack.terminal_status is TerminalStatus.PARTIAL:
            missing = "、".join(item.value for item in pack.missing_dimensions)
            yield f"部分结果：缺少 {missing} 证据。"

        request = ModelSynthesisRequest(
            prompt_version=SYNTHESIS_PROMPT_VERSION,
            system_prompt=load_synthesis_prompt(),
            context=pack,
        )
        async for chunk in self._model.stream_synthesize(request):
            yield chunk.content

    async def synthesize(self, pack: AnswerContextPack) -> str:
        """使用已验收证据生成最终文本。

        Args:
            pack: 只包含 accepted evidence、缺口和 claim level 的上下文。

        Returns:
            对部分结果明确标注缺失维度的安全回答。
        """
        return "".join([content async for content in self.stream(pack)])

    @staticmethod
    def _validate_pack(pack: AnswerContextPack) -> None:
        """在调用 Provider 前验证唯一合成上下文边界。"""
        if pack.rejected_evidence:
            raise ContractViolationError("synthesis context must not contain rejected evidence")
        if pack.claim_level is ClaimLevel.REFUSE:
            raise ContractViolationError("refused evidence cannot enter model synthesis")
        if pack.selected_skill is not None:
            guidance = pack.skill_guidance
            if guidance is None or guidance.skill_name != pack.selected_skill:
                raise ContractViolationError("selected Skill requires matching synthesis guidance")
        elif pack.skill_guidance is not None:
            raise ContractViolationError("non-Skill route cannot receive Skill synthesis guidance")
