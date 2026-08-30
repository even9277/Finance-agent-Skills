---
name: market-move-explain
description: 面向个股、ETF、指数、板块“为什么涨跌/异动”的解释型 skill，先确认市场事实，再用可选网页新闻补充弱线索，不把未经验证的消息面当成已确认原因。
execution_mode: deterministic
allowed_tools:
  - get_stock_basic_info
  - get_market_bars
  - get_index_bars
  - get_sector_snapshot
  - get_sector_constituents
  - get_fund_basic_info
  - get_etf_basic_info
  - get_fund_market_bars
  - search_web_news
---

# Market Move Explain

## Purpose

解释个股、ETF、指数或板块的涨跌和异动。先用 Tushare 确认盘面事实，再用统一 `search_web_news` 补充新闻线索，最终只给保守的“可能驱动”。

## When to Use

- 用户问“为什么涨/为什么跌/为什么异动/为什么拉升/为什么跳水”。
- 对象可以是个股、ETF、指数、板块或主题。
- 用户需要“盘面事实 + 催化线索”的可核对保守解释，而不是完整新闻归因。

## When Not to Use

- 单股 first pass、基金比较、ETF 筛选或仅看板块强弱时交给对应 Skill。
- 没有可识别主语且上下文无法继承时，不猜测对象。

## Required Inputs

- 用户原始问题。
- 标的或板块关键词。
- 时间语境，例如“今天”“最近”“刚刚”。

## Workflow

1. 先给已确认的市场事实，例如近期涨跌、波动特征、是否属于某板块或主题。
2. 根据主体类型调用相应 Tushare 工具，先建立强市场证据。
3. 可选调用 `search_web_news` 获取最近线索，并对齐对象、主题和时间窗口。
4. 只有强证据与弱线索互相支持时，才进入“可能驱动”。
5. 输出显式区分“已确认事实”“搜索线索”和“可能驱动”。

## Tool Use Guide

- Tushare 工具是强证据；`search_web_news` 是同一 Executor 内的可选弱证据工具。
- 新闻结果必须保留标题、链接、摘要和来源域名，且不能回流 Retriever 或 Planner。
- 新闻线索不能单独替代行情证据，也不能写成已确认原因。

## Evidence Rules

- 强证据来自行情、指数、板块或 ETF 数据；弱证据来自网页新闻摘要。
- 只有强证据时允许数据侧解释；强弱证据对齐时允许保守原因解释。
- 只有弱证据时必须降级，禁止确认性归因。

## Degrade Policy

- 标的不清晰：提示用户补充具体对象。
- 没拿到有效行情/板块证据：明确无法可靠解释。
- 只有个体行情，没有板块或指数上下文：只做保守异动解读。
- 搜索关闭、无 key、失败或无可靠结果：保留数据侧解释，不强行补新闻。

## Output Contract

- 默认结构：
  - 先给简短解释，再给已确认事实、可能驱动、风险提示、数据来源。
- `response_pref=risk_first`：
  - 先讲不确定性和误判风险，再给解释。
- `response_pref=concise`：
  - 保留一句解释、事实依据、风险提示、数据来源。
- 始终分别标注 Tushare 强证据与网页搜索弱线索，并尽量给出日期和来源域名。

## References

- `references/新闻线索判读.md`：新闻来源、匹配和保守表达规则。
- `references/数据与消息交叉验证.md`：盘面数据与搜索线索交叉验证方法。
