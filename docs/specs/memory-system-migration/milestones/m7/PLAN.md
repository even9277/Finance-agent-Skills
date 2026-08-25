# PLAN.md

## 1. Plan Metadata

- Plan name: M7 受控自然语言记忆命令与确认治理
- Task type: New Feature / Backend API / Agent workflow / Frontend / Persistent-data safety
- Status: Frozen for implementation review
- Target executor: Codex / Cursor / Claude Code
- Related artifacts:
  - `REQUIREMENT_SPEC.md`
  - `CODEBASE_RECON.md`
  - `CLARIFICATION_QUESTIONS.md`
  - `SOLUTION_TRADEOFF.md`
- Repository root: `D:\\FinanceProject\\Finance-agent-Skills`
- Current branch: `main` at plan-freezing time; implementation must use a dedicated short branch.
- Created date: 2026-08-25

## 2. User-facing Purpose

After this change, an authenticated user can use clear Chinese chat commands to inspect, update, delete, forget, confirm, or cancel their own memory. Destructive or broad operations show a frozen preview and require a one-time confirmation. REST, WebSocket, chat UI, and the memory panel expose the same machine-readable status and a safe user-facing message.

The current problem is that M6 has an authoritative PostgreSQL memory boundary and derived Redis/semantic providers, but no complete natural-language command branch, pending-confirmation state machine, or consistent frontend/API contract.

Success is observable when explicit memory commands terminate before the financial planner/tools, ordinary financial questions retain the existing controlled chain, cross-user/session/replay/expiry/version-conflict attempts fail closed, and a real offline Docker Compose journey verifies authority and derived status end to end.

## 3. Inputs Reviewed

- `REQUIREMENT_SPEC.md`: user-facing behavior, constraints, risks, acceptance criteria.
- `CODEBASE_RECON.md`: entry points, call chain, ownership, tests, logs, and gaps.
- `CLARIFICATION_QUESTIONS.md`: resolved parser, confirmation, TTL, scope, frontend, and offline-provider decisions.
- `SOLUTION_TRADEOFF.md`: selected Option B structured improvement with deterministic parser.
- Code files: `backend/application/chat/*`, `backend/application/memory/*`, `backend/infrastructure/memory/*`, `backend/routers/{chat,memory}.py`, `backend/schemas/{chat,memory}.py`, `backend/db/models.py`, migrations, frontend memory/chat modules, Compose E2E.
- Tests: M0-M6 authority, cache, semantic retrieval, controlled-chat contract, evaluation, and offline Compose suites.
- External references: Mem0 OSS identity/query validation, LangGraph interrupt/resume persistence concepts, OWASP Transaction Authorization Cheat Sheet.

## 4. Final Unified Direction

This iteration will add a typed, deterministic Chinese memory-command parser and preflight branch; persist pending confirmations in PostgreSQL; reuse the existing authority/audit/outbox/cache/semantic boundaries; map one `MemoryCommandResult` through REST, WebSocket, and frontend state; and prove behavior with unit, contract, integration, frontend, and Docker Compose offline E2E tests.

This iteration will not replace the controlled finance workflow or introduce LangGraph, a second authority, a new Mem0 service, real production/Tushare calls, broad report-memory injection, user export, or production migration/high-availability work.

The plan follows the repository's layered API/application/domain/infrastructure architecture, typed contracts, fail-closed authorization, additive compatibility, redacted observability, and one-milestone-at-a-time delivery protocol.

## 5. Planning Assumptions

- “忘掉我的文本记忆” means all active text memories for the authenticated user; it always creates a preview and pending confirmation.
- Default confirmation TTL is 600 seconds. The frozen target ID/version set is the maximum execution scope; records created later are excluded.
- User-visible memory content is limited to current-user summaries/snippets; logs, traces, fixtures, and artifacts never contain content, raw command text, user ID, or credentials.
- Chinese deterministic parsing is the default; English and model-assisted parsing are deferred.
- PostgreSQL is authoritative. Redis, pgvector, and Mem0/provider references remain rebuildable derived layers.
- Existing compatibility routes remain available, but every M7 write path touched by this work delegates to one application authority use case.
- Frontend testing dependencies may be added only if the existing package manager and CI can lock them in the frontend scope; otherwise stop for approval.

## 6. Changed Surface

| Surface | Involved? | Why | Risk | Verification |
| --- | --- | --- | --- | --- |
| Frontend | Yes | memory command/pending/confirm state and UI | Medium | Vitest/Vue Test Utils, build, Playwright/Compose journey |
| Backend API | Yes | shared REST/WS result mapping and compatibility fields | High | contract and integration tests |
| Database | Yes | pending command authority table and migration | High | Alembic upgrade/downgrade/re-upgrade, PostgreSQL E2E |
| Cache | Yes | authority mutation invalidation and derived status | High | cache invalidation/degraded-provider tests |
| Agent runtime | Yes, narrow | preflight branch before finance workflow | High | command termination and ordinary-path regression |
| Tool calling | No behavior change | memory command must prove zero finance tool calls | High | negative contract/E2E assertions |
| RAG / Memory | Yes | parser, scope, mutation, pending lifecycle | High | unit/integration/eval tests |
| MCP | No | M7 does not change financial MCP tools | Low | existing regression |
| Skills | No | no skill runtime change | Low | existing regression |
| Tests | Yes | characterize and prove all new safety semantics | High | full ordered test matrix |
| Observability | Yes | safe command stages and consistency status | Medium | log/trace redaction assertions |
| Security/Auth | Yes, boundary only | ownership/session/replay protection | High | cross-user/session/expiry/version negative tests |
| Build/Deployment | Yes, narrow | migration and offline Compose/CI wiring | High | compose config and offline E2E |

## 7. Repository Context

### 7.1 Relevant Entry Points

- `backend/main.py`: FastAPI bootstrap and settings/logging.
- `backend/routers/chat.py`: REST `send_message` and WebSocket `chat_stream` presenters.
- `backend/application/chat/use_case.py`: `ControlledChatUseCase.execute` orchestration.
- `backend/application/chat/factory.py`: production dependency assembly.
- `backend/routers/memory.py`: compatibility memory CRUD routes.
- `backend/application/memory/authority.py`: authoritative mutation port/result.
- `backend/infrastructure/memory/authority_repository.py`: PostgreSQL transaction/audit/outbox implementation.
- `frontend/src/api/index.ts`, `frontend/src/stores/memoryStore.ts`, `frontend/src/composables/useMemory.ts`, `frontend/src/components/memory/MemorySidebar.vue`.

### 7.2 Relevant Call Chain

```text
REST/WS auth -> ChatCommand -> build_chat_use_case
-> ControlledChatUseCase.prepare_turn
-> M7 memory-command preflight
   -> explicit command: validate -> authority/pending transition -> shared result -> terminate
   -> ordinary message: existing M6 retrieval -> ControlledConversationWorkflow
-> commit -> ChatOutcome -> REST/WS presenter
```

The command branch must occur before planner, permission, execute, evidence, Tushare, or synthesis stages. Session/message persistence must retain the existing transaction semantics and bind pending commands to the authenticated session.

### 7.3 Existing Patterns to Reuse

- typed `ChatCommand`/`ChatOutcome` and additive presenter fields;
- authority repository caller-owned transactions;
- audit plus INDEX outbox mutation results;
- user-scoped SQL filters, Redis cache-aside, semantic provider post-filter;
- versioned Alembic migrations;
- stable trace stages and deterministic offline Compose assembly.

### 7.4 Current Test Structure

Use `tests/unit`, `tests/contract`, `tests/integration`, `tests/evals`, and `tests/e2e`. Existing M0-M6 suites remain mandatory regression. Frontend tests belong under the existing frontend test convention selected during M1.

### 7.5 Current Observability Structure

Use module `logging.getLogger(__name__)`, existing application handlers, and the controlled trace adapter. Add only safe fields: stage, status, command kind, command reference, count, version/consistency status, duration, and error code.

## 8. Scope Control

### 8.1 In Scope

- Typed command intent/result/scope/status/error contracts and deterministic Chinese parser.
- Preflight branch, authority mutation, pending confirmation persistence/state transitions, audit/outbox/cache/derived status.
- REST/WS additive result mapping and compatibility routes' touched write-path delegation.
- Frontend pending/confirm/cancel/partial/error state and memory controls.
- Unit, contract, integration, offline eval, frontend, and real Docker Compose E2E evidence.
- M7 docs, Issue/PR/CI/review/merge reports.

### 8.2 Out of Scope

- Rewriting M0-M6 controlled workflow, planner, verifier, executor, evidence, or financial MCP tools.
- Making Redis, pgvector, Mem0, or any provider authoritative.
- Live paid models, production services, real Tushare, or network Mem0 in default tests/CI.
- Production data migration, physical audit deletion, HA topology, compliance certification, or broad Langfuse redesign.
- English/model-assisted parser, memory export, report-mode injection, or later M8/M9 failure evaluation.

### 8.3 Allowed Files / Modules

- `backend/application/chat/{contracts.py,use_case.py,factory.py}`
- `backend/application/memory/**`
- `Financial-MCP-Agent/src/memory/contracts.py` (only the shared profile-field contract required by the authority path)
- `backend/infrastructure/memory/{authority_repository.py,redis_cache.py,index_tasks.py,semantic_provider.py}` only where required for delegation/invalidation
- `backend/routers/{chat.py,memory.py}` and `backend/schemas/{chat.py,memory.py}`
- `backend/db/models.py`, `backend/migrations/versions/*pending*` (new versioned migration)
- `backend/config.py`, `backend/.env.example` only for approved typed constants/settings
- `frontend/src/api/**`, `frontend/src/stores/memoryStore.ts`, `frontend/src/composables/{useMemory.ts,useChat.ts}`, `frontend/src/components/memory/**`
- `tests/unit/memory/**`, `tests/contract/**`, `tests/integration/**`, `tests/evals/memory/**`, `tests/e2e/**`
- `frontend` test configuration/package manifest and lockfile only if M1 confirms needed and scoped
- `.github/workflows/ci.yml`, `docker/docker-compose.offline.yml`, `tests/e2e/offline_app.py` only for required gates
- `docs/specs/memory-system-migration/milestones/m7/**` reports and plan governance

### 8.4 Forbidden Changes

- Do not perform unrelated refactors or broad formatting.
- Do not modify generated/build artifacts, real `.env`, credentials, or deployment secrets.
- Do not add dependencies without explicit scope confirmation and lockfile review.
- Do not change public fields incompatibly; all new REST/WS fields are additive.
- Do not bypass authentication/ownership or weaken M5 high-impact confirmation.
- Do not use `confirm=true` as a direct broad-delete authorization after M7 touches that path.
- Do not physically delete audit evidence or silently convert provider/authority failures into success.
- Do not call paid models, production services, real Tushare, or network Mem0 in default tests/CI.
- Do not change planner/tool/evidence semantics or introduce a second memory authority/task system.
- Do not weaken or remove existing M0-M6 tests and safety checks.
- Do not touch files outside the allowed surface without stopping for approval.

## 9. Interfaces and Dependencies

| Interface / Dependency | Current Role | Planned Change | Compatibility Requirement | Validation |
| --- | --- | --- | --- | --- |
| `ChatCommand` / `ChatOutcome` | REST/WS shared application contract | add optional typed memory-command result | existing fields unchanged | contract snapshots |
| memory command parser | absent | versioned deterministic parse result | non-command falls through unchanged | parser unit/eval |
| `MemoryCommandResult` | absent/ad hoc dicts | shared status, reference, preview/count, consistency, error | additive API/WS representation | REST/WS same fixtures |
| pending command repository/table | absent | user/session/fingerprint/snapshot/version/TTL/one-shot state | Alembic reversible, no data loss | migration and lifecycle tests |
| authority use case/repository | M6 authoritative mutations | delegate command writes/deletes and invalidate derivatives | PostgreSQL remains source of truth | integration/E2E |
| compatibility memory routes | legacy CRUD | touched writes delegate; reads remain compatible | old request fields accepted | route regression |
| frontend memory store/API | profile/items ad hoc state | explicit pending/success/failure/partial/expired state | old consumers compile | Vitest/type/build |
| Redis/semantic/Mem0 adapters | rebuildable derived layers | status/invalidation only | failure cannot overwrite authority | degraded-provider tests |
| CI/Compose | existing M0-M6 gates | add frontend tests and M7 offline E2E | default offline/no live credentials | CI and compose runs |

## 10. Engineering Implementation Contract

| Category | Files / modules | Required behavior or documentation | Verification | Status |
| --- | --- | --- | --- | --- |
| Architecture and dependency direction | `backend/application/memory/**`, chat use case, routers | routes map protocols; application owns orchestration; repository owns SQL; command branch terminates before finance workflow | import/layer review, contract tests | Required |
| Docstrings, types, field meaning, and section navigation | all new/changed Python and TS contracts | Google-style docstrings, Chinese intent comments, typed enums/models, privacy/version semantics documented | Ruff/Pyright/review | Required |
| Configuration, env, secrets, constants, and prompts | `backend/config.py`, `.env.example`, parser/contracts | typed settings and versioned constants; no secret logging; no live default | config tests, secret scan | Required |
| Terminal output, logs, traces, metrics, and artifacts | command application, presenter, trace adapter | safe stage/status/error/count/reference/duration fields; no content/user ID/credentials | redaction tests and trace assertions | Required |
| Validation, errors, retry/fallback, state, and compatibility | parser, pending repository, authority use case, routes | fail-closed ownership/scope/TTL/version/replay; bounded transient retries; explicit partial/degraded status; additive API | negative integration tests | Required |
| Tests, Agent evaluation, and handoff evidence | `tests/**`, frontend tests, M7 reports | default offline, deterministic fixtures, Docker E2E, ordered commands, exact evidence in reports | full matrix and PR CI | Required |

## 11. Test and Validation Strategy

### 11.1 Existing Tests to Run

Run in this order after each applicable milestone and before merge:

1. `uv run --locked ruff check <maintained scope> tests`
2. `uv run --locked pyright <maintained scope> tests`
3. focused M7 unit/contract/integration tests
4. `uv run --locked pytest backend -q`
5. `uv run --locked pytest Financial-MCP-Agent -q -m "not live"`
6. `uv run --locked pytest tests/evals -q -m "eval_smoke and not live"`
7. `uv run --locked pytest -q`
8. `npm run lint && npm run type-check && npm run build` (frontend)
9. frontend Vitest/Playwright commands established in M1
10. `docker compose -f docker/docker-compose.offline.yml config`
11. `docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e`

### 11.2 New or Updated Tests Required

- parser: inspect/update/delete/forget/confirm/cancel, synonyms, ambiguity, non-command fall-through;
- contracts: REST and WS same `MemoryCommandResult`, compatibility fields retained;
- lifecycle: pending preview, one-shot confirm/cancel, TTL, cross-user/session, replay, fingerprint, version conflict, supersede, transaction rollback;
- authority/derived: deleted record immediately filtered; Redis/semantic/Mem0 failure is explicit partial/pending, never false success;
- workflow negative: memory command has zero planner/permission/execute/evidence/Tushare calls; ordinary finance still follows M6 stages;
- frontend: optimistic update rollback, pending/confirm/cancel/expired/partial/error states and bounded content;
- eval data: versioned synthetic Chinese command fixtures with no private text;
- E2E: real HTTP frontend proxy -> backend -> PostgreSQL/Redis/derived status -> ordinary finance request.

### 11.3 Manual Smoke Tests

Use a synthetic authenticated user in offline Compose:

- “查看我的记忆” -> inspect result;
- “以后回答简短一点” -> direct low-impact update;
- “忘掉我的文本记忆” -> preview/pending only;
- confirm once -> success; repeat/cancel/expired/cross-session -> rejected;
- ordinary finance question -> normal controlled response and no command frame.

### 11.4 Agent/RAG/Tool Evaluation, if applicable

M7 evaluates command classification and termination safety, not model quality. Use deterministic fixtures and assert parser version, command kind, normalized scope, expected status, and zero forbidden tool calls. Live provider evaluation remains explicitly gated and deferred.

### 11.5 Expected Terminal / Logs / Trace / Artifacts

Terminal output stays concise and reports command kind/status/count/reference. Structured logs/traces contain `stage`, `run_id` or `trace_id`, `status`, `elapsed_ms`, `error_code`, `command_kind`, safe reference, count, and consistency status. No command text, memory content, user ID, auth header, or credential is written. Reports store command IDs and test counts only.

### 11.6 Acceptance Criteria

| Behavior / Risk | Test or Check | Command / Method | Expected Result |
| --- | --- | --- | --- |
| Explicit command branch | parser + workflow contract | focused pytest | command returns without finance stages |
| Ordinary finance compatibility | existing controlled-chat regression | `pytest tests/contract tests/e2e` | existing stage/tool behavior unchanged |
| Ownership isolation | integration negatives | focused pytest | cross-user read/write/confirm rejected |
| Destructive safety | lifecycle tests | focused pytest | preview -> one-shot confirmation only |
| Replay/expiry/version | lifecycle + DB constraints | focused pytest | stable rejection, no duplicate side effect |
| Authority/derived consistency | authority/cache/provider tests | focused pytest | authority result correct; degraded state explicit |
| API/WS parity | contract fixtures | focused pytest | same typed result and additive compatibility |
| Frontend recovery | Vitest/Playwright | npm test commands | failure rolls back; pending/expired visible |
| Migration safety | Alembic + Compose | upgrade/downgrade/re-upgrade | reversible and parity-safe |
| Full link | offline Compose E2E | compose command above | real HTTP/DB journey passes offline |
| Privacy | log/fixture scan | repository test/script | no sensitive payload leakage |

## 12. Milestones

### Milestone 0: Safety and Baseline Check

**Goal:** Confirm clean scope, branch strategy, tools, and M0-M6 baseline before edits.

**Files / Modules:** repository status, `AGENTS.md`, M7 docs, CI/test manifests; no source edits.

**Implementation Intent:** Create GitHub Issue, create short branch from current `main`, commit the four existing M7 analysis docs plus this plan, and capture baseline commands/results. Do not implement behavior.

**Tests / Checks:** `git status --short`, branch/remote checks, `docker compose ... config`, focused existing M6 regression if feasible.

**Expected Result:** dedicated branch exists, no user changes are overwritten, issue scope is reviewable, baseline evidence is recorded.

**Stop Condition:** conflicting user edits, unresolved P0, unavailable required tool, or scope outside this plan.

**Rollback Note:** delete only the new branch/Issue if not pushed; preserve all pre-existing files and user changes.

**Handoff Evidence:** issue URL/number, branch name, status output, baseline command summaries, updated Progress.

### Milestone 1: Lock or Add Tests / Reproduction

**Goal:** Establish deterministic fixtures and failing/characterization tests before implementation.

**Files / Modules:** `tests/unit/memory/**`, `tests/contract/**`, `tests/integration/**`, `tests/evals/memory/**`, frontend test config/tests, no production behavior changes.

**Implementation Intent:** Add synthetic command cases and contracts for parser intent, pending state transitions, REST/WS parity, frontend states, and ordinary-path zero-tool-call behavior. Confirm the frontend test runner and dependency policy.

**Tests / Checks:** focused tests (expected new failures where contracts are not implemented), existing M6 tests, frontend lint/type/build.

**Expected Result:** test cases express every acceptance risk without paid/live services; failures are attributable to missing M7 behavior.

**Stop Condition:** test framework/dependency requires unapproved broad changes, or a reproduction contradicts the frozen requirement.

**Rollback Note:** revert only new fixtures/config/tests on the M7 branch; keep analysis docs.

**Handoff Evidence:** test file list, commands, failure signatures, synthetic-data/privacy scan, Progress update.

### Milestone 2: Implement Core Change

**Goal:** Implement typed parser, pending authority, application command branch, and shared result contract.

**Files / Modules:** allowed backend application/domain/infrastructure/schema/model/migration paths listed in section 8.3; only necessary frontend contract plumbing.

**Implementation Intent:** Add versioned deterministic parser and normalized scope; add PostgreSQL pending command model/repository/migration with TTL, fingerprint, frozen IDs/versions, one-shot state and owner/session binding; route explicit commands before finance workflow; delegate mutations through M6 authority/audit/outbox and expose additive REST/WS result.

**Tests / Checks:** M1 tests plus focused unit, contract, migration, and lifecycle tests.

**Expected Result:** explicit command flows work in application tests, ordinary finance path remains unchanged, no direct Mem0/legacy authority write is introduced.

**Stop Condition:** schema/API/auth changes exceed allowed scope, a second authority/task system is needed, or two repair attempts fail.

**Rollback Note:** downgrade the new Alembic revision in an isolated database, revert milestone commits only, and do not touch existing user data or migrations.

**Handoff Evidence:** changed file list, migration upgrade/downgrade evidence, focused test output, API/WS examples with redacted payloads.

### Milestone 3: Add Validation, Error Handling, and Observability

**Goal:** Harden fail-closed validation, derived consistency semantics, logs/traces, frontend state and recovery behavior.

**Files / Modules:** remaining allowed authority/cache/semantic/trace/frontend modules, error mappings, `.env.example` only if typed settings are required.

**Implementation Intent:** Enforce ownership/scope/length/high-impact confirmation, replay/expiry/version conflict, bounded retry/fallback, explicit PARTIAL/PENDING/DEGRADED statuses, safe trace fields, and frontend rollback/refresh/confirmation states.

**Tests / Checks:** negative integration, degraded-provider, redaction, frontend component and browser tests; existing M5/M6 governance tests.

**Expected Result:** every invalid or unavailable dependency state is explicit and recoverable; no sensitive payload is logged or displayed beyond bounds.

**Stop Condition:** unsafe logging, silent success, compatibility break, or required change outside allowed modules.

**Rollback Note:** revert only hardening/observability/frontend milestone commits; retain core contracts if they are independently valid.

**Handoff Evidence:** error-code matrix, redaction scan, trace field assertions, frontend test output and screenshots/artifact references if available.

### Milestone 4: Verification and Narrow Fixes

**Goal:** Run the complete ordered verification matrix and repair only concrete failures.

**Files / Modules:** only files implicated by failed checks; no scope expansion.

**Implementation Intent:** Run lint, type-check, focused tests, backend/agent/eval/root regression, frontend checks, Compose config and real offline Compose E2E. Confirm ordinary finance requests do not call forbidden live tools in the command branch.

**Tests / Checks:** exact commands in section 11.1; collect exit codes, counts, durations, and safe artifacts.

**Expected Result:** all required gates pass or any remaining failure is documented with reproducible cause and explicit decision.

**Stop Condition:** two consecutive repair attempts for the same failure fail; Docker/network/credential issue cannot be safely resolved offline.

**Rollback Note:** preserve failure report and revert the smallest implicated commit; never hide or weaken a failing test.

**Handoff Evidence:** complete verification table, E2E request/response summary, logs/trace redaction result, residual-risk list.

### Milestone 5: Documentation and Handoff

**Goal:** Finalize project docs, interview-口径 mapping, migration/rollback notes, and GitHub delivery evidence.

**Files / Modules:** M7 docs/reports, `AGENTS.md` only if a process rule is explicitly added, README/API docs only when required by changed contract, CI/Issue/PR metadata.

**Implementation Intent:** Update PLAN governance sections and milestone report, document command/status contracts and operations, open PR, obtain CI and review evidence, merge through GitHub, close Issue, delete short branch, and verify clean `main`.

**Tests / Checks:** final diff review, CI status, full required regression, branch/main cleanliness, issue/PR linkage.

**Expected Result:** merged, reviewable, reproducible M7 with no secrets or generated artifacts and a clear handoff for M8.

**Stop Condition:** CI/review failure, undocumented behavior, dirty main, or merge conflict requiring scope change.

**Rollback Note:** use GitHub revert of the merge commit and Alembic downgrade procedure if post-merge verification finds a defect; preserve audit data.

**Handoff Evidence:** PR/merge/CI/review links, final commit SHA, closed Issue, final report and residual risks.

## 13. Execution Protocol

- Execute exactly one milestone at a time.
- Start each milestone by restating its goal and allowed files.
- Run `git status --short` before editing.
- Do not overwrite user changes.
- Do not modify files outside the allowed surface.
- Do not move to the next milestone without reporting evidence and updating governance sections.
- If a required change is outside scope, stop and ask for approval.
- If tests fail, inspect the narrowest relevant logs and fix only the concrete issue.
- After two consecutive repair attempts fail, stop and write a failure report.
- Never claim completion without command output/evidence.
- Default tests remain offline and must not call paid models, production services, real Tushare, or network Mem0.
- Use real Docker Compose E2E with deterministic/offline providers before merge.

## 14. Rollback Plan

Implementation must use a dedicated short branch from the latest verified `main`, with one focused commit or reviewable commit group per milestone. Before implementation, rollback is simply discarding the unexecuted plan. During implementation, each milestone is independently revertible.

For database changes, use an expand-first Alembic revision; validate upgrade, downgrade, and re-upgrade in an isolated PostgreSQL database before any shared environment. Never run destructive data deletion during development. If a milestone fails, preserve the failure report, revert only its commits, leave user changes untouched, and stop after the repair limit. After merge, rollback is a GitHub revert plus the documented migration downgrade only after confirming data compatibility.

## 15. Progress

- [x] Milestone 0: Safety and Baseline Check (Issue #38, branch `feat/38-memory-commands`, baseline captured)
- [x] Milestone 1: Lock or Add Tests / Reproduction (parser/result contracts and offline fixtures added; frontend runner remains a scoped follow-up)
- [x] Milestone 2: Implement Core Change (parser, pending authority/migration, chat branch, REST/WS/TS contract)
- [ ] Milestone 3: Add Validation, Error Handling, and Observability
- [ ] Milestone 4: Verification and Narrow Fixes
- [ ] Milestone 5: Documentation and Handoff

## 16. Decision Log

| Date | Decision | Reason | Source |
| --- | --- | --- | --- |
| 2026-08-25 | Choose deterministic Chinese parser and structured improvement (Option B) | Side-effecting memory writes must be auditable, offline-testable, and fail closed | `CLARIFICATION_QUESTIONS.md`, `SOLUTION_TRADEOFF.md` |
| 2026-08-25 | PostgreSQL remains sole authority; Redis/pgvector/Mem0 are rebuildable derived layers | Prevent split-brain writes and preserve M6 boundary | user requirement, M6 contract |
| 2026-08-25 | Broad forget requires preview + 600s one-shot confirmation | Prevent accidental destructive deletion and replay/TOCTOU | OWASP transaction authorization guidance |
| 2026-08-25 | REST/WS/frontend share one additive result contract | Avoid protocol-specific state drift | `CODEBASE_RECON.md` |
| 2026-08-25 | Default tests are deterministic/offline; live providers remain gated | Protect cost, privacy, and CI reproducibility | user requirement and repository rules |

## 17. Surprises & Discoveries

| Finding | Impact | Action |
| --- | --- | --- |
| Existing M6 authority already emits audit/outbox and supports caller-owned transactions | Reduces need for a new mutation system | Reuse it; add only pending command authority |
| Legacy memory routes still expose ad hoc CRUD and `confirm=true` delete-all | Risk of bypassing M7 safety semantics | Keep compatibility inputs but delegate touched writes to one application use case |
| Frontend memory updates are optimistic without reliable rollback | UI can diverge from PostgreSQL after failure | Add explicit pending/success/failure/refresh states and tests |
| Frontend currently lacks the planned unit/browser test runner | Dependency and CI scope may expand | Verify in M1; stop for approval if it cannot remain narrow |
| Frontend `package.json` has no Vitest/Playwright and no existing test script | Adding both now would expand M1 beyond characterization scope | Keep production lint/type/build green; evaluate the smallest locked test addition in M3 |
| The existing domain contracts already had command action/result types but lacked a low-impact response preference field | A parallel command enum would drift from M6 authority semantics | Reuse the domain action vocabulary and add only `ProfileField.RESPONSE_PREF` plus the application result fields |

## 18. Outcomes & Retrospective

- What changed: To be filled after Milestones 2-5.
- What was verified: To be filled with exact commands and results; no results are claimed during plan freezing.
- What remains risky: Provider availability, migration compatibility, and any deferred live-provider behavior.
- What should be improved next: M8 protected-live evaluation, broader language parsing, report-mode memory, and production operational hardening.

## 19. Deferred Work

- English/multilingual or LLM-assisted command parsing.
- Real Mem0/network provider activation and protected-live evaluation.
- Memory export, full audit viewer, report-mode injection, physical retention deletion.
- Multi-region/HA deployment, compliance certification, and broad Langfuse redesign.
- M8/M9 failure injection and long-running operational evaluation.

## 20. Handoff to Small-step Implementation

Start with Milestone 0 only. Run `git status --short`, confirm the changed surface and available tests, create/link the GitHub Issue and dedicated short branch, and do not edit implementation files until Milestone 1. Report evidence and update the governance sections before proceeding.
