# D06 报告任务治理 M1 执行报告

## 1. Milestone Executed

- Milestone: 1 — Lock Contracts and Failing Reproductions
- Status: Complete
- Date: 2026-09-05

## 2. Development Standards Read

- `PLAN.md`: 已读取；M1 只允许测试、测试 helper、计划治理和 M1 报告，禁止生产实现。
- `DEV_STANDARDS.md`: 未发现。
- `AGENTS.md`: 已读取根合同；测试先行、分层、低敏、真实基础设施与 one-milestone 规则适用。
- nested `AGENTS.md` / `AGENTS.override.md`: M0 已确认无嵌套覆盖。
- `CLAUDE.md`, `.cursor/rules/*.mdc`, `.github/copilot-instructions.md`: 未发现。
- README / contribution / test docs: 延续 M0 已读取的 `CONTRIBUTING.md`、`docs/engineering/testing-strategy.md` 和 migration 指南。
- Personal standard: 已读取 `C:/Users/27411/.codex/PYTHON_AGENT_ENGINEERING_STANDARD.md`；测试使用明确类型/fixture、稳定错误码、隔离 gate 和低敏断言。

Applicable rules:

- Architecture: 未来接口锁定在 `backend.application.report_tasks`，DB/Redis 实现在 `backend.infrastructure.report_tasks`；测试不要求 router 持有业务规则。
- Testing: 先写 red contract；默认无真实模型/生产服务；PostgreSQL/Redis/Live 需要显式隔离开关。
- Security: 测试拒绝未识别数据库/Redis URL；断言 header、command、user、digest 不回显或进入 Redis key/value。
- Quality: 新测试 Ruff、Pyright、ESLint、vue-tsc 必须先过；预期红灯只来自缺少产品行为。
- Delivery: 本里程碑不 commit；D01 保持未触碰。

## 3. Files Inspected

- `backend/routers/report.py`: 确认当前每次 UUID/commit/BackgroundTasks 与连接内 sequence。
- `backend/schemas/report.py`: 确认创建响应缺少幂等元数据，SSE 使用严格 v1 frame。
- `backend/application/report_progress/{contracts,hub,snapshot}.py`: 复用阶段/状态与 D05 单进程边界。
- `backend/db/{models,database,migration_runner}.py`, `backend/migrations/README.md`: 冻结独立 Alembic 表测试方式。
- `backend/infrastructure/memory/{redis_cache,runtime}.py`: 只复用测试模式，不建立业务依赖。
- `frontend/src/api/index.ts`, `frontend/src/composables/useReport.ts`, `frontend/src/stores/reportProgressStore.ts`: 确认当前两参数 generate、无 sessionStorage/restore、终态只清 transport。
- D05 report/Memory/Compose/Live tests: 复用 fixture、gate、低敏 artifact 和真实链路模式。

## 4. Files Modified

- `tests/unit/report/test_report_idempotency_contract.py`: D06-T01/T04 纯合同。
- `tests/contract/test_report_task_governance_contract.py`: D06-T02/T05 创建/replay/conflict/owner/20 并发。
- `tests/integration/test_report_task_governance_migration.py`: D06-T02 独立表/约束/升降级。
- `tests/integration/test_report_task_governance_redis.py`: D06-T03/T06 adapter、真 Redis、安全 envelope、Pub/Sub、不可达。
- `tests/integration/test_report_progress_multi_instance.py`: D06-T06 两 runtime 通知与 missed-notification latest snapshot。
- `tests/e2e/test_report_task_governance_offline_contract.py`: D06-T08 双后端隔离 Compose 拓扑。
- `tests/e2e/test_live_report_task_governance.py`: D06-T10 默认关闭的 protected Live 入口。
- `frontend/src/composables/__tests__/useReport.governance.spec.ts`: D06-T07 显式 key、最小存储、刷新恢复、终态清理。
- `docs/specs/D06_REPORT_TASK_GOVERNANCE_PLAN.md`: M1 进展、决策、发现、结果。
- `docs/specs/D06_REPORT_TASK_GOVERNANCE_MILESTONE_1_EXECUTION_REPORT.md`: 本报告。

## 5. Implementation Summary

M1 仅增加测试合同，没有实现或伪造 D06。Python 共定义 23 个用例：默认收集 22 个，Live 由项目 marker 过滤；隔离 PostgreSQL/Redis/multi-instance 只有设置 `RUN_D06_ISOLATED_INFRA_TESTS=true` 且 URL 满足保护条件才运行。前端三个用例分别证明当前没有显式幂等键、刷新恢复入口和终态活动记录清理。测试先精确红灯，M2/M3/M4 将逐层转绿。

## 6. Diff Summary

- Python tests: added unit/contract/integration/Compose/Live contracts only.
- Frontend tests: added one governance lifecycle spec only.
- D06 docs: updated living plan and added M1 evidence.
- No production, API schema, ORM schema, migration, runtime config, dependency, Prompt, Agent, Memory or auth file changed.
- Protected `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` remains untouched and untracked.

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| new Python `pytest --collect-only ... -q` | 所有新文件可导入/收集 | 22/23 default-collected, 1 Live deselected |
| Ruff on seven new Python files | 语法/import/style | pass |
| Pyright on seven new Python files | 测试类型安全 | 0 errors, 0 warnings |
| `npm run lint -- --quiet; npm run type-check` | 新 frontend spec 静态质量 | pass |
| new Python pytest `-q --tb=line` | 现状 red baseline | 18 failed, 1 passed, 3 skipped, 1 deselected |
| `npm test -- useReport.governance` | 前端 red baseline | 3 expected failures |
| existing D05 backend focused | 测试新增未破坏报告链 | 25 passed, 1 skipped |
| existing D05 frontend focused | 测试新增未破坏报告 UI/transport | 4 files, 16 tests passed |
| `git diff --no-index --check` on new files | 行尾/格式审查 | pass before final report; rerun in final M1 review |

## 8. Test Results

- Passed: static quality; all unchanged D05 backend/frontend focused tests; cross-user current characterization.
- Expected failed:
  - 11 unit parameter/cases: `backend.application.report_tasks.contracts` absent.
  - same-user explicit/implicit reuse and invalid-header API: response lacks idempotency metadata/422 and creates duplicates.
  - migration: `ReportTaskGovernanceRow` absent.
  - Redis adapter/unreachable: `backend.infrastructure.report_tasks.redis_store` absent.
  - Compose: no `backend-secondary` or D06 gates.
  - frontend: no third key arg, no `restoreActiveTask`, no terminal storage cleanup.
- Skipped: 20-way PostgreSQL, true Redis snapshot/PubSub, two-runtime test because explicit isolated-infra gate is off.
- Deselected: protected Live by default `-m not live`.
- Limitations: M1 intentionally does not prove implementation; it proves current gaps and freezes the exact acceptance surface.

## 9. Failures and Fixes

- Failure 1: pytest import-file mismatch because unit and contract files shared `test_report_task_governance_contract.py`; Ruff also found one unused import and Pyright found dynamic contract typing issues.
- Root cause: test directories are not Python packages, so pytest imported both files under one top-level module name; dynamic module/object annotations were too narrow.
- Fix attempt 1: renamed the unit file to `test_report_idempotency_contract.py`, removed the unused import, narrowed `module.__file__`, and used `Any` only at the dynamic future-contract boundary.
- Rerun result: 22/23 cases collect; Ruff and Pyright pass.
- Failure 2: true Redis/multi-instance tests imported future modules before enforcing the isolation gate; terminal frontend test passed because storage started empty.
- Root cause: setup ordering and a false-positive precondition.
- Fix attempt 2: evaluate `_redis_url()` before future imports and prepopulate a stale activity record before terminal completion.
- Rerun result: isolated cases safely skip; all three frontend behaviors now red for the intended missing features. No further repair attempt was needed.

## 10. Scope Compliance

- Allowed files only: Yes.
- Forbidden changes avoided: Yes.
- User changes preserved: Yes.
- Dependencies changed: No.
- API/database/config changed: No; tests only describe future authorized behavior.

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
|---|---|---|
| Architecture and dependency direction | Satisfied | expected application/infrastructure packages are explicit; Memory reverse dependency rejected by source assertion |
| Docstrings, types, field meaning, section navigation | Satisfied | Python test helpers/cases documented and typed; Pyright 0 errors |
| Configuration, secrets, constants, prompts | Satisfied | explicit test gates/recognized URLs; fixture secret only; no Prompt/config mutation |
| Terminal output, logs, traces, artifacts | Satisfied | low-sensitive counts/status; no real calls/artifacts; Redis tests assert raw-value redaction |
| Validation, errors, retry/fallback, state, compatibility | Satisfied as red contract | 422/409, owner isolation, TTL/corruption, version/recovery, old client and D05 regression cases frozen |
| Tests, evaluation, and handoff evidence | Satisfied | D06-T01..T10 mapped; red failures and skips recorded; D05 green baseline preserved |

## 12. Risks Remaining

- M2 must implement DB creation semantics without prematurely making Redis/M3 tests green through fake paths.
- SQLite sequential contracts cannot prove PostgreSQL contention; M2 completion requires the gated 20-way true PostgreSQL case.
- Redis/multi-instance test APIs are now an explicit contract; implementation must keep report ownership independent from Memory and may not weaken assertions for convenience.
- Console code page garbles Chinese pytest text in terminal output; source files are UTF-8 and static checks pass. Evidence should rely on symbols/counts rather than altered source encodings.
- One cross-user test passes today because every request creates a new task; it is only a compatibility guard, not evidence of D06 correctness.

## 13. PLAN.md Updates

- Progress: M1 marked complete with red/green/static counts.
- Decision Log: froze package ownership, governance-row uniqueness/generation, and isolated infra gate.
- Surprises & Discoveries: recorded pytest basename collision, pre-existing cross-user pass, and terminal code-page display.
- Outcomes & Retrospective: recorded tests-only change and current behavior gaps.

## 14. Suggested Commit Message

```text
test(report): lock D06 task governance contracts

- cover idempotency, persistence, Redis and multi-instance recovery
- protect frontend refresh and one-dispatch behavior
- keep live and infrastructure cases explicitly isolated
```

No milestone commit was created; final delivery remains one coherent Issue/PR/squash change under the user's authorization.

## 15. Handoff to User

Milestone 1 is complete. Per the one-milestone execution contract, production implementation starts in Milestone 2, not inside this report.
