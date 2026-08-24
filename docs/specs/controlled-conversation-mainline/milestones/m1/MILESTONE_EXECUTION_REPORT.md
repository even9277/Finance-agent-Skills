# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 1 — Characterization and Contract Tests
- Status: Complete with known expected failure
- Date: 2026-08-24
- GitHub tracking: [Issue #3 — test: freeze controlled-chat legacy contracts before migration](https://github.com/even9277/Finance-agent-Skills/issues/3)
- Local branch: `refactor/3-controlled-chat-characterization`

## 2. Development Standards Read

- `PLAN.md`: 已完整读取，严格按 Milestone 1 的文件范围、停止条件和验收命令执行。
- Personal and repository `AGENTS.md`: 已读取并遵守默认离线、保护秘密、中文接口文档、窄改动和用户改动保护规则。
- `CONTRIBUTING.md`: 已读取 GitHub Issue、短分支、测试和 Review 约定。
- `C:\Users\27411\.codex\PYTHON_AGENT_ENGINEERING_STANDARD.md`: 已读取 Python/Agent 的类型、错误、日志、Trace 和测试标准。
- `small-step-implementation/SKILL.md`: 已读取并执行“一次一个里程碑、两次修正上限、先 diff 后测试、报告后停止”的协议。

## 3. Files Inspected

- `backend/main.py`、`backend/routers/chat.py`: 核对 REST/WS 入口、验证边界、数据库 Session 生命周期和错误 frame。
- `backend/services/chat_service.py`: 核对同步/流式服务参数、提交时点、Trace 终态和失败传播。
- `backend/db/models.py`: 核对 Session/Message 字段、用户隔离和消息持久化。
- `Financial-MCP-Agent/src/agents/skill_router_node.py`: 核对规则/模型路由、follow-up 上下文和模型异常降级。
- `Financial-MCP-Agent/src/agents/skill_executor_node.py`: 核对禁用路径、fallback、并发工具结果和白名单失败。
- `Financial-MCP-Agent/src/tools/skill_trace.py`: 核对根 Trace、工具 span/event、关联字段和脱敏。
- 现有 `tests/`、`pyproject.toml` 和 CI 配置: 核对 markers、默认 `not live`、Ruff/Pyright/pytest 运行方式。

## 4. Files Modified

- `tests/fixtures/conversation/legacy_route_cases.json`: 新增版本化离线路由案例。
- `tests/unit/conversation/test_legacy_router_executor_characterization.py`: 新增 Router/Executor 行为刻画。
- `tests/unit/conversation/test_legacy_trace_characterization.py`: 新增 Trace 根事件、关联字段、工具错误和秘密脱敏刻画。
- `tests/contract/test_controlled_chat_contract.py`: 新增 REST/WS 公开合同和一个严格预期失败。
- `tests/integration/test_controlled_chat_persistence.py`: 新增成功提交、失败回滚和跨用户会话隔离测试。
- `docs/specs/controlled-conversation-mainline/PLAN.md`: 更新 M1 Progress、Decision Log、发现、结果和 M2 交接。
- `docs/specs/controlled-conversation-mainline/milestones/m1/MILESTONE_EXECUTION_REPORT.md`: 新增本报告。

## 5. Implementation Summary

本里程碑没有修改任何生产代码。新增测试用 Fake/Mock 隔离模型、工具和外部服务，冻结迁移前的可观测合同：规则路由和模型故障降级、Executor 的 fallback/禁用/失败归一化、Trace 根终态与脱敏、REST/WS 响应顺序、数据库成功提交/异常回滚和用户会话隔离。

WS 安全合同使用 `xfail(strict=True)` 登记当前缺陷：Router 会把内部异常原文返回客户端。它不是被忽略的失败；若缺陷意外消失或测试不再按预期失败，严格 xfail 会使测试套件失败。按冻结计划，生产修复属于 Milestone 6。

## 6. Diff Summary

- 新增 1 个 JSON fixture 和 4 个 Python 测试文件，共 17 项离线刻画测试。
- 仅更新规格治理文档和新增 M1 报告。
- 未修改生产业务代码、前端、依赖、锁文件、环境变量、数据库 Schema、CI 或 Docker。
- 未读取、输出或提交真实密钥；本里程碑未调用真实 LLM、Tushare 或生产服务。

## 7. Tests / Checks Run

| Command | Purpose | Result |
|---|---|---|
| `uv run --locked python -m pytest tests/unit/conversation/test_legacy_router_executor_characterization.py tests/unit/conversation/test_legacy_trace_characterization.py tests/contract/test_controlled_chat_contract.py tests/integration/test_controlled_chat_persistence.py -q` | 聚焦验证新增刻画合同 | 首次 1 个文案断言失败；修正后 `16 passed, 1 xfailed` |
| `uv run --locked ruff check <4 new Python test files>` | 检查新增测试格式和静态规则 | 通过 |
| `uv run --locked pyright <4 new Python test files>` | 检查新增测试类型 | 首次 2 个测试类型错误；修正后 `0 errors` |
| `uv run --locked python -m pytest tests/contract/test_controlled_chat_contract.py -q` | 修正后的窄回归 | `3 passed, 1 xfailed` |
| `uv run --locked python -m pytest tests/unit tests/contract tests/integration -q` | 测试基础设施分层回归 | `22 passed, 1 skipped, 1 xfailed` |
| `uv run --locked python -m pytest backend -q` | 后端既有回归 | `12 passed` |
| `uv run --locked python -m pytest Financial-MCP-Agent -q -m "not live"` | Agent 默认离线回归 | `33 passed, 4 deselected` |
| `uv run --locked python -m pytest -q` | 仓库默认全量回归 | `76 passed, 6 skipped, 4 deselected, 1 xfailed` |

## 8. Test Results

- Passed: 新增行为刻画、Ruff、Pyright、后端、Agent 离线和仓库默认全量测试全部通过。
- Expected failure: 1 个严格 xfail，证明当前 WS error frame 暴露 `str(exc)`，目标安全合同尚未满足。
- Skipped/deselected: 6 个既有 skip；4 个 `live` 测试按默认配置排除。
- Live services: 本里程碑未调用。真实模型、Tushare 和旧 HTTP 主链的显式 Live 基线见 `../../LIVE_VALIDATION_REPORT.md`，不能替代新主链验收。
- Warnings: Starlette `TestClient` 弃用 1 类；`datetime.utcnow()` 弃用来自既有数据库/服务代码；当前一次全量运行共记录 86 条警告。

## 9. Failures and Fixes

### Attempt 1

- Failure: 禁用 Tushare Skill 的测试期待“未开启/暂不支持”，实际现有文案是“当前能力暂未启用”。
- Root cause: 测试预期没有精确读取当前 `_unsupported_message` 合同。
- Fix: 仅把测试断言改为现有稳定文案，不修改生产代码。
- Rerun: 聚焦套件 `16 passed, 1 xfailed`。

### Attempt 2

- Failure: Pyright 报告 Mock 调用记录可能为 `None`，以及 WS 解码帧的异构类型推断不明确。
- Root cause: 测试类型收窄不足。
- Fix: 显式断言 `await_args` 存在，并标注 `decoded: list[Any]`。
- Rerun: Ruff 通过、Pyright `0 errors`、合同测试 `3 passed, 1 xfailed`。

已达到两次修正上限，后续没有新增失败，因此无需生成 blocked 报告。

## 10. Scope Compliance

- Allowed files only: Yes
- Forbidden production changes avoided: Yes
- User changes preserved: Yes
- Dependencies/config/API/database schema changed: No
- Default paid/production calls avoided: Yes
- Multiple milestones executed: No

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
|---|---|---|
| Architecture and dependency direction | Satisfied | 测试仅从公开入口和现有边界刻画，没有新增运行时耦合 |
| Docstrings, types, comments | Satisfied | 测试函数具备中文责任说明和类型标注；Ruff/Pyright 通过 |
| Configuration and secrets | Satisfied | 外部入口全部 Fake/Mock；Trace 测试验证 token/authorization 不落盘 |
| Logs, traces, artifacts | Satisfied | 根 Trace 唯一开始/终态、correlation fields、工具失败与脱敏均有测试 |
| Validation, errors, state, compatibility | Satisfied with known gap | REST 422、WS 帧顺序、事务与隔离已冻结；WS 安全错误为 strict xfail |
| Tests and evaluation | Satisfied | 聚焦、分层和全量默认离线回归均通过；Live 项显式排除 |

## 12. Risks Remaining

- WS 内部错误详情泄露：M6 使用稳定错误码和安全文案修复，strict xfail 在修复前持续提醒。
- Router 静默吞掉模型异常：M2 的 Typed StageResult/Trace 必须表达降级原因，不能只保留隐式 fallback。
- 事务所有权依赖请求 Session 生命周期：M2 先定义 Unit of Work/Use Case 合同，M6 切换入口时验证。
- Starlette TestClient 与 `datetime.utcnow()` 弃用警告：另开技术债，不在 M1 修改依赖或生产代码。
- 当前工作区仍包含上一轮未提交基础设施改动：所有后续里程碑必须继续逐文件保护并保持窄范围。

## 13. PLAN.md Updates

- Progress: M1 标记完成，记录测试计数、strict xfail 和警告限制。
- Decision Log: 记录 Issue #3/短分支、纯测试策略和 WS 缺陷处理边界。
- Surprises & Discoveries: 记录 Router 静默降级、WS 泄露、事务边界和弃用警告。
- Outcomes & Retrospective: 更新 M1 的实际实现、验证、风险和 M2 目标。
- Handoff: 下一步限定为 M2 Typed Contracts and Offline Vertical Slice。

## 14. Suggested Commit Message

```text
test(controlled-chat): freeze legacy conversation contracts

- characterize router, executor, trace, REST, and WebSocket behavior
- verify persistence rollback and cross-user session isolation
- record the known WebSocket error disclosure as a strict xfail

Refs #3
```

## 15. Handoff to User

Milestone 1 is complete with one explicit known security gap. The implementation report was first produced before GitHub delivery；用户随后持续授权每个里程碑完成 Issue、commit/push、PR、CI/Review 和 Squash Merge，最终交付状态以 Issue #3 及其关联 PR 为准。没有执行 release、部署或生产写。下一个执行单元仅为 Milestone 2：在不切换公开 REST/WS 入口的前提下，引入 Typed Contracts 和 Fake-external 600519.SH 离线纵向切片。
