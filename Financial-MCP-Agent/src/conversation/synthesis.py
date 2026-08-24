"""只基于 AnswerContextPack 调用模型 Provider 生成受控回答。"""

from __future__ import annotations

from src.prompts.chat.registry import SYNTHESIS_PROMPT_VERSION, load_synthesis_prompt

from .contracts import AnswerContextPack, ModelSynthesisRequest, TerminalStatus
from .ports import ModelPort


class ControlledSynthesizer:
    """隔离 Prompt 加载和模型调用，并强制显式部分结果文案。"""

    def __init__(self, model: ModelPort) -> None:
        self._model = model

    async def synthesize(self, pack: AnswerContextPack) -> str:
        """使用已验收证据生成最终文本。

        Args:
            pack: 只包含 accepted evidence、缺口和 claim level 的上下文。

        Returns:
            对部分结果明确标注缺失维度的安全回答。
        """
        model_reply = (
            await self._model.synthesize(
                ModelSynthesisRequest(
                    prompt_version=SYNTHESIS_PROMPT_VERSION,
                    system_prompt=load_synthesis_prompt(),
                    context=pack,
                )
            )
        ).strip()
        if pack.terminal_status is TerminalStatus.PARTIAL:
            missing = "、".join(item.value for item in pack.missing_dimensions)
            return f"部分结果：缺少 {missing} 证据。{model_reply}"
        return model_reply
