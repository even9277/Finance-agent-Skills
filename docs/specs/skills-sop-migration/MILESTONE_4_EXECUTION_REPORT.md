# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 4 — Retriever, Confidence Routing, Confirmation, and Skill-aware Rewrite
- Status: Complete
- Date: 2026-08-26
- Branch: `feature/skills-sop-migration`

## 2. Development Standards Read

- `PLAN.md`: 已读取 Milestone 4 的目标、范围、禁区、阈值/回退意图、测试和停止条件。
- `DEV_STANDARDS.md`: Not found。
- Personal/root `AGENTS.md`: 已读取；遵循唯一主仓库、历史仓库只读、typed interface、中文 Google-style docstring、测试先行、diff-first、默认离线和无授权不 commit/push。
- nested `AGENTS.md` / `AGENTS.override.md`: Not found。
- `CLAUDE.md`、Cursor/Copilot instructions: Not found。
- Small-step references: 已读取 development、execution、testing/failure、diff/commit 和 report template。
- Personal Python/Agent standard: 已读取并应用 Agent 边界、配置、错误、日志、秘密、类型和验证要求。

## 3. Files Inspected

- `Financial-MCP-Agent/src/conversation/{contracts,skill_discovery,routing,rewriting,workflow,ports,errors,entity}.py`: 理解链、实体优先级、路由、Rewrite、终态和 Port 现状。
- `Financial-MCP-Agent/src/skills/{contracts,loader,skill_registry}.py`: route metadata、input contract、请求固定 Loader 和 catalog facade。
- `backend/application/chat/factory.py`、`backend/config.py`、`backend/infrastructure/chat/providers.py`: 生产装配、现有 typed settings 和 OpenAI-compatible Provider 模式。
- `Financial-MCP-Agent/src/prompts/chat/registry.py`: 版本化 Prompt 加载模式。
- `tests/unit/conversation/**`、`tests/evals/{skill_activation,route,rewrite,skills_sop}/**`、`tests/e2e/test_controlled_chat_chain.py`: 既有行为、冻结红灯和离线纵向链。
- 两份用户口径文档及历史仓库：沿用 REQUIREMENT/RECON/TRADEOFF 中已抽取证据；本里程碑无历史 runtime import。

## 4. Files Modified

- `Financial-MCP-Agent/src/conversation/contracts.py`: 新增置信档位、typed candidates/rerank/confirmation，并让结果携带确认载荷。
- `Financial-MCP-Agent/src/conversation/ports.py`: 新增 metadata-only `SkillRerankerPort`。
- `Financial-MCP-Agent/src/conversation/skill_discovery.py`: 规则+资产 metadata 检索、集中阈值、候选解释、top-K rerank 和失败回退。
- `Financial-MCP-Agent/src/conversation/routing.py`: explicit 优先、high/mid/low 分层和结构化确认。
- `Financial-MCP-Agent/src/conversation/rewriting.py`: Loader input contract、主体基数、显式选择输入校验和多任务拆分。
- `Financial-MCP-Agent/src/conversation/workflow.py`: 注入同快照 Loader/reranker；确认在权限/计划/执行前终止；输出安全 route preview。
- `Financial-MCP-Agent/src/skills/skill_registry.py`: catalog routing view 携带已校验 spec metadata，并允许 catalog/Loader 共享同一固定快照。
- `Financial-MCP-Agent/src/prompts/chat/{registry.py,skill_rerank_v1.md}`: 版本化 rerank Prompt，明确禁止历史/记忆/正文/工具输入。
- `backend/infrastructure/chat/skill_rerank.py`: OpenAI-compatible typed adapter；默认不构造模型，返回不合法即由领域回退。
- `backend/{config.py,.env.example}`: `disabled/openai`、model、top-K、timeout 安全配置。
- `backend/application/chat/factory.py`: 一次固定 RegistrySnapshot 后装配 catalog、Loader 和可选 reranker。
- `tests/unit/conversation/{test_skill_routing_m4.py,test_skill_rerank_adapter.py}`: 15 项专项合同。
- `docs/specs/skills-sop-migration/{PLAN.md,MILESTONE_3_EXECUTION_REPORT.md,MILESTONE_EXECUTION_REPORT.md}`: 治理进度、上一报告归档和本报告。

## 5. Implementation Summary

Registry 的已校验 `route_metadata` 现在会进入不可变 routing view。Retriever 先执行少量稳定金融意图规则，再以 `when_to_use/when_not_to_use`、正反例和主体类型计算可解释候选；阈值统一收敛为 high（直接选择）、mid（结构化确认）和 low（Stage2/fallback）。

可选在线 rerank 默认关闭。启用时只发送当前 query 和最多 5 个 typed routing candidates，不发送对话历史、记忆、Skill Markdown、工具权限或 Reference；Provider 必须把每个 top-K 候选恰好返回一次。异常、越界、漏项或结构错误均回到 deterministic 分数。

中置信 `SkillConfirmation` 带候选名、分数、理由、版本和 Registry snapshot hash，Workflow 在 permission/planner/executor 之前以 `NEEDS_CLARIFICATION` 终止。用户显式选择只覆盖自动路由，Rewrite 仍从同一固定 Loader 加载 input contract，校验 `exactly_one/at_least_two/zero_or_more`、筛选意图和多任务拆分。

## 6. Diff Summary

- Retriever: 从硬编码单命中升级为资产 metadata + 规则的候选检索和置信分层。
- Confirmation: 从通用文字澄清升级为机器可消费、版本可追溯的终态载荷。
- Rewrite: 生产主链开始消费 Loader 的 input contract；explicit 不能绕过输入门禁。
- Rerank: 默认关闭、top-K typed、失败安全；没有新增依赖或第二执行器。
- Assembly: catalog 与 Loader 固定同一 RegistrySnapshot，避免并发刷新版本漂移。
- No unrelated refactor、数据库/API/前端/Planner/Evidence/Web News 改动。

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
| --- | --- | --- |
| `.venv/Scripts/python.exe -m pytest tests/unit/conversation/test_skill_routing_m4.py tests/unit/conversation/test_skill_rerank_adapter.py -q` | metadata/rerank/confirmation/explicit/input-contract/workflow | `15 passed` |
| `.venv/Scripts/python.exe -m pytest <understanding + activation/route/rewrite + controlled E2E> -q` | 既有理解链和纵向回归 | `17 passed` |
| `.venv/Scripts/python.exe -m pytest <catalog/registry/understanding/governance/E2E> -q` | 既有主链回归 | `24 passed` |
| `.venv/Scripts/python.exe -m pytest tests/evals/{skill_activation,route,rewrite,planner,mainline} -q` | 离线路由/改写/主线 eval | `6 passed` |
| `.venv/Scripts/python.exe -m pytest <Milestone 3 focused> -q` | Snapshot/LKG/Loader/catalog 回归 | `24 passed` |
| `.venv/Scripts/python.exe -m pytest <Milestone 2 focused> -q` | Asset/Gate/version/lifecycle 回归 | `27 passed, 2 deselected` |
| `.venv/Scripts/python.exe -m pytest tests/unit/conversation -q` | conversation 包宽回归 | `52 passed, 2 expected failed` |
| `.venv/Scripts/python.exe -m pytest <Milestone 1 target matrix> -q` | 后续红灯边界 | `23 passed, 3 expected failed` |
| `uv run --locked ruff check <M4 files>` | Lint | `All checks passed` |
| `uv run --locked pyright <M4 surface>` | 类型边界 | `0 errors, 0 warnings` |
| `uv lock --check` | 无依赖变化 | passed |
| `git diff --check`、history runtime import/usable-secret scans | 范围、格式和安全 | passed / no matches |
| 七条 route + explicit guard + Workflow confirmation Python smoke | 具体模块调用 | passed；五 Skill high、negative fallback、mid confirm、explicit clarify、`0 tool/0 model` |

## 8. Test Results

- Passed: M4 focused 15；existing mainline 24；existing eval 6；M3/M2 regression 24/27；Ruff、Pyright、lock、安全和具体调用 smoke。
- Expected failed: 3 项——公开 `ChatMessageRequest.explicit_skill`（Milestone 7）、`WEB_NEWS` 治理（Milestone 6）、`skills_sop` 可复现 runner（Milestone 8）。
- Not run: root full、frontend、Compose offline E2E、protected live 和真实在线 rerank；分别由 Milestones 7-9 或显式凭证环境验收。
- Limitations: 本里程碑只验收 route/rewrite/confirmation；spec-guided Planner/Evidence/Synthesis 属于 Milestone 5。

## 9. Failures and Fixes

- Failure: ETF 筛选“半导体 ETF”因板块实体与基金主体类型不一致被降为中置信。
- Root cause: 权威实体解析器把“半导体”作为筛选范围解析为 sector，但 Retriever 将它误当成待执行主体。
- Fix attempt: 仅在 `etf-screen + 明确基金 universe` 时把 sector 视为 screening scope，不增加基金主体。
- Rerun result: route/rewrite/activation/E2E `17 passed`。

- Failure: 首轮 Pyright 报告 optional reranker、BaseModel narrowing 和测试属性联合类型。
- Root cause: 防御性判断未在局部变量中完成类型收窄。
- Fix attempt: 显式收窄 reranker、使用 typed cast、先断言事件值为 `int`。
- Rerun result: `uv run --locked pyright` 最终 `0 errors, 0 warnings`。

- Failure: 锁定环境 Pyright 发现测试构造 `Settings(_env_file=...)` 不在静态签名。
- Root cause: pydantic-settings 运行时专用参数不属于生成的 typed constructor。
- Fix attempt: 用显式 `skill_rerank_provider="disabled"` 覆盖环境并删除专用参数。
- Rerun result: adapter/routing `15 passed`，Pyright 全绿。

## 10. Concrete Calls

```text
stock-first-pass       0.96 stage1_high
market-move-explain    0.98 stage1_high
fund-compare           0.98 stage1_high
etf-screen             0.92 stage1_high
sector-hotspot-brief   0.96 stage1_high
“黄金ETF是什么”         fallback / stage2
“分析黄金相关产品”      0.58 stage1_low / typed confirmation
explicit fund-compare + 1 fund -> fund_compare_requires_two_entities
confirmation Workflow stages -> context/entity_resolution/route/controller/termination
confirmation external calls -> tool=0, model=0
```

Registry: `registry-v2-e58213b8651c`；snapshot hash: `e58213b8651c7b26758f63d6d41d2711f9c42a67d835e4ba7f6e9b9481891165`。

## 11. Scope Compliance

- Allowed files only: Yes；实现位于 PLAN Section 8.3 全局允许面，`skill_registry.py` 和 factory 只承担 routing metadata/同快照 Loader 的必要装配。
- Forbidden changes avoided: Yes；未进入 Planner/Evidence/Executor/Web News/API/frontend/database/auth/deployment。
- User changes preserved: Yes；Milestones 1-3 的专题改动作为当前明确输入组合，未覆盖无关工作。
- Dependencies changed: No。
- API/database changed: No。
- Config changed: Yes，仅新增默认 `disabled` 的 typed rerank 非秘密设置和安全示例。
- Commit/push/PR: No。

## 12. Engineering Contract Compliance

| Category | Result | Evidence |
| --- | --- | --- |
| Architecture and dependency direction | Satisfied | Domain Port + infrastructure adapter；唯一 Workflow/Executor；factory 注入同一固定快照 |
| Docstrings, types, field meaning, section navigation | Satisfied | frozen dataclass/Protocol/Pydantic；中文公共 docstring；Pyright 全绿 |
| Configuration, secrets, constants, prompts | Satisfied | rerank 默认关闭；复用现有 secret；阈值集中在代码；Prompt 版本化；无可用 secret |
| Terminal output, logs, traces, artifacts | Satisfied | Provider 失败只记录 error type；route preview 为低基数字段；不记录 query/正文 |
| Validation, errors, retry/fallback, state, compatibility | Satisfied | typed output、候选闭合、deterministic fallback、确认终态、旧构造参数均可选 |
| Tests, evaluation, and handoff evidence | Satisfied | focused/related/static/target matrix/concrete calls 均有实测证据 |

## 13. Risks Remaining

- 当前 Planner/Verifier/Synthesis 仍使用通用硬编码路径；Milestone 5 必须分别消费同一 spec 的阶段视图，且不得建立第二 Executor。
- 公开 REST/WS/Frontend 尚不能传 `explicit_skill` 或展示确认卡；内部合同已准备，Milestone 7 完成协议闭环。
- 在线 rerank adapter 只通过 fake/失败路径验证；默认关闭，本轮没有使用真实 key、网络或付费模型。
- 当前 route scorer 为针对五类 SOP 的确定性基线；后续新增 Skill 必须补 route metadata/eval，而不是无限追加无测试规则。

## 14. PLAN.md Updates

- Progress: Milestone 4 marked complete with exact evidence。
- Decision Log: 记录资产 metadata routing、top-K rerank fallback、typed confirmation/input guard 和同快照装配。
- Surprises & Discoveries: 记录 ETF scope entity、ENTITY_REQUIRED 顺序、Pyright 入口和 3 个后续红灯。
- Outcomes & Retrospective: 更新为 route/rewrite 主链已接入、23 green/3 future red 和具体调用结果。

## 15. Suggested Commit Message

```text
feat(skills): add metadata routing and input guards

- route five SOP skills with confidence bands and typed confirmation
- validate explicit skills through snapshot-fixed rewrite contracts
- add optional top-k rerank with deterministic failure fallback
```

## 16. Handoff to User

Milestone 4 is complete. I will not proceed to the next milestone unless you explicitly ask me to continue.
