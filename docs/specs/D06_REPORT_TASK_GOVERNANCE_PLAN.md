# D06 报告任务治理执行计划

## 1. Plan Metadata

- Plan name: D06 报告幂等、Redis 可恢复快照与跨实例观察
- Task type: 跨后端 API / PostgreSQL / Redis / SSE / Vue 的高风险兼容性功能
- Status: Frozen for implementation review
- Target executor: Codex
- Related artifacts:
  - `docs/specs/D06_REPORT_TASK_GOVERNANCE_REQUIREMENT_SPEC.md`
  - `docs/specs/D06_REPORT_TASK_GOVERNANCE_CODEBASE_RECON.md`
  - `docs/specs/D06_REPORT_TASK_GOVERNANCE_CLARIFICATION_QUESTIONS.md`
  - `docs/specs/D06_REPORT_TASK_GOVERNANCE_SOLUTION_TRADEOFF.md`
- Repository root: `D:/FinanceProject/Finance-agent-Skills`
- Current branch: `feat/52-report-task-governance`
- Tracking issue: GitHub Issue #52
- Base: `origin/main` at `80f4a0c` when D06 started
- Created date: 2026-09-05

## 2. User-facing Purpose

After this change, the user should be able to submit or retry the same report request without accidentally creating and charging for duplicate report workflows, keep seeing one authoritative task across two backend instances, and refresh/reconnect to recover the latest real progress instead of restarting the report.

The current problem is that every `POST /api/report/generate` creates a new UUID/Report and registers a new FastAPI BackgroundTask. The only duplicate guard is the frontend button state. D05 progress lives in one process, so another worker or a reconnect can only recover coarse Report status and cannot restore the latest stage/version. Historical Redis code expresses the desired 10-minute Claim but cannot guarantee correctness during timeout, restart or Redis failure.

The success of this plan can be observed by 20 concurrent requests across two application instances returning one task/report and dispatching one real workflow; Redis outage/restart/corruption preserving that invariant; SSE reconnect starting from a persistent monotonic snapshot version; page refresh resuming the same task without another POST; all existing report/chat/Skills/Memory tests remaining green; and one protected real model + read-only finance-data report proving the same behavior.

## 3. Inputs Reviewed

- REQUIREMENT_SPEC.md: D06 user journeys, acceptance matrix, security/privacy, compatibility, latest-snapshot boundary and protected Live authorization.
- CODEBASE_RECON.md: actual POST→Report→BackgroundTasks→Agent→Report update→in-process Hub→SSE/REST/frontend call chain; hybrid `create_all + Alembic`; current Redis, tests, Compose and historical implementation.
- CLARIFICATION_QUESTIONS.md: 30 frozen decisions for effective key, conflict/expiry, database authority, Redis failure, snapshot/version, frontend recovery, configuration, tests and interview documentation.
- SOLUTION_TRADEOFF.md: selected Option B, rejected Redis-only baseline, deferred durable queue/Streams, official evidence and rollback direction.
- Code files: `backend/routers/report.py`, `backend/schemas/report.py`, `backend/services/agent_service.py`, `backend/application/report_progress/*`, `backend/db/models.py`, migrations/config/main/health, Memory Redis adapter/runtime, frontend report API/composable/store/view, Docker/Nginx/Compose.
- Tests: report unit/contract/E2E/live, Memory migration/Redis integration, frontend report parser/store/composable/component, offline Compose stack.
- External references: PostgreSQL unique constraints and `ON CONFLICT`; SQLAlchemy transaction rollback; Redis Pub/Sub at-most-once; FastAPI BackgroundTasks caveat.
- Repository rules: root `AGENTS.md` and personal engineering rules; Python comments/docstrings/types and secrets/observability/testing requirements are mandatory.

## 4. Final Unified Direction

This iteration will add a dedicated Alembic-managed `report_task_governance` record as the PostgreSQL authority for one active idempotency key and the latest persistent stage snapshot/version. It will route report creation through an application service that atomically creates or reuses one Report; mirror validated snapshots in Redis; publish Redis notifications containing only task digest/version; evolve D05 SSE to subscribe-before-read and reconcile persistent versions across instances; and persist only a minimal per-user active task reference in browser `sessionStorage` for refresh recovery.

This iteration will not replace BackgroundTasks with a durable queue, implement crash-resume/cancel/pause/full event replay, change report Prompt/Agent/financial calculations, change tool/Skill/Memory/auth rules, or introduce new Python/npm production dependencies.

The plan follows Option B from the solution tradeoff and reuses D05 typed progress/commit-before-publish/strict reducer, Memory Redis versioned fail-open cache patterns, and existing Alembic-managed table/bootstrap patterns. Redis Pub/Sub is a lossy wake-up only; PostgreSQL and snapshot version close every correctness gap.

## 5. Planning Assumptions

- Assumption: `task_id` and `report_id` continue to be application-generated UUID strings, so both can be allocated before the atomic transaction without a sequence round trip.
- Assumption: production correctness is PostgreSQL. SQLite remains suitable for pure logic/route tests, but concurrency and locking acceptance must use actual PostgreSQL.
- Assumption: `reports.status` values remain `pending/running/completed/failed`; D06 will not add a cancellation state.
- Assumption: a running report exceeding 600 seconds remains reusable until terminal, regardless of `expires_at`; terminal expiry permits a new generation under the same logical key.
- Assumption: the existing application/JWT secret can be domain-separated for HMAC digests; no digest input or result is exposed publicly. If code evidence shows unsafe coupling, stop before adding a new required production secret.
- Assumption: Redis 7.4 and redis-py 8 already in the repository support async Pub/Sub; no dependency change is required.
- Assumption: D05 `report-progress-v1` consumers accept any positive `sequence`; changing it from connection-local to task-persistent monotonic version is compatible and must be locked by tests.
- Assumption: user authorization covers one non-destructive Alembic migration and isolated PostgreSQL/Redis/real API data; never run against an unidentified production database.
- Assumption: `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` is untracked user work and must remain untouched and unstaged.

## 6. Changed Surface

| Surface | Involved? | Why | Risk | Verification |
| --- | --- | --- | --- | --- |
| Frontend | Yes | explicit key, response metadata, sessionStorage recovery, persistent version reducer | Medium | Vitest + build + browser smoke |
| Backend API | Yes | create-or-reuse header/response/conflict, same-task observation | High | route contract + concurrency integration |
| Database | Yes | new governance table, unique key, stage JSON/version and migration | High | upgrade/downgrade/fresh + PostgreSQL contention |
| Cache | Yes | Redis snapshot envelope, TTL, rebuild and Pub/Sub wake-up | High | true Redis fault matrix |
| Agent runtime | Narrow | progress writes become persistent/awaitable; graph/Prompt unchanged | Medium | runner regression + one real execution count |
| Tool calling | No behavior change | only protected live exercises existing read-only tools | Low | existing regression/live count |
| RAG / Memory | No behavior change | Redis ownership must not regress Memory cache | Medium | memory Redis/full regression |
| MCP | No behavior change | report real data adapter remains existing | Low | protected live only |
| Skills | No behavior change | D06 is report task governance | Low | full regression |
| Tests | Yes | D06-T01..T10 and migration/Redis/multi-instance/live coverage | High | commands below |
| Observability | Yes | idempotency/cache/snapshot/pubsub/reconcile health metrics/logs | Medium | assertions + secret scan |
| Security/Auth | Ownership validation only | every cached/read task remains user-scoped; no auth protocol change | High | 401/404/cross-user/cache-poison tests |
| Build/Deployment | Yes | Redis report runtime, feature config, two-backend Compose acceptance | Medium | Compose config/build/E2E |

## 7. Repository Context

### 7.1 Relevant Entry Points

- HTTP report API: `backend/routers/report.py`
- API schemas: `backend/schemas/report.py`
- report runner: `backend/services/agent_service.py::run_report_task`
- D05 progress contracts/hub/snapshot: `backend/application/report_progress/`
- ORM and bootstrap ownership: `backend/db/models.py`, `backend/db/database.py`, `backend/migrations/`, root `migrations/` and `alembic.ini`
- application lifecycle/config/health: `backend/main.py`, `backend/config.py`, `backend/.env.example`, health router(s)
- Memory Redis reference only: `backend/infrastructure/memory/redis_cache.py`, `backend/infrastructure/memory/runtime.py`
- frontend API/state/UI: `frontend/src/api/index.ts`, `frontend/src/api/reportProgress.ts`, `frontend/src/composables/useReport.ts`, `frontend/src/stores/reportProgressStore.ts`, `frontend/src/views/ReportView.vue`
- proxy/deployment: `docker/`, Compose yaml files, frontend Nginx configuration, GitHub workflows

### 7.2 Relevant Call Chain

```text
ReportView.generate
  -> useReport.generateReport
  -> reportApi.generate(command, optional Idempotency-Key)
  -> POST /api/report/generate + authenticated user
  -> report task governance create_or_reuse transaction
       -> CREATED: Report + governance row commit -> register one BackgroundTask
       -> REPLAYED: return existing task/report -> no BackgroundTask
       -> CONFLICT: stable 409 -> no write/dispatch
  -> run_report_task (winner only)
  -> real report stages
  -> transactionally update Report + governance stage snapshot/version
  -> best-effort Redis snapshot SET + PUBLISH(version notification)
  -> SSE on any instance: subscribe -> DB/Redis latest snapshot -> future notifications/reconcile
  -> frontend strict reducer accepts monotonic persistent sequence
  -> terminal loads same report content; clears active sessionStorage record
```

### 7.3 Existing Patterns to Reuse

- D05 typed `ReportProgressNotification`, fixed stage/status enums and safe public messages.
- D05 database commit before publisher, DB owner-bound projector and polling fallback.
- Memory Redis adapter's Protocol narrowing, versioned JSON envelope, digest key, TTL, malformed delete, fail-open, health and metrics.
- Memory new-table Alembic pattern and `ALEMBIC_MANAGED_TABLE_NAMES` exclusion from `create_all`.
- frontend strict protocol parser, Pinia single reducer, epoch/task checks, AbortController and serialized polling.
- protected Live marker/env gate, temporary artifact, hash-only evidence and no full-workflow retry.

### 7.4 Current Test Structure

- Python unit: `tests/unit/report/`, `tests/unit/memory/`
- API/stream contract: `tests/contract/test_report_progress_contract.py`
- infrastructure integration: `tests/integration/test_memory_migrations.py`, `tests/integration/test_memory_redis_cache.py`
- full-stack: `tests/e2e/test_report_progress_offline_contract.py`, `tests/e2e/test_offline_compose_stack.py`
- protected live: `tests/e2e/test_live_report_progress.py`
- frontend: colocated `frontend/src/**/__tests__/*.spec.ts`
- default pytest excludes `live` through root `pyproject.toml`.

### 7.5 Current Observability Structure

- Python modules use `logging.getLogger(__name__)`; app entrypoint configures logging.
- D05 report logs use stable stage/status/task/report/elapsed/error fields and exclude report body/Prompt/token/raw exceptions.
- Memory Redis exposes counters and health without failing startup.
- D05 Live artifact records counts, hashes, versions/progress and elapsed time rather than model/tool payloads.

## 8. Scope Control

### 8.1 In Scope

- Effective key normalization/digest/header validation and 600-second semantics.
- PostgreSQL atomic create/reuse/conflict/expired-generation rotation and once-only BackgroundTask registration.
- New Alembic-managed governance persistence with latest stage snapshot/version.
- Redis report snapshot/cache/PubSub/rebuild/degraded health, independent of Memory business ownership.
- D05 progress port/version/SSE multi-instance recovery and DB reconcile.
- REST response compatibility and stable 409/422 error metadata.
- frontend explicit key lifecycle, response-loss reuse, sessionStorage refresh recovery, terminal/logout cleanup.
- typed config, `.env.example`, Docker/Compose test topology, low-sensitive logs/metrics/health.
- D06-T01..T10 tests, README/testing/acceptance/spec governance, interview Claim alignment.
- Issue #52, branch, commit, push, PR, independent self-review, checks and authorized merge.

### 8.2 Out of Scope

- durable queue/outbox/worker, crash recovery, lease/redelivery/DLQ.
- cancellation, pause/resume, workflow retries, report content token streaming.
- Redis Streams, complete event history, Last-Event-ID replay.
- generic rate limiting, circuit breaker, quota, multi-tenant scheduler.
- Prompt, Agent graph/business logic, financial analysis rules, tools/permissions, Skill routing, STM/LTM behavior.
- auth/JWT protocol changes, query-token transport, production credential/data mutation.
- cross-device persistence, BroadcastChannel and indefinite idempotency history.

### 8.3 Allowed Files / Modules

- Existing: `backend/routers/report.py`, `backend/schemas/report.py`, `backend/services/agent_service.py`, `backend/application/report_progress/**`
- New/existing report ownership: `backend/application/report_tasks/**`, `backend/infrastructure/report_tasks/**` (exact package names frozen at M1 after import contract)
- Database: `backend/db/models.py`, `backend/db/database.py` only where managed-table registration requires it; `backend/migrations/**` / root migration configuration and one D06 revision
- Runtime/config/health: `backend/config.py`, `backend/.env.example`, `backend/main.py`, existing health router/module
- Frontend: `frontend/src/api/index.ts`, `frontend/src/api/reportProgress.ts`, `frontend/src/composables/useReport.ts`, `frontend/src/stores/reportProgressStore.ts`, `frontend/src/views/ReportView.vue`, report progress component only if user-visible replay label requires it
- Deployment: exact existing Compose/Nginx/Docker/workflow files needed for two-instance acceptance; no new platform
- Tests: `tests/unit/report/**`, `tests/contract/test_report_progress_contract.py`, new `tests/integration/test_report_task_governance*.py`, report E2E/live files, related frontend specs, shared test helpers only if narrowly required
- Documentation: `README.md`, `docs/engineering/testing-strategy.md`, D06 spec/reports, the two user-referenced project-description documents only for verified D06 Claim additions

### 8.4 Forbidden Changes

- Do not perform unrelated refactor or broad directory reorganization.
- Do not reformat unrelated files or fix the repository-wide historical Ruff baseline.
- Do not modify generated files, frontend build output, logs, live artifacts with sensitive payloads, or vendor content.
- Do not add Python/npm/infra dependencies without stopping for new approval; redis/SQLAlchemy/Alembic are already present.
- Do not change any database schema except the authorized independent D06 governance table and its indexes/FKs; never delete or rewrite Report/user data.
- Do not make breaking API path/required-field changes; additions must remain optional for old clients.
- Do not modify authentication/JWT issuance, passwords, authorization rules or query-token behavior; only reuse current authenticated owner context.
- Do not write real secrets to `.env`, tracked config, logs, Redis keys, tests, docs or artifacts.
- Do not change production data or run migrations against a URL whose isolated/test identity is not proven.
- Do not weaken tests, skip required checks, hide failures, or alter test markers to make Live run by default.
- Do not change report Prompt, Agent node graph, financial algorithms, tool schemas/permissions, Skills, STM/LTM or Memory cache behavior.
- Do not implement queue/outbox/Streams/replay/cancel/pause/generic governance.
- Do not touch, stage, delete or commit `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md`.
- Do not use `git add .`; stage an explicit D06 file list only.
- Do not touch files outside allowed scope without stopping and recording the new need.

## 9. Interfaces and Dependencies

| Interface / Dependency | Current Role | Planned Change | Compatibility Requirement | Validation |
| --- | --- | --- | --- | --- |
| `POST /api/report/generate` | always creates task | optional `Idempotency-Key`; create/replay/conflict | no header still works; existing response fields remain | T01/T05/T10 |
| Create response schema | task/report/status | add optional `idempotency_status`, `expires_at` | old TS/Python clients ignore additions | contract/frontend |
| Public error | generic HTTP detail | stable 409 conflict and 422 invalid header metadata | no raw key/command/old task leakage | negative route tests |
| effective key normalizer | absent | NFKC + whitespace collapse + digest | deterministic across instances/Python versions | parameterized unit |
| `report_task_governance` | absent | unique user/key, fingerprint, current generation, stage JSON/version, expiry | migration reversible; Report remains authority for content/status | migration/persistence |
| report create service | route-local | typed create-or-reuse result and dispatch ownership | router remains thin; only CREATED dispatches | unit/contract/concurrency |
| progress publisher | sync in-process | awaitable coordination after persistent commit | same D05 public stages/messages; failure safe | D05 regressions/snapshot tests |
| `report-progress-v1.sequence` | connection-local | task-persistent snapshot version | positive/monotonic field remains; parser compatible | contract/reconnect/frontend |
| Redis report adapter | absent | versioned snapshot SET/GET/delete/rebuild/PubSub | optional/fail-open to DB; separate report namespace | true Redis tests |
| Redis Pub/Sub | absent | task digest/version invalidation | never carries report body/user/key/command; loss tolerated | cross-instance/fault |
| typed Settings | memory Redis only | report enable/namespace/TTL/reconcile/timeouts | safe defaults; validation; no real secrets | config unit/import |
| application health | memory-focused | report governance ready/degraded counters | Redis degraded does not make DB/API unavailable | health tests |
| `useReport` | ephemeral one-tab state | explicit key + minimal activity persistence/recovery | no second generate; old report history works | Vitest/browser |
| BackgroundTasks | unconditionally scheduled | schedule winner only | execution platform unchanged; crash recovery not claimed | dispatch spy/live count |
| PostgreSQL/SQLAlchemy/Alembic | current deps | unique transaction and new migration | no new dependency; SQLite only non-critical unit fallback | integration/Compose |

## 10. Engineering Implementation Contract

| Category | Files / modules | Required behavior or documentation | Verification | Status |
| --- | --- | --- | --- | --- |
| Architecture and dependency direction | report router/schema; new application/infrastructure packages; progress port | API adapts; application owns use cases/contracts; infrastructure owns ORM/Redis; Agent imports only application port; no Memory→Report business dependency | import graph review, focused tests | Required |
| Docstrings, types, field meaning, and section navigation | all changed Python/TS public boundaries and ORM/schema fields | Google-style repository-language docs; explain TTL, digest, version, privacy, transaction/failure semantics; no core `dict[str, Any]`; maintain Python 3.11 runtime syntax | Ruff/Pyright/review/container compile | Required |
| Configuration, env, secrets, constants, and prompts | `backend/config.py`, `.env.example`, runtime | single typed settings load; positive bounds; version/TTL constants in code where stable; digest domain separation; no secret defaults added to docs; Prompt untouched | config tests/secret scan/diff | Required |
| Terminal output, logs, traces, metrics, and artifacts | report task service, Redis adapter, health, Live | stable `stage/status/idempotency_status/snapshot_version/elapsed_ms/error_code` plus digested task ref; metrics for created/replayed/conflict/db contention/cache hit/miss/malformed/error/rebuild/publish/reconcile; never raw command/user/key/token/body/exception | mock-log tests, artifact scan | Required |
| Validation, errors, retry/fallback, state, and compatibility | API/service/repository/Redis/SSE/frontend | validate header at boundary; DB unique/lock; rollback before loser read; bounded Redis operations; DB fallback; stage/progress/version monotonic; terminal locked; old client works | T01..T10 | Required |
| Tests, Agent evaluation, and handoff evidence | Python/frontend/Compose/Live/docs | failing contracts first; true PostgreSQL/Redis for critical semantics; one protected Live; exact commands/results in milestone reports and final acceptance; PR review/checks | reports/CI/PR | Required |

## 11. Test and Validation Strategy

### 11.1 Existing Tests to Run

- Backend report focused: `uv run --locked pytest tests/unit/report tests/contract/test_report_progress_contract.py tests/e2e/test_report_progress_offline_contract.py -q`
- Memory Redis/migration regression: `uv run --locked pytest tests/integration/test_memory_migrations.py tests/integration/test_memory_redis_cache.py tests/unit/memory/test_redis_cache_contract.py -q`
- Python full offline: `uv run --locked pytest -q`
- Changed Python lint/type: `uv run --locked ruff check <explicit changed Python files>` and `uv run --locked pyright backend tests`
- Frontend report focused: `npm test -- reportProgress useReport ReportProgress` from `frontend/`
- Frontend full: `npm test`, `npm run lint`, `npm run type-check`, `npm run build`
- Compose syntax: existing production/offline compose commands discovered in M0, both rendered with `config` before build/run.

### 11.2 New or Updated Tests Required

- D06-T01 `tests/unit/report/test_report_idempotency.py`: normalizer/header/digest/decision table; fails before interfaces exist.
- D06-T02 `tests/integration/test_report_task_governance_persistence.py`: migration/model/create-or-reuse/expiry/cross-user; PostgreSQL-specific concurrency is mandatory.
- D06-T03 `tests/integration/test_report_task_governance_redis.py`: true Redis TTL/corruption/mismatch/flush/restart/unreachable/rebuild; must skip with explicit reason only when M1 baseline lacks Redis, then run in Compose.
- D06-T04 `tests/unit/report/test_report_governance_snapshot.py` plus runner tests: DB version/stage monotonic/terminal/commit-before-publish failure.
- D06-T05 update contract file or new `tests/contract/test_report_task_governance_contract.py`: POST created/replayed/conflict/legacy/owner and 20 concurrent one dispatch.
- D06-T06 `tests/integration/test_report_progress_multi_instance.py`: two app/runtime instances share PostgreSQL/Redis; cross-instance SSE/reconnect and version dedupe.
- D06-T07 update frontend API/store/composable specs: key reuse/new intent, structured errors, user-scoped minimal sessionStorage, refresh same task, cleanup/no second POST.
- D06-T08 extend offline Compose app/stack: two backend endpoints or equivalent two process fixtures, concurrency/Redis restart/Nginx SSE.
- D06-T09 existing full compatibility suite; no duplicate per-module test copies.
- D06-T10 update protected live test: one true report, 20 concurrent same key/two instances, one workflow; default skipped and no whole-report retry.

### 11.3 Manual Smoke Tests

- Start isolated frontend/backend/PostgreSQL/Redis; log in as test user; click generate once; verify CREATED and real progress.
- Refresh while running; verify same task ID and restored latest stage, with no new POST in browser network history.
- Retry the identical HTTP request/key; verify REPLAYED and same IDs.
- Click a deliberate new generation after cleanup/new key; verify new IDs.
- Stop/restart/flush isolated Redis during a deterministic report; verify UI continues through DB reconcile/polling and no second workflow.
- Connect SSE through the second backend/proxy instance; verify task-persistent sequence and same terminal/report.
- Cross-user test uses a second test identity and sees safe 404/no cache leakage.

### 11.4 Agent/RAG/Tool Evaluation, if applicable

- Agent/Prompt/tool quality is not changed and is not re-evaluated subjectively.
- Protected Live checks engineering behavior only: graph invocation count=1, existing real model/tool attempts occur, report terminal/content hash agree, no raw content in artifact.
- Do not assert model wording, financial value, tool completion order or investment recommendation quality.

### 11.5 Expected Terminal / Logs / Trace / Artifacts

- Concise logs: `stage=report_task_governance`, digested task reference, `status`, `idempotency_status`, `snapshot_version`, `transport`, `cache_status`, `elapsed_ms`, stable `error_code`.
- Health: report governance database readiness plus Redis `READY|DEGRADED|DISABLED`, safe counters and last stable error code.
- Milestone files: `docs/specs/D06_REPORT_TASK_GOVERNANCE_MILESTONE_<N>_EXECUTION_REPORT.md` or `_BLOCKED.md`.
- Final acceptance: `docs/specs/D06_REPORT_TASK_GOVERNANCE_ACCEPTANCE_REPORT.md` maps D06-C/T cases to commands and results.
- Live artifact: task/report IDs may be hashed; contains request count, unique task/report/workflow counts, versions/progress, elapsed, report body hash and redaction result only.

### 11.6 Acceptance Criteria

| Behavior / Risk | Test or Check | Command / Method | Expected Result |
| --- | --- | --- | --- |
| key semantics | D06-T01 | focused unit pytest | normalization deterministic; invalid header 422; conflict matrix exact |
| atomic one creation | D06-T02/T05 | true PostgreSQL, 20 concurrent/two sessions | 1 Report, 1 governance row/generation, 1 dispatch; 19 replay |
| expiry/running | persistence integration | controlled clock + row lock | running never expires; expired terminal rotates once |
| Redis failure safety | D06-T03 | true Redis unreachable/flush/restart/corrupt | DB creates/reuses once; safe degraded/rebuild |
| snapshot authority | D06-T04 | unit/integration | Report + stage/version atomic; no regression; terminal after content commit |
| cross-instance SSE | D06-T06 | two app instances | B observes A; reconnect latest version then monotonic updates |
| API compatibility/security | D06-T05 | FastAPI contract | old POST works; fields preserved; 401/404/409/422 stable; no leaks |
| frontend no duplicate | D06-T07 | Vitest fake network/storage/clock | retry/refresh no POST; deliberate new key creates; cleanup correct |
| production topology | D06-T08 | Compose config/build/E2E | PostgreSQL/Redis/two instances/Nginx behavior matches contract |
| broad compatibility | D06-T09 | full Python/frontend | D05/chat/Skills/Memory/report CRUD all pass |
| true external execution | D06-T10 | opt-in live command | 20 requests → one real graph/report; REST/SSE/DB hashes/terminal match |
| docs/Claim | diff review | Claim matrix | code supports every statement; DB/Redis/BackgroundTasks limits explicit |
| no secrets/user file | secret scan + git status | explicit staged list | no raw sensitive values; D01 remains untracked/unstaged |

## 12. Milestones

### Milestone 0: Safety and Baseline Check

**Goal:** Confirm branch, user changes, exact migration ownership, available runtimes/tests and current D05 baseline without source edits.

**Files / Modules:** Read-only repository/AGENTS, status/diff, report/migration/Redis/Compose/test files; create only `D06_REPORT_TASK_GOVERNANCE_MILESTONE_0_EXECUTION_REPORT.md` and update this plan governance sections.

**Implementation Intent:** Resolve exact Alembic directory/head, fresh bootstrap order, Python/Node/Docker/Redis/PostgreSQL availability, current focused test pass/fail and Compose commands. Record D01 as protected user work. No production services or migrations.

**Tests / Checks:** `git status --short`; branch/HEAD/remotes; `alembic heads/current` against disposable URL only if available; pytest collect/focused D05+Memory; frontend focused; Compose `config`; tool versions; no real API.

**Expected Result:** Baseline is reproducible, no overlapping user edits, exact commands and allowed surfaces are confirmed, and report file records existing failures separately.

**Stop Condition:** Any user modification overlaps allowed source files; migration URL cannot be proven disposable; branch/base mismatch; P0 design contradiction; essential toolchain missing with no safe fallback.

**Rollback Note:** Only documentation/governance changes; remove/revert the M0 report and plan updates without touching D01.

**Handoff Evidence:** status/branch/head, changed surfaces, commands/results, migration/Compose discovery, blockers, governance updates.

### Milestone 1: Lock Contracts and Failing Reproductions

**Goal:** Add the minimal D06-T01..T10 test contracts/skeletons before changing behavior, proving current duplicate and recovery gaps.

**Files / Modules:** allowed test/frontend spec files, test helpers/offline app, D06 M1 report and plan governance only.

**Implementation Intent:** Define public/application interfaces through behavior, not implementation internals. Use fakes only for deterministic unit boundaries; concurrency acceptance must retain true PostgreSQL/Redis slots. Live skeleton remains skipped unless explicit gate. Do not create production modules or migration.

**Tests / Checks:** collect all new tests; run unit/contract/frontend subsets expecting narrowly documented failures because D06 symbols/behavior are absent; ensure existing D05 focused tests remain green; Ruff/lint/type on test changes.

**Expected Result:** Every D06 behavior maps to one test responsibility; pre-change failures demonstrate duplicate dispatch/missing persistent version/recovery rather than test setup mistakes; protected Live is default skipped.

**Stop Condition:** Tests require changing Prompt/Agent/Memory/auth/adding dependency; production behavior already contradicts Spec; PostgreSQL concurrency cannot be represented in existing harness and requires an unapproved platform.

**Rollback Note:** Revert only D06 test/spec additions; no production or database state changed.

**Handoff Evidence:** test files, D06-T mapping, collect counts, expected failure signatures, D05 baseline, skipped Live proof.

### Milestone 2: PostgreSQL Authority and Atomic Create-or-Reuse

**Goal:** Implement the independent governance table, migration, typed idempotency contracts/service/repository and API creation path so concurrency produces one task and one dispatch without Redis.

**Files / Modules:** new report task application/infrastructure packages; report router/schema; ORM/managed-table registration/migration; config only for core feature flag/TTL; M2-targeted tests/report.

**Implementation Intent:** Implement normalization/digest/header validation, unique `(user,key)` row, same-transaction Report+governance winner, loser rollback/read, row-locked expired terminal rotation, stable CREATED/REPLAYED/CONFLICT results. Register BackgroundTasks only after winner commit. Keep DB/feature fallback behavior explicit and old no-header clients protected by command hash.

**Tests / Checks:** T01/T02/T05 core; migration upgrade/downgrade/fresh; true PostgreSQL 20-way contention; API 401/404/409/422; report CRUD regression; Ruff/Pyright/import/container Python 3.11 syntax.

**Expected Result:** With Redis absent, two instances or sessions can never create/dispatch more than one active report for the same effective key; old response consumers still work.

**Stop Condition:** Requires destructive alteration to `reports`, production URL uncertainty, DB dialect cannot support frozen semantics, second failed repair attempt, or auth/API breaking change.

**Rollback Note:** Disable feature path to old route behavior if necessary; downgrade independent migration only in disposable test DB; revert M2 files explicitly; never delete user Report rows.

**Handoff Evidence:** migration proof, row/dispatch counts, API samples without secrets, focused test/lint/type results, decision/surprise updates.

### Milestone 3: Persistent Snapshot, Redis Adapter and Cross-instance SSE

**Goal:** Persist every true report stage/version, mirror/rebuild in Redis, notify across instances and recover D05 SSE from latest snapshot.

**Files / Modules:** governance/progress application and infrastructure; `run_report_task`; report SSE/snapshot router; Redis report runtime; main/config/env/health; targeted unit/integration/contract tests and M3 report.

**Implementation Intent:** Evolve publisher to awaitable if required; atomically update Report/governance then best-effort Redis SET/PUBLISH. Strict versioned envelope, digest keys/channels, TTL and owner/fingerprint validation. SSE subscribes before snapshot read, emits only greater persistent versions, reconciles on timeout, and uses DB when Redis fails. Preserve D05 fixed public stages/messages and polling terminal semantics.

**Tests / Checks:** T03/T04/T06; true Redis hit/miss/TTL/corruption/flush/restart/unreachable; two runtime instances; D05 full report progress unit/contract; memory Redis regression; health/log redaction; resource cleanup/no leaked pubsub connections.

**Expected Result:** Instance B observes A's progress; reconnect returns current stage/version then later updates without gaps causing incorrect state; Redis can disappear without duplicate execution or false completion.

**Stop Condition:** Redis becomes required for correctness/startup, publisher failure rolls back DB, cross-user cache access, full replay/Streams becomes necessary, or two repair attempts fail.

**Rollback Note:** Feature flag selects DB/in-process D05 fallback; Redis data is disposable and may be flushed only in isolated tests; independent migration remains compatible with M2; revert M3 adapter/runtime changes explicitly.

**Handoff Evidence:** version sequences, cross-instance evidence, Redis fault matrix, health/metrics/log redaction, D05/Memory regression, cleanup counts.

### Milestone 4: Frontend Recovery and Deployment Topology

**Goal:** Make browser retries/refresh resume the same governed task and extend isolated topology to exercise two backend instances through the real proxy.

**Files / Modules:** allowed frontend report API/composable/store/view/components/specs; exact Compose/Nginx/offline app files; backend response/error adaptation if a frozen frontend contract exposes a narrow mismatch; M4 report.

**Implementation Intent:** Generate a new explicit key per deliberate click, reuse through one request lifecycle, persist minimal user-scoped active reference in sessionStorage, restore via status/SSE without POST, clear on terminal/logout/invalid owner. Treat REPLAYED as normal. Preserve D05 SSE→poll same-task fallback. Add two-instance test wiring without changing production architecture beyond supported horizontal instances.

**Tests / Checks:** T07; frontend focused/full lint/type/build; storage privacy scan; actual browser smoke at `http://127.0.0.1:5173/chat` or report route; Compose config/build and deterministic two-instance E2E where available.

**Expected Result:** response loss and page refresh never create a second task; deliberate new generation uses a new key; old history/detail UI works; proxy streams persistent versions from either instance.

**Stop Condition:** Requires auth-store/JWT protocol rewrite, stores raw command/token/body, adds E2E dependency, changes unrelated UI, or two repair attempts fail.

**Rollback Note:** Remove only new sessionStorage entries and frontend changes; optional response fields are ignorable; Compose topology can revert independently; do not clear unrelated browser storage.

**Handoff Evidence:** Vitest/build/browser/network observations, storage payload example with redaction, Compose instance/task counts, governance updates.

### Milestone 5: Full Offline Verification and Narrow Fixes

**Goal:** Run the complete agreed offline/static/Compose matrix and repair only evidence-backed D06 regressions.

**Files / Modules:** all previously allowed changed files, tests, M5 report/plan governance; no new feature surface.

**Implementation Intent:** Review diff before testing; run narrow→broad. Inspect the first failing log, apply one focused fix, rerun narrow then affected broad checks. Run migration and Redis fault cycles only in verified disposable resources. Secret/privacy scan and Python 3.11 container check are release gates.

**Tests / Checks:** D06-T01..T09; full `uv run --locked pytest -q`; changed Ruff; Pyright; frontend test/lint/type/build; production/offline Compose config/build/E2E; migration upgrade/downgrade/fresh; `git diff --check`; explicit secret/forbidden-field scan.

**Expected Result:** All D06 offline cases and existing regressions pass; any unrelated baseline is precisely recorded with command/evidence; no skipped required PostgreSQL/Redis/Compose test remains.

**Stop Condition:** Same failure persists after two focused repair attempts, requires forbidden scope/new dependency/destructive action, Docker/infra remains unavailable after safe diagnostics, or a security/privacy invariant fails without narrow fix.

**Rollback Note:** Preserve failing state and write `_BLOCKED.md`; do not reset user work. Each previous milestone may be reverted from explicit diff; migration rollback only on disposable DB.

**Handoff Evidence:** exact command matrix/counts/durations, migration/Compose/Redis evidence, diff/secret review, failures/repairs, rollback status.

### Milestone 6: Protected Live, Documentation, Independent Review and GitHub Delivery

**Goal:** Prove exactly one real report execution under concurrent retries, align documentation/Claims, perform independent diff review, then commit/push/PR/checks/authorized merge.

**Files / Modules:** protected live test/artifact, D06 acceptance/report docs, README/testing docs, verified Claim passages in the two project-description documents, narrow fixes only, Git metadata/Issue/PR.

**Implementation Intent:** Run one gated real model + existing read-only financial-data report with 20 same-key requests split across two app instances; no whole-report retry. Record only hashes/counts/versions/timing. Review architecture, transactions, cache poisoning, auth isolation, privacy, resource cleanup, migration rollback, frontend race and Claim accuracy. Stage explicit D06 files excluding D01; one coherent conventional commit; push; PR references #52; wait for checks; address findings; squash merge only when green.

**Tests / Checks:** `$env:RUN_PROTECTED_LIVE_REPORT_E2E='true'; uv run --locked pytest tests/e2e/test_live_report_progress.py -q -m live` or final gated path; focused regressions after any review fix; final diff/stat/check/status; secret scan; `gh pr checks`; review PR diff against plan/acceptance.

**Expected Result:** one real workflow/report/task; 20 responses share IDs; SSE/REST/DB terminal/content hash match; docs state database/Redis/BackgroundTasks limits accurately; PR checks green; authorized squash merge lands on main and Issue closes.

**Stop Condition:** Missing/invalid live credentials, test would write production data or repeat paid report, real execution count exceeds one, leaked sensitive data, actionable review finding cannot be narrowly fixed, CI fails twice for same D06 cause, or merge conflict changes scope.

**Rollback Note:** Do not rerun the whole live report automatically. Remove/redact unsafe artifact immediately without exposing it. Remote branch/PR can remain open for diagnosis; never force-push main. Before merge, revert D06 commit or close PR; after merge, use a forward/revert PR and feature flag, not destructive reset.

**Handoff Evidence:** protected live counts/hash/timing, final acceptance matrix, review findings/fixes, commit SHA, PR URL/checks/merge SHA, Issue status, final clean/expected status showing D01 untouched.

## 13. Execution Protocol

- Execute exactly one milestone at a time using the Small-step Implementation skill.
- Start each milestone by restating its goal and allowed files.
- Run `git status --short` before editing and explicitly confirm D01 remains untracked.
- Do not overwrite user changes; stop on overlap.
- Do not modify files outside allowed scope or move to the next milestone without a written execution report and evidence.
- Run failing tests before production edits for M1+, then the narrowest relevant check after each change.
- Inspect logs before repair and fix only the concrete issue; one focused post-failure edit equals one repair attempt.
- If two consecutive repair attempts fail, stop and produce `D06_REPORT_TASK_GOVERNANCE_MILESTONE_<N>_EXECUTION_BLOCKED.md` with command, error, suspected cause, files touched and decision needed.
- Never claim PostgreSQL/Redis/multi-instance/Live acceptance from fakes or SQLite.
- Never run migration/flush/restart against a resource until its isolated test identity is proven.
- Never rerun the protected whole report automatically.
- Review diff before broad tests and before staging; stage explicit files only, never `git add .`.
- Do not claim completion without tests, privacy scan, independent review and GitHub evidence.
- Update Progress, Decision Log, Surprises & Discoveries, and Outcomes & Retrospective after every milestone.
- Satisfy every applicable Engineering Implementation Contract row; report any `Not applicable` explicitly.

## 14. Rollback Plan

Before implementation, rollback is simply discarding the unexecuted plan. During implementation, each milestone must remain independently reviewable and reversible on `feat/52-report-task-governance`.

- Branch: all work remains on the dedicated feature branch until PR checks/review pass; never rewrite or reset `main`.
- User work: D01 remains untracked/unstaged; every stage/commit uses explicit paths. If overlap appears, stop instead of restoring files.
- Application rollback: typed feature flag/runtime composition can return to D05's old create + in-process observation path; optional API fields do not require client rollback.
- Database rollback: governance is an independent table; verify downgrade only on disposable data. Production rollback disables the feature first and preserves reports; destructive downgrade requires a separate operational decision.
- Redis rollback: report namespace is derived and disposable, but flush/delete is permitted only for isolated test namespace/instance; Memory namespace must never be touched.
- Frontend rollback: remove only D06-specific sessionStorage key for the authenticated test user; no global `sessionStorage.clear()` in product code.
- Dependencies: no dependency additions are planned; if one becomes necessary, stop for approval rather than modifying lockfiles.
- Remote rollback: before merge close PR/delete feature branch if desired; after merge use revert/forward-fix PR, never force-push or hard reset shared history.
- Stop rather than rollback destructively when DB identity, user-file ownership, migration safety, sensitive artifact content or live side effects are uncertain.

## 15. Progress

- [x] Milestone 0: Safety and Baseline Check
  - Completed: 2026-09-05
  - Evidence: branch/HEAD and `origin/main` all at `80f4a0c`; both Compose configs valid; Alembic single head `20260825_04`; D05 report baseline `25 passed, 1 skipped`; Memory Redis/migration baseline `13 passed, 4 skipped`; frontend report baseline `16 passed`; details in `D06_REPORT_TASK_GOVERNANCE_MILESTONE_0_EXECUTION_REPORT.md`.
- [x] Milestone 1: Lock Contracts and Failing Reproductions
  - Completed: 2026-09-05
  - Evidence: 23 Python D06 cases defined (22 default-collected + 1 Live filtered) and 3 frontend cases; red baseline is `18 failed, 1 passed, 3 skipped, 1 deselected` plus frontend `3 failed`, each failure maps to absent D06 behavior; new tests pass Ruff/Pyright/ESLint/type-check; unchanged D05 report baselines remain backend `25 passed, 1 skipped` and frontend `16 passed`; details in `D06_REPORT_TASK_GOVERNANCE_MILESTONE_1_EXECUTION_REPORT.md`.
- [x] Milestone 2: PostgreSQL Authority and Atomic Create-or-Reuse
  - Completed: 2026-09-05
  - Evidence: typed NFKC/header/HMAC/decision contracts, independent Alembic revision `20260905_05`, one stable `(user_id, key_digest)` row with row-locked terminal rotation, Report+governance same-transaction creation, winner-only BackgroundTasks and backward-compatible response metadata; isolated pgvector/PostgreSQL ran 28/28 including 20-way contention and up/down/reupgrade; focused report regression `51 passed, 3 skipped`; Ruff/Pyright and Python 3.11 compile passed; details in `D06_REPORT_TASK_GOVERNANCE_MILESTONE_2_EXECUTION_REPORT.md`.
- [x] Milestone 3: Persistent Snapshot, Redis Adapter and Cross-instance SSE
  - Completed: 2026-09-07
  - Evidence: every report stage now commits one monotonic PostgreSQL snapshot/version before best-effort Redis mirror/PubSub; a second runtime observes remote versions and reloads the database authority; Redis miss/corruption/flush/restart/unreachable cases remain fail-open and rebuildable; isolated PostgreSQL+Redis evidence passed 6/6 plus a post-restart rebuild case, true Redis rerun passed 4/4, Memory Redis regression passed 13/13, and the final default report matrix passed `64 passed, 7 skipped`; Ruff, Pyright and local Python 3.11 compile passed; details in `D06_REPORT_TASK_GOVERNANCE_MILESTONE_3_EXECUTION_REPORT.md`.
- [x] Milestone 4: Frontend Recovery and Deployment Topology
  - Completed: 2026-09-07
  - Evidence: 浏览器端显式 UUID 幂等键、同键一次安全重试、按用户摘要隔离的四字段 `sessionStorage` 引用和刷新无 POST 恢复均由 10 个 D06 前端契约覆盖；前端全量 `53 passed`，lint/type-check/build 通过；生产与离线 Compose 配置有效；真实 Nginx 双后端 + PostgreSQL + Redis 栈通过 `334 passed, 4 skipped, 48 deselected, 3 xfailed`，20 路同键跨实例只创建/执行一次并在定向清空报告缓存后从数据库重建；详情见 `D06_REPORT_TASK_GOVERNANCE_MILESTONE_4_EXECUTION_REPORT.md`。
- [x] Milestone 5: Full Offline Verification and Narrow Fixes
  - Completed: 2026-09-07
  - Evidence: 全量本机 `441 passed, 14 skipped, 9 deselected, 3 xfailed`；前端 `53 passed` 且 lint/type-check/build 通过；Python 3.11 只读编译通过；真实 Nginx 双后端 + PostgreSQL + Redis runner 两次通过 `335 passed, 4 protected-live skipped, 48 deselected, 3 xfailed`，D06 基础设施定向矩阵 `27 passed, 0 skipped`。M4 发现的复合订阅取消泄漏由专项红测复现并修复，关闭日志不再出现 pending receive；Ruff 与触达范围 Pyright 通过，仓库全量 Pyright 的 4 个错误精确归属于未触达的历史 provider 代码。详情见 `D06_REPORT_TASK_GOVERNANCE_MILESTONE_5_EXECUTION_REPORT.md`。
- [x] Milestone 6: Protected Live, Documentation, Independent Review and GitHub Delivery
  - Completed: 2026-09-08
  - Evidence: exactly one protected real report passed with 20 requests split 10/10 across two ASGI applications, `1 CREATED + 19 REPLAYED + 1 workflow`, 17 model runs, 46 read-only Tushare calls, terminal `completed`, snapshot version 15 and redaction pass. Claim docs are aligned; independent review fixed the frontend restore-vs-new-create epoch race, CI ownership gap, a multi-instance process-local metrics assertion and migration lifecycle isolation from running backends. The metrics fix was rechecked in an isolated true two-backend Compose stack with `335 passed, 4 skipped, 48 deselected, 3 xfailed`; final dedicated-migration-database evidence is recorded by PR #53 checks. PR #53 references/closes #52; authorized squash merge follows the final GitHub checks and its result is recorded on GitHub.

## 16. Decision Log

| Date | Decision | Reason | Source |
| --- | --- | --- | --- |
| 2026-09-05 | Preserve default `user + normalized command hash + 600s`, add optional explicit key | align interview Claim and distinguish retries from deliberate new intent | Clarification Q01-Q04 |
| 2026-09-05 | PostgreSQL is correctness authority; Redis is derived | Redis outage/restart cannot permit duplicate paid workflow | Clarification Q05/Q11-Q16 |
| 2026-09-05 | Use independent Alembic-managed governance table | avoid risky legacy Report/create_all ownership change and enable rollback | Tradeoff Option B |
| 2026-09-05 | Recover latest snapshot, not full replay | sufficient UX with bounded infrastructure; Pub/Sub loss is tolerated | Clarification Q16-Q19 |
| 2026-09-05 | Keep BackgroundTasks and disclose crash boundary | durable queue is valuable but outside D06 | Clarification Q08-Q09 |
| 2026-09-05 | One protected real report, no automatic whole-run retry | prove actual graph while bounding cost/side effects | Clarification Q29 |
| 2026-09-05 | Execute seven narrow milestones and explicit D06 reports | separate contracts, DB, Redis/SSE, frontend, verification and release risks | Plan Freezing |
| 2026-09-05 | All D06 Compose operations must use a unique project name and only disposable services | host already runs a separate `finance_*` stack; name/target isolation is mandatory before down/restart/flush/migration | M0 environment inspection |
| 2026-09-05 | Freeze application contracts under `backend.application.report_tasks` and adapters under `backend.infrastructure.report_tasks` | tests now express dependency direction without importing router/Memory implementation into the domain contract | M1 D06-T01/T03/T06 |
| 2026-09-05 | Freeze governance table as one stable row per `(user_id, key_digest)` with generation rotation | supports database uniqueness and atomic expired-terminal replacement without delete/reinsert races | M1 migration contract + Clarification Q06/Q10 |
| 2026-09-05 | Keep real PostgreSQL/Redis/multi-instance tests gated by `RUN_D06_ISOLATED_INFRA_TESTS=true` | prevents accidental use of running host services while retaining required Compose acceptance | M0 isolation finding + M1 tests |
| 2026-09-05 | Use optimistic Report+governance insert and follow the unique-constraint winner after full rollback | keeps the Report and governance row in one transaction and prevents loser Report leakage without adding a queue or distributed lock | M2 PostgreSQL contention proof |
| 2026-09-05 | Rotate expired terminal tasks by locking and updating the stable governance row | running tasks remain protected beyond TTL and delete/reinsert cannot create a duplicate-execution window | M2 D06-T01/T02 |
| 2026-09-05 | Domain-separate the HMAC digest with the existing injected JWT secret | no new production secret/dependency is introduced and raw user/key/command never enters storage | M2 typed Settings/application contract |
| 2026-09-07 | Increment snapshot version only in the PostgreSQL transaction that accepts a state/stage change | reconnect and cross-instance ordering must be sourced from one correctness authority, while Redis remains disposable | M3 D06-T04 |
| 2026-09-07 | Redis notifications carry only digested task reference and version; subscribers always reload PostgreSQL | Pub/Sub loss, duplication or spoofed payload cannot become report state or leak owner/content | M3 D06-T03/T06 |
| 2026-09-07 | SSE subscribes before its snapshot read and reconciles on Redis notification or timeout | closes read/subscribe race without requiring Streams/full replay and preserves D05 polling fallback | M3 D06-T06 |
| 2026-09-07 | 浏览器只保存用户 SHA-256 摘要命名空间下的 task/report/key/fingerprint 四字段引用 | 刷新恢复需要最小可用状态，但不得持久化原始用户、命令、token 或报告正文 | M4 D06-T07 |
| 2026-09-07 | 仅对网络、408/425/429/5xx 做一次同键重试；冲突和其他 4xx 不重试 | 覆盖响应丢失且避免把确定性客户端错误放大为重复流量 | M4 D06-T07 |
| 2026-09-07 | 离线验收使用 Nginx `least_conn` 双后端；生产 Compose 启用报告 Redis 配置但不把 Redis 健康设为后端启动前置 | 真实验证水平扩展，同时维持 PostgreSQL 正确性与 Redis fail-open 启动承诺 | M4 D06-T08 |
| 2026-09-07 | 复合本地/Redis receive 的 `asyncio.wait` 必须位于 `try/finally` 内，并在任何外层取消后 cancel + gather 全部子任务 | `wait_for` 可在 FIRST_COMPLETED 前取消外层协程；只有无条件观察所有子任务才能消除 SSE 周期对账泄漏 | M5 D06-T06 资源审计 |
| 2026-09-07 | M5 同时保留仓库全量 Pyright 结果和触达范围 Pyright 门禁，不越界修改历史 provider 错误 | 4 个全量错误均位于未触达的 `profile_extractor.py`/`stock_resolver.py`，D06 触达范围为 0 error；修复它们会扩大本里程碑 | M5 静态验证 |
| 2026-09-08 | D06 Live 用两个独立 ASGI 应用共享一次性 PostgreSQL，真双进程结论只引用 M5 Compose | 同时证明真实模型/工具与 API 治理，又不把进程内 TestClient 拓扑夸大为 OS 进程隔离 | M6 protected Live |
| 2026-09-08 | 报告面试 Claim 以 PostgreSQL 唯一约束为幂等权威，Redis 只作最新快照/通知 | 历史 Redis-only `SET NX EX`、query token 和 Redis-first 说法与主线代码冲突且存在正确性/隐私缺口 | M6 Claim alignment |

## 17. Surprises & Discoveries

| Finding | Impact | Action |
| --- | --- | --- |
| Historical Redis branch contains exact Claim but uses Redis-only fail-open and a 3-second placeholder wait | cannot migrate wholesale without preserving duplicate risk | retain normalization/TTL concepts only; database anchor is mandatory |
| D05 sequence is connection-local and hub is process-local by explicit design | reconnect/multi-instance needs persistent version semantics, not just a new adapter | reuse wire field but source it from governance snapshot version |
| Fresh DB uses `create_all` while Memory tables are Alembic-managed exclusions | changing legacy Report columns can conflict with bootstrap | create independent managed governance table and verify fresh/up/down |
| FastAPI officially positions BackgroundTasks as same-process/simple work | D06 cannot honestly claim crash-resume or distributed job execution | freeze once-only route dispatch only; defer durable queue |
| Host has running `finance_backend`, `finance_frontend`, `finance_postgres` and unrelated application containers | an unqualified Compose down, Redis flush or migration could disrupt user services/data | use a D06-specific Compose project and tmpfs/test DB; never operate on existing container names or broad Docker state |
| True-Redis Memory tests are environment-gated and four cases skipped in the host baseline | local focused success does not prove Redis integration availability | M1 preserves explicit skips; M3/M5 must run required Redis cases inside isolated Compose and may not count skips as acceptance |
| Current focused suites emit only known Starlette/httpx and naive-UTC deprecation warnings | not a D06 baseline failure but may obscure new warnings | record without unrelated dependency or datetime refactor; compare warning set after implementation |
| Pytest imports same-named files as top-level modules because these test directories are not packages | duplicate basenames cause collection mismatch | use unique `test_report_idempotency_contract.py` name; do not add package markers only to mask it |
| Current code already isolates identical keys across users only because it creates every request anew | one D06 cross-user test passes before implementation but does not prove idempotency | retain as compatibility characterization; require same-user replay and one-dispatch tests for governance proof |
| Host output renders Chinese pytest text with a legacy console code page while file encodings and collection IDs remain valid UTF-8 | logs are visually noisy but test assertions/files are not corrupted | keep UTF-8 source; report stable English error symbols/counts rather than rewriting text or terminal configuration |
| The true PostgreSQL contract fixture initially reused asyncpg pooled connections across `asyncio.run` and TestClient event loops | produced Windows `Event loop is closed` before business assertions | use `NullPool` in this test-only harness; production engine ownership remains unchanged |
| The production backend image is Python 3.11 while the local project environment is Python 3.12 | host-only type/tests do not prove deployed syntax compatibility | compile the touched Python files in a read-only `python:3.11-slim` container with pycache redirected to `/tmp` |
| Existing model defaults still emit naive-UTC deprecation warnings in Report fixture creation | M2 tests pass but warnings remain part of the historical baseline | record and defer repository-wide datetime migration; D06 governance writes timezone-aware timestamps |
| D05 race coverage expected the authenticated in-process snapshot before a later database state | replacing the first frame with a newer DB value changed an existing observable contract | retain subscribe-before-read, emit the authorized initial snapshot, then immediately reconcile the persistent database version |
| Real PostgreSQL snapshot fixtures require the pgvector extension and schema-length-valid user IDs before reaching governance assertions | the first harness attempts failed before D06 business behavior | install the extension only in the disposable pgvector container and use UUID-shaped fixture IDs; production schema/code unchanged |
| `uv run --locked pytest` on this Windows host omits the repository root from the console-script import path, while `python -m pytest` works | the executable form fails collection with `No module named backend` despite valid code | standardize milestone evidence on `uv run --locked python -m pytest`; do not patch product/test imports for a host launcher quirk |
| Docker Desktop's WSL engine stopped during a redundant final combined-stack rerun after successful isolated PostgreSQL/Redis, Redis-restart, true-Redis and Memory-Redis runs | the last rerun could not establish connections, but no application assertion regressed and `--rm` left no container/volume | preserve earlier required real-infrastructure evidence, report the environment interruption, and retry the full topology only in M4/M5 when Docker is available |
| PowerShell policy rejected recursive deletion of the verified `D:\FinanceProject\.codex_tmp\d06_m3_pycache` directory | Python 3.11 compile passed, but this generated cache may remain outside the repository | do not bypass endpoint policy; keep the exact safe path in the report and exclude it from Git |
| M1 前端红测用任意字符串模拟存储 key，而正式实现按用户 Web Crypto 摘要寻址 | 恢复/清理断言最初无法命中当前用户记录 | 让测试调用正式 key 派生函数，不放宽生产隔离策略 |
| 双实例会在客户端尚未观察每个中间版本前提交更高持久版本 | D05 旧离线断言把合法单调序列误写为必须无间断连续 | 保留正整数、严格递增和不回退契约；不虚构完整事件回放 |
| D06 双实例测试最初在未初始化用户时直接发 20 路请求 | 用户补建逻辑竞争触发 `users_pkey`，掩盖报告幂等验收 | 按真实前端顺序先调用一次 `/api/user/init`，再并发验证报告创建 |
| 首轮双实例关闭时出现一个 `ReportProgressSubscription.receive()` pending-task 提示 | 当前断言和资源终态均通过，但复合等待取消清理仍值得专项审计 | 不在 M4 越界改后端；列为 M5 diff/资源清理检查项 |
| 浏览器标签页仍指向 `127.0.0.1:5173`，但宿主 dev server 已停止 | 可见浏览器烟测在导航前即 `ERR_CONNECTION_REFUSED`，不是页面运行错误 | 如实记录未执行；以真实 Compose 浏览器同构产物、API/代理 E2E 和前端单测为 M4 验收证据，M5 再决定是否需要重复启动 |
| `_ReportUpdateSubscription.receive()` 在进入清理块前等待 FIRST_COMPLETED | 外层 reconcile 超时会取消 receive 并遗留本地/Redis 两个 pending 子任务 | 专项红测复现；把 wait 纳入 `try/finally` 并无条件 cancel + gather，真实双实例关闭日志复核无告警 |
| 首次 M5 Compose build 获取 Docker Hub metadata 时本机 `127.0.0.1:7890` 代理被强制断开 | 容器尚未创建，业务断言未执行 | 确认项目为空后按同一命令重试一次并通过；没有修改镜像或网络配置 |
| 仓库全量 Pyright 报告 4 个历史错误 | 错误位于未触达 provider 文件，不能宣称仓库全量类型检查绿 | 保留精确文件/行号；D06 全部触达 Python 文件 Pyright 0 error；不在 M5 越界修复 |
| 为补充 skip 原因而覆盖 Compose runner 命令时，首次遗漏 `PYTHONPATH`，第二次又把无 marker 的默认配置单测放进注入 Redis 环境 | 两次都在收集/环境合同层失败，不是产品回归 | 校正验证命令为镜像原始 marker 选择并加 `-rs`；最终得到与 runner 相同的 335/4/48/3，4 个 skip 均为受保护 Live |
| 首个 D06 Live harness 把过多 patch 写进一个静态 `with` | Python 3.11 编译报 `too many statically nested blocks`，但尚未进入真实调用 | 在消耗 Live 预算前改用 `ExitStack`，静态门禁全绿后才运行唯一一次报告 |
| 唯一 Live 中 Tushare `sw_daily` 返回当前账号无权限 | 既有 Agent 工具按允许的降级语义继续，其他只读接口和最终报告成功 | 记录为真实 provider 边界，不重跑报告、不伪造该接口成功 |
| 独立前端 review 发现挂载恢复的 Web Crypto await 可与新建任务竞争 | 旧恢复可能在用户点击新建后接管 observation epoch | await 前后校验 epoch/`isGenerating`/用户，并增加延迟恢复专项测试 |
| PR 第二轮 Offline Compose E2E 的缓存命中断言偶发为 0 | Nginx 将聊天与健康请求分配到不同后端，而缓存/记忆可观测计数器是进程内状态；单个代理健康响应不能代表全局 | 直读两个 Compose 后端并聚合计数，保留逐实例 `UP` 校验；独立双后端完整回归通过 |
| PR 后续 Offline Compose E2E 在 downgrade 时出现 PostgreSQL deadlock | 原测试在运行中双后端持续读取应用数据库时执行全量多表 DDL，GitHub Runner 的更快时序暴露了锁顺序反转 | 为迁移生命周期增加独立 tmpfs pgvector 数据库，并在其中验证历史行保留；生产数据库与迁移实现不变 |

## 18. Outcomes & Retrospective

- What changed: M0 froze the safety baseline; M1 added D06 behavior contracts; M2 added the independent PostgreSQL governance authority and atomic create/reuse path; M3 added atomic stage snapshots, task-persistent versions, a strict disposable Redis cache/PubSub adapter, database rebuild/reconcile, cross-instance SSE observation and safe database/Redis health components；M4 added browser-scoped explicit key/retry/refresh recovery and a real Nginx two-backend acceptance topology；M5 closed the composite-subscription cancellation leak；M6 added the single protected real-governance harness, evidence-backed Claim documentation, a reviewed frontend epoch guard, correct cross-process aggregation in the Compose assertion and a dedicated migration-lifecycle database.
- What was verified: M2 proved one creation/dispatch under contention; M3 proved monotonic stage/terminal protection, Report content plus terminal snapshot atomicity, cache TTL/corruption/outage/restart behavior, remote-runtime notification and database-authoritative recovery；M4 proved 20 proxy requests split across both instances return one task/report and one invocation, a non-creator instance reaches terminal after report-cache deletion；M5 reran the complete host/frontend/Python 3.11/Compose matrix and a zero-skip D06 infrastructure submatrix；M6's only protected Live proved 20 same-key API requests result in one real workflow with matching DB/REST/SSE terminal state and redacted evidence.
- What remains risky: BackgroundTasks still has a process-crash window; Redis provides latest-state wake-up rather than complete replay；仓库全量 Pyright 仍有 4 个未触达 provider 历史错误。
- What should be improved next: Evaluate a durable outbox/worker only if production reliability requires it; do not pre-commit to a platform. Treat full event replay, rate limiting and production SLA as separate scoped tasks.

## 19. Deferred Work

- Durable queue/outbox/worker leases, crash recovery, redelivery, DLQ and rolling-worker operations.
- Redis Streams/database event log and complete cursor replay.
- Cancel/pause/resume/retry workflows and generic rate limit/circuit breaker/quota scheduling.
- Cross-device/multi-tab coordination and long-term idempotency history.
- Report body token streaming and any Prompt/Agent/financial/tool/Skill/Memory changes.
- Historical repository-wide Ruff issues and unrelated migration-worker log noise.

## 20. Handoff to Small-step Implementation

Start with Milestone 0 only. Run `git status --short`, confirm the branch/base, protected D01 file, changed surface, migration ownership, available PostgreSQL/Redis/Docker tests and current D05 baseline. Do not edit production or test code until Milestone 1. Report M0 evidence and update this plan's governance sections before proceeding.
