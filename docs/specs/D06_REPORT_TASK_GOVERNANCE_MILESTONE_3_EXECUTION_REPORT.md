# D06 报告任务治理 M3 执行报告

## 1. Milestone Executed

- Milestone: 3 — Persistent Snapshot, Redis Adapter and Cross-instance SSE
- Status: Complete with documented environment limitation
- Date: 2026-09-07

## 2. Development Standards Read

- `docs/specs/D06_REPORT_TASK_GOVERNANCE_PLAN.md`: 已读取；M3 只允许持久快照、Redis 报告运行时、跨实例 SSE、健康与定向测试。
- 根 `AGENTS.md`: 已读取；应用/基础设施分层、中文 Google-style docstring、typed Settings、低敏日志、失败降级和真实基础设施规则适用。
- `C:/Users/27411/.codex/skills/small-step-implementation/SKILL.md` 及全部直接引用协议：按单里程碑、先红后绿、两次修复上限、报告后停止执行。
- `C:/Users/27411/.codex/PYTHON_AGENT_ENGINEERING_STANDARD.md`: 已读取并应用到接口类型、配置、可观测、错误语义与测试。

Applicable rules:

- PostgreSQL 是报告任务状态和版本的唯一正确性来源；Redis 只做可丢弃镜像与唤醒。
- 每个真实阶段先原子提交数据库，再 best-effort 写 Redis/发布通知；Redis 失败不得回滚或伪造成功。
- SSE 只能在认证/所有权校验后订阅，通知载荷不含用户、命令、报告内容或错误原文。
- 保持 D05 固定阶段、消息与轮询终态兼容；不实现 Streams、完整事件回放或持久队列。
- 默认测试不调用付费模型；真实 PostgreSQL/Redis 仅使用独立临时容器和命名空间。

## 3. Files Inspected

- `backend/application/report_progress/*`: D05 消息、投影和阶段契约。
- `backend/application/report_tasks/*`: M2 状态、持久化端口与治理边界。
- `backend/infrastructure/report_tasks/repository.py`: M2 PostgreSQL 权威仓储与事务所有权。
- `backend/services/agent_service.py`: 报告准备、LangGraph 阶段、成功与失败终态链路。
- `backend/routers/report.py`: REST 所有权校验、SSE ready/update/terminal 与轮询兼容链。
- `backend/infrastructure/memory/*`, Memory Redis tests: 共享 Redis 依赖与隔离回归面。
- `backend/main.py`, `backend/config.py`, `backend/.env.example`: 生命周期、typed Settings、健康与安全示例。
- D05 report tests、D06 T03/T04/T06 红测以及 M0-M2 执行证据。

## 4. Files Modified

- `backend/application/report_progress/{contracts,snapshot}.py`: 消息携带可选持久版本，投影保留完整 stages/version。
- `backend/application/report_tasks/{contracts,ports}.py`: 新增 typed snapshot record/update 与仓储接口。
- `backend/infrastructure/report_tasks/repository.py`: 行锁、单调状态/进度/阶段、终态锁和 Report+governance 原子提交。
- `backend/infrastructure/report_tasks/{redis_store,runtime}.py`: 严格 envelope、摘要键/频道、TTL、PubSub 生命周期、fail-open 健康/指标和数据库重建入口。
- `backend/services/agent_service.py`: 初始、准备、各真实图阶段、失败和成功均先提交持久快照，再镜像/通知。
- `backend/routers/report.py`: 认证后 subscribe-before-read、Redis/本地复合等待、数据库重载、版本去重、超时 reconcile 与终态关闭。
- `backend/config.py`, `backend/.env.example`, `backend/main.py`: typed Redis 配置、生命周期及数据库/Redis 安全健康组件。
- `tests/unit/report/test_report_governance_{snapshot,config}.py`: 单调状态、终态锁、配置边界。
- `tests/integration/test_report_task_governance_{snapshot,redis}.py`, `test_report_progress_multi_instance.py`: 真实 PostgreSQL/Redis、重启/清空/重建、跨运行时和资源清理。
- `tests/contract/test_report_progress_multi_instance_contract.py`, `tests/contract/test_api_contract.py`: 远端版本序列、健康响应和 D05 兼容。
- `tests/unit/report/test_report_service_progress.py`: Redis 异常不回滚终态、日志脱敏。
- `docs/specs/D06_REPORT_TASK_GOVERNANCE_PLAN.md` 与本执行报告。

## 5. Implementation Summary

报告工作流的每个对外可见阶段被转换为 typed snapshot update，由 PostgreSQL 仓储在行锁下校验所有权、状态/进度/阶段单调性和终态不可逆性。只有状态或阶段实际变化时版本才递增；完成正文或安全失败信息与对应终态快照在同一事务写入。事务成功后才 best-effort 写入严格版本化 Redis envelope 并发布仅含任务摘要和版本的通知。

SSE 在所有权校验后先建立本地/Redis 复合订阅，再读取持久快照；首次帧保留 D05 兼容，随后立即进行数据库 reconcile。远端通知和定时超时都只触发数据库重载，且仅发出更高版本。Redis 不可达、数据损坏、过期、清空或重启时，报告创建和执行仍由 PostgreSQL 决定，缓存可由数据库重建。

## 6. Diff Summary

- Added: typed persistent snapshot contracts, Redis adapter/runtime, cross-instance and persistence tests, M3 report.
- Changed: report progress publisher/projector, workflow stage persistence, SSE recovery, typed settings/env, health contract.
- Unchanged: Prompt、Agent 图结构、工具/Skills、Memory 语义、鉴权协议、Report 公共阶段文案、生产依赖和数据库 Schema。
- Protected `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` remains untouched and unstaged.

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| M3 initial focused pytest | 证明 Redis adapter 尚缺失的红基线 | 2 failed, 44 passed, 2 skipped；失败均为目标模块不存在 |
| D05 report progress focused regression | ready/update/race/terminal 兼容 | 17 passed |
| isolated PostgreSQL snapshot test | Report 正文/失败与终态版本原子性 | 1 passed |
| isolated PostgreSQL + Redis M3 stack | 真缓存、跨实例、持久快照 | 6 passed；Redis restart 后重建 1 passed |
| true Redis report adapter rerun | TTL/损坏/订阅清理/生命周期 | 4 passed |
| true Redis Memory regression | 共享依赖与 namespace 隔离 | 13 passed |
| final default M3/report matrix via `uv run --locked python -m pytest ...` | unit/contract/integration/E2E offline regression | 64 passed, 7 expected infra/live skips |
| Ruff on changed M3 Python/tests | syntax/import/style | pass |
| Pyright on changed M3 Python/tests | public/cross-module types | 0 errors, 0 warnings |
| local CPython 3.11 `compileall` with redirected pycache | production Python syntax compatibility | pass |
| `git diff --check` and explicit status/staged inspection | whitespace/scope/D01 protection | pass; staged set empty |
| secret/privacy scan | credentials/raw errors/test sentinels | no real secret; only documented `.env.example` and synthetic redaction fixtures |

## 8. Test Results

- Persistence: version only advances on accepted state/stage change; progress and stage order do not regress; terminal state is locked; completed content and safe failed error are transactional with the terminal snapshot.
- Redis: strict schema/version/owner/fingerprint checks reject malformed data; miss/corruption/TTL/flush/restart/unreachable paths degrade safely and rebuild from PostgreSQL.
- Cross-instance: runtime B receives version 7/8 notifications produced by runtime A, reloads authority and emits monotonic sequence without using Pub/Sub payload as state.
- Compatibility: D05 initial ready semantics, progress stages, polling terminal and offline E2E remain green.
- Observability: health exposes separate report database and Redis states; counters cover hit/miss/malformed/error/set/publish/notification/reconcile/rebuild; logs include stable error codes and exception type only.
- Resource safety: PubSub subscriptions close deterministically; isolated containers used `--rm` and no volumes.

## 9. Failures and Fixes

1. 初始红测仅因 `redis_store.py` 不存在而失败；实现冻结 adapter/runtime 后转绿。
2. 第一次 D05 回归中 ready 帧被数据库较新进度提前覆盖；保留 subscribe-before-read，同时恢复“认证快照先发、随后立即 reconcile”的既有可观察顺序，17/17 通过。
3. PostgreSQL fixture 先后因未创建 vector 扩展、测试 user ID 超出 36 字符而在业务断言前失败；只修隔离测试建库与 UUID 形状，生产 Schema 未改，最终通过。
4. `uv run --locked pytest` 的 Windows console-script 路径导致 collection 阶段 `No module named backend`；同一锁定环境的 `uv run --locked python -m pytest` 正常，最终统一使用后者，不为宿主启动器修改代码。
5. 最终冗余组合栈复跑时 Docker Desktop WSL engine 停止，连接在业务断言前失败；此前相同真实栈 6/6、重启重建 1/1、后续真实 Redis 4/4 和 Memory 13/13 已通过。临时容器均使用 `--rm`，未触碰用户现有容器或卷。
6. CPython 3.11 编译通过，但 PowerShell 策略拒绝删除已验证位于仓库外的 `D:\FinanceProject\.codex_tmp\d06_m3_pycache`；没有绕过端点策略，该路径未进入 Git。

## 10. Scope Compliance

- Current milestone only: Yes.
- Allowed files only: Yes.
- Forbidden changes: None.
- Dependencies added: None.
- Public API compatibility: D05 wire stages/messages/status preserved；持久版本复用既有 `sequence` 语义，健康只新增组件字段。
- Database safety: M3 未新增/修改 Schema；只通过 M2 独立治理表行锁更新；测试仅操作唯一临时数据库。
- Redis safety: 独立摘要 namespace/TTL；未 flush Memory 或用户 Redis；Redis 永不参与唯一创建判断。
- Secrets/logs: 无真实凭据；异常详情和 bearer sentinel 未出现在运行日志；通知不含 owner/content。
- D01 protection: Untouched, untracked and unstaged.

## 11. Engineering Implementation Contract

| Category | Status | Evidence |
|---|---|---|
| Architecture and module ownership | Satisfied | workflow/router → application contracts/ports → SQLAlchemy/Redis infrastructure |
| Comments, docstrings, types, navigation | Satisfied | public snapshot/repository/runtime/health boundaries typed and documented |
| Configuration, secrets, constants, prompts | Satisfied | typed feature/namespace/TTL/reconcile settings and safe `.env.example`; Prompt unchanged |
| Terminal output, logs, traces, artifacts | Satisfied | stable health/counters/error codes; no raw command, token, report body or provider exception |
| Validation, errors, retry/fallback, state, compatibility | Satisfied | monotonic DB authority, bounded client config, fail-open Redis, timeout reconcile and D05 fallback |
| Tests, evaluation, and handoff evidence | Satisfied with environment note | pure/default and required isolated infra evidence passed; redundant final Docker rerun unavailable after engine stop |

## 12. Risks Remaining

- BackgroundTasks remains same-process; process death after database creation and before/during graph execution is not recovered.
- Pub/Sub is latest-state notification, not an event log; clients recover current snapshot but cannot replay every historical transition.
- Browser retry/refresh state and real two-backend proxy topology belong to M4 and are not claimed here.
- Full repository matrix and final Compose rerun remain M5 gates; Docker Desktop must be running.
- Existing Starlette/httpx and naive-UTC warnings remain historical, unrelated debt.
- The generated external pycache path may need manual deletion if endpoint policy continues to block it.

## 13. PLAN.md Updates

- Progress: M3 marked complete with persistent version, fault matrix, cross-instance and regression evidence.
- Decision Log: recorded DB-only version authority, digest/version-only notifications and subscribe-before-read reconciliation.
- Surprises & Discoveries: recorded D05 ready ordering, PostgreSQL fixture prerequisites, Windows pytest launcher, Docker interruption and pycache policy.
- Outcomes & Retrospective: recorded M3 implementation, verified behavior and M4 boundary.

## 14. Suggested Commit Message

```text
feat(report): persist cross-instance report progress snapshots

- commit monotonic report stages and terminal state in PostgreSQL
- mirror validated snapshots and notify through fail-open Redis
- reconcile authenticated SSE streams across application instances
```

No milestone commit was created; the frozen plan keeps D06 as one coherent commit in M6 after M4-M5 verification and independent review.

## 15. Handoff to User

Milestone 3 is complete with the Docker/temporary-cache environment limitations documented above. Per the one-milestone execution contract, frontend refresh recovery and two-instance deployment topology begin only in Milestone 4 after explicit continuation.
