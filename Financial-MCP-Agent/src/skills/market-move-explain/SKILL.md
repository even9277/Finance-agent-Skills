---
name: market-move-explain
description: 面向个股、ETF、指数、板块“为什么涨跌/异动”的解释型 skill，先用 Tushare 确认盘面事实，再用网页/新闻搜索补充催化线索，最终给出可核对、可追溯、保守的异动解释。
execution_mode: deterministic
allowed_tools:
  - get_stock_basic_info
  - get_market_bars
  - get_index_bars
  - get_sector_snapshot
  - get_sector_constituents
  - get_fund_basic_info
  - get_fund_market_bars
  - search_web_news
---

# Market Move Explain

## Purpose

解释个股、ETF、指数或板块的涨跌和异动。这个 skill 的原则是先用 Tushare 确认盘面事实，再用 `search_web_news` 搜索网页/新闻线索，最后只给“可能驱动”的保守解释，不把新闻标题写成确定原因。

## When to Use

- 用户问“为什么涨/为什么跌/为什么异动/为什么拉升/为什么跳水”。
- 对象可以是个股、ETF、指数、板块或主题。
- 用户需要的是可核对的盘面解释和保守判断，而不是只靠新闻猜原因。
- 适合“盘面事实 + 催化线索”双证据回答，不适合完整深度研报。

## When Not to Use

- 用户只是要单只股票 first pass，应交给 `stock-first-pass`。
- 用户只是筛选 ETF 或比较基金，应交给 `etf-screen` 或 `fund-compare`。
- 用户只问板块强弱简报且不需要原因解释，应交给 `sector-hotspot-brief`。
- 没有可识别的主语且上下文也无法继承时，不要猜测对象。

## Required Inputs

- 用户原始问题。
- 标的或板块关键词。
- 时间语境，例如“今天”“最近”“刚刚”。
- 当前会话里的 `active_entities` 与轻量画像背景，仅用于补主语和调整表达顺序。

## Workflow

1. 识别主语类型：个股、ETF/基金、指数、板块或主题。
2. 先查 Tushare 市场事实：个股用 `get_stock_basic_info` + `get_market_bars`，ETF 用 `get_fund_basic_info` + `get_fund_market_bars`，指数用 `get_index_bars`，板块用 `get_sector_snapshot` 和 `get_sector_constituents`。
3. 调用 `search_web_news` 搜索最近网页/新闻线索，默认围绕用户原问题补齐 A 股、公告、新闻等语境。
4. 对齐时间窗口：只有搜索线索和行情异动发生在相近窗口，才允许进入“可能驱动”。
5. 输出时分开写“已确认事实”“搜索线索”“可能驱动”“风险和不确定性”。

## Tool Use Guide

- Tushare 工具是强证据，用于确认价格、指数、板块、ETF 等市场事实。
- `search_web_news` 是统一 executor 里的补充工具，不是 skill 私有脚本。
- 网页搜索结果必须保留标题、链接、摘要和来源域名，便于 trace 和人工复核。
- 搜索结果只能提供候选催化，不能单独替代行情证据或写成“已确认原因”。

## Evidence Rules

- 强证据：Tushare 行情、指数、板块、ETF 数据。
- 弱证据：网页搜索结果、新闻摘要、公告标题。
- 只有强证据，允许做“数据侧解释”。
- 强证据和弱证据在对象、主题、时间窗口上互相支持，才允许做“较保守的原因解释”。
- 只有弱证据，不允许写“确认原因”，只能说明“搜索线索存在，但缺少市场事实支撑”。

## Degrade Policy

- 标的不清晰：提示用户补充具体对象。
- 没拿到有效行情/板块证据：明确无法可靠解释。
- 只有个体行情，没有板块或指数上下文：只做保守异动解读。
- 搜索工具不可用或未返回可靠结果：保留 Tushare 数据侧解释，不强行编新闻归因。

## Output Contract

- 默认结构：
  - 先给简短解释，再给已确认事实、搜索线索、可能驱动、风险提示、数据来源。
- `response_pref=risk_first`：
  - 先讲不确定性和误判风险，再给解释。
- `response_pref=concise`：
  - 保留一句解释、事实依据、风险提示、数据来源。
- 始终标注：
  - 价格/板块/ETF 等硬数据来源为 **Tushare**
  - 新闻/公告类补充线索来源为 **网页搜索结果**
  - 尽量给出数据日期和搜索来源域名

## References

- `references/新闻线索判读.md`：新闻线索的来源、匹配和保守表达规则。
- `references/数据与消息交叉验证.md`：盘面数据和搜索线索交叉验证方法。
