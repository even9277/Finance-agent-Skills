"""
profile_extractor.py — 对话画像要素抽取器

职责：从一段对话消息中提取两类用户偏好信号：
  A. 结构化投资画像字段（写入 user_invest_profiles DB）
  B. 自由文本回复风格偏好（仅写入 Mem0，作为语义记忆）

核心原则：
  - B 类事实是精心设计的人类可读记忆条目，描述用户希望系统【如何回复】
  - 不存原始对话，只存高维度偏好摘要
  - 低置信度推断不输出
"""

import os
import json
import logging
from typing import Any

logger = logging.getLogger("profile_extractor")

_EXTRACT_PROMPT = """你是一个投资顾问 AI 的用户偏好分析师。请仔细分析以下对话，提取两类偏好信号。

════════════════════════════════════════
【A 类】结构化投资画像字段
════════════════════════════════════════

可提取的字段：

1. risk_level: 风险偏好
   允许值: conservative(保守), moderate(稳健), balanced(平衡), aggressive(进取), speculative(激进)

2. investment_horizon: 投资周期
   允许值: ultra_short(超短线), short(短线), swing(波段), long(中长线)

3. sectors: 关注投资板块（数组，从以下选项选择）
   允许值: 科技/半导体, AI/大模型, 新能源/光伏, 医药/生物, 消费/白酒, 金融/银行,
           军工/航天, 房地产, 汽车/新能源车, 黄金/贵金属, 红利/高股息, 周期/资源

4. expected_return_min / expected_return_max: 期望收益率（数字，百分比）

5. constraints: 投资约束（数组，如 "不碰ST股"）

6. response_pref: 回答偏好
   允许值: concise(简洁), detailed(详细), balanced(平衡), risk_first(先讲风险)
   触发场景：用户抱怨内容太长/太复杂 → concise；希望更详细 → detailed；先说风险 → risk_first

抽取 A 类的规则：
- 显式偏好（置信度 high）：用户明确表达偏好、约束、目标收益
- 隐式兴趣（置信度 medium）：用户主动询问某板块行情或请求板块推荐（如"黄金行情怎样"→黄金/贵金属，"有 Agent 相关股票吗"→AI/大模型）
- 只询问单只股票不代表板块偏好，不抽取

════════════════════════════════════════
【B 类】回复风格偏好（自由文本，存入长期记忆）
════════════════════════════════════════

B 类捕捉用户对 AI【如何回复】的明确或隐含反馈，生成可读的记忆条目。

触发信号 → 应生成的记忆条目示例：

| 用户说 | 生成的记忆条目 |
|--------|----------------|
| "太长了"、"别说那么多"、"简单点" | "用户偏好：回复简洁，避免冗长表格和免责声明，核心结论优先" |
| "看不懂"、"太专业了"、"能说人话吗" | "用户偏好：使用通俗语言，避免专业术语堆砌，适当举例说明" |
| "能举个例子吗"、"举例说明一下" | "用户偏好：在讲解概念或策略时主动举实例" |
| "别老分析了，直接给结论"、"就说买不买" | "用户偏好：直接给出明确建议和结论，减少推导过程" |
| "能详细一点吗"、"说得更深入些" | "用户偏好：提供深入详细的分析，不简化" |
| "能先说风险吗"、"先讲坏的" | "用户偏好：回复时先陈述风险和不利因素" |
| "帮我总结一下"、"出个表格" | "用户偏好：重要信息用表格或要点形式呈现" |
| "数据太多了看花眼了" | "用户偏好：减少数字堆砌，用文字叙述代替大量数据罗列" |

生成规则：
- 记忆条目必须以"用户偏好："开头，用一句完整的中文描述
- 描述系统【应该怎么做】，而不是用户说了什么
- 只有用户明确表达不满或明确提出要求时才生成
- 同一偏好多次触发可更新描述，不重复生成

════════════════════════════════════════
## 对话内容

{conversation}

════════════════════════════════════════
## 输出要求

严格输出以下 JSON 结构，不要任何其他内容：
{{
  "updates": [
    {{"field": "sectors", "value": ["AI/大模型", "黄金/贵金属"], "confidence": "medium", "evidence": "用户询问了Agent概念股和黄金行情"}},
    {{"field": "response_pref", "value": "concise", "confidence": "high", "evidence": "用户说内容太长了"}}
  ],
  "style_facts": [
    "用户偏好：回复简洁，避免冗长表格，核心结论优先",
    "用户偏好：关注 AI/大模型 和 黄金/贵金属 板块的投资机会"
  ],
  "has_profile_signal": true
}}

如果对话无任何偏好信号：
{{"updates": [], "style_facts": [], "has_profile_signal": false}}

注意：updates 和 style_facts 均可独立为空，has_profile_signal 只要任一非空即为 true。"""


# ─────────────────────────────────────────────────────────────
# 字段可读化映射
# ─────────────────────────────────────────────────────────────

_FIELD_LABELS: dict[str, str] = {
    "risk_level": "风险偏好",
    "investment_horizon": "持有周期",
    "expected_return_min": "最低期望收益率",
    "expected_return_max": "最高期望收益率",
    "sectors": "关注投资板块",
    "constraints": "投资约束条件",
    "response_pref": "回答偏好",
}

_VALUE_LABELS: dict[str, dict[str, str]] = {
    "risk_level": {
        "conservative": "保守型", "moderate": "稳健型", "balanced": "平衡型",
        "aggressive": "进取型", "speculative": "激进型",
    },
    "investment_horizon": {
        "ultra_short": "超短线（日内~1周）", "short": "短线（1周~1月）",
        "swing": "波段（1~6个月）", "long": "中长线（6个月以上）",
    },
    "response_pref": {
        "concise": "简洁", "detailed": "详细", "balanced": "平衡", "risk_first": "先讲风险",
    },
}


def _format_value(field: str, value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(v) for v in value)
    label_map = _VALUE_LABELS.get(field, {})
    return label_map.get(str(value), str(value))


def build_fact_messages(updates: list[dict], style_facts: list[str] | None = None) -> list[dict]:
    """
    将结构化 updates 和自由文本 style_facts 合并为 Mem0 事实字符串列表。

    updates 示例输出：
      "用户投资偏好（推断） - 关注投资板块：AI/大模型、黄金/贵金属 | 来源：用户询问Agent股票"

    style_facts 直接作为独立记忆条目，示例：
      "用户偏好：回复简洁，避免冗长表格，核心结论优先"
    """
    messages = []

    for u in updates:
        field = u.get("field", "")
        value = u.get("value")
        evidence = u.get("evidence", "")
        confidence = u.get("confidence", "medium")

        field_label = _FIELD_LABELS.get(field, field)
        value_str = _format_value(field, value)
        confidence_label = "明确" if confidence == "high" else "推断"

        fact = f"用户投资偏好（{confidence_label}） - {field_label}：{value_str}"
        if evidence:
            fact += f" | 来源：{evidence}"
        messages.append({"role": "user", "content": fact})

    for sf in (style_facts or []):
        if sf and sf.strip():
            messages.append({"role": "user", "content": sf.strip()})

    return messages


# ─────────────────────────────────────────────────────────────
# 主抽取函数
# ─────────────────────────────────────────────────────────────

async def extract_profile_updates(
    messages: list[dict],
    running_summary: str = "",
) -> dict:
    """
    从对话消息中抽取画像更新信号。

    Args:
        messages: [{"role": "user"/"assistant"/"system", "content": "..."}]
        running_summary: 当前会话的 STM 摘要（可选）

    Returns:
        {
            "updates": [...],       # A 类结构化字段，供写 DB
            "style_facts": [...],   # B 类自由文本，仅供 Mem0
            "has_profile_signal": bool
        }
    """
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage

        api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY")
        base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL")
        model_name = os.getenv("OPENAI_COMPATIBLE_MODEL")

        if not all([api_key, base_url, model_name]):
            logger.debug("[profile_extractor] 未配置 LLM，跳过抽取")
            return {"updates": [], "style_facts": [], "has_profile_signal": False}

        # 构建对话文本：用户消息完整保留，助手消息只保留前100字
        conv_parts = []
        if running_summary:
            conv_parts.append(f"[对话摘要] {running_summary[:400]}")
        for m in messages:
            role = m.get("role", "user")
            content = (m.get("content") or "").strip()
            if role == "system":
                conv_parts.append(f"[系统摘要] {content[:300]}")
            elif role == "user":
                conv_parts.append(f"用户: {content[:400]}")
            else:
                # 助手回复只保留前100字，避免长文干扰判断
                preview = content[:100] + ("..." if len(content) > 100 else "")
                conv_parts.append(f"助手: {preview}")

        conversation_text = "\n".join(conv_parts)
        if not conversation_text.strip():
            return {"updates": [], "style_facts": [], "has_profile_signal": False}

        llm = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0,
            max_tokens=700,
        )

        resp = await llm.ainvoke([
            HumanMessage(content=_EXTRACT_PROMPT.format(conversation=conversation_text))
        ])
        text = resp.content.strip()

        # 解析 JSON（兼容 markdown code block 输出）
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        result = json.loads(text)

        # A 类过滤：白名单字段 + high/medium 置信度 + 非空值
        _ALLOWED_FIELDS = {
            "risk_level", "investment_horizon", "expected_return_min",
            "expected_return_max", "sectors", "constraints", "response_pref",
        }
        updates = result.get("updates") or []
        filtered_updates = [
            u for u in updates
            if u.get("confidence") in ("high", "medium")
            and u.get("field") in _ALLOWED_FIELDS
            and u.get("value") is not None
            and u.get("value") != []
        ]

        # B 类过滤：必须以"用户偏好："开头，长度合理
        style_facts = result.get("style_facts") or []
        filtered_style = [
            sf for sf in style_facts
            if isinstance(sf, str) and sf.strip()
            and sf.strip().startswith("用户偏好")
            and 4 < len(sf.strip()) < 200
        ]

        has_signal = bool(filtered_updates or filtered_style)

        output = {
            "updates": filtered_updates,
            "style_facts": filtered_style,
            "has_profile_signal": has_signal,
        }

        logger.info(
            f"[profile_extractor] 抽取结果: "
            f"A类={[u.get('field') for u in filtered_updates]}, "
            f"B类={len(filtered_style)}条"
        )
        return output

    except Exception as exc:
        logger.warning(f"[profile_extractor] 抽取失败（降级空结果）: {exc}")
        return {"updates": [], "style_facts": [], "has_profile_signal": False}
