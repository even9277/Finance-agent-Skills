# PLAN.md

## 1. Plan Metadata

- Plan name: Controlled Conversation Memory System Full Migration
- Task type: Cross-module Agent memory refactor, persistent-data migration, infrastructure integration, evaluation, and full-stack delivery
- Status: Frozen for implementation review
- Target executor: Codex
- Related artifacts:
  - `REQUIREMENT_SPEC.md`
  - `CODEBASE_RECON.md`
  - `CLARIFICATION_QUESTIONS.md`
  - `SOLUTION_TRADEOFF.md`
- Repository root: `D:\FinanceProject\Finance-agent-Skills`
- Current branch: `docs/22-memory-migration-spec`
- GitHub tracking: Issue #22 currently tracks specification; each implementation milestone requires its own Issue/short branch/PR before GitHub delivery.
- Created date: 2026-08-24

## 2. User-facing Purpose

After this change, the user should be able to hold a multi-turn financial conversation in which the system safely remembers the active entity, current constraints, and temporary answer preference; compresses older dialogue without losing the last good context; and recalls governed cross-session preferences without treating memory as market evidence.

The user must also be able to say ordinary Chinese commands such as “我的风险偏好改成稳健型”“以后回答简短一点”“删除新能源偏好”“忘掉我的文本记忆”, then inspect the effective result through the current API/frontend. PostgreSQL/pgvector, Redis, Mem0, workers, backend, and frontend must run through the documented Compose topology.

The current problem is that the repository has partial STM/LTM assets but no verified single lifecycle: Working State is not persisted as a typed contract, compaction is not scheduled by the active chat chain, profile and task writes are not one transaction, Mem0 may be unavailable or provider-authoritative, Redis is absent, deletion ownership is incomplete, and memory-specific tests/E2E are missing.

The success of this plan can be observed by deterministic offline tests, database/cache/provider integration tests, multi-turn and cross-session evaluation, one automated browser/API Compose journey, a protected real-model/real-Tushare memory journey, safe trace evidence, cleanup evidence, and a final mapping that marks each interview claim with reproducible code/test proof.

## 3. Inputs Reviewed

- REQUIREMENT_SPEC.md: Full STM-01 through STM-10 and LTM-01 through LTM-10 scope and acceptance boundaries.
- CODEBASE_RECON.md: Active entry path, current/historical module mapping, persistence gaps, flags, tests, and risks.
- CLARIFICATION_QUESTIONS.md: Resolved P0 decisions and accepted P1 defaults.
- SOLUTION_TRADEOFF.md: Option B selected; project-governed memory with PostgreSQL authority, Redis cache-aside, and Mem0 as derived semantic provider.
- Code files: `backend/application/chat/*`, `backend/infrastructure/chat/*`, `backend/db/*`, `backend/config.py`, `backend/main.py`, `backend/routers/memory.py`, `backend/schemas/memory.py`, current `backend/services/*memory*`/STM files, `Financial-MCP-Agent/src/conversation/*`, `Financial-MCP-Agent/src/memory/*`, frontend memory/chat files, Docker, CI, and test harnesses.
- Tests: Existing unit/contract/integration/eval/E2E files listed in `CODEBASE_RECON.md`; no existing memory-focused suite is accepted as sufficient.
- External references: Mem0 OSS config/async/filter/source, pgvector, Redis cache-aside, PostgreSQL locking/constraints, SQLAlchemy async transactions, Alembic, LangGraph memory concepts, Langfuse/OpenTelemetry, OpenClaw memory architecture, and Hermes memory-provider boundaries.

## 4. Final Unified Direction

This iteration will deliver one complete memory program through ordered, cumulative milestones:

- `Financial-MCP-Agent/src/memory` owns provider-independent typed memory contracts and deterministic policy.
- `backend/application/memory` owns memory use cases, stage-specific context, command handling, transaction intent, and ports.
- `backend/infrastructure/memory` owns SQLAlchemy, Redis, Mem0, model, and token-provider implementations.
- PostgreSQL owns authoritative state, candidate lifecycle, profile/text memory, audit metadata, and durable outbox tasks.
- Redis owns only versioned rebuildable hot snapshots and bounded coordination.
- Mem0 `AsyncMemory` owns derived semantic indexing/search; promoted writes use inference disabled because project governance decides add/update/delete authority.
- PostgreSQL lexical recall and Mem0/pgvector semantic recall are fused, authoritatively post-filtered, reranked, and packed to a stage budget.
- The current `ControlledChatUseCase` and controlled workflow remain the only foreground mainline.
- Versioned Alembic migrations replace new ad-hoc startup DDL behavior.
- Default CI stays deterministic/offline; protected live verification uses existing typed provider settings, isolated test identities, real model calls, and read-only Tushare.

This iteration will not create a standalone Mem0 service, Redis-only job durability, a second conversation orchestrator, a LangGraph runtime replacement, a production user-data migration, multi-region deployment, or a broad Langfuse major-version upgrade.

The plan follows Option B from `SOLUTION_TRADEOFF.md` and embeds observation-first characterization before behavior replacement.

## 5. Planning Assumptions

- Assumption: The current REST and WebSocket chat schemas remain compatible. Memory-control results use ordinary assistant messages plus existing-compatible/additive metadata only if required.
- Assumption: The existing PostgreSQL container is replaced by or remains on the existing `pgvector/pgvector:pg16` image; a separate vector database is not required.
- Assumption: Mem0 runs in-process inside backend/worker containers. The Mem0 index is derived and can be rebuilt from project-owned active memory records.
- Assumption: `alembic>=1.19,<2` is introduced with the authoritative schema in Milestone 2; `redis>=8.1,<9` is introduced with the cache adapter in Milestone 4; `mem0ai>=2.0.18,<2.1` and `pgvector>=0.5,<1` are introduced only with the governed provider adapter in Milestone 6. `uv.lock` freezes exact resolved versions at each owning milestone. If compatibility fails, stop before source changes and record the smallest compatible decision.
- Assumption: Milestone 4 must resolve and record an immutable Redis 7.4 patch tag or digest before changing Compose. `redis:7.4-alpine` is only a family candidate and must not be committed as the final reproducible image reference.
- Assumption: Explicit direct user memory commands are trusted user evidence after authentication and validation. Model-extracted high-impact profile suggestions are not.
- Assumption: Confirmed memories remain until explicit deletion/supersession. Typed defaults are 30 days for unpromoted candidates, 90 days for auto-promoted inferred text, 10 minutes for pending destructive confirmations, and 180 days for safe audit metadata. They are reproducible engineering defaults, not production legal/SLA claims.
- Assumption: Real `.env` values may be read by the application at runtime but are never copied into reports, commands, fixtures, screenshots, or committed files.

## 6. Changed Surface

| Surface | Involved? | Why | Risk | Verification |
| --- | --- | --- | --- | --- |
| Frontend | Yes | Inspect/correct/delete/forget and chat command feedback | Medium | Vitest/component checks, type/build, Playwright/Compose journey |
| Backend API | Yes | Authenticated memory commands and existing memory CRUD | High | Contract and E2E tests; schema snapshot |
| Database | Yes | Typed state, events, candidates, records, audit, outbox, versions | High | Alembic upgrade/downgrade, transaction/concurrency tests |
| Cache | Yes | Redis hot state, version/TTL/invalidation/lease | High | Real Redis integration and outage/fallback tests |
| Agent runtime | Yes | Context gateway, stage injection, command bypass, post-turn events | High | Controlled workflow unit/eval/E2E regression |
| Tool calling | Indirect | Memory must not expand finance tools or replace evidence | High | Negative planner/tool-governance tests |
| RAG / Memory | Yes | Hybrid lexical/vector retrieval and bounded injection | High | Retrieval contract, relevance/scope/deletion eval |
| MCP | No | No memory feature requires MCP protocol change | Low | Existing MCP regression only |
| Skills | No direct schema change | Financial skills remain consumers of current state/evidence | Medium | Existing skill activation/planner/executor regression |
| Tests | Yes | New memory suites and fixtures | High | Collection, focused, root regression, CI |
| Observability | Yes | Foreground/background trace correlation and redaction | High | Trace contract/redaction tests and artifact inspection |
| Security/Auth | Yes | Ownership and destructive memory commands | High | Cross-user negative tests, confirmation and deletion tests |
| Build/Deployment | Yes | Dependencies, migrations, Redis, worker, health checks | High | Locked install, Compose config/health/E2E/cleanup |

## 7. Repository Context

### 7.1 Relevant Entry Points

- Frontend chat: `frontend/src/views/ChatView.vue`, `frontend/src/composables/useChat.ts`, `frontend/src/stores/chatStore.ts`, `frontend/src/api/index.ts`.
- Frontend memory: `frontend/src/composables/useMemory.ts`, `frontend/src/stores/memoryStore.ts`, `frontend/src/components/memory/*`.
- HTTP/WebSocket: `backend/routers/chat.py`; memory API: `backend/routers/memory.py` and `backend/schemas/memory.py`.
- Chat application: `backend/application/chat/factory.py`, `backend/application/chat/use_case.py`, `backend/application/chat/ports.py`, `backend/application/chat/contracts.py`.
- Persistence adapter: `backend/infrastructure/chat/repository.py`.
- Controlled workflow: `Financial-MCP-Agent/src/conversation/workflow.py` and its entity/context/rewrite/route/plan/execution/verification/synthesis modules.
- Current memory/bootstrap: `backend/main.py`, `backend/config.py`, `backend/services/memory_service.py`, `backend/services/stm_context_service.py`, `backend/services/stm_compaction_worker.py`, `backend/services/stm_compaction_support.py`, `Financial-MCP-Agent/src/memory/*`.
- Database and runtime: `backend/db/models.py`, `backend/db/database.py`, Docker Compose files, Dockerfiles, CI workflows.

### 7.2 Relevant Call Chain

```text
ChatView / API client
-> POST /api/chat/message or WS /api/chat/stream
-> backend.routers.chat
-> build_chat_use_case
-> ControlledChatUseCase.execute
-> repository.prepare_turn
-> typed memory preflight + explicit memory command decision
   -> memory command?
      -> yes: command use case -> validate/authorize -> mutate or persist pending confirmation
              -> persistence/cache/index consistency result -> REST/WS response
      -> no: ControlledConversationWorkflow.run
             -> typed Working State / Context Gateway
             -> entity -> route -> rewrite -> permission -> plan -> validate
             -> execute -> verify -> controller/bounded replan -> synthesis
-> repository.save_result + state/events/outbox in one transaction
-> commit foreground response
-> memory worker claims durable tasks
   -> compaction and/or candidate extraction/governance
   -> promoted memory record
   -> Mem0/pgvector derived index
   -> Redis invalidation/refresh
-> later turn hybrid retrieval + authoritative post-filter + bounded injection
```

### 7.3 Existing Patterns to Reuse

- Thin FastAPI routers and application use-case construction.
- Typed controlled-conversation contracts and provider ports.
- One SQLAlchemy `AsyncSession` scoped to a request/worker transaction.
- Existing session/message/profile/summary concepts and current authenticated memory routes.
- Existing optional local trace plus Langfuse exporter boundary.
- Existing fake providers, offline eval runner, Compose E2E, and protected `live` marker.
- Existing Vue API/composable/store/component separation.

### 7.4 Current Test Structure

- Python test roots are configured in `pyproject.toml`; default pytest excludes `live`.
- Existing layers: `tests/unit`, `tests/contract`, `tests/integration`, `tests/evals`, `tests/e2e`, backend tests, and Agent-package tests.
- Frontend gates: `npm ci`, ESLint, Vue TypeScript check, and production build.
- Offline Compose: `docker/docker-compose.offline.yml` with `offline-e2e` exit-code ownership and cleanup.
- Protected live: `.github/workflows/live-e2e.yml`, currently memory/STM disabled and therefore requiring expansion.

### 7.5 Current Observability Structure

- Application startup initializes trace support in `backend/main.py`.
- Chat trace adapter lives in `backend/infrastructure/chat/trace.py` and Agent trace utilities include `Financial-MCP-Agent/src/tools/skill_trace.py`.
- Stable required additions: `memory.preflight`, `memory.command`, `memory.state.extract`, `memory.state.merge`, `memory.compact`, `memory.candidate.extract`, `memory.candidate.govern`, `memory.index`, `memory.retrieve`, `memory.inject`, `memory.mutate`, `memory.delete`, and correlated worker spans.

## 8. Scope Control

### 8.1 In Scope

- Characterization fixtures for current memory/profile/summary behavior and narrative bad cases.
- Typed memory domain and command/state/candidate/retrieval/task contracts.
- Alembic migration environment and expand-first memory schema revisions.
- Foreground state/profile/message/outbox transaction correction.
- Working State extraction/merge/version/audit and stage-specific context.
- Token budget, recent raw tail, Rolling Summary, last-good/CAS behavior.
- Redis cache-aside, version/TTL/invalidation, bounded lease/single-flight, health/degradation.
- LTM candidate extraction, evidence validation, dedupe/conflict/promotion/expiry/deletion/audit.
- Mem0 async adapter, pgvector derived index, lexical/vector hybrid retrieval and reranking.
- Explicit natural-language memory commands, existing API, and current frontend memory controls.
- Logs/traces/metrics/redaction, offline eval, integration, Compose/browser, protected live, cleanup, docs/claim mapping.

### 8.2 Out of Scope

- Production deployment, production data mutation, or production user-memory migration.
- Standalone Mem0 HTTP service or new microservice boundary.
- Kafka/Celery/Redis Streams as primary task durability.
- Multi-region Redis/PostgreSQL, autoscaling, production backup orchestration, or legal compliance certification.
- Replacement of the controlled workflow or introduction of a parallel memory runtime.
- Changes to unrelated Tushare tools, financial evidence rules, portfolio/report business behavior, or MCP protocol.
- Report-mode memory injection and report-mode E2E; report mode shares domain contracts and authoritative repositories only in this program and requires a later separately scoped milestone for runtime integration.
- Broad Langfuse SDK major upgrade.
- Historical performance/quality claims without new evidence.

### 8.3 Allowed Files / Modules

- Specification/report path: `docs/specs/memory-system-migration/**`.
- Agent memory domain: `Financial-MCP-Agent/src/memory/**`.
- Controlled integration only where required: `Financial-MCP-Agent/src/conversation/context.py`, `contracts.py`, `workflow.py`, `rewriting.py`, `synthesis.py`, `ports.py`, `errors.py`, and `__init__.py`.
- Backend application: `backend/application/memory/**`, `backend/application/chat/{contracts,factory,ports,use_case}.py`.
- Backend infrastructure: `backend/infrastructure/memory/**`, `backend/infrastructure/chat/{repository,trace,testing}.py`.
- API/bootstrap/config: `backend/routers/{chat,memory}.py`, `backend/schemas/{chat,memory}.py`, `backend/config.py`, `backend/main.py`.
- Persistence/migrations: `backend/db/{models,database}.py`, new `backend/migrations/**`, root/pyproject Alembic configuration.
- Existing memory services may be changed, split, or retired: `backend/services/{memory_service,profile_extractor,stm_compaction_support,stm_compaction_worker,stm_context_service,token_counter}.py`.
- Frontend: `frontend/src/api/index.ts`, chat/memory composables/stores/components/views, `frontend/package.json`, `frontend/package-lock.json`, and new focused frontend tests/E2E configuration.
- Dependency/config/build: `pyproject.toml`, `uv.lock`, `.env.example` files, `.gitignore`/`.dockerignore` only if needed for safe artifacts, Dockerfiles, Compose files, `docker/postgres/init.sql`.
- CI/docs: `.github/workflows/{ci,live-e2e}.yml`, `CONTRIBUTING.md`, `README.md`, memory/eval documentation.
- Tests/evals: `tests/unit/memory/**`, memory-related controlled tests, `tests/contract/*memory*`, `tests/integration/*memory*`, `tests/evals/memory/**`, `tests/e2e/*memory*`, shared fake providers/fixtures when necessary.

### 8.4 Forbidden Changes

- Do not perform unrelated refactors or reformat unrelated files.
- Do not edit the historical `D:\FinanceProject\Finance` repository.
- Do not create a second chat orchestrator, compatibility adapter, permanent forwarding module, dual write, or dual authority.
- Do not let Mem0 inference or assistant/tool text directly establish confirmed high-impact profile fields.
- Do not make Redis or Mem0 required for foreground correctness when PostgreSQL and current input are available.
- Do not treat memory as market evidence, tool authorization, or permission to bypass planner/verifier/controller boundaries.
- Do not modify generated/build/run artifacts or commit real trace/eval runs containing private data.
- Do not add dependencies outside the approved memory/migration/frontend-test surface. Any compatibility-driven substitute must be added to the Decision Log before editing.
- Do not make destructive database changes before an expand-first migration and downgrade/restore check.
- Do not break public API schemas; additive changes require contract tests and documentation.
- Do not weaken authentication/authorization, test gates, redaction, logging, or safety checks.
- Do not read secrets into terminal output, copy `.env`, or commit credentials/usable connection strings.
- Do not delete real user data. Destructive E2E acts only on generated isolated identities and must verify cleanup scope.
- Do not enable paid/live providers in default pytest or pull-request CI.
- Do not touch files outside the allowed list without stopping and updating this plan/Decision Log.
- Do not commit, push, create/merge PR, release, or deploy unless the user has authorized that delivery action for the milestone.

## 9. Interfaces and Dependencies

| Interface / Dependency | Current Role | Planned Change | Compatibility Requirement | Validation |
| --- | --- | --- | --- | --- |
| `POST /api/chat/message` | Synchronous chat | Detect/execute memory commands and consume governed context | Existing request/response fields remain readable | API contract + E2E |
| `/api/chat/stream` | Streaming chat | Equivalent memory behavior and stable events | Existing event types/order preserved unless additive documented event | WS contract + E2E |
| Memory REST endpoints | Profile/text memory CRUD | Backed by authoritative records, ownership, version, delete semantics | Existing frontend calls remain compatible | Contract/frontend tests |
| `ControlledChatUseCase` | Foreground orchestration/transaction | Coordinate preflight, workflow, persistence, outbox | Single public use-case owner remains | Unit/integration |
| Controlled workflow state/context | Route/plan/execute/synthesis inputs | Typed Working State and stage-specific memory packets | LTM cannot broaden tools/evidence | Unit/eval/negative tests |
| Memory domain contracts | Currently fragmented/untyped | Closed enums/models for state, command, candidate, lifecycle, retrieval, task | Versioned schema; no `dict[str, Any]` core state | Type/contract tests |
| PostgreSQL schema | Sessions/messages/profile/tasks | Add authoritative state/events/records/candidates/audit/outbox/version fields | Expand-first; existing sessions/messages readable | Alembic/integration |
| Redis | Absent | Versioned cache-aside and bounded coordination | Safe miss/outage falls back to DB | Real Redis integration |
| Mem0 `AsyncMemory` | Partial/Noop-capable client | One adapter; promoted `infer=False` writes; scoped CRUD/search/history | Project DB remains authority; IDs mapped/versioned | Fake + real pgvector integration |
| pgvector | Docker DB image capability | Derived vector collection/index; measured exact/HNSW choice | Embedding dimensions/version consistent | Migration/query/eval |
| Hybrid retrieval | Missing | Lexical + semantic candidates, fusion, post-filter, rerank, budget | Only active authorized records returned | Unit/integration/eval |
| Durable outbox | Partial separate task commits | Same foreground transaction; deterministic claiming/idempotency | No lost/duplicate effective writes | Concurrency/crash tests |
| Redis image | None | Resolve an immutable supported Redis 7.4 patch tag or digest in Milestone 4; do not treat `redis:7.4-alpine` as frozen | Supported by locked redis-py and obtainable in the active registry environment | Manifest/digest record + Compose health/contract |
| Python dependencies | No Mem0/Redis/Alembic/pgvector package | Add Alembic in M2, redis-py in M4, and Mem0/pgvector only in M6 | Each dependency appears only when its governed adapter is ready; `uv.lock` and Python 3.12 remain compatible | Per-milestone `uv lock`/`uv sync --locked` + import/no-activation smoke |
| Frontend test dependencies | Lint/type/build only | Add focused Vitest/Vue Test Utils and one Playwright journey if compatible | Existing build/toolchain remains | npm lock/lint/type/test/build |
| Typed Settings | Current flags/provider secrets | Redis/Mem0/embedding/rerank/task/budget/retention/live settings | Safe defaults; no real values committed | Settings tests + Compose config |
| Prompts/schemas | Current summary/profile extraction assets | Versioned Working State/summary/candidate/command structured outputs | Version in tasks/traces/eval | Snapshot/schema tests |
| Trace schema | Current controlled trace | Stable memory foreground/background stage names and safe attributes | Langfuse remains optional exporter | Trace/redaction tests |

### 9.1 Frozen Field Authority Matrix

| Field / memory kind | Authority | Model path | Automatic effect | Scope and precedence |
| --- | --- | --- | --- | --- |
| `risk_level`, `investment_horizon`, `expected_return_min/max` | Explicit user command, UI/API edit, or user confirmation | Candidate allowed | Never auto-promote | Persistent until superseded/deleted; current explicit instruction wins for the turn |
| `sectors`, `watchlist` | Explicit user command, UI/API edit, or user confirmation | Candidate allowed | Never auto-promote | Persistent, item-addressable, owner-scoped; current entity never mutates these implicitly |
| Real holdings/positions | Portfolio/account domain only | No Memory authority | Never | Memory cannot overwrite, infer, or expose these as account facts |
| `user_reported_position_context` | Explicit user statement or confirmation | Labelled text candidate only | Never auto-promote | Time-bounded; cannot act as portfolio truth, market evidence, valuation input, or tool authorization |
| Persistent financial constraints | Explicit user command, UI/API edit, or user confirmation | Candidate allowed | Never auto-promote | Persistent until superseded/deleted; session Working State may override without rewriting LTM |
| Current `constraints` | Validated current user message | Not LTM by default | Working State only | `this_turn` or `session_segment`; deterministic clear/expiry |
| Current `reply_preference_hint` | Validated current user message | May seed text candidate | Working State only | Current explicit wording wins; bounded turn/segment scope |
| Text response preference | Explicit command or repeated user-side evidence | Candidate allowed | Only after deterministic repeat/context/recency/conflict gates | Bounded scope, visible and deletable; current hint wins |
| Text topic interest | Explicit command or repeated user-side evidence | Candidate allowed | Only after the same gates plus topic/entity/task scope | Cannot change active entity, widen tools, or act as market evidence |

Assistant text, tool output, market data, and unsupported summary content cannot independently establish or promote any field. Portfolio/account data remains outside Memory authority. Every effective write records source, evidence reference, `policy_version`, `activation_source`, version, scope, and deletion state.

## 10. Engineering Implementation Contract

| Category | Files / modules | Required behavior or documentation | Verification | Status |
| --- | --- | --- | --- | --- |
| Architecture and dependency direction | Agent memory domain, backend application/infrastructure, chat integration | Routes/UI adapt protocols; application orchestrates; domain decides policy; adapters own providers; no reverse dependency | Import/type checks and architecture-focused review | Required |
| Docstrings, types, field meaning, and section navigation | All new/changed Python public interfaces and TS contracts | Chinese Google-style docstrings, explicit types/enums, field source/scope/version/privacy/expiry meaning, intent comments before non-obvious boundaries | Ruff, Pyright, review checklist | Required |
| Configuration, env, secrets, constants, and prompts | `backend/config.py`, safe examples, pyproject/lock, prompt/schema assets | Typed validation; safe defaults; operational knobs only; pinned/locked dependencies; versioned prompts/schemas; no secret output | Settings tests, lock check, secret/diff scan | Required |
| Terminal output, logs, traces, metrics, and artifacts | Existing trace adapters, worker/bootstrap, eval/E2E reports | Concise terminal; stable stage/status/elapsed/error/version/count IDs; foreground/background correlation; redacted content; large diagnostics in ignored artifacts | Logger/trace/redaction tests and artifact inspection | Required |
| Validation, errors, retry/fallback, state, and compatibility | Domain/application/provider/repository/workers | Closed status/error codes, boundary validation, CAS/idempotency, transient-only bounded retry, cache/provider fail-open, explicit partial/stale states, compatible API | Unit/contract/concurrency/failure E2E | Required |
| Tests, Agent evaluation, and handoff evidence | `tests/**`, frontend tests, Docker/CI, milestone reports | Tests-first characterization, unit/contract/integration/eval/Compose/live/browser layers, cleanup proof, exact commands, no invented metrics | Cumulative gates and independent review | Required |

## 11. Test and Validation Strategy

### 11.1 Existing Tests to Run

Run from `D:\FinanceProject\Finance-agent-Skills` unless stated otherwise:

1. `uv sync --locked --no-install-project --group dev`.
2. Run the exact maintained-scope Ruff command from `.github/workflows/ci.yml`, plus every Python file/module changed by the current milestone. Every changed or newly owned module must finish with zero Ruff errors.
3. Run the exact maintained-scope Pyright command from `.github/workflows/ci.yml`, plus every Python file/module changed by the current milestone. Every changed or newly owned module must finish with zero Pyright errors.
4. Run `uv run --locked ruff check backend Financial-MCP-Agent/src tests` and `uv run --locked pyright backend Financial-MCP-Agent/src tests` as repository-debt scans at cumulative gates. Compare against Issue #20's recorded baseline of 81 Ruff errors and 80 Pyright errors/6 warnings; this program may introduce no new finding. A touched historical module must be reduced to zero in the owning PR, and no new ignore may hide debt. Until Issue #20 closes, unchanged pre-existing findings are recorded rather than misreported as milestone regressions.
5. `uv run --locked python -m pytest backend -q`.
6. `uv run --locked python -m pytest Financial-MCP-Agent -q -m "not live"`.
7. `uv run --locked python -m pytest tests/unit tests/contract tests/integration -q`.
8. `uv run --locked python -m pytest tests/evals -q -m "eval_smoke and not live"`.
9. `uv run --locked python -m pytest tests/e2e -q -m "e2e and not live"`.
10. `uv run --locked python -m pytest -q`.
11. From `frontend`: `npm.cmd ci`, `npm.cmd run lint -- --quiet`, `npm.cmd run type-check`, `npm.cmd run build`; add the frozen frontend unit/E2E test script when introduced.
12. `docker compose -f docker/docker-compose.yml config --quiet`.
13. `docker compose -f docker/docker-compose.offline.yml config --quiet`.
14. `docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e`.
15. Always cleanup: `docker compose -f docker/docker-compose.offline.yml down -v --remove-orphans`.

Focused milestones run only their relevant subset first. Root regression, frontend gates, Compose, and live gates are cumulative final checks. Test result counts must be recorded from each actual run; historical counts are not acceptance facts.

### 11.2 New or Updated Tests Required

- `tests/unit/memory/test_contracts.py`: model/enums/schema/version/privacy validation.
- `tests/unit/memory/test_working_state_policy.py`: explicit entity switch, safe inheritance, ambiguity, multi-entity, constraint add/clear/expiry, preference precedence, no-op/version behavior.
- `tests/unit/memory/test_token_budget_and_summary.py`: estimate/reserve/safety margin, protected tail, summary boundary, last-good fallback, stale result rejection.
- `tests/unit/memory/test_candidate_governance.py`: provenance/evidence, dedupe, conflict, promotion/rejection/expiry, no assistant-only promotion.
- `tests/unit/memory/test_memory_commands.py`: direct profile/text update, inspect, targeted delete, bulk forget confirmation, ordinary finance query non-mutation.
- `tests/unit/memory/test_hybrid_retrieval.py`: filters, fusion, rerank, token budget, post-filter, current-state precedence.
- `tests/contract/test_memory_api_contract.py`: current endpoints, ownership, validation/errors, compatible response fields.
- `tests/contract/test_memory_provider_contract.py`: normalized Mem0 add/search/update/delete/history and filter validation using a fake provider.
- `tests/contract/test_memory_trace_contract.py`: stable stages/status/error/version fields and redaction.
- `tests/integration/test_memory_migrations.py`: Alembic upgrade, downgrade, re-upgrade, existing-session readability.
- `tests/integration/test_memory_transactional_outbox.py`: message/state/outbox atomicity, idempotency, row claiming, stale task, crash/retry.
- `tests/integration/test_memory_redis_cache.py`: real Redis key scope, TTL, version, invalidation, miss, corruption, outage fallback, lease token ownership.
- `tests/integration/test_memory_mem0_pgvector.py`: real Docker pgvector add/search/update/delete, metadata filters, cross-user isolation, derived-index reconciliation.
- `tests/integration/test_memory_controlled_chat.py`: foreground Working State/context/outbox/injection without real paid providers.
- `tests/evals/memory/data/smoke.jsonl` and runner tests: multi-turn state, compaction, cross-session retrieval, conflict, deletion, pollution, instruction adherence.
- `tests/e2e/test_memory_chat_chain.py`: deterministic complete STM/LTM/natural-language-control chain.
- `tests/e2e/test_memory_compose_stack.py`: frontend proxy/backend/PostgreSQL/Redis/worker/pgvector health, state, trace, and cleanup.
- `tests/e2e/test_live_memory_chain.py`: protected real LLM + real local memory infrastructure; selected read-only Tushare scenario.
- Focused frontend tests under `frontend/src/**/__tests__` for memory store/API/components and one browser journey under a frozen frontend E2E path.

Tests expected to fail before implementation are added in the milestone that owns the behavior; they must fail for the intended missing contract, not import/setup noise.

### 11.3 Manual Smoke Tests

1. Start documented Compose stack and open `http://127.0.0.1:5173/chat`.
2. Ask about one stock, follow with a pronoun-based question, then explicitly switch stocks. Confirm the UI answer and safe trace show correct Working State transitions.
3. Send enough fixed turns to cross the compaction threshold. Confirm recent raw messages remain verbatim and a versioned last-good Rolling Summary covers only older messages.
4. Say “我的风险偏好改成稳健型”. Confirm an acknowledgement, profile UI/API change, audit event, and next-session behavior.
5. Say “以后回答简短一点”. Confirm text memory storage/retrieval and compact response behavior in a new session.
6. Say “删除刚才的回答偏好”. Confirm targeted deletion and no subsequent active retrieval.
7. Say an ambiguous “把记忆都删了”. Confirm a scoped clarification/confirmation rather than an immediate broad delete.
8. Stop Redis and repeat a turn. Confirm the conversation falls back to PostgreSQL with a degraded cache status.
9. Stop or misconfigure Mem0 only in an isolated test profile. Confirm foreground conversation remains available and semantic recall reports explicit degradation.

### 11.4 Agent/RAG/Tool Evaluation, if applicable

- Dataset version: `memory-mainline-v1`; every sample has stable ID, turns/sessions, expected state transitions, allowed memory operations, forbidden injection, and expected trace stages.
- Initial coverage categories: safe entity inheritance/switch/ambiguity; constraints/preference scope; summary boundaries/failure/stale CAS; explicit profile/text mutation; candidate provenance/dedupe/conflict/promotion; cross-session recall; deleted/stale/cross-user suppression; tool non-expansion; synthesis instruction adherence.
- Grade intermediate state and retrieval evidence, not only final text.
- Establish baseline first. Freeze numeric gates only after at least one reproducible target-repository run; record dataset/prompt/schema/model/provider versions and safe run artifact path.
- LLM-as-judge is not a default CI requirement. Deterministic graders own correctness gates; optional judge results are separately labeled.

### 11.5 Expected Terminal / Logs / Trace / Artifacts

- Terminal reports stage-level `STARTED/SUCCEEDED/FAILED/SKIPPED/PARTIAL`, counts, elapsed time, safe IDs, and artifact path only.
- Structured log/trace fields include `stage`, `trace_id`, `task_id`, safe user/session reference, `state_version`, `summary_version`, `memory_version`, `prompt_version`, `schema_version`, `provider`, `model`, `status`, `elapsed_ms`, counts, `error_code`, `fallback_reason`, and safe artifact/cleanup reference.
- Raw profile values, messages, prompts, model responses, API keys, Authorization/Cookie headers, provider connection strings, and Tushare token are not general log/trace attributes.
- Offline/live reports are written under the milestone spec directory or ignored test artifact path after redaction. Real run payloads are not committed unless converted into safe fixtures.

### 11.6 Acceptance Criteria

| Behavior / Risk | Test or Check | Command / Method | Expected Result |
| --- | --- | --- | --- |
| Typed Working State | Unit + controlled integration | Focused memory state tests | Correct source/scope/version transitions; no untyped core state |
| Foreground atomicity | PostgreSQL integration | Transaction/outbox tests | Message/state/task commit or rollback together |
| Rolling Summary | Unit + E2E | Budget/summary tests and threshold journey | Protected tail retained; only older range summarized; last-good preserved |
| Stale concurrency | CAS/worker integration | Concurrent state/summary task cases | Late result marked stale and never overwrites newer state |
| Redis correctness | Real Redis integration | Cache contract/failure tests | Tenant/version/TTL correct; write invalidates; outage falls back |
| Candidate governance | Unit/eval | Candidate bad-case suite | Unsupported/assistant-only/high-impact inferred data not effective |
| Mem0/pgvector lifecycle | Real provider integration | Add/search/update/delete/reconcile tests | Scoped derived index and consistent deletion |
| Hybrid retrieval | Unit/integration/eval | Retrieval suite | Active authorized relevant bounded memories only |
| Tool/evidence isolation | Controlled eval | Planner/executor negative cases | Memory never broadens tools or becomes market evidence |
| Chat memory mutation | API/E2E/browser | Explicit update/delete/forget journeys | Correct location, acknowledgement, subsequent behavior, confirmation |
| Cross-user isolation | API/DB/Redis/Mem0 negatives | Two generated users | No cross-user read/update/delete/cache/vector result |
| Observability/redaction | Trace/log contract | Mock exporter/logger assertions | Complete stage correlation, no private/secrets |
| Dependency failure | Compose fault cases | Stop Redis/provider/worker | Foreground safe degradation; task recoverable |
| Full offline stack | Compose E2E | Offline Compose command | All services healthy, scenarios pass, resources removed |
| Protected live | Explicit live marker | `uv run --with socksio -- python -m pytest tests/e2e/test_live_memory_chain.py -q -m live` | Real model STM/LTM and read-only Tushare scenario pass; isolated data cleaned |
| Compatibility | Root + frontend regression | Existing commands | No unexplained regression or weakened gate |
| Interview mapping | Documentation audit | Module evidence table | Every claim marked verified/partial/deferred with links |

## 12. Milestones

### Milestone 0: Safety, Toolchain, Dependency, and Baseline Check

**Goal:** Confirm branch/worktree safety, artifact consistency, tool versions, dependency resolvability, Docker availability, current test collection, and exact allowed surface without changing code or configuration.

**Files / Modules:** Read-only inspection of repository rules, plan artifacts, pyproject/lock, Docker/CI, current memory/chat modules, and tests.

**Implementation Intent:** No implementation. Check Python/uv/Node/npm/Docker/Compose, `git status`, current branch, lock validity, proposed package metadata compatibility, Compose config, and pytest collection. Record baseline facts in `milestones/m0/MILESTONE_EXECUTION_REPORT.md` and update living sections.

**Tests / Checks:** `git status --short`, `git branch --show-current`, tool version commands, `uv lock --check`, current Compose `config --quiet`, `uv run --locked python -m pytest --collect-only -q`, frontend script listing, and safe configuration-key inspection without values.

**Expected Result:** No conflicting user edits in required files; prerequisites and current collection are known; proposed dependencies have a viable Python 3.12 path; no external provider call occurs.

**Stop Condition:** Required paths overlap unknown user changes; Docker/toolchain is unavailable; P0 decisions conflict; package resolution proves the selected architecture infeasible.

**Rollback Note:** Read-only except the milestone report and plan governance update; discard those documentation edits if needed.

**Handoff Evidence:** Exact commands/results, versions, collected test count, skips, config keys checked, blockers, and unchanged runtime files.

### Milestone 1: Characterization Contracts and Memory Evaluation Baseline

**Goal:** Lock current behavior and desired narrative bad cases before production changes.

**Files / Modules:** New/updated memory unit/contract/eval fixtures and tests, fake providers, spec milestone report; no production behavior change.

**Implementation Intent:** Add stable cases for Working State, compaction, candidate governance, retrieval, direct commands, ownership, evidence isolation, and trace fields. Use xfail only for explicitly missing target behavior with a reason/Issue reference; never hide setup failures.

**Tests / Checks:** Focused Ruff/Pyright; focused new pytest/eval cases; existing controlled conversation unit/contract regressions; secret/fixture review.

**Expected Result:** Current behavior and missing behaviors are reproducible. Tests fail/xfail only for intended gaps and pass for preserved contracts.

**Stop Condition:** Narrative expectation contradicts confirmed requirement; test harness cannot isolate paid providers; fixture would contain private/real data.

**Rollback Note:** Revert only new test/eval/report files; production remains unchanged.

**Handoff Evidence:** Case inventory, red/xfail reasons, preserved green contracts, commands/results, and dataset version.

### Milestone 2: Typed Memory Domain, Versioned Migrations, and Transactional Outbox Foundation

**Goal:** Establish the authoritative data model and transaction boundary needed by all later memory behavior.

**Files / Modules:** `Financial-MCP-Agent/src/memory` domain contracts/policy; new backend memory application/infrastructure boundaries; database models/Alembic; chat application/repository transaction integration; schema settings and Alembic dependency only; focused tests/docs.

**Implementation Intent:** Add typed Working State, events, summary metadata, profile/text record, candidate, audit, outbox task, provider-reference, command/retrieval/status/error contracts. Add expand-first Alembic revisions and replace new memory schema mutation through startup patching. Ensure foreground message/state/outbox rows share one transaction and services do not commit internally. Install Alembic only; explicitly defer redis-py to Milestone 4 and Mem0/pgvector SDKs to Milestone 6 so a dependency cannot activate the ungoverned legacy provider path.

**Tests / Checks:** Domain/contract tests; Alembic upgrade/downgrade/re-upgrade; existing-session readability; rollback/atomicity/idempotency/concurrency tests; `uv sync --locked`; Ruff/Pyright; focused and root database regressions.

**Expected Result:** PostgreSQL is the single authority; a failed foreground transaction leaves no orphan task/profile mutation; duplicate task keys are rejected deterministically.

**Stop Condition:** Migration cannot be downgraded/restored; existing session/message reads break; dependency resolution requires an unapproved platform change; internal commits cannot be removed without out-of-scope API changes.

**Rollback Note:** Revert milestone code/dependency lock and run the tested downgrade only against isolated development/test databases. Never downgrade production or user data in this plan.

**Handoff Evidence:** Schema revision graph, upgrade/downgrade output, transaction tests, exact dependencies, diff/secret review, and no external writes.

### Milestone 3: Working State, Token Budget, and Rolling Summary Mainline

**Goal:** Make session-scoped memory real in the active controlled workflow.

**Files / Modules:** Memory domain/application, controlled context/workflow, chat use case/repository, summary/model adapter, worker bootstrap, settings/prompts/schemas, focused tests/eval.

**Implementation Intent:** Extract and deterministically merge active entity, constraints, and temporary reply preference; persist versioned events; build protected recent raw tail; estimate budgets; enqueue compaction post-turn; validate structured summary; enforce source boundary/CAS/last-good fallback; construct stage-specific context that preserves current instruction precedence.

**Tests / Checks:** Working-state transitions, entity/constraint/preference regressions, token budget, compaction threshold/boundary/failure/stale task, context injection, planner/tool non-expansion, offline STM eval, integration and E2E slice.

**Expected Result:** Multi-turn STM persists and updates correctly; older content compacts without overwriting newer state; summary failure does not consume the foreground turn.

**Stop Condition:** State extraction changes route/tool behavior outside accepted cases; compaction can overwrite newer summary/state; context cannot stay within defined budget.

**Rollback Note:** Disable only the new STM integration seam and revert milestone changes; authoritative messages and prior schema remain readable. Do not restore the old profile-from-summary mutation.

**Handoff Evidence:** State-event examples using safe values, summary boundary/version evidence, eval results, trace stages, and revert check.

### Milestone 4: Redis Hot-State Cache and Worker Coordination

**Goal:** Add Redis acceleration and bounded coordination without making it authoritative.

**Files / Modules:** Redis adapter/ports/settings/bootstrap, application repositories/use cases, Docker/CI, fake/real integration tests, health/trace code.

**Implementation Intent:** Before changing Compose, resolve an obtainable immutable Redis 7.4 patch tag or image digest, record it with redis-py compatibility evidence, and use that reference in committed configuration. Then implement namespaced versioned cache-aside for Working State, recent tail/summary, and compact profile; TTL, invalidate-on-write, malformed/stale rejection, database fallback, single-flight/lease token rules, health status, and metrics. Use PostgreSQL tasks as durable truth.

**Tests / Checks:** Real Redis key/TTL/version/invalidation/isolation/corruption/outage tests; lease ownership/expiry; concurrent reads; Compose health/config; STM regression with Redis on/off.

**Expected Result:** Cache hits return the same authoritative version; stale/malformed data is ignored; stopping Redis causes explicit degradation but not foreground failure or state loss.

**Stop Condition:** Cache can serve a newer/older mismatched state without detection; Redis becomes required to recover task/state; cross-user keys collide.

**Rollback Note:** Remove Redis integration/Compose service or disable the cache seam; PostgreSQL behavior remains complete and cached keys may be safely discarded.

**Handoff Evidence:** Redis commands/tests, cache metrics/trace fields, outage proof, key namespace without real IDs, cleanup status.

### Milestone 5: Long-term Candidate Extraction and Governance

**Goal:** Build the controlled write path from user evidence to effective profile/text memory.

**Files / Modules:** Memory domain/application, extraction prompt/schema/model adapter, outbox worker, SQL repository, current profile/memory services/routes as needed, tests/eval/trace.

**Implementation Intent:** Extract typed candidates asynchronously from user-side evidence/state events; persist provenance/source versions; validate/dedupe/conflict; calculate deterministic promotion eligibility; keep high-impact profile inference confirmation-only; implement supersession/expiry/deletion/audit and stuck-task recovery. Explicit user commands use a separate direct-authority path with validation.

**Tests / Checks:** Candidate schema/provenance, assistant/tool poisoning, repeat/unique-session/active-day/recency/contradiction scoring, promotion/rejection/expiry, direct-confirmed profile, outbox crash/retry/idempotency, deletion and audit redaction, offline governance eval.

**Expected Result:** Unsupported content remains quarantined; only allowed candidates become active; profile and text memory boundaries match the interview narrative.

**Stop Condition:** Model text can bypass deterministic gates; assistant/tool results can become user-confirmed facts; retries duplicate effective memory; raw private evidence leaks to logs/audit.

**Rollback Note:** Stop governance workers/integration and reject new auto-promotions from the reverted `policy_version`. Records already auto-promoted under that policy are identified by `policy_version` and `activation_source`, immediately excluded by the integration seam when required, and reported for owner-scoped inspection/repair. User-confirmed writes remain authoritative and are not automatically undone by code rollback. Do not bulk-delete any non-test record.

**Handoff Evidence:** Candidate lifecycle matrix, provenance-negative tests, task recovery proof, prompt/schema versions, safe trace/audit samples.

### Milestone 6: Mem0/pgvector Index, Hybrid Retrieval, and Stage Injection

**Goal:** Make governed cross-session memory searchable and useful without creating a second authority.

**Files / Modules:** Mem0 provider adapter/settings/lifecycle, pgvector/migration/index configuration, retrieval application/domain policy, controlled context/rewrite/synthesis integration, worker reconcile/delete tasks, Docker/tests/eval.

**Implementation Intent:** Add and lock the Mem0/pgvector SDK dependencies only after a no-activation test proves the legacy client/worker cannot start outside the new governed bootstrap. Initialize one `AsyncMemory` per process; index promoted records with `infer=False`; store project memory/version/provider IDs; perform mandatory scoped Mem0 search plus PostgreSQL lexical recall; fuse/rerank, authoritatively post-filter, and token-pack results; inject only into allowed stages. Handle index lag, provider timeout, dimension/version mismatch, reconciliation, and delete retry.

**Tests / Checks:** Fake provider contract; real pgvector CRUD/filter/ownership; exact vs indexed query baseline before HNSW; hybrid retrieval/fusion/rerank; deleted/expired/conflicted suppression; cross-session eval; tool/evidence non-expansion; Mem0 outage degradation.

**Expected Result:** Relevant active user memories can be recalled across sessions; deleted/unauthorized/stale index rows never affect prompts; provider failure leaves foreground chat safe.

**Stop Condition:** Mem0 result cannot be mapped to authoritative record/version; tenant filtering is unreliable; embedding dimension migration is undefined; retrieval changes planner authorization.

**Rollback Note:** Disable semantic retrieval/index workers and fall back to PostgreSQL governed profile/lexical behavior. Derived vector rows can be rebuilt; never roll back authoritative records to match the index.

**Handoff Evidence:** Provider/version config, real pgvector lifecycle results, retrieval evaluation artifact, deletion/reconciliation proof, fallback traces.

### Milestone 7: Natural-language Memory Commands, API, and Frontend Controls

**Goal:** Let users manage memory from ordinary chat and existing memory UI with safe authorization and confirmation.

**Files / Modules:** Memory command domain/application, chat integration, memory routes/schemas, current frontend API/store/composables/components/chat view, focused frontend tests/browser path, docs.

**Implementation Intent:** Detect inspect/update/delete/forget commands before financial planning; validate typed target/scope/value; perform owner-scoped mutations; acknowledge exact effect and consistency state; refresh/invalidate frontend/Redis/provider projections. Ambiguous or broad destructive requests create a persisted pending command bound to authenticated `user_id`, `session_id`, normalized target scope, safe preview/count, command fingerprint, expected state version, and expiry. Confirmation is one-shot and idempotent, rejects replay/cross-user/cross-session/stale-version use, and is cancelled when it expires, the user cancels, or a new conflicting memory command supersedes it. REST and WebSocket presenters consume the same application result/status contract. Preserve ordinary finance queries and API compatibility.

**Tests / Checks:** Command classification/actions, profile/text updates, targeted deletion, pending-command TTL/fingerprint/version/one-shot/replay/cancellation, bulk confirmation, unauthorized/cross-user/cross-session attempts, REST/WS parity, ordinary-query non-mutation, API contract, frontend unit/type/lint/build, browser journey, controlled E2E.

**Expected Result:** The requested Chinese commands modify only the intended memory, are visible in UI/API, and affect later sessions after the defined consistency boundary.

**Stop Condition:** Ambiguous destructive text deletes immediately; UI and chat produce different authorities; auth scope can be bypassed; response/API compatibility breaks.

**Rollback Note:** Disable/revert chat command entry while retaining authenticated API/UI management and authoritative data. Revert additive UI/API changes without deleting stored records.

**Handoff Evidence:** User-journey screenshots or redacted browser trace, API contract results, frontend gates, ownership/confirmation negatives, rollback status.

### Milestone 8: Observability, Failure Hardening, and Offline Evaluation Gates

**Goal:** Make the complete foreground/background lifecycle diagnosable and regression-resistant.

**Files / Modules:** Existing trace/log adapters, memory instrumentation, worker metrics, redaction, eval runner/data, CI gates, failure tests, docs.

**Implementation Intent:** Finalize stable span/stage names and foreground/background links; record safe versions/status/counts/timing/errors; add cache/task/provider/retrieval/mutation metrics; redact private fields; cover dependency outage, retry exhaustion, stale work, partial delete, worker restart, and cleanup. Establish and document reproducible memory evaluation baseline before setting numeric gates.

**Tests / Checks:** Trace/log/redaction contracts; failure injection; full memory offline eval; root Python regression; frontend regression; CI parity; secret scan/diff review.

**Expected Result:** A turn and its background tasks can be replayed from safe trace metadata; known failures have explicit state/fallback; offline baseline artifact is reproducible.

**Stop Condition:** Required diagnosis needs raw private content in logs; a failure is silently reported as success; CI would invoke paid/live providers; numeric gate cannot be reproduced.

**Rollback Note:** Revert only new instrumentation/eval gates that are defective; never remove safety/failure behavior merely to restore green tests.

**Handoff Evidence:** Trace tree/stage inventory, redaction proof, failure matrix, baseline run metadata, cumulative offline commands/results.

### Milestone 9: Full Compose, Protected Live E2E, Documentation, and Delivery Closure

**Goal:** Prove the complete system through real deployment topology and reconcile code with every interview module.

**Files / Modules:** Docker/Compose/health/migrations/worker/frontend E2E, protected live workflow/test, cleanup tooling, README/CONTRIBUTING/spec mapping, PR evidence.

**Implementation Intent:** Start PostgreSQL/pgvector, Redis, backend, worker, frontend, and offline providers; run deterministic STM/LTM/mutation/deletion/failure/browser journeys; clean resources; then explicitly run the protected real LLM case and one read-only Tushare financial case using isolated memory identities. Fix only concrete failures. Produce final module evidence map and retrospective.

**Tests / Checks:** Full commands in Section 11, Compose config/up/down, health/readiness, browser/API journey, protected `live` command, cleanup/residual-data check, diff/secret scan, independent review, CI, and authorized Git delivery steps.

**Expected Result:** All required services are healthy; offline and live memory chains pass; test data is cleaned; interview claims are evidence-linked; no secret/private artifact is committed.

**Stop Condition:** Docker cannot pull approved images after documented mirror/retry handling; live endpoint is production-writing; isolated cleanup cannot be proven; two consecutive focused repair attempts fail; user has not authorized an external Git/merge/deploy action.

**Rollback Note:** Tear down Compose with volumes for the isolated test stack; revert the current milestone/PR; use previous verified commit/image. Do not deploy or alter production.

**Handoff Evidence:** Service health, exact test outputs, live provider/model identifiers without secrets, Tushare read-only proof, trace/artifact links, cleanup report, final mapping, independent review findings, CI/PR/merge status, and remaining risk.

## 13. Execution Protocol

- Execute exactly one milestone at a time.
- Start each milestone by restating its goal and allowed files.
- Run `git status --short` before editing and compare with the prior handoff.
- Do not overwrite, clean, reset, or revert unrelated user changes.
- Do not modify files outside the milestone's allowed surface.
- Use tests-first behavior characterization before production changes.
- Review the diff before running tests; run the narrowest relevant checks first, then milestone regressions.
- Do not move to the next milestone without reporting files, commands, results, blockers, rollback status, and governance updates.
- If a required change is outside scope, stop and update the plan/Decision Log before proceeding.
- If a check fails, inspect the narrowest logs and fix only the concrete issue.
- After two consecutive focused repair attempts fail, stop and produce `MILESTONE_EXECUTION_BLOCKED.md` with command, error, suspected cause, files touched, preserved state, and decision needed.
- Every completed milestone produces `docs/specs/memory-system-migration/milestones/mX/MILESTONE_EXECUTION_REPORT.md`.
- Never claim completion from skipped tests, module existence, or historical metrics.
- Default tests never access paid or production services. Live tests require the explicit marker/environment, safe namespace, bounded cost/rate, no production writes, redaction, and cleanup.
- Satisfy every category in Section 10 and report any `Not applicable` item explicitly.
- Update Progress, Decision Log, Surprises & Discoveries, and Outcomes & Retrospective after each milestone.
- GitHub Issue/branch/commit/push/PR/review/merge actions follow `AGENTS.md`; external mutations require the authorization applicable at execution time.

## 14. Rollback Plan

Before implementation, rollback is simply discarding the unexecuted plan. During implementation, each milestone is isolated so it can be reverted independently.

- Branch strategy: Keep specification on `docs/22-memory-migration-spec`. Each implementation milestone uses one Issue and a short `feat/`, `refactor/`, `test/`, or `chore/` branch from the then-current verified `main`.
- User changes: Record pre-milestone `git status`; never use destructive reset/checkout. If overlap occurs, stop rather than overwrite.
- Code rollback: Revert the milestone's narrow commit/PR. Do not revert unrelated files or later user work.
- Database rollback: Use only tested Alembic downgrade for isolated development/test databases. Prefer expand-first changes and leave old readable fields until final evidence. Never run destructive downgrade on production/user data.
- Dependency rollback: Restore the milestone's `pyproject.toml`/`uv.lock` and frontend package/lock pair together; rebuild containers from the prior lock.
- Redis rollback: Disable/remove cache integration and discard namespaced keys; PostgreSQL remains authoritative.
- Mem0/pgvector rollback: Disable derived semantic indexing/retrieval and rebuild later from authoritative records. Do not rewrite authoritative state from the vector index.
- Worker rollback: Stop worker containers after current tasks reach a known status; PostgreSQL tasks remain recoverable. Never acknowledge/drop unfinished durable tasks merely to roll back.
- Config rollback: Restore safe example/Compose settings from the previous verified milestone. Real local `.env` is not modified by implementation.
- Frontend/API rollback: Revert additive UI/API behavior while preserving stored data and existing compatible endpoints.
- Stop instead of continuing when authorization/ownership, migration safety, secret isolation, provider side effects, or cleanup scope cannot be proven.

## 15. Progress

- [x] Milestone 0: Safety, Toolchain, Dependency, and Baseline Check
  - Completed: 2026-08-24
  - Evidence: `uv lock --check`, both Compose config checks, and `uv run --locked python -m pytest --collect-only -q` succeeded; 128/133 tests collected and 5 live tests were deselected.
- [ ] Milestone 1: Characterization Contracts and Memory Evaluation Baseline
- [ ] Milestone 2: Typed Memory Domain, Versioned Migrations, and Transactional Outbox Foundation
- [ ] Milestone 3: Working State, Token Budget, and Rolling Summary Mainline
- [ ] Milestone 4: Redis Hot-State Cache and Worker Coordination
- [ ] Milestone 5: Long-term Candidate Extraction and Governance
- [ ] Milestone 6: Mem0/pgvector Index, Hybrid Retrieval, and Stage Injection
- [ ] Milestone 7: Natural-language Memory Commands, API, and Frontend Controls
- [ ] Milestone 8: Observability, Failure Hardening, and Offline Evaluation Gates
- [ ] Milestone 9: Full Compose, Protected Live E2E, Documentation, and Delivery Closure

## 16. Decision Log

| Date | Decision | Reason | Source |
| --- | --- | --- | --- |
| 2026-08-24 | Deliver the full STM/LTM/Redis/Mem0/pgvector/control/E2E program | Explicit user authorization; minimal slice no longer sufficient | User decision, REQUIREMENT_SPEC |
| 2026-08-24 | Select structured consolidation, not current-service wiring or platform replacement | Meets complete scope while preserving verified mainline | SOLUTION_TRADEOFF |
| 2026-08-24 | PostgreSQL is authoritative; Redis and Mem0 are derived/rebuildable | Prevents dual authority and enables transactional/auditable behavior | Clarification P1-01/02 |
| 2026-08-24 | Use PostgreSQL outbox claiming; do not use Redis Streams as primary durability | Foreground transaction already belongs to PostgreSQL | PostgreSQL evidence, SOLUTION_TRADEOFF |
| 2026-08-24 | Promoted Mem0 writes use inference disabled | Project candidate governance must own add/update/delete authority | Mem0 source evidence, memory safety contract |
| 2026-08-24 | Add Alembic for new persisted contracts | Current startup DDL is not reviewable/rollback-safe | CODEBASE_RECON, Alembic evidence |
| 2026-08-24 | Default CI remains offline; final protected live is mandatory | Controls cost/production risk while proving real provider behavior | User decision, AGENTS.md |
| 2026-08-24 | Controlled conversation is mandatory public E2E; report mode shares contracts only | Avoids duplicate runtime while matching immediate target | Clarification P1-05 |
| 2026-08-24 | Keep frontend unit/browser testing in scope and add it only in the owning milestone | Current frontend exposes lint/type/build but no test script; memory commands need UI evidence | Milestone 0 inspection |
| 2026-08-24 | Treat Docker registry access as an explicit pre-Compose risk rather than a passed prerequisite | Docker daemon works, but a non-pulling Redis manifest request did not complete in the 30-second inspection window | Milestone 0 inspection |
| 2026-08-24 | Correct the controlled stage order to `entity -> route -> rewrite` and prohibit formal LTM before route | The previous plan text contradicted the production workflow and could misplace Context Gateway ownership | PR #23 independent review |
| 2026-08-24 | Install Alembic, redis-py, and Mem0/pgvector only in their owning milestones | Installing Mem0 in M2 could activate the ungoverned legacy provider path before ownership/filter controls exist | PR #23 independent review |
| 2026-08-24 | Freeze controlled conversation as the only runtime acceptance path; report mode shares contracts/repositories only | Removes a contradiction between complete acceptance and deferred report E2E | PR #23 independent review |
| 2026-08-24 | Freeze the field-level authority/auto-promotion matrix | Schema and promotion work must not invent product/safety decisions during implementation | PR #23 independent review |
| 2026-08-24 | Use zero-error gates for maintained/changed scope and baseline-diff scans for untouched repository debt | Full scans currently contain 81 Ruff and 80 Pyright errors tracked by Issue #20 | PR #23 independent review / Issue #20 |
| 2026-08-24 | Keep real holdings/positions exclusively in the Portfolio/account domain | Memory must not become a second authority for account facts; only labelled, expiring user-reported context is permitted | PR #23 second independent review |
| 2026-08-24 | Freeze development retention defaults while deferring production legal/SLA policy | Reproducible tests need concrete values, but the project cannot invent compliance guarantees | PR #23 second independent review |
| 2026-08-24 | Model memory commands as a branch before the ordinary controlled workflow | Mutation/confirmation must not accidentally continue into financial planning, while ordinary requests retain permission/validation/controller stages | PR #23 second independent review |

## 17. Surprises & Discoveries

| Finding | Impact | Action |
| --- | --- | --- |
| Current `mem0ai` is absent from the lock and silently degrades to Noop | Existing memory UI/tasks may imply storage that is not active | Add explicit dependency/readiness/contract verification before claiming provider availability |
| Current profile mutation and LTM task enqueue commit separately | Claimed transactional outbox behavior is false | Move commit ownership to application transaction in Milestone 2 |
| Controlled chat loads a profile but does not inject it into workflow | Current LTM is returned metadata, not active personalization | Integrate only through governed Context Gateway |
| STM worker starts under a flag but active chat does not enqueue compaction | Rolling Summary lifecycle is dormant | Add post-turn durable task in Milestone 3 |
| Historical Redis assets do not prove an STM cache path | Cannot claim Redis migration by copying files | Implement/test cache-aside from contracts in Milestone 4 |
| Mem0 supports rich filters but provider semantics differ | Filter presence alone is insufficient tenant proof | Validate actual pgvector filters and post-authorize every result |
| Current Langfuse dependency is v2 while current docs describe newer OTel-native SDKs | A broad observability upgrade would expand risk | Preserve existing adapter; stabilize project trace schema without major upgrade |
| Frontend `package.json` has no unit or browser E2E command | API-only testing would not prove the requested dialogue-box workflow | Add focused Vitest/Vue tests and one Playwright journey in Milestone 7, then wire the gate in Milestone 8/9 |
| Docker Engine/Compose are available, but Docker Hub manifest inspection stalled | Later image pulls may repeat the user's prior authorization/network failure | Recheck registry access at the first milestone that changes Compose; prefer pinned images and document a registry mirror/local-cache fallback without changing real Docker settings silently |
| Test collection reports a Starlette/httpx deprecation warning | Baseline is usable but future dependency changes could turn it into a failure | Track the warning; do not broaden Milestone 0 into an unrelated dependency upgrade |
| Independent review found five P1 and three P2 contract gaps before merge | The plan was not yet safely executable despite green CI | Correct stage order, dependency timing, report scope, authority matrix, static gates, data rollback, pending-command state, and immutable Redis image requirements in PR #23 |

## 18. Outcomes & Retrospective

- What changed: Planning and Milestone 0 documentation only; no runtime, dependency, database, API, Docker, frontend, or secret file changed.
- What was verified: Branch/worktree baseline, Python/uv/Node/npm/Docker/Compose availability, current lock validity, both Compose schemas, safe example-key inspection, frontend script inventory, Python 3.12 package-metadata viability, and pytest collection. No test body or external provider was executed.
- What remains risky: Combined dependency resolution is deferred to the dependency-owning milestone; Docker Hub reachability was not confirmed within 30 seconds; provider compatibility, migrations, concurrency, deletion reconciliation, extraction quality, and live cleanup remain unimplemented.
- What should be improved next: Execute Milestone 1 only to lock memory characterization and offline evaluation cases before production behavior changes.

## 19. Deferred Work

- Standalone/shared Mem0 HTTP platform and independent service scaling.
- Redis Streams/Kafka/Celery as primary job durability.
- LangGraph runtime/checkpointer replacement.
- Multi-region, autoscaling, production backup/restore automation, and compliance certification.
- Report-mode memory injection and full report-mode E2E; both require a later separately scoped milestone.
- Broad Langfuse major upgrade.
- Numeric quality/performance/resume claims before target baselines.
- User memory export format.
- Production deployment and production user-data migration.

## 20. Handoff to Small-step Implementation

Milestone 0 is complete. The first unchecked milestone is Milestone 1. Execute only its characterization contracts and memory evaluation baseline, keep production behavior unchanged, produce the M1 execution report, update Sections 15-18, and stop before Milestone 2.
