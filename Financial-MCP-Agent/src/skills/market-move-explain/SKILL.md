---
name: market-move-explain
description: 面向个股、ETF、指数、板块“为什么涨跌/异动”的解释型 skill，基于行情和板块上下文给出可核对的事实与保守解释，不把未经验证的消息面当成已确认原因。
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
---

# Market Move Explain

## When to Use

- 用户问“为什么涨/为什么跌/为什么异动/为什么拉升/为什么跳水”。
- 对象可以是个股、ETF、指数、板块或主题。
- 用户需要的是可核对的盘面解释和保守判断，而不是完整新闻归因。

## Inputs

- 用户原始问题。
- 标的或板块关键词。
- 时间语境，例如“今天”“最近”“刚刚”。

## Decision Rules

1. 先给已确认的市场事实，例如近期涨跌、波动特征、是否属于某板块或主题。
2. 对“原因”只给基于当前数据能支持的解释，不把未验证消息当成确定事实。
3. 如能识别到板块联动，优先说明板块层面因素；否则只给个体层面的观察。
4. 如果只有行情没有更高层上下文，要明确说明“只能做数据侧解释，不能确认真实驱动事件”。
5. 输出中要显式区分“已确认事实”和“可能驱动”。

## Fallbacks

- 标的不清晰：提示用户补充具体对象。
- 没拿到有效行情/板块证据：明确无法可靠解释。
- 只有个体行情，没有板块或指数上下文：只做保守异动解读。

## Output Template

- 默认结构：
  - 先给简短解释，再给已确认事实、可能驱动、风险提示、数据来源。
- `response_pref=risk_first`：
  - 先讲不确定性和误判风险，再给解释。
- `response_pref=concise`：
  - 保留一句解释、事实依据、风险提示、数据来源。
- 始终标注：数据来源为 Tushare，并尽量给出数据日期。
