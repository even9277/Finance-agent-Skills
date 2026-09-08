# D06 报告任务治理 M2 执行报告

## 1. Milestone Executed

- Milestone: 2 — PostgreSQL Authority and Atomic Create-or-Reuse
- Status: Complete
- Date: 2026-09-05

## 2. Development Standards Read

- `PLAN.md`: 已读取；M2 只允许 PostgreSQL 权威层、原子创建路径、报告 HTTP 兼容字段、核心配置和目标测试。
- `AGENTS.md`: 已读取根工程合同；分层、中文 Google-style docstring、typed Settings、低敏日志、可逆迁移、真实基础设施和 tests-first 规则适用。
- nested `AGENTS.md` / `AGENTS.override.md`, `CLAUDE.md`, `.cursor/rules/*.mdc`, `.github/copilot-instructions.md`: 未发现额外覆盖。
- `docs/engineering/testing-strategy.md`、migration runner/README 与既有 Memory Alembic 模式：沿用隔离 URL、显式降级确认和默认无真实外部调用。
- `C:/Users/27411/.codex/PYTHON_AGENT_ENGINEERING_STANDARD.md`: 已读取；应用/基础设施边界、类型、失败语义、日志与测试要求已应用。

Applicable rules:

- Router 只适配认证、Header、HTTP 错误和响应；幂等语义属于 application，事务属于 infrastructure。
- 不修改 legacy `reports` Schema；只新增独立 Alembic 管理表并提供可逆降级。
- 原始 command、用户 ID 和显式键不进入治理表、日志或错误响应；只持久化摘要与低敏关联 ID。
- 默认测试不调用模型/金融数据；真实 PostgreSQL 必须使用可识别的 D06 隔离目标。
- 不新增生产依赖，不触碰 Redis/SSE、前端恢复、Prompt、Agent、Skills、Memory 或鉴权协议。

## 3. Files Inspected

- `backend/routers/report.py`, `backend/schemas/report.py`: 原创建/响应/BackgroundTasks 链路。
- `backend/db/models.py`, `backend/db/database.py`, `backend/db/migration_runner.py`: 混合 create_all/Alembic 所有权与隔离降级入口。
- `backend/migrations/versions/20260825_04_memory_pending_commands.py`: revision、索引和 fail-closed downgrade 模式。
- `backend/config.py`, `backend/.env.example`: typed Settings 与安全示例位置。
- `backend/application/report_progress/contracts.py`: 复用现有报告阶段/任务状态枚举。
- M1 D06 unit/contract/migration tests与 D05 report regression：冻结行为和兼容性门禁。

## 4. Files Modified

- `backend/application/report_tasks/{__init__,contracts,ports,service}.py`: NFKC/键校验/HMAC、幂等决策、快照类型、持久化端口和创建用例。
- `backend/infrastructure/report_tasks/{__init__,repository}.py`: SQLAlchemy 原子创建、唯一竞争跟随、行锁复用和过期终态换代。
- `backend/db/models.py`: 新增 Alembic-managed `ReportTaskGovernanceRow`。
- `backend/migrations/versions/20260905_05_report_task_governance.py`: 独立治理表、唯一约束、索引和受控降级。
- `backend/routers/report.py`, `backend/schemas/report.py`: 可选 `Idempotency-Key`、稳定 409/422、兼容响应元数据和 winner-only dispatch。
- `backend/config.py`, `backend/.env.example`: 默认开启治理和 600 秒 typed TTL。
- `tests/unit/report/test_report_idempotency_contract.py`: 补齐指纹/状态/TTL 决策表。
- `tests/contract/test_report_task_governance_contract.py`: SQLite HTTP、401 与 20 路真实 PostgreSQL 并发合同；测试引擎使用 `NullPool` 隔离事件循环。
- `tests/integration/test_report_task_governance_migration.py`: SQLite 与真实 PostgreSQL up/down/reupgrade。
- `tests/integration/test_report_task_governance_repository.py`: 运行中超期复用与过期终态 generation 换代。
- `docs/specs/D06_REPORT_TASK_GOVERNANCE_PLAN.md`: M2 进度、决策、发现和结果。
- `docs/specs/D06_REPORT_TASK_GOVERNANCE_MILESTONE_2_EXECUTION_REPORT.md`: 本报告。

## 5. Implementation Summary

创建请求先规范化 command 并生成 SHA-256 fingerprint；显式 Header 或兼容命令哈希形成有效键，再使用已注入服务器秘密生成用户作用域 HMAC。SQLAlchemy 仓储先读取并锁定稳定治理行；首次创建把候选 `Report` 与 governance 放入同一事务，唯一约束失败方回滚整笔事务后跟随获胜行。相同键不同指纹返回低敏 409；pending/running 无视 TTL 始终复用；仅 completed/failed 且过期时锁行、递增 generation 并改指向新 Report。Router 只给 `CREATED` 注册一次 BackgroundTask。

Redis、持久进度版本与跨实例 SSE 仍属于 M3，本里程碑没有实现或伪造它们。

## 6. Diff Summary

- Added: application contracts/service/port, SQLAlchemy repository, one Alembic revision, M2 integration test and report.
- Changed: report ORM managed-table registration, POST generate adaptation/response, typed TTL/feature settings, targeted M1 tests and living plan.
- Unchanged: Report content/Prompt/Agent graph/tool/Skill/Memory/auth protocol, Redis/SSE/front-end runtime and production dependencies.
- Protected `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` remains untouched and untracked.

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| focused M2 pytest on unit/migration/repository/API | 本地 SQLite 与纯逻辑 | 25 passed, 1 PostgreSQL-gated skipped |
| isolated pgvector/PostgreSQL M2 suite with `RUN_D06_ISOLATED_INFRA_TESTS=true` | 迁移可逆、20 路唯一创建/派发 | 28 passed, 0 skipped |
| D05 + M2 report regression | 报告状态/SSE/CRUD 兼容与默认门禁 | 51 passed, 3 expected environment skips |
| Ruff on touched Python/tests | 语法/import/style | pass |
| Pyright with `.venv` Python | 跨模块类型 | 0 errors, 0 warnings |
| `alembic heads` | 迁移拓扑 | one head: `20260905_05` |
| read-only `python:3.11-slim` compileall | 生产 backend image 语法兼容 | pass |
| exact-container cleanup check | 仅清理 D06 临时 PostgreSQL | container stopped/auto-removed |

## 8. Test Results

- Unit: NFKC/空白折叠、8..128 可见 ASCII、旧客户端命令哈希、显式请求意图、指纹/HMAC 脱敏、快照类型和完整 expiry 决策表通过。
- Contract: CREATED/REPLAYED/409/422/401、同用户复用、跨用户隔离、旧客户端兼容和 winner-only BackgroundTasks 通过。
- Persistence: SQLite up/down/reupgrade、真实 PostgreSQL up/down/reupgrade、运行态超期保护和终态 generation 换代通过。
- Concurrency: 20 个并发 HTTP 请求返回一个 task、一个 report、一个 CREATED、19 个 REPLAYED、一次 dispatch。
- Regression: D05 报告进度链无新增失败；默认跳过需要完整 Compose/Live 环境的既有三项。
- Warnings: 仅既有 Starlette/httpx 与 ORM naive-UTC deprecation；没有新增失败或秘密输出。

## 9. Failures and Fixes

1. Pyright 首次发现 `Protocol` 方法缺少 ellipsis；补齐抽象方法体后又发现 ORM `str` 未显式收窄为 `ReportTaskStatus`，以枚举转换修复；最终 0/0。
2. 第一次 PostgreSQL 验收发现测试函数插入位置和 fixture user ID 长度错误；只修测试结构与 36 字符 ID。
3. 第二次 PostgreSQL 验收在业务断言前发现 asyncpg 连接池跨 TestClient/`asyncio.run` 事件循环复用；仅将测试 harness 改为 `NullPool`，第三次 28/28 通过，生产 engine 未改。
4. Python 3.11 compile 首次命令引号错误、第二次只读挂载无法写 pycache；把 pycache 重定向至容器 `/tmp` 后通过，没有修改代码或宿主生成物。

## 10. Scope Compliance

- Current milestone only: Yes.
- Allowed files only: Yes.
- Forbidden changes: None.
- Dependencies added: None.
- Public API compatibility: Existing path/status and `task_id/report_id/status` retained; additions are optional metadata; stable 409/422 only cover new invalid/conflict states.
- Database safety: Only independent governance table added; no existing Report/user data altered or deleted; downgrade ran only against disposable D06 databases.
- Secrets/logs: No real credential committed; test-only placeholders remain in gated fixtures; runtime logs exclude user, command, Header and digest.
- D01 protection: Untouched and unstaged.

## 11. Engineering Implementation Contract

| Category | Status | Evidence |
|---|---|---|
| Architecture and module ownership | Satisfied | router → application port/service → infrastructure repository; ORM/migration own persistence |
| Comments, docstrings, types, navigation | Satisfied | typed Pydantic/Enum/Protocol; public boundaries have Chinese responsibility/failure docs |
| Configuration, secrets, constants, prompts | Satisfied | typed enable/TTL settings, safe `.env.example`, domain-separated injected HMAC; Prompt unchanged |
| Terminal output, logs, traces, artifacts | Satisfied for M2 | low-cardinality claim log with task/report/generation; no raw request material |
| Validation, errors, retry/fallback, state, compatibility | Satisfied | deterministic 422/409, DB unique/rollback/follow, row-locked rotation, explicit emergency feature fallback |
| Tests, evaluation, and handoff evidence | Satisfied | pure/SQLite/real PostgreSQL/API/regression/static/3.11 evidence captured |

## 12. Risks Remaining

- BackgroundTasks remains a same-process dispatcher; process crash recovery is explicitly deferred and not claimed.
- Governance snapshot fields exist but M2 does not yet advance persistent stage/version or provide Redis/SSE recovery; this is M3.
- Feature disable restores the old non-idempotent route and is only an emergency rollback path, not a correctness mode.
- Existing project datetime defaults are naive UTC; D06 timestamps are timezone-aware, but repository-wide warning cleanup is outside scope.
- Full Compose, browser and protected Live proof remains M4-M6.

## 13. PLAN.md Updates

- Progress: M2 marked complete with real PostgreSQL and regression evidence.
- Decision Log: recorded optimistic insert/follow-winner, stable-row rotation and domain-separated existing secret.
- Surprises & Discoveries: recorded TestClient asyncpg loop isolation, backend Python 3.11 proof and historical datetime warnings.
- Outcomes & Retrospective: recorded implemented DB authority and verified behavior.

## 14. Suggested Commit Message

```text
feat(report): add atomic task governance authority

- deduplicate report creation with PostgreSQL uniqueness
- expose compatible idempotency outcomes and safe conflicts
- prove migration and 20-way winner-only dispatch
```

No milestone commit was created; the user authorized final D06 delivery as one coherent Issue/PR/squash change.

## 15. Handoff to User

Milestone 2 is complete. Per the one-milestone execution contract, persistent snapshots, Redis and cross-instance SSE start in Milestone 3, not inside this report.
