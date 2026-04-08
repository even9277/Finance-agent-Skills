---
name: etf-screen
description: 通用 ETF 筛选与推荐 skill，面向宽基、行业、主题、黄金、红利等场景，先发现候选 ETF/场内基金，再补净值、份额和场内行情证据，输出可核对的 shortlist 与筛选逻辑。
execution_mode: deterministic
allowed_tools:
  - get_fund_basic_info
  - get_etf_basic_info
  - get_fund_nav
  - get_fund_market_bars
  - get_fund_share
---

# ETF Screen

## When to Use

- 用户希望筛选、推荐、初步 shortlist 某类 ETF 或场内基金，例如宽基 ETF、黄金 ETF、红利 ETF、科创 ETF、半导体 ETF。
- 用户给出了风险偏好、持有周期、主题偏好、是否看重流动性等约束，希望得到更适合的候选。
- 用户需要“先找候选，再补证据”的真实筛选流程，而不是只比较两个已知产品。

## Inputs

- 用户原始问题。
- 主题、指数、行业、资产类别等筛选意图。
- 用户画像摘要，主要用于风险偏好、持有周期和回答偏好。

## Decision Rules

1. 先用基础信息发现候选 ETF/基金，再补净值、份额、场内行情做二次筛选。
2. 输出优先是 shortlist 和筛选逻辑，不是唯一推荐答案。
3. 尽量解释“为什么这些候选进入 shortlist”，例如主题匹配、近期表现、规模和流动性。
4. 如果候选很多，优先保留 2 到 3 只最像用户需求的产品。
5. 若证据不足，只能给方向性 shortlist，不编造确定性排序。

## Fallbacks

- 主题过于宽泛：先给高相关 ETF 方向，再提醒用户补充持有周期或风险偏好。
- 只有基础信息，没有表现或规模数据：只做候选归纳，不做强推荐。
- 工具结果冲突或为空：说明当前 shortlist 可靠性有限。

## Output Template

- 默认结构：
  - 先给 shortlist 结论，再给筛选逻辑、候选差异、主要风险、适配建议、数据来源。
- `response_pref=risk_first`：
  - 先讲波动、拥挤、主题偏差、流动性等风险，再给 shortlist。
- `response_pref=concise`：
  - 保留 shortlist、2 到 3 个筛选理由、风险提示、数据来源。
- 始终标注：数据来源为 Tushare，并尽量给出数据日期。
