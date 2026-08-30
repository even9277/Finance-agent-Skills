# Milestone 5 Execution Report

## 1. Milestone

Spec-guided Planning, Evidence, Degrade, and Synthesis

- Date: 2026-08-26
- Branch: `feature/skills-sop-migration`
- Status: COMPLETE
- Commit / push / PR: Not performed

## 2. Frozen Contract

- Goal: 让 financial-sop 的 permission、planner、validator、verifier、controller 和 synthesis 消费同一请求固定 spec 的最小阶段视图，并继续复用唯一执行内核。
- Allowed area: `conversation/{contracts,permissions,planning,tool_governance,validation,verification,control,synthesis,workflow,execution}.py`、版本化 prompt、相关 tests/evals/e2e 与本专题文档。
- Excluded: Web News Provider/治理、公开 API/前端、数据库、依赖、鉴权、部署、真实凭证、历史 runtime 导入、第二 Executor、记忆权威逻辑。
- Escalation conditions: 第二执行环、reference 扩权、rejected evidence 进入回答、需要修改记忆权威边界或禁区文件。

## 3. Files Changed in This Milestone

### Domain and workflow

- `Financial-MCP-Agent/src/conversation/contracts.py`
- `Financial-MCP-Agent/src/conversation/tool_governance.py`
- `Financial-MCP-Agent/src/conversation/permissions.py`
- `Financial-MCP-Agent/src/conversation/planning.py`
- `Financial-MCP-Agent/src/conversation/validation.py`
- `Financial-MCP-Agent/src/conversation/execution.py`
- `Financial-MCP-Agent/src/conversation/verification.py`
- `Financial-MCP-Agent/src/conversation/control.py`
- `Financial-MCP-Agent/src/conversation/synthesis.py`
- `Financial-MCP-Agent/src/conversation/workflow.py`

### Prompt

- `Financial-MCP-Agent/src/prompts/chat/registry.py`
- `Financial-MCP-Agent/src/prompts/chat/synthesis_v3.md`

### Tests and eval fixtures

- `backend/infrastructure/chat/testing.py`
- `tests/unit/conversation/test_skill_spec_execution_m5.py`
- `tests/unit/conversation/test_tool_governance.py`
- `tests/evals/planner/test_planner_eval.py`
- `tests/evals/planner/data/smoke.jsonl`
- `tests/evals/executor/test_executor_eval.py`
- `tests/evals/executor/data/smoke.jsonl`
- `tests/evals/synthesis/test_synthesis_eval.py`
- `tests/e2e/test_controlled_chat_chain.py`
- `tests/e2e/offline_app.py`

### Governance artifacts

- `docs/specs/skills-sop-migration/PLAN.md`
- `docs/specs/skills-sop-migration/MILESTONE_4_EXECUTION_REPORT.md`（归档上一里程碑报告）
- `docs/specs/skills-sop-migration/MILESTONE_EXECUTION_REPORT.md`

## 4. Implementation Summary

### 4.1 Permission

financial-sop 权限现在固定为 `PlannerSkillView.allowed_tools ∩ ToolGovernanceCatalog`。Skill/version/spec hash/Registry snapshot hash 写入不可变权限快照；Planner 必须提交同一身份。`market-move-explain` 虽在资产中声明 `search_web_news`，但 Milestone 6 完成统一治理前不会获得该权限，也不会产生该调用。

### 4.2 Planning and validation

Planner 不再根据 Rewrite 的少量硬编码需求生成 SOP 计划，而是逐项消费 spec 的 `tool_plan_steps`、`required`、模板参数、`repeat_for_each_subject`、并发和证据合同。基金比较对两个权威主体生成 10 个节点；个股首轮生成 6 个节点；板块简报生成 3 个节点；ETF 筛选保留 `top_n=3` 和触发工具元数据。

所有节点仍进入既有 `PlanValidator`，继续校验只读权限、参数 Schema、权威主体、重复动作、DAG、预算和证据覆盖。Validator 新增 spec/permission 身份闭合、must-all/must-any/per-symbol/min-distinct 计划前覆盖校验。

### 4.3 Execution

只保留 `ControlledExecutor` 一个实现和 Workflow 中一个生产实例。Executor 仍只接受 `ValidatedToolPlan`，并发上限取请求预算与 Skill spec batch size 的较小值；没有新增私有执行器、动态脚本或第二执行环。

### 4.4 Evidence and degrade

Verifier 在既有主体、时间、新鲜度、来源、冲突门禁上增加金融 SOP 字段语义质量门禁，并验收：

- `must_have_all`
- `must_have_any`
- `per_symbol_must_have_any`
- `min_distinct_symbols`

缺口以稳定 `missing_evidence_groups` 和维度并集返回。Controller 继续遵守有界 replan 预算，并将 spec degrade stage 写入决定；证据完整为 `primary`，基金单主体缺少动态证据为 `partial_compare`，无可接受证据到终止阶段或按策略澄清/拒绝。

### 4.5 Synthesis and memory boundary

`synthesis_v3` 只允许模型消费 accepted evidence。`skill_guidance` 仅包含输出章节顺序、风格变体、Controller 已选降级阶段和 synthesis-stage 静态 reference；不包含工具白名单或计划模板。Reference 明确只是方法/口径参考，不能作为当前市场事实；retrieved memory 仍只影响表达偏好和历史语境，不能提升 claim level、扩权或替代证据。

## 5. Five-Skill Concrete Calls

| Case | Plan/tool calls | Result | Claim | Degrade |
| --- | ---: | --- | --- | --- |
| `stock-first-pass` | 6：基础、行情、指标、利润表、资产负债表、现金流 | `SUCCEEDED` | `ANALYTICAL` | `primary` |
| `fund-compare` | 10：5 个模板步骤 × 2 个主体 | `SUCCEEDED` | `ANALYTICAL` | `primary` |
| `etf-screen` | 5：基金/ETF 候选、净值、行情、份额 | `SUCCEEDED` | `ANALYTICAL` | `primary` |
| `sector-hotspot-brief` | 3：板块快照、成分、指数背景 | `SUCCEEDED` | `ANALYTICAL` | `primary` |
| `market-move-explain` | 5：股票基础/行情、指数与板块背景；Web News 被治理交集排除 | `SUCCEEDED` | `ANALYTICAL` | `primary` |
| `fund-compare` 缺一主体动态证据 | 10；`per_symbol:159937.SZ` 缺口 | `PARTIAL` | `DESCRIPTIVE` | `partial_compare` |

每个成功 case 只有 1 个 `execute` 事件和 1 次 synthesis model call。并发下 Port 接收顺序可不同于模板顺序，但 `ToolPlan.steps`、step id 和证据合同保持确定性。

## 6. Tests and Checks

| Command / Method | Result |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest tests/unit/conversation/test_skill_spec_execution_m5.py -q` | `12 passed` |
| `.venv/Scripts/python.exe -m pytest tests/unit/conversation --ignore=tests/unit/conversation/test_skill_sop_migration_contract.py -q` | `62 passed` |
| `.venv/Scripts/python.exe -m pytest tests/unit/skills tests/contract/test_skill_assets_v2_contract.py tests/contract/test_skill_catalog_contract.py -q` | `43 passed` |
| `.venv/Scripts/python.exe -m pytest tests/evals/{skill_activation,route,rewrite,planner,executor,verifier,synthesis,mainline} -q` | `9 passed` |
| `.venv/Scripts/python.exe -m pytest tests/e2e/test_controlled_chat_chain.py tests/unit/conversation/test_skill_spec_execution_m5.py -q` | `23 passed` |
| `uv run --locked ruff check <M5 surface>` | All checks passed |
| `uv run --locked pyright <conversation + M5 test surface>` | `0 errors, 0 warnings` |
| `uv lock --check` | passed；无依赖变化 |
| `git diff --check` | passed；仅已有 Windows LF/CRLF 提示 |
| history runtime import / usable secret scans | no matches |
| concrete six-case Workflow smoke | 五 Skill成功 + 一条 spec 降级成功；single executor proof passed |

Target matrix command：

```text
.venv/Scripts/python.exe -m pytest \
  tests/unit/conversation/test_skill_sop_migration_contract.py \
  tests/evals/skills_sop/test_skills_sop_eval.py -q
```

Result: `3 passed, 3 failed as planned for later milestones`：

1. public `ChatMessageRequest.explicit_skill` — Milestone 7
2. `EvidenceDimension.WEB_NEWS` / governed `search_web_news` — Milestone 6
3. reproducible `skills_sop` runner target — Milestone 8

## 7. Failures and Repairs

### Snapshot tool order false mismatch

- Failure: 首轮 M5 focused `11 failed`，均在 permission 阶段报 planner/execution tool views 不一致。
- Root cause: Registry execution view 对工具名稳定排序，Planner view 保留 spec 声明顺序；身份、hash 和工具集合实际相同。
- Repair: 继续严格比较 Skill/version/spec/Registry hash，工具闭合改为集合相等；计划步骤仍保持 spec 顺序。
- Rerun: `11 passed`，增加降级 E2E 后最终 `12 passed`。

### Existing tests used pre-spec three-step assumptions

- Failure: 旧治理/Planner/Executor/E2E fixtures 未提供固定 Loader，并假设个股 SOP 只有 3 个工具；synthesis eval 固定 v2 prompt。
- Root cause: Milestone 5 按计划改变 financial-sop 合同，测试仍验证 M4 的临时硬编码行为。
- Repair: 测试从同一 RegistrySnapshot 构造 catalog+Loader，gold 更新为真实 spec 步骤，离线 Tool fixture 返回各维度字段合格事实，prompt gold 更新为 v3。
- Rerun: related eval/E2E `16 passed`，最终相关组合 `23 passed`。

### ETF partial test-fixture collision

- Failure: 新增基金降级 fixture 后，ETF screen 被误判 partial。
- Root cause: 无主体 ETF 调用的 symbol 为空，恰好等于 fixture 默认空的 drop symbol。
- Repair: 只有显式配置非空 drop symbol 时才丢弃动态证据。
- Rerun: focused `12 passed`。

## 8. Diff and Scope Review

- Allowed files only: Yes.
- Existing user work preserved: Yes；Milestones 1-4 改动继续作为本里程碑输入，未覆盖无关文件。
- Second executor / private runtime: No；源码只有一个 `ControlledExecutor` 类，Workflow 只构造一个实例。
- Unaccepted evidence in model context: No；`AnswerContextPack.create` 仍只复制 `verification.accepted`，rejected 仅保留无事实摘要。
- Reference permission escalation: No；synthesis guidance 不含 allowed tools/plan，权限只来自 planner view 与治理目录交集。
- Memory authority change: No.
- API / frontend / database / auth / deployment change: No.
- Dependency or real secret change: No.
- Historical `Finance` runtime import/path dependency: No.

## 9. Risks and Deferred Work

- `search_web_news` 仍只是资产声明；本里程碑明确 fail-closed 排除，Milestone 6 才接入统一弱证据治理和 Provider。
- 公开 REST/WS/前端仍不能提交/确认 explicit Skill，归 Milestone 7。
- `skills_sop` 可复现 runner 与完整 route→synthesis 低基数 trace 元数据归 Milestone 8。
- ETF `candidate_expansion.top_n` 已进入计划合同和 Trace-ready 字段；当前离线实现以 query 型受控工具调用验证，真实候选回填需在 Provider/Compose/live 验收中确认，不能由 Planner 读取执行结果后建立第二执行环。

## 10. Suggested Commit Message

```text
feat(skills): drive controlled analysis from skill specs

- intersect skill permissions with governed read tools
- plan and verify spec evidence groups through the single executor
- apply skill degrade and synthesis contracts to accepted evidence
```

## 11. Handoff

Milestone 5 is complete. The next frozen step is Milestone 6: add `search_web_news` as a default-off, read-only weak-evidence tool through the same governance, Validator and `ControlledExecutor` path.
