# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 4 — Planner, Validator, Executor, and Tool Governance Migration
- Status: Complete, pending GitHub PR delivery at report creation time
- Date: 2026-08-24
- GitHub tracking: [Issue #11 — feat: migrate controlled planner executor and tool governance](https://github.com/even9277/Finance-agent-Skills/issues/11)
- Local branch: `feat/11-controlled-tool-governance`

## 2. Scope and Standards

- 只迁移 Planner、Validator、Executor 和 Tool Governance，不切换公开 REST/WebSocket，不迁移 M5 Evidence/Controller/Replanner/Synthesis。
- 完整遵循 `PLAN.md`、仓库 `AGENTS.md`、`CONTRIBUTING.md`、工程结构/测试/观测文档、个人 Python Agent 工程标准和 small-step 执行协议。
- 未新增依赖、数据库 Schema、环境变量、历史 Runtime Adapter、双写或 `Finance` 运行时引用。
- 默认测试只使用确定性实现或 Fake external Port，没有调用真实 LLM、Tushare 或生产服务。

## 3. Files and Modules Changed

- `Financial-MCP-Agent/src/conversation/contracts.py`: 新增强类型工具 Schema、只读策略、权限快照、计划、校验后计划、调用、结果、预算与错误合同。
- `Financial-MCP-Agent/src/conversation/tool_governance.py`: 新增版本化只读工具治理目录，集中描述 15 个当前对话 Tushare 工具的参数、数据维度和副作用。
- `Financial-MCP-Agent/src/conversation/permissions.py`: 新增 Skill 执行白名单与治理目录求交的请求级冻结权限解析。
- `Financial-MCP-Agent/src/conversation/planning.py`: 新增确定性 requirement-to-tool 计划、多主语步骤、稳定计划 ID 和 action 幂等指纹。
- `Financial-MCP-Agent/src/conversation/validation.py`: 新增权限、只读、参数、实体、预算、重复 action、依赖和环校验，并输出拓扑执行层。
- `Financial-MCP-Agent/src/conversation/execution.py`: 新增仅接收 `ValidatedToolPlan` 的有界并发执行、总/单工具超时、瞬时失败重试、永久失败终止、依赖跳过和防御性去重。
- `Financial-MCP-Agent/src/conversation/errors.py`: 新增可由执行边界稳定分类的瞬时与永久工具错误。
- `Financial-MCP-Agent/src/conversation/rewriting.py`: 扩展业务需求到证据维度的强类型映射。
- `Financial-MCP-Agent/src/conversation/workflow.py`: 将权限、计划、校验和执行阶段接入 M2/M3 单一 Orchestrator，并输出稳定阶段指标。
- `backend/infrastructure/chat/testing.py`: 让 Fake timeout 工具名称与新治理目录一致。
- `tests/unit/conversation/`、`tests/evals/{planner,executor}`、`tests/e2e/test_controlled_chat_chain.py`: 新增合同、bad case、固定离线评测和纵向路径证据。

## 4. Migrated Behavior Matrix

| Module | Migrated contract and behavior | Verification |
|---|---|---|
| Tool Governance | 15 个只读工具的版本化名称、参数类型/范围、证据维度和副作用；未知或写工具不进入权限 | catalog/permission unit tests |
| Permission | Skill execution view 与治理目录求交；Tushare 只按需求映射最小工具集；快照不可变且可哈希复现 | unit/contract/E2E |
| Planner | 只从权限快照选择工具；参数强类型；多基金按主语拆步；计划和 action ID 稳定 | planner unit + eval |
| Validator | 权限、只读、Schema、实体、最大步骤、重复 ID/action、未知依赖、循环和证据维度覆盖 | validator bad-case matrix |
| Executor | 只接受校验后计划；按拓扑层并发；执行边界再去重；依赖失败后跳过下游 | executor unit + eval |
| Timeout/Retry | 单工具和总预算；只有 timeout/瞬时失败可在上限内重试，永久或未知失败不重试 | timeout/failure tests |
| Workflow | 高置信股票 SOP 可从理解链进入计划和工具执行；M5 未迁移部分以受控基线收口 | full-chain E2E |

## 5. Test and Check Evidence

| Check | Result |
|---|---|
| M4 scoped Ruff | `All checks passed` |
| M4 scoped Pyright | `0 errors, 0 warnings` |
| M4 focused unit/eval/E2E | `42 passed` |
| `pytest backend -q` | `12 passed` |
| `pytest Financial-MCP-Agent -q -m "not live"` | `33 passed, 4 deselected` |
| `pytest tests/unit tests/contract -q` | `39 passed, 1 xfailed` |
| `pytest tests/integration -q -m integration` | `3 passed, 1 skipped` |
| `pytest tests/evals -q -m "eval_smoke and not live"` | `9 passed, 1 skipped` |
| `pytest tests/e2e -q -m e2e` | `12 passed, 1 skipped` |
| `pytest -q` | `108 passed, 3 skipped, 4 deselected, 1 xfailed` |
| `uv lock --check`、`git diff --check` | 通过 |
| Offline Compose build/run | 前端、后端镜像构建成功；Nginx/FastAPI/PostgreSQL 健康；容器测试 `56 passed, 1 xfailed`；E2E 容器退出码 0 |
| Compose cleanup | 容器、网络、数据卷删除；`ps --all` 为空 |

Planner/Executor eval 已从“因不存在旧模块而 skip”改为实际执行新受控组件。固定离线案例和 Fake 工具结果只能证明合同及控制流，不代表真实模型质量或 Tushare 数据正确性。

## 6. Failure and Recovery Record

测试先行阶段按预期因新合同与组件尚不存在而 collection 失败，不计入修复次数。实现后的第一次窄修复调整了错误参数所属工具和永久失败步骤的测试定位；第二次窄修复移除了旧 M2 测试对已替代 `DeterministicPlanner` 的导入，改为直接验证唯一 `ControlledPlanner` 主链。之后 focused、静态、分层全量和 Compose 均通过，没有第三次实现修复。

## 7. Trace and Failure Semantics

- 计划、权限快照、工具调用和结果携带同一 `trace_id`，执行阶段输出总调用数、失败数、去重数和批次数。
- 越权、写工具、非法参数、重复 action、未知依赖、循环和预算超限在执行前被稳定错误码拒绝。
- timeout/瞬时失败仅在固定次数和时间预算内重试；永久、未知失败不重试；异常原文不进入安全结果。
- 依赖失败的下游步骤标记 `SKIPPED`，不会误报调用成功；重复 action 在 Validator 与 Executor 两层拦截。
- 没有在日志、报告、fixture 或 Trace 中写入秘密、授权头、Provider payload 或真实模型响应。

## 8. Remaining Risks and Honest Limitations

- 公开 REST/WS 仍走旧 `backend/services/chat_service.py`；M4 新链通过直接 Application/Workflow E2E 和同一 Compose 容器测试验证，公开入口切换属于 M6。
- Evidence/Verifier/Controller/Replanner/Synthesis 属于 M5；当前股票路径仍复用 M2 单实体基线，实体缺失 SOP 在工具执行后诚实返回 `UNSUPPORTED`。
- M4 的 ToolPort 仍为 Fake；真实 LLM/Tushare 受保护只读 E2E 尚未执行，不能据此宣称 Provider 或行情生产可用。
- 历史 `src/agents` planner/executor 仍存在，但新 Workflow 不引用；按 M6 入口切换和旧编排删除计划统一收敛，不新增 Adapter 或双写。
- 全仓旧代码仍有静态债务；M4 触及范围 Ruff/Pyright 为零问题。
- Compose 暴露既有 PostgreSQL 初始化重复 `ALTER TABLE` 和事务中止日志；应用与测试成功，但数据库迁移幂等性仍是技术债。
- 既有 WS 内部异常泄露 strict xfail、Starlette TestClient 与 `datetime.utcnow()` 弃用警告仍保留，未在 M4 越界修复。

## 9. Rollback

M4 没有切生产入口、改 Schema、改依赖或访问真实外部服务。合并后可通过 revert 本里程碑 squash commit，恢复 M3 的理解链边界；不需要数据回滚或配置恢复。

## 10. Suggested Commit Message

```text
feat(controlled-chat): govern planned tool execution

- freeze typed read-only tool permissions and validated DAG contracts
- execute bounded concurrent tool layers with retry and failure semantics
- enable planner and executor offline evals and workflow E2E

Closes #11
```

## 11. Handoff

下一个且唯一执行单元是 M5：归一化工具结果，建立 Evidence/Verification/Controller/Answer 唯一合同，并以有界补证证明证据不足不强答。M5 不得提前切换 REST/WS，也不得把真实模型或生产数据源放进默认测试。
