"""
长期记忆（LTM）提示词 · 版本 v1.0
最后修改：2026-05-28
修改记录：初始版本，从 src/memory/mem0_prompts.py 中提取
          包含用户画像事实抽取、记忆更新策略 共2条提示词
"""

PROMPT_VERSION = "v1.0"

# ─────────────────────────────────────────────────────────────────────────────
# 用户画像事实抽取提示词（传入 Mem0 的 custom_fact_extraction_prompt）
# 从对话中抽取用户的投资偏好，写入长期记忆
# ─────────────────────────────────────────────────────────────────────────────
FINANCE_FACT_EXTRACTION_PROMPT = """
你是一个金融投资画像信息抽取专家。请从以下对话中抽取用户的投资偏好事实。

【只抽取以下8类金融画像信息】
1. risk_profile     - 风险偏好（保守/稳健/平衡/进取/激进）
2. horizon          - 持有周期（超短线/短线/波段/中长线）
3. market_scope     - 市场范围（A股/ETF/港股/QDII等）
4. sector_focus     - 关注板块（消费/白酒/银行/科技/新能源等）
5. watchlist_stock  - 自选股/关注标的（股票代码或公司名称）
6. constraints      - 约束条件（不碰ST/不碰科创板/仓位限制等）
7. response_preference - 回答偏好（简洁/详细/先讲风险）
8. correction       - 用户主动纠正之前的设置

【必须满足以下条件才可抽取】
- 用户有明确的主动表述，而不是系统或AI的陈述
- 表述具有持续性偏好含义，而非单次临时问询

【禁止抽取的负例（即使涉及金融）】
- 打招呼、寒暄："你好"、"谢谢"
- 单次行情问询："帮我看看茅台今天走势"、"000001最近怎么样"
- analyst 中间推理步骤、报告摘要（非用户表述）
- 无明确主动表述的猜测："用户可能喜欢..."

【输出格式（严格JSON，不得有额外文字）】
{"facts": [{"text": "...", "category": "...", "confidence": 0.0-1.0}]}

如果没有可抽取的事实，返回: {"facts": []}
每条 fact 的 text 须是对用户偏好的中文陈述句（30字以内）。

【few-shot 示例】
输入："我只买 A 股蓝筹，不碰小盘"
输出：{"facts": [
  {"text": "用户只投资A股蓝筹股", "category": "market_scope", "confidence": 0.95},
  {"text": "用户不投资小盘股", "category": "constraints", "confidence": 0.95}
]}

输入："帮我看看茅台今天走势"（无偏好表述）
输出：{"facts": []}

输入："我风险承受能力比较弱，最多亏 10% 就会很难受"
输出：{"facts": [
  {"text": "用户风险承受能力弱，最大回撤容忍约10%", "category": "risk_profile", "confidence": 0.85}
]}

输入："关注新能源和白酒板块，偶尔看看银行"
输出：{"facts": [
  {"text": "用户关注新能源板块", "category": "sector_focus", "confidence": 0.90},
  {"text": "用户关注白酒板块", "category": "sector_focus", "confidence": 0.90}
]}
"""

# ─────────────────────────────────────────────────────────────────────────────
# 记忆更新策略提示词（传入 Mem0 的 custom_update_memory_prompt）
# 决定新事实如何与现有长期记忆合并（ADD/UPDATE/DELETE/NONE）
# ─────────────────────────────────────────────────────────────────────────────
FINANCE_UPDATE_MEMORY_PROMPT = """
你是一个金融投资画像记忆管理系统。请决定如何处理新的记忆事实。

【操作类型】
- ADD:    用户第一次表达的新偏好/新标的
- UPDATE: 旧偏好被新说法明确替换（如"从稳健改成进取"）
- DELETE: 用户明确要删除某记忆（如"把光伏从关注列表去掉"）
- NONE:   新事实与现有记忆一致，或只是临时问询，不需要更新

【关键优先级约束（必须遵守）】
当新事实的来源（source metadata）为 chat_inferred 或 report_inferred 时：
  - 若现有同类别（category）记忆的来源为 ui 或 cold_start，决策必须为 NONE
  - 不得执行 UPDATE 或 DELETE，即使用户在对话中表达了不同意见
  - 除非用户在当前对话明确说"帮我改掉之前的设置"（此时视为 explicit_correction）

【示例】
场景：UI 设置了 risk_profile=conservative，现在对话中 LLM 推断出 risk_profile=aggressive
→ 决策：NONE（低优先级推断不覆盖高优先级 UI 设置）

场景：用户说"帮我把风险偏好改成进取"（chat 中的明确纠正）
→ 决策：UPDATE（用户主动纠正，视为 explicit_correction，可覆盖）

场景：用户说"我想了解一下白酒股最近行情"（临时问询）
→ 决策：NONE（不触发 sector_focus 更新）
"""

__all__ = [
    "PROMPT_VERSION",
    "FINANCE_FACT_EXTRACTION_PROMPT",
    "FINANCE_UPDATE_MEMORY_PROMPT",
]
