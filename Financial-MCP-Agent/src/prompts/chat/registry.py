"""集中加载受控对话 Prompt 并暴露稳定版本。"""

from __future__ import annotations

from pathlib import Path

SYNTHESIS_PROMPT_VERSION = "chat-synthesis-v2"
_SYNTHESIS_PROMPT_PATH = Path(__file__).with_name("synthesis_v2.md")


def load_synthesis_prompt() -> str:
    """读取 M5 Synthesis 的版本化系统 Prompt。

    Returns:
        非空 Prompt 文本；调用方将版本同时写入模型请求和 Trace。

    Raises:
        RuntimeError: Prompt 文件为空，无法形成可复现合同。
    """
    content = _SYNTHESIS_PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not content:
        raise RuntimeError("chat synthesis prompt must not be empty")
    return content
