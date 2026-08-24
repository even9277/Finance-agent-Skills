# SOLUTION_TRADEOFF.md

## 1. Tradeoff Context

The target is a complete memory subsystem inside the existing controlled conversation mainline, not a disconnected showcase. The principal decision is how to add Redis, Mem0, pgvector, typed Working State, Rolling Summary, long-term governance, natural-language memory control, and real E2E without creating multiple authorities or copying the historical monolith.

The current repository already has partial session summary, profile, LTM task, Mem0 adapter, worker, API, frontend, and trace assets. Their main problem is ownership and connectivity: foreground persistence, state extraction, compaction scheduling, candidate governance, provider operations, and retrieval are not one transactionally and observably controlled lifecycle.

## 2. Inputs Reviewed

- REQUIREMENT_SPEC.md: Complete STM-01 through STM-10 and LTM-01 through LTM-10 delivery contract, including Redis, Mem0, pgvector, frontend controls, Compose E2E, and protected live E2E.
- CODEBASE_RECON.md: Active controlled call chain, partial/dormant current capabilities, historical `Finance` assets, persistence/configuration/test gaps, and module mapping.
- CLARIFICATION_QUESTIONS.md: No unresolved P0 blocker; conservative defaults fix authority, promotion, retention, report-mode, and live-test boundaries.
- User decisions: Deliver the whole memory program; selectively reuse both repositories; allow Docker/dependency/provider configuration; finish with real end-to-end verification.
- External sources: Mem0, Redis, PostgreSQL, pgvector, SQLAlchemy, Alembic, LangGraph, Langfuse, OpenClaw, and Hermes Agent official/repository evidence listed below.

## 3. User Decisions and Defaults

### 3.1 Confirmed Decisions

- `Finance-agent-Skills` and its controlled conversation workflow are the only maintained runtime.
- Redis, Mem0, PostgreSQL/pgvector, memory workers, vector retrieval, frontend/API controls, and live E2E are final-scope requirements.
- Existing local LLM/embedding/reranking/Tushare credentials may be used only through protected, redacted, isolated test gates.
- Explicit chat commands must inspect, change, or forget user-owned profile/text memory.
- Final acceptance requires running behavior and evidence, not files or module names.
- Current explicit intent and accepted financial evidence outrank every remembered value.

### 3.2 Conservative Defaults Used

- PostgreSQL is authoritative for business status, provenance, versions, audit metadata, deletion state, and durable tasks.
- Redis is rebuildable cache/coordination, never the only copy of a memory.
- Mem0 is a semantic provider/index, never the authority that decides whether an inferred memory becomes effective.
- High-impact investment-profile inference remains confirmation-only; explicit authenticated user commands can update it directly after validation.
- The controlled conversation path is the mandatory public E2E; report mode shares contracts/repositories without gaining a duplicate runtime.
- Historical metrics remain hypotheses until reproducible target-repository baselines exist.

### 3.3 Blocking Decisions

None. P1 defaults are recorded in `CLARIFICATION_QUESTIONS.md`; P2 items are deferred without blocking implementation.

## 4. Core Decision Point

Choose whether to connect existing services as-is, build one project-governed memory lifecycle around provider adapters, or replace the controlled mainline with an external/general-purpose memory runtime.

## 5. Reference Sources and Repository Evidence

### 5.1 Official Docs

#### Source: Mem0 OSS configuration

**Link:** https://docs.mem0.ai/open-source/configuration
**What was inspected:** Provider configuration for LLMs, embedders, rerankers, pgvector, collection naming, and deterministic extraction guidance.
**Relevant practice:** `Memory.from_config` supports project-selected components; production collections should be explicit; low extraction temperature and bounded rerank depth improve predictability.
**Reusable part:** Partially reusable.
**Fit for this task:** The provider configuration maps well to typed Settings, but Mem0 configuration must be constructed inside an infrastructure adapter rather than distributed through workflow code.

#### Source: Mem0 Async Memory

**Link:** https://docs.mem0.ai/open-source/features/async-memory
**What was inspected:** Async CRUD/search/history, lifecycle reuse, scopes, bounded retries, FastAPI usage, and deletion guidance.
**Relevant practice:** Reuse one async client per process, await every operation, scope by user/agent/run, bound concurrency/retries, and surface errors.
**Reusable part:** Directly reusable at the adapter boundary.
**Fit for this task:** `AsyncMemory` fits FastAPI and workers. The documentation examples do not supply our candidate governance, ownership checks, or transaction boundary, so the SDK cannot be called directly from routes/workflow nodes.

#### Source: Mem0 enhanced metadata filtering

**Link:** https://docs.mem0.ai/open-source/features/metadata-filtering
**What was inspected:** Tenant/status/category filters, logical operators, provider-specific differences, validation, and pgvector support.
**Relevant practice:** Always include user scope, validate filters, test the actual backend, put selective indexed filters first, and degrade explicitly when an operator is unsupported.
**Reusable part:** Directly reusable for provider contract tests; partially reusable for production retrieval.
**Fit for this task:** Mem0 filters reduce candidate leakage, but every result still must be post-authorized against project-owned active/deletion state.

#### Source: pgvector

**Link:** https://github.com/pgvector/pgvector
**What was inspected:** Exact search, HNSW/IVFFlat tradeoffs, filtered ANN behavior, iterative scans, multitenancy, and hybrid search with PostgreSQL full-text search.
**Relevant practice:** Start exact for small datasets; add HNSW only with measured need; combine vector and full-text rankings; account for filters reducing ANN results; partition or otherwise constrain tenant access.
**Reusable part:** Directly reusable.
**Fit for this task:** PostgreSQL full-text search plus pgvector supports lexical/semantic retrieval without a second vector database. Index choices must be baseline-driven rather than copied from a large-scale design.

#### Source: Redis cache-aside

**Link:** https://redis.io/docs/latest/develop/use-cases/cache-aside/
**What was inspected:** Read-through-on-miss, TTL-bounded staleness, invalidate-on-write, namespaced keys, and stampede protection.
**Relevant practice:** Durable store first, cache on read, delete cache keys after writes, bound staleness with TTL, and use token-safe locks only where single-flight is useful.
**Reusable part:** Directly reusable.
**Fit for this task:** Working State, summaries, and compact profiles are small rebuildable objects. Cache-aside fits; write-behind and cache-as-authority do not.

#### Source: PostgreSQL `SKIP LOCKED`, locks, and unique constraints

**Links:** https://www.postgresql.org/docs/current/sql-select.html, https://www.postgresql.org/docs/current/explicit-locking.html, https://www.postgresql.org/docs/current/ddl-constraints.html
**What was inspected:** Queue-like row claiming, transaction locks, deadlock behavior, and database-enforced uniqueness.
**Relevant practice:** `FOR UPDATE SKIP LOCKED` is appropriate for multiple consumers of a queue-like table; deterministic ordering and unique idempotency constraints remain necessary.
**Reusable part:** Directly reusable.
**Fit for this task:** The existing PostgreSQL task tables can evolve into durable outbox work without making Redis Streams a second durability source.

#### Source: SQLAlchemy async transactions

**Links:** https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html, https://docs.sqlalchemy.org/en/20/orm/session_transaction.html
**What was inspected:** One `AsyncSession` per concurrent task and explicit transaction scopes.
**Relevant practice:** One conversation transaction writes the user-visible state plus outbox rows; workers use separate sessions per claimed task.
**Reusable part:** Directly reusable.
**Fit for this task:** It directly corrects the current separate internal commits in profile and LTM task methods.

#### Source: Alembic

**Link:** https://alembic.sqlalchemy.org/en/latest/tutorial.html
**What was inspected:** Versioned migration environment, transactional upgrade, and revision tracking.
**Relevant practice:** Persisted contract changes live in reviewable upgrade/downgrade revisions rather than exception-swallowing startup DDL.
**Reusable part:** Directly reusable.
**Fit for this task:** The breadth and rollback requirements of memory schemas justify replacing ad-hoc column patching for new changes with versioned migrations.

#### Source: LangGraph memory model

**Links:** https://docs.langchain.com/oss/python/concepts/memory, https://docs.langchain.com/oss/python/langgraph/add-memory
**What was inspected:** Thread-scoped state/checkpoints, cross-thread namespaces, semantic search, and production migration requirements.
**Relevant practice:** Short-term state and long-term store are different contracts; user namespaces are mandatory; persistence requires an explicit setup/migration lifecycle.
**Reusable part:** Conceptual only.
**Fit for this task:** The distinction supports our model, but replacing the active controlled runtime with LangGraph persistence would be an unnecessary framework migration.

#### Source: Langfuse and OpenTelemetry observability

**Links:** https://langfuse.com/docs/observability/best-practices, https://opentelemetry.io/docs/specs/semconv/general/trace/
**What was inspected:** One trace per chat turn, session grouping, nested operations, stable observation names, producer/consumer correlation, and standardized attributes.
**Relevant practice:** Use one turn trace, one conversation session, and correlated producer/consumer spans for memory tasks; do not put raw sensitive content into general attributes.
**Reusable part:** Partially reusable.
**Fit for this task:** The repository already has Langfuse v2 infrastructure. Preserve its adapter and stable schema now; a broad SDK upgrade is not required for memory correctness.

### 5.2 Open-source Repositories

#### Source: mem0ai/mem0

**Link:** https://github.com/mem0ai/mem0
**What was inspected:** `memory/main.py` inference/update lifecycle and the pgvector adapter's metadata-filter translation.
**Relevant practice:** Mem0 can infer add/update/delete decisions and store semantic records with provider-specific filters.
**Reusable part:** Partially reusable.
**Fit for this task:** Provider CRUD/filter normalization is useful. Default inference is not our governance authority; promoted project-owned memories should be indexed with inference disabled to avoid a second decision engine.

#### Source: OpenClaw memory architecture

**Link:** https://github.com/openclaw/openclaw/blob/main/docs/concepts/memory-architecture.md
**What was inspected:** Provenance tiers, deterministic promotion gates, bounded model judgment, background curation, recall-loop prevention, selective injection, audit/review, and non-blocking failure behavior.
**Relevant practice:** Writing is the security boundary; provenance is structural; untrusted/assistant-derived content cannot gain authority through prose; background memory failure never consumes a foreground turn.
**Reusable part:** Conceptual and partially reusable.
**Fit for this task:** Provenance, candidate quarantine, deterministic gates, and failure boundaries map directly. Its file/SQLite memory surfaces and broad dreaming system should not be copied.

#### Source: Hermes Agent memory provider boundary

**Links:** https://github.com/NousResearch/hermes-agent/blob/main/agent/memory_provider.py, https://github.com/NousResearch/hermes-agent/blob/main/plugins/memory/mem0/__init__.py
**What was inspected:** Provider lifecycle, prefetch/sync hooks, one active external provider, circuit-breaker behavior, and separation of provider-specific logic from the core runtime.
**Relevant practice:** Core orchestration depends on one provider contract; provider code owns connection/configuration/failure behavior; multiple active providers are avoided.
**Reusable part:** Partially reusable.
**Fit for this task:** A narrow `SemanticMemoryProvider` port is appropriate. A general plugin marketplace is unnecessary.

### 5.3 Local Project Patterns

| Local pattern | Evidence from CODEBASE_RECON.md | How to reuse |
| --- | --- | --- |
| Controlled application entry | Router → `ControlledChatUseCase` → repository/workflow → save/commit | Keep all memory reads, commands, and outbox creation coordinated by the existing application use case. |
| Typed workflow artifacts | Controlled conversation contracts, evidence envelopes, route/plan/result types | Introduce equivalent typed memory state, commands, candidates, retrieval results, and task statuses. |
| Existing SQLAlchemy persistence | Session, messages, summaries, profile, LTM/STM task rows | Migrate rather than create a separate database service; remove internal service commits from application transactions. |
| Existing Mem0 boundary | `mem0_client.py`, `memory_service.py`, worker | Preserve useful provider normalization but move governance and ownership outside provider code. |
| Existing Langfuse trace adapter | `skill_trace.py` and trace initialization | Extend stable memory stage/span fields without scattering SDK calls. |
| Existing Compose/E2E patterns | Offline Compose and explicit live workflow | Add memory services/scenarios while retaining offline-default and protected-live separation. |
| Existing frontend memory feature | API/store/composables/components | Evolve current controls instead of creating a second frontend area. |

## 6. Reusable Patterns

### 6.1 Directly Reusable Patterns

- PostgreSQL transaction + durable outbox rows + unique idempotency keys.
- Worker row claiming through deterministic ordering and `FOR UPDATE SKIP LOCKED`.
- Redis cache-aside with versioned namespaced keys, TTL, and invalidate-on-write.
- Mem0 `AsyncMemory` process lifecycle and scoped CRUD through one adapter.
- PostgreSQL full-text + pgvector candidates followed by bounded fusion/reranking.
- One chat turn per trace and one conversation per trace session.

### 6.2 Partially Reusable Patterns

- Current `MemoryService`, `ltm_worker`, STM worker, profile API, and frontend controls: reuse contracts and tested behavior, but eliminate internal commits, unbounded metadata, unsafe ownership, and disconnected scheduling.
- Historical candidate/audit/state modules: reuse domain vocabulary, schema ideas, bad cases, and tests; do not copy monolithic orchestration or implicit profile writes.
- Hermes provider boundary: reuse a narrow provider port and lifecycle, not a generic plugin framework.
- OpenClaw provenance and promotion gates: reuse structural provenance/quarantine/review principles, not its file-based store or full dreaming subsystem.

### 6.3 Conceptual References Only

- LangGraph checkpointer/store separation validates STM/LTM boundaries but does not justify replacing the active workflow.
- OpenClaw multi-phase dreaming illustrates future deep consolidation; this delivery implements bounded candidate governance needed by the interview contract, not an autonomous nightly learning platform.

### 6.4 Not Suitable for This Iteration

- Mem0 as authoritative profile/candidate/deletion state.
- Mem0 default inference for promoted writes; it could issue autonomous add/update/delete decisions outside project gates.
- Redis Streams as the only durable job source; PostgreSQL already owns the foreground transaction and task evidence.
- A separate Mem0 HTTP microservice for this repository; in-process `AsyncMemory` in backend/worker containers has fewer auth, deployment, and failure boundaries.
- Replacing the controlled workflow with LangGraph persistence.
- Upgrading the entire Langfuse SDK solely to implement memory; use the existing trace adapter and treat SDK migration separately.

## 7. Solution Options

### 7.1 Option A: Minimal Fix

**What changes:** Connect the existing profile, STM summary worker, LTM worker, and Mem0 client; add Redis and enable current flags.

**What does not change:** Current untyped state, internal commits, task shape, Mem0 authority, startup DDL, and weak memory tests.

**Benefits:** Fastest route to visible modules and a simple demo.

**Costs:** Low initial cost, high later correction cost.

**Risks:** False completeness, stale writes, duplicate authority, unsafe deletion, cross-user provider access, and interview claims that tests cannot defend.

**Testing burden:** Medium because integration can run, but correctness remains difficult to isolate.

**Rollback difficulty:** Low for flags; medium for uncontrolled provider writes.

**Engineering impact:**

- Architecture/module ownership: Continues mixed service ownership.
- Documentation/types: Small improvement only.
- Configuration/secrets/prompts: Adds provider variables but leaves scattered policy.
- Terminal/logging/tracing/artifacts: Extends current logs without a stable lifecycle.
- Errors/retry/state: Preserves several current partial-failure and race risks.

**When to choose it:** Only for a disposable demonstration where truthful full-chain governance is not required.

### 7.2 Option B: Structured Improvement

**What changes:** Consolidate memory into typed domain policy, application use cases/context gateway, project-owned SQL repositories/outbox, Redis cache adapter, Mem0 semantic adapter, bounded workers, and current frontend/API integration. Introduce versioned migrations and cumulative offline/live verification.

**What does not change:** Public chat entry points, controlled route/tool/evidence/verifier boundaries, the main PostgreSQL deployment, Vue application foundation, or historical code's evidence-only status.

**Benefits:** Satisfies the full requirement with one authority, clear failure semantics, testable provider boundaries, credible interview mapping, and reversible milestones.

**Costs:** Moderate-to-high implementation and testing effort; new dependencies and migrations must be governed.

**Risks:** Broad cross-module work, data-model mistakes, worker races, provider-version mismatch, and longer cumulative E2E.

**Testing burden:** High but decomposable: domain, repository, Redis, Mem0 contract, workflow, offline eval, Compose, and live gates.

**Rollback difficulty:** Medium; reduced through expand-first migrations, flags at integration seams, derived indexes, and independent milestones.

**Engineering impact:**

- Architecture/module ownership: Domain rules inward; application orchestration central; providers outward.
- Documentation/types: Typed state/actions/statuses with Chinese Google-style contracts.
- Configuration/secrets/prompts: One Settings boundary, safe examples, versioned extraction/summary schemas.
- Terminal/logging/tracing/artifacts: Stable foreground/background correlation and redacted evidence.
- Errors/retry/state: PostgreSQL authority, CAS/version checks, bounded retry, idempotency, cache fail-open, provider degradation.

**When to choose it:** When the complete capability must be real and explainable without rebuilding the whole Agent platform.

### 7.3 Option C: Long-term Architecture Direction

**What changes:** Replace current memory/runtime persistence with a general LangGraph store/checkpointer or a standalone Mem0 memory service; use Redis Streams or a dedicated queue as the primary background bus; potentially refactor the entire conversation graph.

**What does not change:** Product behavior goals.

**Benefits:** Maximum framework generality and future provider portability.

**Costs:** Very high; requires a runtime migration, more deployment units, protocol/auth design, and compatibility work.

**Risks:** Duplicate orchestration, dual writes, larger blast radius, difficult rollback, and time spent on framework migration rather than memory correctness.

**Testing burden:** Very high across runtime, service, queue, data migration, and compatibility.

**Rollback difficulty:** High.

**Engineering impact:**

- Architecture/module ownership: Replaces several current owners.
- Documentation/types: New public/internal protocols throughout.
- Configuration/secrets/prompts: More services and credentials.
- Terminal/logging/tracing/artifacts: Cross-service propagation required.
- Errors/retry/state: Distributed consistency and migration complexity increase.

**When to choose it:** Deferred until the project genuinely requires independent scaling or multiple applications sharing one memory platform.

### 7.4 Option D: Observation-first Option

**What changes:** Add memory characterization datasets, traces, and baselines before behavioral migration.

**What does not change:** Existing disconnected implementation.

**Benefits:** Lowest behavioral risk and strongest baseline evidence.

**Costs:** Does not deliver the requested functionality by itself.

**Risks:** Delays user-visible progress and still leaves architectural contradictions.

**Testing burden:** Low-to-medium.

**Rollback difficulty:** Low.

**Engineering impact:** Mainly evaluation and observability.

**When to choose it:** Use its characterization principle inside the first milestones, not as the selected whole-program solution.

## 8. Decision Matrix

| Dimension | Option A Minimal Fix | Option B Structured Improvement | Option C Long-term Architecture | Option D Observation-first |
| --- | --- | --- | --- | --- |
| Scope | Partial | Complete requested scope | Broader than requested | Evidence only |
| Development Cost | Low initially | Medium-high | Very high | Low-medium |
| Risk | High hidden correctness risk | Medium, controlled by milestones | High migration/distribution risk | Low |
| Reusability | Medium | High | High | Medium |
| Fit to Current Requirement | Poor | Excellent | Medium | Poor alone |
| Local Pattern Fit | Medium | High | Low | High |
| Test Burden | Medium | High but bounded | Very high | Low-medium |
| Rollback Difficulty | Medium after provider writes | Medium | High | Low |
| Long-term Maintainability | Low | High | Potentially high, currently excessive | Medium |
| Engineering-standard fit | Poor | Strong | Strong but overbuilt | Strong but incomplete |
| Recommendation | Reject | Select | Defer | Embed into Option B milestones |

## 9. Recommended Solution

Selected option: Option B — Structured Improvement with characterization-first milestones.

Why selected: It is the only option that delivers every authorized capability while retaining the verified controlled mainline and enforcing one memory authority. It also creates a truthful mapping between the interview narrative, code, tests, and traces.

Why not the other options: Option A preserves the exact gaps that caused this migration. Option C turns a memory refactor into a platform rewrite and conflicts with the no-dual-runtime rule. Option D supplies valuable baselines but not the requested product behavior.

Local patterns reused: Controlled application use case, typed conversation artifacts, SQLAlchemy repository transaction, existing task/profile/summary concepts, Mem0 client boundary, Langfuse adapter, Compose E2E, and Vue memory UI.

External practices reused: PostgreSQL durable queue/outbox semantics, Redis cache-aside, Mem0 async scoped CRUD, pgvector/full-text hybrid retrieval, provider isolation, structural provenance, deterministic promotion gates, and foreground non-blocking failure behavior.

Remaining risks: Mem0/current dependency compatibility, migration from ad-hoc startup DDL, provider deletion lag, embedding dimension changes, model extraction instability, Redis cache races, large regression surface, and live-test cleanup.

What must be verified later: Locked dependency versions, upgrade/downgrade migrations, exact query plans/recall baselines, model/provider compatibility, cache version behavior, task concurrency, memory command ambiguity, tenant-negative tests, and real E2E evidence.

## 10. Unified Technical Direction

- Keep the existing HTTP/WebSocket → `ControlledChatUseCase` → controlled workflow chain as the only foreground entry.
- Create one typed memory domain covering Working State, summary metadata, profile authority, text-memory candidates, provenance, scope, lifecycle, commands, retrieval results, and stable error/status codes.
- Let the application layer own preflight/context assembly, explicit memory commands, foreground transaction boundaries, and post-turn outbox creation.
- Persist authoritative state and tasks in PostgreSQL through versioned Alembic migrations. The message/result/state update and corresponding background tasks must be committed together.
- Use separate worker processes that claim PostgreSQL tasks with deterministic ordering, unique idempotency, bounded retry, stale-version rejection, and stuck-task recovery. Redis may coordinate leases, but PostgreSQL remains durable authority.
- Cache only versioned rebuildable snapshots in Redis using cache-aside, TTL, tenant/session namespacing, invalidate-on-write, and database fallback.
- Run Mem0 `AsyncMemory` behind one semantic-provider adapter. Project code performs extraction, candidate governance, promotion, ownership, and deletion decisions. Index already-promoted text with Mem0 inference disabled and project metadata attached.
- Treat the Mem0/pgvector collection as a derived semantic index. Project-owned memory records remain sufficient to determine whether a result is active, authorized, superseded, expired, or deleted.
- Retrieve with mandatory user/status/scope filtering, PostgreSQL lexical recall, Mem0/pgvector semantic recall, deterministic fusion/reranking, authoritative post-filtering, and token-budget packing.
- Detect explicit memory commands before ordinary financial tool planning; execute only typed authenticated commands, request clarification for ambiguity/destructive breadth, and preserve current financial safety boundaries.
- Extend the existing Langfuse/log adapter with stable memory stages and foreground/background correlation. Do not perform a broad Langfuse major-version migration in this program.
- Verify each milestone offline and cumulatively; finish with Compose and protected live LLM/Tushare tests using isolated data and cleanup evidence.

Likely ownership areas are `backend/domain/memory`, `backend/application/memory`, `backend/infrastructure/memory`, the existing chat application/repository boundary, controlled workflow context stages, database models/migrations, worker bootstrap, typed settings, existing memory API/frontend, Docker/CI, and memory-specific tests/evaluations. Exact files and steps belong to `PLAN.md`.

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Mem0 autonomously changes memory outside policy | Use project extraction/governance and promoted writes with Mem0 inference disabled. |
| PostgreSQL and vector index diverge | Treat vector data as derived; store provider IDs/version; post-filter through authoritative records; durable reconcile/delete tasks. |
| Cross-user retrieval or mutation | Mandatory authenticated user scope at route, repository, provider filter, and negative-test levels. |
| Late summary/state/task overwrites newer data | Snapshot versions, CAS writes, stale terminal status, deterministic state-event audit. |
| Redis outage breaks conversations | Cache-aside, short timeouts, database fallback, no Redis-only authoritative state. |
| Duplicate worker execution | Database idempotency constraints, row claiming, attempt state, side-effect keys, and provider-result reconciliation. |
| Provider deletion partially fails | Mark inactive first, invalidate cache, block retrieval by authoritative post-filter, retry hard deletion durably. |
| Embedding model/dimension change | Version embedding config and collection/index identity; require migration/reindex procedure. |
| Model extracts unsupported memory | User-only provenance, structured schema, evidence spans, candidate quarantine, deterministic promotion rules. |
| Natural-language delete is too broad | Typed target/scope, ownership check, preview/confirmation for ambiguous or bulk destructive commands. |
| Trace leaks private finance data | IDs/hashes and safe summaries only; redact content and provider errors before export. |
| Huge change is hard to revert | Expand-first schema, one milestone at a time, integration flags only at seams, no dual production runtime. |

## 12. Verification Direction

### 12.1 Engineering Contract for Plan Freezing

- Architecture/module ownership: Domain owns memory policy; application owns orchestration/transactions; infrastructure owns SQL/Redis/Mem0/model providers; API/UI remain protocol adapters.
- Interfaces/docstrings/types: Core state, commands, candidates, lifecycle, tasks, provider ports, retrieval results, and errors are typed and documented in Chinese Google style.
- Configuration/secrets/constants/prompts: One typed Settings source; safe `.env.example`; pinned dependencies; versioned summary/extraction schemas/prompts; no real secret in Git/log/artifact.
- Terminal/logging/tracing/artifacts: Stable `stage`, `trace_id`, `task_id`, safe user/session reference, versions, status, elapsed time, counts, error code, and cleanup/artifact reference.
- Validation/errors/retry/state: Boundary validation, explicit partial/degraded statuses, transient-only bounded retry, idempotency, CAS, cache fail-open, provider circuit/degradation, and no silent empty-success conversion.
- Tests/evaluation/delivery evidence: Characterization, unit, contract, database/Redis/Mem0 integration, offline multi-turn evaluation, Compose E2E, protected live LLM/Tushare E2E, tenant/deletion/failure tests, diff review, independent review, and rollback evidence.

## 13. Deferred Work

- A standalone shared Mem0 HTTP service and independent scaling plane.
- Redis Streams/Kafka as primary task durability.
- Replacement of the controlled workflow with LangGraph persistence.
- Multi-region cache/database replication and production disaster-recovery automation.
- Report-mode memory injection and full report-mode E2E; both require a later separately scoped milestone, while this program shares only domain contracts and authoritative repositories.
- A broad Langfuse v2-to-current-major migration.
- Numeric performance/quality claims until reproducible baselines exist.
- User data export format; inspect/correct/delete/forget remains in scope.

## 14. Handoff to Plan Freezing

Next step should use the Plan Freezing Skill and produce `PLAN.md`.

The plan should:

- follow selected option: Option B structured consolidation with characterization-first milestones.
- allow modules/files: memory domain/application/infrastructure, controlled chat integration, database migrations/models, settings/bootstrap, workers, current API/frontend memory surfaces, Docker/CI, tests/evals/docs.
- forbid modules/files: unrelated financial tools, a second orchestrator, historical `Finance` writes, real `.env` content, permanent adapters/dual writes, and framework-wide rewrites.
- include required tests: typed state, merge/version, summary budget/CAS, outbox/idempotency, Redis contract/failure, Mem0 CRUD/filter/ownership, hybrid retrieval, candidate governance, chat memory commands, frontend/API, Compose, protected live, cleanup, and regressions.
- include required logs/metrics: state transitions, compaction, extraction, promotion, retrieval/fusion/injection, cache, worker, mutation/deletion, failure/fallback, provider/model/version, and safe cleanup evidence.
- include rollback strategy: expand-first downgrade-capable migrations, provider index as derived data, cache invalidation, feature-seam rollback, milestone-level revert, and no production data migration.
- preserve these constraints: PostgreSQL authority, current-turn precedence, financial evidence isolation, tenant isolation, offline CI defaults, live-test isolation, secret redaction, and one milestone at a time.
- keep these external references in mind: Mem0 async/config/filter behavior, pgvector filtered/hybrid search, Redis cache-aside, PostgreSQL row claiming, SQLAlchemy transaction scope, Alembic versioning, OpenClaw provenance gates, Hermes provider isolation, and Langfuse trace structure.
