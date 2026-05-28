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

为单只 A 股做首轮可核对研判。这个 skill 不负责写完整研报，也不输出确定买卖点，而是把“标的是谁、近期行情怎样、财务质量有没有硬证据、当前主要风险是什么、后续还要跟踪什么”先搭成一个稳定的 first pass 框架。

## When to Use

- 用户围绕单只 A 股提出首轮判断问题，例如“值不值得继续跟踪”“这份财报怎么看”“现在还能买吗”“核心风险是什么”。
- 用户需要一个可核对、可复述的 first pass，而不是完整深度研报或精确买卖点。
- 用户希望先快速建立“结论 + 证据 + 风险 + 后续跟踪点”的基本框架。

## When Not to Use

- 用户同时比较多只股票、基金或 ETF，应该交给比较类或筛选类 skill。
- 用户主要问板块、行业、主题热点，应该交给 `sector-hotspot-brief`。
- 用户主要问“为什么今天涨跌”，且需要新闻/催化线索，应该交给 `market-move-explain`。
- 用户没有给出可继承的单一股票主语时，不要猜测标的。

## Required Inputs

- `stock_subject`：唯一股票名称或代码，必须能解析成单只 A 股。
- `effective_query`：经过 rewrite 后的用户问题，用来保留分析重点。
- `time_scope`：如“最近”“本季度”“财报期”，没有时使用默认近期窗口。
- `user_constraints`：风险偏好、持有周期、回答偏好等，只用于调整表达，不替代证据。

## Workflow

1. 先确认这是单标的股票问题，不把多标的比较、板块分析、ETF 筛选混入本 skill。
2. 调用 `get_stock_basic_info` 确认股票基础信息，避免把简称、别名或同名对象误当成目标股票。
3. 调用 `get_market_bars` 查看近期行情，把当前价格区间、涨跌、波动和趋势作为市场事实底座。
4. 调用 `get_fina_indicator` 获取核心财务指标，优先看盈利能力、成长性、偿债能力和现金质量相关字段。
5. 按需调用 `get_income`、`get_balance_sheet`、`get_cashflow` 补三表证据，判断利润、资产负债和经营现金流是否互相支持。
6. 综合市场事实和财务证据，输出 first pass 结论、支持证据、主要风险、适配建议和后续跟踪点。

## Tool Use Guide

- `get_stock_basic_info` 是标的确认工具，必须优先执行。
- `get_market_bars` 是近期市场证据工具，默认取近期交易窗口。
- `get_fina_indicator` 是财务指标主证据工具，不能只用三表替代。
- `get_income`、`get_balance_sheet`、`get_cashflow` 是财务质量补充工具，用于解释利润、负债和现金流是否匹配。
- 不调用网页/新闻搜索；如果用户需要异动原因或新闻催化，应路由到 `market-move-explain`。

## Evidence Rules

- 强证据必须至少包含 `stock_basic`、`stock_market`、`financial_indicator`。
- 三表证据至少需要命中 `income_statement`、`balance_sheet`、`cashflow_statement` 中的一类，才允许展开经营质量判断。
- 市场证据和财务证据要分开表述：行情只能说明价格和交易事实，财务指标才能支持基本面判断。
- 证据不足时只能输出保守观察，不允许补写不存在的财务结论。

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
