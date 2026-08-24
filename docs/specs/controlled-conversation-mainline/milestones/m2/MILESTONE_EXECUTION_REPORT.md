# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 2 — Typed Contracts and Offline Vertical Slice
- Status: Complete, pending GitHub PR delivery at report creation time
- Date: 2026-08-24
- GitHub tracking: [Issue #7 — feat: establish typed controlled-chat vertical slice](https://github.com/even9277/Finance-agent-Skills/issues/7)
- Local branch: `feat/7-controlled-chat-vertical-slice`

## 2. Development Standards Read

- `PLAN.md`: 完整读取，只执行 M2，保持公开 REST/WS 不切换。
- Personal/repository `AGENTS.md`、`CONTRIBUTING.md`、工程结构/测试/观测文档：完整读取并遵守分层、中文合同文档、默认离线、秘密保护和 GitHub 闭环规范。
- `C:\Users\27411\.codex\PYTHON_AGENT_ENGINEERING_STANDARD.md`: 完整读取并落实 Typed State、稳定错误码、有限预算、Port 隔离和 Trace 关联要求。
- `small-step-implementation/SKILL.md` 及全部引用：完整读取并执行先测试、一次一个里程碑、窄修复、diff review 和执行报告协议。

## 3. Files Inspected

- `backend/services/chat_service.py`、`backend/routers/chat.py`: 确认 M2 不改现有公开入口和巨型旧编排。
- `Financial-MCP-Agent/src/agents/skill_router_node.py`、`skill_executor_node.py`、`skill_evidence.py`: 识别可在后续里程碑迁移的规则，M2 不形成运行时依赖。
- `Financial-MCP-Agent/src/utils/state_definition.py`: 对比旧 `Dict[str, Any]` 状态并建立独立 Typed Conversation State。
- `Financial-MCP-Agent/src/tools/skill_trace.py`: 对齐 trace/run/stage/error 基础字段和 exporter 隔离语义。
- `docker/Dockerfile.e2e`、`docker/docker-compose.offline.yml`: 确认容器测试会执行 `tests/e2e`，公开 HTTP 当前仍使用旧 offline 装配。

## 4. Files Modified

- `Financial-MCP-Agent/src/conversation/`: 新增合同、状态机、错误、Ports 和 Context/Entity/Route/Rewrite/Permission/Plan/Validate/Execute/Verify/Controller/Synthesis/Workflow 阶段。
- `Financial-MCP-Agent/src/prompts/chat/`: 新增版本化 synthesis Prompt 和只读注册入口。
- `backend/application/chat/`: 新增单一 `ControlledChatUseCase`，协调工作流与最终结果保存。
- `backend/infrastructure/chat/testing.py`: 新增 Model/Tool/Repository/Trace 四个外部 Port 的确定性 Fake。
- `tests/fixtures/conversation/vertical_slice_cases.json`: 新增四条版本化纵向案例。
- `tests/unit/conversation/`、`tests/contract/test_controlled_conversation_contracts.py`、`tests/e2e/test_controlled_chat_chain.py`: 新增状态、合同、依赖方向和全链验收。
- `docs/specs/controlled-conversation-mainline/PLAN.md`: 更新 M2 进度、决策、发现、结果和 M3 交接。
- 本报告：记录验收、限制、修复和回滚证据。

## 5. Implementation Summary

M2 建立了可运行的模块化单体纵向基线：Protocol/API 层尚未接入，Application 用例调用唯一 Domain Workflow，Workflow 按显式状态机执行全部受控阶段，Infrastructure 仅在 Model、Tool、Repository、Trace 四个外部边界使用 Fake。核心状态使用 dataclass、`StrEnum` 和只读 tuple，不以 `dict[str, Any]` 传递业务主状态；阶段事件携带连续 sequence、trace_id、run_id、stage、status、error_code 和安全属性。

四条业务路径共享同一 Orchestrator：`600519.SH` 成功；“平安现在能买吗”在工具前进入 `NEEDS_CLARIFICATION`；行情工具超时在两次受控尝试后返回 `PARTIAL`；行情空证据经 Verifier/Controller 返回 `PARTIAL`。Synthesis 只接收验收通过的 Evidence，步骤总预算和 Trace sink 故障也有独立收口测试。

## 6. Contract and Module Evidence

| Boundary / stage | Input | Output / responsibility |
|---|---|---|
| Application | `ConversationRequest` | 执行唯一 Workflow 并通过 Repository Port 保存唯一结果 |
| Context | Request + budget/version | `ConversationRunContext`、稳定 trace/run 标识 |
| Entity | message/context | 唯一 `Entity` 或显式澄清候选 |
| Route | resolved entity/message | `RouteDecision`，不改写实体 |
| Rewrite | route/entity/message | `RewrittenQuery` 结构化查询 |
| Permission | route/tool metadata | 不可变 `PermissionSnapshot` 与 hash |
| Planner/Validator | rewrite + snapshot | `ToolPlan` / `ValidatedToolPlan`，越权执行前失败 |
| Executor | validated plan | 有限次数 `ToolObservation`，稳定错误分类 |
| Verifier | observations | accepted/rejected Evidence 与缺失维度 |
| Controller | verification + budget | 唯一继续/澄清/部分/失败/成功决策 |
| Synthesis | `AnswerContextPack` | 仅基于 accepted Evidence 的回答 |
| Workflow | all stage contracts | `ConversationResult` + 连续 `WorkflowEvent` + 唯一终态 |

## 7. Tests / Checks Run

| Command | Result |
|---|---|
| 首次聚焦 pytest（测试先行） | 预期 collection red：`src.conversation`、`backend.application` 尚不存在 |
| M2 范围 Ruff | 首轮 1 个 unused variable；修复后 `All checks passed` |
| M2 范围 Pyright | 首轮 2 个 Protocol 方法体问题；修复后 `0 errors, 0 warnings` |
| M2 聚焦 unit/contract/e2e | `25 passed` |
| `pytest backend -q` | `12 passed` |
| `pytest Financial-MCP-Agent -q -m "not live"` | `33 passed, 4 deselected` |
| `pytest tests/unit tests/contract -q` | `28 passed, 1 xfailed` |
| `pytest tests/integration -q -m integration` | `3 passed, 1 skipped` |
| `pytest tests/evals -q -m "eval_smoke and not live"` | `6 passed, 4 skipped` |
| `pytest tests/e2e -q -m e2e` | `9 passed, 1 skipped` |
| `pytest -q` | `91 passed, 6 skipped, 4 deselected, 1 xfailed` |
| `docker compose ... up --build --abort-on-container-exit` | 前端 build 成功；容器测试 `42 passed, 1 xfailed`；退出码 0 |
| Compose cleanup + `ps --all` | 容器、网络、卷已删除，列表为空 |
| `uv lock --check`、`git diff --check` | 通过 |

## 8. Trace Example

成功案例的安全摘要如下；真实对象另含 trace_id/run_id，但报告不保存用户载荷或 Provider 原文：

```json
{"status":"SUCCEEDED","error_code":null,"tool_call_count":2,"stages":["context","entity_resolution","route","rewrite","permission","plan","validate","execute","verify","controller","synthesis","termination"]}
```

事件 sequence 为 1–12 连续值，所有事件使用同一 trace_id/run_id，终止事件唯一且最后出现。Trace sink 故障被隔离，业务结果仍为 `SUCCEEDED`。

## 9. Failures and Fixes

### Repair attempt 1

- Failure: Ruff 报告路由局部变量未使用；Pyright 报告两个 Protocol 方法缺少抽象体。
- Fix: 让路由原因/置信度真实依赖识别结果，为 Protocol 方法补充 `...`，并收窄 Workflow helper 类型。
- Rerun: M2 Ruff/Pyright 全通过，聚焦测试通过。

随后主动增强了总步骤预算、精确阶段序列、accepted Evidence 隔离和错误码断言；这些增强首次即通过。没有发生第二次失败修复，因此未触发 blocked 条件。

## 10. Scope Compliance

- 只执行 M2，未切公开 REST/WS。
- 未修改数据库 Schema、依赖、锁文件、CI、Docker、真实 `.env` 或生产服务。
- 未从历史 `Finance` 导入运行时代码，未增加 Adapter、双写或长期双 Runtime。
- 默认测试未调用真实 LLM/Tushare；Fake 只位于四个外部 Port，核心 Orchestrator 没有被替换。
- 用户已有改动和已合并 M0/M1 基线均保留。

## 11. Static Debt Disclosure

新增 M2 范围 Ruff/Pyright 为零问题。额外执行的全仓严格扫描仍失败：Pyright 报告 111 个既有错误/15 个警告，Ruff 问题集中于旧 Agent/Backend 文件；这些文件不属于 M2 允许修改范围。CI 当前尚未对所有历史文件执行同等严格静态门禁，M7 会在不降低规则的前提下扩展新增主链覆盖。此限制不影响 M2 测试通过，但意味着不能宣称“全仓静态检查已清零”。

## 12. Risks Remaining

- 公开 REST/WS 仍走旧 `chat_service.py`；M2 只证明新工作流在 Application 和容器测试环境可运行。
- 当前确定性 Entity/Route/Planner/Verifier 是合同基线，尚未迁入历史复杂规则和 provider adapters。
- Repository/Trace 只有测试实现，真实数据库/skill_trace adapter 分别属于 M6/M7。
- Compose 中旧数据库初始化会输出重复列/事务中止日志，但应用健康、测试通过；需后续独立治理。
- 既有 strict xfail（WS 内部错误泄露）、弃用警告和全仓静态债务仍未修复。

## 13. Rollback

M2 未切生产入口，可通过单独 revert 本里程碑新增目录、测试和文档恢复 M1，不涉及数据回滚、Schema 迁移、配置或依赖恢复。GitHub 交付后以 PR 的 squash commit 为唯一回滚目标。

## 14. Suggested Commit Message

```text
feat(controlled-chat): add typed offline vertical slice

- define typed conversation contracts, state machine, ports, and stages
- run success, clarification, timeout, and missing-evidence paths
- verify the real orchestrator with offline unit, contract, E2E, and Compose tests

Closes #7
```

## 15. Handoff

M2 完成后下一个执行单元仅为 M3：迁移实体解析、两阶段路由、结构化 rewrite、窄约束/回答偏好和 Skill discovery，并以离线 eval 证明迁移规则。公开 REST/WS、真实工具执行、Evidence 深化和真实 adapter 仍不得提前混入 M3。
