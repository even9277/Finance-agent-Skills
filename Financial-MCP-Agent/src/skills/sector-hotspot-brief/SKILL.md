---
name: sector-hotspot-brief
description: 面向板块、行业、主题热点的简报 skill，基于板块快照、成分股与指数上下文回答“最近什么板块强、为什么热、龙头是谁、还能不能继续看”这类高频问题。
execution_mode: deterministic
allowed_tools:
  - get_sector_snapshot
  - get_sector_constituents
  - get_index_bars
---

# Sector Hotspot Brief

## Purpose

为板块、行业、主题或概念做热点简报，先确认板块事实，再补代表成分和指数上下文，回答强弱、扩散、龙头与追高风险。

## When to Use

- 用户询问某个板块、行业、概念或主题近期强弱、热点演化、代表性龙头、是否值得继续关注。
- 用户希望快速理解“板块层面的情况”，而不是单只股票的深度研究。
- 适合热点扫描、行业轮动观察、当日或近几日的板块强弱复盘。

## When Not to Use

- 单股 first pass、异动归因或 ETF 筛选分别交给对应 Skill。
- 板块主语无法识别时先澄清，不使用模型常识猜测。

## Required Inputs

- 用户原始问题。
- 板块、行业、概念或指数关键词。
- 用户画像摘要，仅用于调整表达与风险强调。

## Workflow

1. 优先回答板块整体表现，再补代表性成分股，不把个股结论冒充板块结论。
2. 尽量同时给出“板块现状 + 龙头/核心成分 + 风险提示”三层信息。
3. 如果缺少板块快照，可退回指数或成分股上下文，但要说明比较口径有限。
4. 对“还能不能追”这类问题，只能给观察性判断和风险提示，不给确定性承诺。
5. 若板块概念本身不明确，要先指出歧义。

## Tool Use Guide

- `get_sector_snapshot` 是板块事实主工具，`get_sector_constituents` 支持代表标的判断。
- `get_index_bars` 只提供指数近似上下文，不能替代板块快照。
- 事件驱动解释转 `market-move-explain`，本 Skill 不调用网页搜索。

## Evidence Rules

- `sector_snapshot` 是首选主证据；缺失时只能按 `index_daily` 降级观察。
- 龙头判断必须有成分或板块内部证据，不能凭模型常识指定。
- “还能不能追”必须说明拥挤、回撤和轮动风险。

## Degrade Policy

- 板块关键词不清晰：提示用户补充更明确的行业或主题。
- 只有板块快照，没有成分股：可做简报，但不展开龙头比较。
- 工具结果稀缺：只保留已确认的板块信息，避免编造热点成因。

## Output Contract

- 默认结构：
  - 先给板块简结论，再给热度依据、代表标的、风险、关注建议、数据来源。
- `response_pref=risk_first`：
  - 先讲“追高/拥挤/回撤”类风险，再讲板块亮点。
- `response_pref=concise`：
  - 保留结论、热点依据、风险提示、数据来源。
- 始终标注：数据来源为 Tushare，并尽量给出数据日期。

## References

- `references/板块简报口径.md`：板块与指数口径、龙头判断和追高风险。
