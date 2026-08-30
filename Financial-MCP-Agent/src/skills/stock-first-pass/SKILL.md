---
name: stock-first-pass
description: 面向单只股票的首轮研判 skill，基于个股基础信息、近期行情与核心财务指标做可核对的 first pass，回答“值不值得继续跟踪、财报怎么看、当前该重点关注什么”这类高频问题。
execution_mode: deterministic
allowed_tools:
  - get_stock_basic_info
  - get_market_bars
  - get_fina_indicator
  - get_income
  - get_balance_sheet
  - get_cashflow
---

# Stock First Pass

## Purpose

为单只 A 股搭建可核对的首轮研判框架。它回答“是否值得继续跟踪、当前证据支持什么、主要风险在哪里”，不替代完整研报，也不输出确定买卖点。

## When to Use

- 用户围绕单只 A 股提出首轮判断问题，例如“值不值得继续跟踪”“这份财报怎么看”“现在还能买吗”“核心风险是什么”。
- 用户需要一个可核对、可复述的 first pass，而不是完整深度研报或精确买卖点。
- 用户希望先快速建立“结论 + 证据 + 风险 + 后续跟踪点”的基本框架。

## When Not to Use

- 多标的基金比较、ETF 筛选、板块简报或异动原因问题应交给对应 Skill。
- 用户没有给出且上下文无法继承唯一股票主语时，不猜测标的。

## Required Inputs

- 用户原始问题。
- 单只明确的股票实体或股票代码。
- 用户画像摘要，只用于调整输出风格和风险表述。

## Workflow

1. 先确认这是单标的股票问题，不把多标的比较、板块分析、ETF 筛选混入本 skill。
2. 先查个股基础信息与近期市场数据，再补财务指标，避免只凭一句“财报好/不好”下结论。
3. 结论优先回答“当前值不值得继续跟踪”，而不是给绝对化买卖承诺。
4. 明确区分已确认事实、分析判断和仍待验证的问题。
5. 如果市场证据或财务证据缺失，只能给保守 first pass，不编造完整结论。

## Tool Use Guide

- `get_stock_basic_info` 先确认标的；`get_market_bars` 提供近期市场事实。
- `get_fina_indicator` 是核心财务证据，三表工具用于补充利润、负债和现金质量。
- 本 Skill 不使用网页搜索；新闻催化问题转 `market-move-explain`。

## Evidence Rules

- 强证据至少包含 `stock_basic`、`stock_market`、`financial_indicator`。
- 三表至少命中利润表、资产负债表、现金流量表之一，才展开经营质量判断。
- 行情事实与财务判断分开表达，证据不足时禁止补写结论。

## Degrade Policy

- 标的不明确：说明需要明确股票名称或代码。
- 只有行情没有财务：可以做交易面观察，但不能给扎实的基本面判断。
- 只有财务没有近期行情：可以做经营质量点评，但不能替代当前市场判断。
- 工具结果冲突或为空：保留已确认事实，明确边界。

## Output Contract

- 默认结构：
  - 先给 first pass 结论，再给核心证据、主要风险、适配建议、后续跟踪点、数据来源。
- `response_pref=risk_first`：
  - 先给风险和不确定性，再给结论和支持逻辑。
- `response_pref=concise`：
  - 压缩为结论、2 到 3 个核心证据、1 段风险提示。
- 始终标注：数据来源为 Tushare，并尽量给出数据时间或财报期。

## References

- `references/财务与风险口径.md`：财务指标、三表质量和非投资建议边界。
