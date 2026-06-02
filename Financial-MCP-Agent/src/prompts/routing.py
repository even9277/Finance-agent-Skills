"""
Stage1 路由提示词 · 版本 v1.0
最后修改：2026-05-28
修改记录：初始版本，从 src/agents/route_stage1.py 中提取
          build_stage1_prompt 是动态构建函数，接受运行时参数后返回完整字符串
"""

from __future__ import annotations

PROMPT_VERSION = "v1.0"

# ─────────────────────────────────────────────────────────────────────────────
# Stage1 路由提示词构建函数
# 本阶段只判断是否命中金融 SOP Skill（三档：sop_hit_high / sop_hit_low / sop_miss）
# 注意：outcome 含义由调用方传入的 confidence_high 阈值决定
# ─────────────────────────────────────────────────────────────────────────────
def build_stage1_prompt(
    user_message: str,
    active_entity: dict | None,
    shortlist_json: str,
    confidence_high: float,
) -> str:
    """
    构建 Stage1 路由提示词。

    参数说明：
    - user_message: 用户当前输入的问题
    - active_entity: 当前会话中已识别的活跃实体（如股票名称、代码），可为空
    - shortlist_json: 候选 Skill 列表的 JSON 字符串（每项含 name/description/trigger 等字段）
    - confidence_high: 判断为高置信度命中的最低分值（通常为 0.75~0.85）

    返回：
    - 拼好的 prompt 字符串，直接传给 LLM
    """
    import json as _json
    entity_str = _json.dumps(active_entity or {}, ensure_ascii=False)
    return (
        "你是金融对话路由器第一阶段，只判断是否命中某个金融 SOP Skill。\n"
        "仅输出 JSON，字段：outcome, skill_id, confidence, reasoning_brief。\n"
        f"outcome=sop_hit_high 表示 confidence >= {confidence_high}; "
        "outcome=sop_hit_low 表示像某技能但需要用户确认；outcome=sop_miss 表示未命中。\n\n"
        f"[当前用户问题]\n{user_message}\n\n"
        f"[active_entity]\n{entity_str}\n\n"
        "[候选 Skill metadata]\n"
        f"{shortlist_json}"
    )


__all__ = ["PROMPT_VERSION", "build_stage1_prompt"]
