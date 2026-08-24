# CODEBASE_RECON.md

## 1. Reconnaissance Target

Requirement source: `docs/specs/memory-system-migration/REQUIREMENT_SPEC.md`

Focus areas:

- `短期记忆.md` 与 `长期记忆.md` 中 20 个需求模块的当前代码证据。
- `Finance-agent-Skills` 的真实 REST/WebSocket 入口、受控工作流、持久化、配置、前端、测试和 Trace。
- 历史 `Finance` 仓库中可作为迁移证据的 STM、working state、LTM、候选池和 Redis 资产。
- 识别 active、partial、dormant、historical-only、document-only 和 conflicting behavior。
- 确定后续澄清与方案比较需要关注的边界，不制定最终实现计划。

Out-of-scope reminders:

- 本阶段未修改业务代码、数据库、配置或测试。
- 本阶段未运行测试、Docker、模型、Tushare、Mem0、Redis 或任何生产服务。
- 历史仓库和面试文档不是当前实现真相源。
- 本文不选择最终存储、缓存、队列、检索组件或文件级实施方案。

## 2. Project Overview

Project type: Confirmed — full-stack financial Agent application with a controlled multi-stage conversation workflow, REST/WebSocket APIs, persistence, financial tools, offline evaluation, optional live E2E, and legacy memory/report paths.

Languages: Confirmed — Python 3.12 target; TypeScript/Vue frontend; SQL and YAML configuration.

Frameworks: Confirmed — FastAPI, SQLAlchemy async, Pydantic v2, Vue 3/Pinia/Vite, LangChain/OpenAI-compatible provider adapters, Tushare, optional Langfuse. Historical/dormant code references Mem0 and pgvector.

Runtime / package manager: Confirmed — `uv` with `pyproject.toml`/`uv.lock`; frontend uses npm and `package-lock.json`; Docker Compose is provided.

Main service type: Confirmed — FastAPI application in `backend/main.py`.

Frontend/backend split: Confirmed — `frontend/` calls `/api` REST endpoints and `/api/chat/stream` WebSocket; `backend/` owns authentication, application use cases, persistence, workers, and provider adapters.

Test framework: Confirmed — pytest, Ruff, Pyright, ESLint, Vue TypeScript checks, Docker Compose E2E, and data-driven offline eval smoke suites.

Deployment clues: Confirmed — Docker Compose contains PostgreSQL/pgvector, backend, frontend, and pgAdmin. The main Compose file has no Redis service. CI has deterministic offline jobs and a manual protected live job with memory and STM explicitly disabled.

Confirmed facts:

- The only maintained public chat path is `backend.routers.chat -> ControlledChatUseCase -> ControlledConversationWorkflow`.
- The target repository already contains legacy/dormant STM and LTM services, but the controlled use case does not call their complete lifecycle.
- `PreparedChatTurn.memory_profile` is loaded when `ENABLE_MEMORY=true` and returned to the client, but it is not passed into `ControlledConversationWorkflow.run`; it cannot currently influence controlled-workflow route, plan, or synthesis.
- `SqlAlchemyConversationRepository.save_result` refreshes token metrics but does not call `maybe_enqueue_compaction`; therefore the controlled chat path does not create STM compaction tasks.
- `ENABLE_STM` starts `stm_compaction_worker`, but a running worker without an enqueue call does not provide automatic compaction for the controlled chat path.
- `mem0ai` is not declared in the locked project dependencies. `mem0_client.py` therefore deliberately falls back to `NoopMem0Client` unless an undeclared external installation exists.
- No Redis dependency or Redis service exists in the target repository.
- The target repository has no Alembic migration directory; startup uses `create_all` plus best-effort `ALTER TABLE` statements whose exceptions are swallowed.
- Default CI and protected live E2E both run with `ENABLE_STM=false` and `ENABLE_MEMORY=false` in their Compose/live environments.

Assumptions:

- Assumption: The current branch is for specification/reconnaissance only; later code milestones will use separate implementation branches or an explicitly approved continuation.
- Assumption: Existing production-like data may use either SQLite or PostgreSQL because both paths remain in code; later clarification must select the supported migration baseline.

## 3. Directory Structure Summary

| Path | Apparent role | Relevance | Notes |
| --- | --- | --- | --- |
| `backend/routers/chat.py` | REST/WS chat protocol adapter | Critical | Confirmed thin entry into the controlled use case. |
| `backend/application/chat/` | Chat application contracts and use cases | Critical | Confirmed single orchestration owner around workflow and transaction. |
| `backend/infrastructure/chat/` | SQLAlchemy, model/tool, and trace adapters | Critical | Current memory inputs are loaded in the repository, but only recent messages/summary reach the workflow. |
| `Financial-MCP-Agent/src/conversation/` | Typed controlled conversation domain/workflow | Critical | Current production workflow owner; has context, entity, route, rewrite, plan, evidence, controller, and synthesis boundaries. |
| `backend/services/stm_*` | Legacy/dormant STM budgeting and compaction worker | Critical | Partly implemented but not enqueued by the controlled chat path. |
| `backend/services/memory_service.py` | FastAPI-facing memory facade | Critical | Delegates to Agent-side `MemoryService`; includes profile and memory-item CRUD. |
| `Financial-MCP-Agent/src/memory/` | Mem0 client, service, worker, prompts, schema | Critical | Legacy LTM implementation with optional Noop fallback and mixed DB access styles. |
| `backend/db/models.py` | Current ORM persistence models | Critical | Sessions/messages/summaries/profile/STM task/LTM task exist; no current working state or candidate tables. |
| `backend/db/database.py` | Engine, sessions, startup schema creation | Critical | Uses `create_all` and swallowed incremental DDL; no versioned migration chain. |
| `backend/routers/memory.py` | Profile/memory CRUD API | High | Authenticated user-scoped endpoints exist, but several semantics conflict with the target narrative. |
| `frontend/src/components/memory/` | Profile and memory sidebar UI | Medium | Profile edit, items, and clear-all UI exist; no verified candidate review or evidence UI. |
| `tests/evals/` | Offline controlled-chain evals | High | Entity/rewrite/mainline assets exist; no multi-turn STM or cross-session LTM evaluation set. |
| `tests/e2e/` | Controlled and Compose E2E | High | Memory/STM are disabled in available live/offline stacks. |
| `.github/workflows/` | CI and protected live E2E | High | Strong base pipeline but no active memory feature gate. |
| `D:/FinanceProject/Finance/backend/services/working_state.py` | Historical working-state store | Historical evidence | Has state/event persistence but untyped fields and simplistic merge/version behavior. |
| `D:/FinanceProject/Finance/backend/services/stm_summary_runtime.py` | Historical STM runtime | Historical evidence | Large monolith with schema gate, fallback, preflight, CAS-like operations, and tests. |
| `D:/FinanceProject/Finance/backend/services/chat/` | Historical chat orchestration modules | Historical evidence | More memory integration exists, but it is not the target workflow and contains narrative conflicts. |
| `D:/FinanceProject/Finance/Financial-MCP-Agent/src/memory/` | Historical LTM/candidate extensions | Historical evidence | Candidate pool/dedupe/audit code exists behind flags; Deep promotion is not complete. |
| `D:/FinanceProject/Finance/backend/integrations/redis/` | Historical generic Redis infrastructure | Historical evidence | Key builder/cache/lock/metrics are tested; STM keys are not connected to STM reads/writes. |
| `D:/FinanceProject/Finance/migrations/004_memory_candidates_and_audit.sql` | Historical candidate schema | Historical evidence | PostgreSQL-only SQL, not represented in target ORM/migrations. |

## 4. Entry Points

### 4.1 Startup Entry

Confirmed startup:

```text
backend/main.py::lifespan
-> init_db() using create_all + best-effort column DDL
-> initialize_trace_runtime()
-> optional seed authentication accounts
-> if ENABLE_MEMORY: init_mem0_client() + start ltm_worker_loop()
-> if ENABLE_STM: start stm_compaction_worker_loop()
-> serve FastAPI routes
```

Important distinction: worker startup is confirmed; useful foreground-to-worker task creation is not confirmed for the controlled chat path.

### 4.2 Request / Task Entry

Confirmed controlled chat:

```text
POST /api/chat/message or WebSocket /api/chat/stream
-> backend.routers.chat
-> backend.application.chat.factory.build_chat_use_case
-> ControlledChatUseCase.execute
-> SqlAlchemyConversationRepository.prepare_turn
-> ControlledConversationWorkflow.run
-> SqlAlchemyConversationRepository.save_result
-> commit once
-> REST/WS response mapping
```

Confirmed memory management API:

```text
/api/memory/*
-> require_query_user (JWT user must equal requested user_id)
-> backend.services.memory_service
-> Agent-side MemoryService
-> user_invest_profiles and/or ltm_write_tasks and/or direct Mem0 call
```

Dormant STM task path:

```text
maybe_enqueue_compaction (no controlled-chat caller found)
-> stm_compaction_tasks
-> stm_compaction_worker_loop
-> LLM summary
-> messages.is_compressed + sessions.running_summary + session_summaries
-> optional inferred profile extraction
```

Partial LTM task path:

```text
explicit profile/cold-start or dormant summary extraction
-> ltm_write_tasks
-> ltm_worker_loop
-> Mem0 add/update/delete
```

## 5. Relevant Call Chain

```text
Authenticated REST / WebSocket input
-> ControlledChatUseCase
-> transaction prepares Session + current user Message
-> uncompressed recent-message tail + current running_summary
-> ContextBuilder produces one generic ContextPacket
-> current deterministic entity resolver
-> route -> rewrite -> permission -> plan -> validate
-> execute -> verify -> bounded controller/replan -> synthesis
-> assistant Message + context counters
-> single transaction commit
-> API/WS result and controlled-workflow trace
```

Confirmed segments:

- Current message, recent uncompressed messages, and `running_summary` enter the workflow.
- Current entity resolver supports a small code-local catalog, explicit codes, several aliases, “平安” ambiguity, fund-concept non-inheritance, and follow-up inheritance from recent raw messages.
- Current rewrite extracts constraints and reply preferences only from the current message.
- `ContextPacket.confirmed_constraints` exists but is never populated by `ContextBuilder`.
- The profile snapshot is returned in `ChatOutcome` but not consumed by workflow stages.

Inferred segments:

- Existing STM/LTM files were carried forward from an older architecture and retained for UI/report or future activation, but were not reconciled during the controlled-workflow cutover.
- Feature flags can make workers appear enabled while the primary chat lifecycle remains disconnected.

Unknown segments:

- Whether any external deployment installs `mem0ai` outside the lockfile.
- Whether production data relies on direct startup DDL behavior or an external migration process not committed to the repository.
- Whether any deployment outside the committed Compose/CI files calls `maybe_enqueue_compaction` or legacy Agent graph memory nodes.

### 5.1 Module-by-module narrative-to-code mapping

Status terms: `Active` means reached from the maintained controlled entry; `Partial` means some behavior exists but the full contract does not; `Dormant` means code exists without a maintained mainline caller; `Missing` means no suitable target implementation was found; `Conflict` means existing behavior contradicts the approved narrative.

| Requirement module | Target repository evidence | Historical `Finance` evidence | Status and gap |
| --- | --- | --- | --- |
| STM-01 Preflight/context budget | `token_counter.py`, `stm_context_service.py`, session token fields | Historical preflight and `stm_summary_runtime.py` include richer thresholds | Partial/Dormant — metrics refresh is active after a turn, but preflight decision/enqueue is not called before workflow execution. |
| STM-02 Recent raw tail | Repository loads `settings.stm_keep_recent` uncompressed messages; `ContextBuilder` applies another last-six bound | Historical defaults and docs vary between 6 and 10 | Active/Partial — bounded tail works, but “turn” vs “message” semantics and double trimming are inconsistent; configured default is 4, not the narrative 10. |
| STM-03 Rolling summary/compaction | Worker, task, summary snapshot, version-before check | Historical 1,831-line runtime has schema gate, fallback, chunking, audit, and CAS helpers | Partial/Dormant — no enqueue from controlled chat; current worker has no summary schema/quality gate, last-good status, safe fallback, or commit-time CAS recheck. |
| STM-04 Typed working state | No current session working-state fields or typed domain model | `working_state.py`, `WorkingStateEvent`, session JSON fields | Missing — historical state is `dict[str, Any]`, with no typed scope/action contracts. |
| STM-05 Entity inheritance | Current `AuthoritativeEntityResolver` is active and precedes route | Historical `entity_resolver_v2`, `working_state`, hot-summary entity logic | Active/Partial — correct workflow position exists, but catalog is small/static and inheritance reads raw history rather than a versioned confirmed entity. |
| STM-06 Constraints/preferences | Current deterministic extractors run after route and read current message | Historical post-rewrite concurrent extractors persist to working state | Partial — no persisted scope, add/override/clear/expire semantics, source evidence, or session-segment inheritance. |
| STM-07 Merge/version/audit | No current working-state persistence | Historical state version/event table and field upserts | Missing — historical code always increments on write, lacks typed local merge actions and request-level optimistic concurrency. |
| STM-08 Context Gateway | One minimal `ContextBuilder`; controlled stages pass typed results | Historical route/answer summary slices and context strings | Partial — no per-stage memory retrieval/injection, token/drop policy, or drop trace. Historical path injects profile into route and sometimes passes “full LTM,” conflicting with the newer narrative. |
| STM-09 Hot-state cache | No Redis package, service, config, or dependency | Generic Redis client/cache/envelope/key/lock/metrics with STM key names | Missing — historical Redis is used for report concerns; no STM state/tail/summary cache-aside call path was found. |
| STM-10 Eval/observability | Entity/rewrite/mainline eval assets; controlled trace has `context` stage | Historical STM runtime and working-state tests | Partial — no current multi-turn state-transition dataset, compaction tests, cache tests, or memory-specific trace grading. |
| LTM-01 Boundary/precedence | Profile table plus Mem0 service; profile not consumed by current workflow | Historical memory prompt and full-LTM injection | Conflict — current profile includes `constraints` and `response_pref`; inferred code may directly mutate authoritative fields; no enforced runtime precedence. |
| LTM-02 Confirmed structured profile | Profile table, authenticated CRUD UI/API, cold start | Same with more integrations | Partial/Conflict — no `profile_version` or confirmation workflow; response preference is stored as authoritative; horizon update also writes minimum return as `0`. |
| LTM-03 Durable scheduling | `ltm_write_tasks` and polling worker | Historical worker adds stale recovery and more governance | Partial — current helper commits profile and task separately, so it is not a transactional outbox; task schema lacks idempotency, next retry, lock lease, trace, source versions, and dead-letter status. |
| LTM-04 Candidate/evidence gate | No target candidate table; evidence endpoint has a TODO | Historical migration, candidate pool, audit logs, evidence metadata | Missing — historical candidate code records metadata but does not establish the full user-source/schema gate described by the documents. |
| LTM-05 Deep governance | Not found | Historical fingerprint/semantic dedupe, conflict groups, manual accept/reject/delete, auto-forget, metrics | Missing — no daily Deep scoring using occurrences, unique sessions/queries, active days, contradiction, or automatic bounded promotion. Historical tests only verify disabled guards. |
| LTM-06 Storage/retrieval | Optional Mem0/pgvector code; structured profile SQL | Historical service adds candidate CRUD but same semantic search core | Partial — `mem0ai` is not locked; retrieval is vector search plus client-side category/source/active checks, not metadata + lexical + vector + rerank; no topic/entity/task/time scope. |
| LTM-07 Conflict/freshness/forgetting | Memory-item delete enqueue and direct delete-all/profile reset | Historical candidate status/conflict/auto-forget helpers | Partial/High risk — memory-item ID ownership is not verified before update/delete; delete-all can partially succeed; no retrieval-wide versioned invalidation or deletion consistency test. |
| LTM-08 Stage-specific injection | Profile loaded but not passed to workflow | Historical route receives profile summary and later stages can receive full LTM | Missing/Conflict — current path has no personalization effect; historical path risks route pollution and has no Context Gateway budget. |
| LTM-09 User control/privacy | Profile edit, memory list/add/update/delete/all-clear APIs and sidebar | Historical candidate service methods exist but no matching router/UI was found | Partial — authentication validates requested user ID, but candidate review/evidence are incomplete; no memory projection, data classification, profile version, or complete deletion audit. |
| LTM-10 Eval/observability | No target memory tests/evals; worker/service logs exist | Historical governance metrics and two guard tests | Missing — no extraction/retrieval/promotion/deletion evaluation, no accepted baseline, and memory stages are absent from controlled trace events. |

## 6. Related Files

### 6.1 Definitely Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/application/chat/contracts.py` | Application boundary | Future prepared memory/state snapshot must remain protocol-independent | Clarify/freeze contract evolution | High |
| `backend/application/chat/use_case.py` | Single chat orchestrator | Correct owner for foreground transaction and post-commit handoff | Preserve single owner | High |
| `backend/infrastructure/chat/repository.py` | Durable chat adapter | Loads tail/summary/profile and writes messages/counters | Characterize transaction and concurrency | High |
| `Financial-MCP-Agent/src/conversation/contracts.py` | Typed workflow contracts | Natural owner for typed current-turn memory inputs | Extend only after compatibility design | High |
| `Financial-MCP-Agent/src/conversation/context.py` | Context construction | Current generic packet and current-turn precedence | Compare stage-specific options | High |
| `Financial-MCP-Agent/src/conversation/entity.py` | Active entity resolution | Already before route and contains useful safe-inheritance tests | Preserve behavior while changing source | High |
| `Financial-MCP-Agent/src/conversation/rewriting.py` | Current constraints/preferences | Current-turn extractors already in correct general stage | Reconcile persistence/scope | High |
| `backend/db/models.py` | Persisted session/profile/task models | Any migration changes durability and rollback | Explicit approval and migration design | High |
| `backend/db/database.py` | Startup schema behavior | Current DDL has no reliable rollback/history | Replace/contain through solution design | High |
| `backend/config.py` | Typed settings | Feature flags, budgets, provider settings, secret defaults | Validate and document future settings | High |
| `backend/services/stm_context_service.py` | Budget/enqueue helper | Contains reusable token/cutoff logic but is disconnected | Characterize before reuse | Medium |
| `backend/services/stm_compaction_worker.py` | Current summary worker | Contains task claim/process/write lifecycle | Redesign quality/concurrency boundary later | High |
| `backend/services/stm_compaction_support.py` | Summary prompt/model/profile hook | Contains prohibited direct inferred-profile path | Remove or replace in later milestone | High |
| `backend/services/memory_service.py` | Memory API facade | Public behavior and logs depend on it | Split responsibilities later | High |
| `Financial-MCP-Agent/src/memory/memory_service.py` | Current LTM service | Mixes DB modes, CRUD, retrieval, task enqueue, commits | Do not copy forward unchanged | High |
| `Financial-MCP-Agent/src/memory/ltm_worker.py` | Current LTM worker | Background reliability and provider calls | Redesign task contract later | High |
| `Financial-MCP-Agent/src/memory/mem0_client.py` | Provider adapter | Optional missing dependency and configuration | Tradeoff required | High |
| `backend/routers/memory.py` | Public user controls | API/auth/deletion compatibility | Contract and security review | High |
| `backend/schemas/memory.py` | Public schemas | Current mutable/unbounded metadata and profile boundaries | Version/validation clarification | High |
| `frontend/src/api/index.ts` | Frontend API contract | Existing profile/item calls must remain coherent | Verify later integration | Medium |
| `frontend/src/composables/useMemory.ts` | UI use-case wrapper | Existing user controls and optimistic errors | Candidate/evidence UX clarification | Medium |

### 6.2 Probably Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `Financial-MCP-Agent/src/tools/skill_trace.py` | JSONL/exporter trace | Has unused memory enqueue helpers and redaction rules | Add stable memory events later | High |
| `backend/infrastructure/chat/trace.py` | Workflow-to-trace adapter | Must correlate memory decisions with current run | Preserve low-cardinality fields | Medium |
| `backend/services/token_counter.py` | Token estimation | STM trigger and stage budgets depend on it | Validate model/budget semantics | Medium |
| `backend/routers/user.py` | Cold-start entry | Can create confirmed profile/outbox tasks | Reconcile authoritative write path | High |
| `frontend/src/components/memory/` | User profile/memory controls | Required inspect/edit/delete behavior partly exists | Verify product scope | Medium |
| `tests/evals/entity/` | Entity baseline | Can seed multi-turn STM cases | Extend later without changing old gold silently | Low |
| `tests/evals/rewrite/` | Constraint/preference baseline | Contains representative single-turn cases | Extend to state transitions | Low |
| `tests/e2e/test_controlled_chat_chain.py` | Application E2E | Natural non-provider memory flow location | Candidate later | Medium |
| `tests/e2e/test_offline_compose_stack.py` | Full stack E2E | Current Compose proof with memory disabled | Candidate later | High |

### 6.3 Supporting Context

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `.github/workflows/ci.yml` | Default quality gates | Establishes offline-safe checks | Add memory gates only after tests exist | Medium |
| `.github/workflows/live-e2e.yml` | Explicit live gate | Correct place for opt-in model/Tushare verification | Keep memory data isolated | High |
| `docker/docker-compose.yml` | Main local stack | pgvector present; Redis/Mem0 package absent | Infrastructure tradeoff later | High |
| `docker/docker-compose.offline.yml` | Isolated E2E stack | Memory/STM explicitly disabled | Extend only with fake/local providers | Medium |
| `backend/.env.example` | Configuration documentation | STM defaults and prose already disagree | Correct after decisions freeze | Medium |
| `docs/股票Agent项目技术总览.md` | Current repo narrative | Claims memory components but not their active connectivity | Update only with verified results | Medium |

### 6.4 Out of Scope

| Path / Area | Reason |
| --- | --- |
| Real `.env` files | Contain secrets; values are unnecessary for read-only architecture reconnaissance. |
| Tushare tool internals | Memory must not change financial evidence behavior in this analysis stage. |
| Report generation internals | Relevant later only if shared memory ownership is approved. |
| Historical `Reference/` vendor/open-source copies | Not part of the target repository and not required to establish current behavior. |
| Build outputs, logs, reports, caches, virtual environments | Generated artifacts; must not become implementation evidence. |

## 7. Existing Patterns to Reuse

| Pattern | Example file | Why reuse it |
| --- | --- | --- |
| One public chat use case for REST and WS | `backend/application/chat/use_case.py` | Prevents a second memory orchestration path. |
| Typed immutable workflow contracts | `Financial-MCP-Agent/src/conversation/contracts.py` | Strong base for current-turn memory/state contracts and stable enums. |
| Current-turn-first context object | `Financial-MCP-Agent/src/conversation/context.py` | Correct safety principle even though stage-specific assembly is incomplete. |
| Entity resolution before routing | `Financial-MCP-Agent/src/conversation/workflow.py` | Matches the required controlled chain and should remain authoritative. |
| Bounded controller/replan loop | `Financial-MCP-Agent/src/conversation/workflow.py` | Memory must not introduce an unbounded Agent loop. |
| Single foreground DB commit | `ControlledChatUseCase.execute` | Useful transaction owner; background publication must respect post-commit/outbox semantics. |
| Auth user equality check | `backend/middleware/auth.py::ensure_user_access` | Correct tenant-boundary pattern for public memory APIs. |
| Stable workflow event contracts and redaction | `skill_trace.py`, `backend/infrastructure/chat/trace.py` | Reusable for safe memory observability. |
| Offline fixtures plus explicit protected live marker | `tests/evals/`, `tests/e2e/test_live_controlled_chat_chain.py` | Matches cost-safe default and opt-in real-provider validation. |
| Historical CAS/schema/fallback tests as characterization evidence | `Finance/tests/test_stm_summary_runtime.py` | Useful cases to port selectively, not proof that target behavior works. |
| Historical candidate status/audit concepts | `Finance/migrations/004_memory_candidates_and_audit.sql` | Provides vocabulary for candidate governance after schema redesign. |
| Historical Redis envelope/version API | `Finance/backend/integrations/redis/cache_service.py` | May be reusable if cache is later justified; it is not an STM implementation by itself. |

## 8. Data Flow and State

### 8.1 Input Data

- Confirmed chat inputs: authenticated `user_id`, message, optional session/request/explicit-skill identifiers.
- Confirmed profile inputs: risk, sectors, expected return range, horizon, response preference, arbitrary memory category/content/metadata.
- Risk: public memory metadata is currently an unbounded dictionary; profile enum descriptions are not consistently enforced by validators.
- Risk: historical LTM extraction reads user and assistant messages and summary text; this contradicts the desired user-evidence boundary.

### 8.2 Intermediate State

- Active workflow: `ConversationRunContext`, `ContextPacket`, entity result, route, rewrite, permissions, plan, evidence, verification, controller decision, answer context.
- `ContextPacket` currently contains current message, recent messages, optional running summary, and an unused confirmed-constraints tuple.
- No active typed `WorkingState` spans requests.
- Existing legacy `AgentState` and `memory_nodes.py` belong to report/old graph code, not the maintained controlled chat workflow.

### 8.3 Persistent State

- Current `sessions`: summary text/version, token counts/budget, compression status, turn count, timestamps.
- Current `messages`: role/content/token count/compressed/LTM-used flags.
- Current `session_summaries`: summary snapshots and approximate compressed range metadata.
- Current `stm_compaction_tasks`: minimal pending/running/done/failed task data.
- Current `user_invest_profiles`: profile plus constraints and response preference, without profile version.
- Current `ltm_write_tasks`: JSON text payload and minimal status/retry/error timestamps.
- Not found in target: working-state JSON/event tables, memory candidates/audit tables, memory version, deletion tombstone contract, or cache state.

### 8.4 Output Data

- Chat response: reply, session ID, memory profile snapshot, context window.
- Workflow result: typed status, trace/run IDs, entity/route/rewrite/plan/evidence/controller/synthesis state.
- Memory APIs: structured profile, memory items, CRUD acknowledgements, incomplete evidence response.
- Background outputs: summary snapshots, Mem0 items, worker logs. No stable memory execution report artifact was found.

### 8.5 Potential Data Mismatch Points

1. Repository loads `memory_profile`, but use case does not pass it to workflow.
2. `stm_keep_recent` is 4 messages, `.env.example` prose says 10 rounds, ContextBuilder independently caps at 6 strings, and interview narrative says 10 turns.
3. Context usage is refreshed after reply, while intended Preflight requires a before-stage projection.
4. Current summary worker checks `summary_version_before` before the LLM call but does not enforce the same condition atomically in the final update.
5. Summary text has no schema/quality status; failed/unsupported candidates cannot be distinguished from last-good summaries.
6. Profile and outbox helpers commit internally and separately, violating the claimed “same transaction” outbox property.
7. `update_horizon` routes through return update with `value=0`, potentially overwriting `expected_return_min`.
8. Current profile stores inferred-capable `constraints` and `response_pref`, conflicting with the document's confirmed-profile boundary.
9. `stm_compaction_support` extracts from a system-role summary and can write `chat_inferred` values directly into the authoritative profile.
10. Mem0 memory update/delete calls accept a memory ID but do not first verify that the ID belongs to the authenticated user.
11. Memory-item fallback lists LTM task history as pseudo-memory, which can mislead users about whether a memory is active.
12. Evidence lookup contains a TODO and does not resolve `evidence_ref` to owned source messages.
13. Historical candidate tables are SQL-only and absent from target ORM/startup migrations.
14. Historical Redis contains STM key builders but no STM cache-aside read/write path.

## 9. External Dependencies

| Dependency | Where called | Input | Output | Error handling / fallback |
| --- | --- | --- | --- | --- |
| PostgreSQL/SQLite | repositories, MemoryService, workers | messages, profiles, tasks, summaries | durable rows | Current startup swallows DDL errors; dual DB code paths duplicate behavior. |
| OpenAI-compatible LLM | compaction support, controlled model provider | prompt/messages | summary or model response | Compaction timeout/retry is local; configuration absence raises in worker and retries task. |
| Mem0 `AsyncMemory` | `mem0_client.py` | messages, user ID, metadata | memory CRUD/search | Import/init failure becomes Noop; dependency is not in lockfile. |
| pgvector | Mem0 config and Docker PostgreSQL image | embeddings/metadata | vector hits | No direct target integration test found. |
| Embedding provider | Mem0 config | memory text/query | vectors | Uses OpenAI-compatible credentials; model/dimension mismatch risk is not contract-tested. |
| Redis | Not present in target | Not applicable | Not applicable | Historical-only generic infrastructure. |
| Langfuse/JSONL trace | trace exporters | controlled workflow events | local/remote trace | Exporter failures are isolated; memory events are not connected. |
| Tushare | controlled tool provider | financial tool requests | financial evidence | Must remain separate from memory truth; live test is explicit and memory-disabled. |

## 10. Tests and Evaluation Assets

### 10.1 Existing Tests

- Confirmed target controlled-chat unit, contract, integration, E2E, and offline eval suites.
- Confirmed entity eval covers explicit entities, ambiguity, multi-entity, and selected follow-up behavior.
- Confirmed rewrite eval covers current-turn constraints and reply-preference examples.
- Confirmed Compose E2E verifies chat persistence and context counters with memory disabled.
- Confirmed protected live E2E calls real model/Tushare only via manual dispatch, also with memory/STM disabled.
- No target test file matching memory/STM/summary/profile behavior was found.
- Historical `Finance/tests/test_stm_summary_runtime.py` contains substantial summary/quality/fallback/CAS-style characterization.
- Historical `Finance/tests/test_working_state_store.py` covers a basic three-field round trip and audit row count.
- Historical Redis directory has unit/integration tests for generic cache/lock/envelope/key/health behavior.
- Historical candidate-governance tests only verify that auto-forget/metrics do nothing when the pool flag is disabled; they do not prove governance correctness.

### 10.2 Coverage Gaps

- No active controlled-chat test proves compaction enqueue, worker completion, or safe foreground fallback.
- No typed working-state unit or multi-turn transition test in target.
- No cross-request/session test proves entity/constraint/preference persistence and precedence.
- No target test proves profile writes and LTM tasks are atomic/idempotent.
- No candidate extraction, source gate, dedupe, conflict, promotion, expiry, or deletion test.
- No negative cross-user memory-ID update/delete test.
- No Mem0/pgvector adapter contract or local integration test.
- No stage-specific retrieval/injection or context-budget test.
- No memory redaction/trace contract tests.
- No realistic cross-session memory E2E, offline or protected live.

### 10.3 Candidate Test Locations

- `tests/unit/memory/` for domain state, merge, precedence, scope, conflict, redaction, and budget rules.
- `tests/contract/memory/` for schemas, statuses, trace events, profile APIs, and provider ports.
- `tests/integration/memory/` for PostgreSQL transactions, task claims, versions, deletion, and tenant isolation.
- `tests/evals/memory/stm/` for multi-turn state-transition fixtures.
- `tests/evals/memory/ltm/` for extraction/retrieval/promotion/deletion fixtures.
- `tests/e2e/` for offline Compose multi-turn and cross-session scenarios.

### 10.4 Visible Test Commands

Commands documented by current CI, not executed during reconnaissance:

```text
uv run --locked ruff check ...
uv run --locked pyright ...
uv run --locked pytest backend -q
uv run --locked pytest Financial-MCP-Agent -q -m "not live"
uv run --locked pytest tests/evals -q -m "eval_smoke and not live"
uv run --locked pytest -q
npm ci
npm run lint
npm run type-check
npm run build
docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e
```

## 11. Logging and Observability

### 11.1 Existing Logs

- Controlled workflow emits stable stage/status/elapsed/error fields through `WorkflowEvent` and `SkillTraceSink`.
- `skill_trace.py` defines `chat.memory_write_enqueue` and `chat.compaction_enqueue`, but no active controlled-chat caller was found.
- Workers log task status and errors and print progress to terminal.
- Memory routes/services log user identifiers and sometimes profile values, sectors, expected returns, source facts, or raw error text.

### 11.2 Missing Logs

- No active memory read/injection event in controlled workflow.
- No working-state before/decision/merge/after event.
- No summary quality/version/source-boundary/fallback event tied to the foreground trace.
- No candidate source-gate/dedupe/conflict/promotion decision event in target.
- No deletion/invalidation completion event across authoritative store, outbox, Mem0, cache, and derived projection.
- No stable memory error-code taxonomy.

### 11.3 Observability Risks

- F-string logs include full `user_id` and financial profile values; this exceeds the desired minimum safe telemetry.
- Worker `error_msg` may persist raw provider exceptions.
- Direct prints and structured logs duplicate output and make automation noisy.
- Trace correlation is lost between foreground chat and background STM/LTM tasks because task models lack trace/run/request/source-version fields.
- No artifact proves historical metric claims.

### 11.4 Output-channel Separation

| Channel | Current implementation | Stable fields / format | Redaction | Gaps |
| --- | --- | --- | --- | --- |
| User/API result | Typed chat responses and Pydantic memory responses | Mostly stable REST/WS schemas | Auth boundary exists | Memory fallback may present task history as active items; evidence incomplete. |
| Terminal progress | `print` in startup, routes, services, workers | Free-form Chinese strings | Some IDs truncated | Duplicated, noisy, and may include profile values/errors. |
| Logs | module/custom loggers | Controlled workflow is structured; legacy memory is mostly free-form | Partial | Full user IDs/profile values and raw errors appear. |
| Traces | controlled `WorkflowEvent` JSONL/exporters | `stage`, `status`, IDs, elapsed, error code | Central trace redaction exists | No connected memory-specific lifecycle. |
| Artifacts | controlled trace artifacts/eval runs | Existing controlled-chain conventions | Trace capture flags default safe | No memory run report, candidate-decision, or deletion proof artifact. |

## 12. Engineering Baseline Recon

| Area | Status | Evidence | Gap / implication |
| --- | --- | --- | --- |
| API/orchestration/domain/infrastructure boundaries | Partial | New controlled chat has good application/domain/infrastructure separation | Memory remains split across router facade, Agent service, raw SQL, direct commits, worker, and optional provider. |
| Agent/workflow/tool/prompt/model/memory/evaluation boundaries | Partial | Controlled workflow and versioned chat prompts/evals are explicit | Legacy memory prompts/provider/state are not integrated into controlled contracts or evals. |
| Docstrings, types, and key intent comments | Partial | New chat code has Chinese docstrings/types | Memory code uses many untyped dictionaries, broad metadata, f-string SQL/logging, and comments that overstate implementation. |
| File-section navigation vs module separation | Partial | Controlled modules are focused | Current `MemoryService` (~1,002 lines) and historical LTM/STM monoliths mix persistence, providers, policy, retries, and presentation. |
| Typed configuration and secret handling | Partial | Pydantic Settings and safe examples exist | Legacy memory modules read `os.getenv` directly; insecure local password/JWT defaults; Mem0 dependency/config is incomplete. |
| Error, retry, fallback, and state semantics | Partial | Foreground controlled workflow has stable statuses and bounded loops | Memory code swallows DB errors, returns success/noop ambiguously, commits internally, lacks idempotency/lease/dead-letter contracts, and cannot prove deletion consistency. |

## 13. Risk Areas

| Area | Why risky | Likely touched? | Recommended handling |
| --- | --- | --- | --- |
| Persistent session/profile/task schemas | Data loss, incompatibility, rollback difficulty | Yes | Versioned migration and rollback proof; no startup-only blind DDL. |
| Authentication/tenant isolation | Memory contains private financial preferences | Yes | Keep route auth; add repository-level ownership checks and negative tests. |
| Inferred profile writes | Can alter future investment analysis globally | Yes | Disable/remove direct inferred authoritative writes before activation. |
| Summary quality and races | Bad or late summary can erase reliable context | Yes | Typed summary status, source boundaries, commit-time version condition, last-good fallback. |
| Background task idempotency | Duplicate/late work can create stale memories | Yes | Stable task identity, unique constraints, leases, bounded retry and terminal statuses. |
| Mem0/embedding dependency | Cost, missing lockfile dependency, version drift, deletion semantics | Maybe | Official behavior and alternative tradeoff required before adoption. |
| Memory update/delete by ID | Current service does not verify item ownership | Yes | High-priority security contract and tests before any live use. |
| Logging/tracing privacy | User IDs, preferences, evidence, errors may leak | Yes | Redaction/data classification before richer traces. |
| Historical code copy | Large monoliths contain incompatible behavior and dual DB paths | Yes | Port contracts/tests/algorithms selectively; do not copy directories wholesale. |
| Redis cache | Adds stale-state and consistency failure modes | Unknown | Remain out of first semantic slice unless baseline justifies it. |
| Public API compatibility | Frontend already consumes profile/items/delete endpoints | Yes | Characterization tests and versioned changes. |
| Report-mode memory | Could become a second source/runtime | Unknown | Share domain/repositories; integrate one path at a time after clarification. |

## 14. Unknowns and Assumptions

### 14.1 Unknowns From Missing Code Access

- No missing local source access was encountered.
- Real `.env` values were intentionally not inspected.
- External deployed infrastructure, existing database rows, and undeclared installed packages were not inspected.

### 14.2 Unknowns From Incomplete Requirement

- Required retention, encryption, export, hard-deletion, and backup behavior for financial profile data.
- Whether response preferences belong exclusively to inferred text memory or may also be user-confirmed structured fields.
- Whether first release must expose candidate review and evidence UI or only backend contracts.
- Whether report mode must use the new memory path in the first migration wave.

### 14.3 Unknowns From Ambiguous Architecture

- Final durable schema ownership for semantic memories if Mem0 remains.
- Whether PostgreSQL-only is acceptable or SQLite must remain a supported production-like path.
- Whether runtime cache is justified and, if so, which state is safe to cache.
- Whether background execution remains an in-process worker, uses a PostgreSQL task table, or later adds a broker.
- Exact stage-specific retrieval queries and token budgets.

### 14.4 Assumptions

- Assumption: The controlled workflow remains the sole production conversation runtime.
- Assumption: User-confirmed profile fields remain durable and user-editable, but their exact schema may change.
- Assumption: Historical metrics and thresholds will be treated as candidate baselines only.
- Assumption: Default CI will remain fully offline and protected live tests will use isolated identities and read-only financial data.

## 15. Handoff to Next Step

Next step should use the Requirement Clarification Skill and produce `CLARIFICATION_QUESTIONS.md`.

It should clarify:

- The exact authoritative-profile fields, especially `constraints`, `response_pref`, watchlist, and holdings.
- The first vertical slice: typed working state, rolling-summary compaction, or LTM governance.
- Whether SQLite remains supported beyond local development.
- Whether Mem0 remains a desired dependency after its current lockfile and governance gaps are understood.
- Whether Redis is deferred until a measured need exists.
- Which inferred memory kinds may auto-promote and which require explicit user acceptance.
- Required candidate/evidence UI for the first release.
- Retention, deletion, privacy, encryption, and audit expectations.
- Whether report mode joins the shared memory layer immediately or later.
- Which historical thresholds/metrics should be re-baselined before becoming acceptance gates.

It should consider these files/modules in later solution design:

- `backend/application/chat/*`
- `backend/infrastructure/chat/repository.py`
- `Financial-MCP-Agent/src/conversation/*`
- `backend/db/models.py` and a future versioned migration boundary
- `backend/services/stm_*`
- `backend/services/memory_service.py`
- `Financial-MCP-Agent/src/memory/*`
- `backend/routers/memory.py` and `backend/schemas/memory.py`
- `frontend/src/api/index.ts`, `useMemory.ts`, `memoryStore.ts`, and memory UI components
- memory-specific tests/evals and CI gates

It should require explicit user approval before modifying these high-risk areas:

- Persistent schemas or existing user memory/profile data.
- Authentication, tenant isolation, public memory APIs, or deletion semantics.
- Real provider credentials, paid model calls, Tushare live calls, or production-like user data.
- New production dependencies such as Mem0/Redis/broker components.
- Report-mode integration, deployment, release, or production migration.

Most defensible first-slice candidate for clarification: persist a typed working-state contract and let the existing controlled workflow consume it while preserving current entity/rewrite behavior. This is a reconnaissance recommendation only, not an approved design or implementation plan.
