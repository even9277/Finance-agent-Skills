# REQUIREMENT_SPEC.md

## 1. Task Type

Primary type: Existing-system memory subsystem migration and refactor requirement definition.

Secondary types: Agent context engineering, persisted-state governance, asynchronous processing, retrieval, observability, evaluation, security/privacy, and repository engineering governance.

Classification rationale: This work spans the controlled conversation workflow, database state, background workers, model calls, memory retrieval, user controls, logs/traces, tests, and migration rollback. It can change persistent and cross-module contracts, so it must use the full Spec Coding chain rather than direct implementation.

## 2. Requirement Restatement

Use `Finance-agent-Skills` as the only implementation source of truth. Extract the intended short-term memory (STM) and long-term memory (LTM) behavior from the two interview documents, then compare that behavior with the current target repository and the historical `Finance` repository. The result must establish a one-to-one mapping between narrative modules, current implementation evidence, reusable historical assets, missing capabilities, and migration boundaries.

The delivery target is no longer a minimal first slice. It is one complete memory program integrated into the existing controlled conversation mainline, covering typed Working State, recent raw context, Rolling Summary and token budgeting, long-term candidate governance, user-confirmed profile, text memory, Mem0-backed semantic retrieval, PostgreSQL/pgvector persistence, Redis hot-state/cache support, user memory controls, observability, offline evaluation, Compose E2E, and a protected real-provider E2E. Intermediate milestones may temporarily expose incomplete capability on the feature branch, but no milestone may be reported as accepted and no final delivery may be reported as complete until its declared checks pass.

The implementation must not create a second orchestrator, a long-lived compatibility adapter, or a parallel memory runtime. Historical code may be reused selectively only after its contracts, dependencies, failure semantics, security boundaries, and tests are reconciled with the target architecture. Work remains decomposed into independently reviewable, testable, reversible milestones even though all milestones belong to one authorized delivery program. This specification defines required outcomes; exact schemas, SDK versions, module placement, and milestone mechanics are frozen only after tradeoff analysis.

## 3. Problem Source

The project currently has three non-equivalent sources of information:

1. The `Finance-agent-Skills` repository contains the maintained controlled conversation workflow and is the final implementation truth source.
2. The historical `Finance` repository contains earlier memory experiments and potentially reusable code, but also incomplete, duplicated, or outdated implementations.
3. `短期记忆.md` and `长期记忆.md` describe the desired interview narrative and design vocabulary, but their implementation claims, metrics, thresholds, and technology choices are not automatically current facts.

Without reconciliation, code may contradict the interview narrative, historical modules may be copied without their dependencies or failure semantics, and memory may silently override the user's current intent or contaminate financial tool planning.

## 4. Current Behavior

Based on the previously verified controlled-conversation mainline, the current workflow can consume recent conversation messages, an existing running summary, and an existing profile snapshot. It does not yet have verified end-to-end evidence for the complete target memory lifecycle described in the two documents, including automatic STM compaction scheduling, typed working-state governance, full LTM candidate extraction and promotion, hybrid retrieval, conflict handling, stage-specific injection, and user-controlled forgetting.

Read-only Codebase Reconnaissance has now verified the principal code ownership, database schemas, workers, feature flags, tests, trace fields, and dormant historical capabilities in `CODEBASE_RECON.md`. The target repository contains partial STM/LTM assets, but the complete lifecycle is not connected to the active controlled mainline and currently has material gaps in typed state, automatic compaction scheduling, transactional memory work, candidate governance, hybrid retrieval, ownership validation, Redis integration, and memory-focused tests. Any document statement such as “implemented,” test counts, latency values, cache hit rates, or model-quality percentages remains unverified until matched to current code and reproducible target-repository evidence.

## 5. Expected Behavior

The target memory subsystem must form one governed lifecycle around the existing controlled workflow:

1. Preserve the current user's explicit message and current-turn working state as the highest-priority input.
2. Keep a bounded recent raw-message tail for verbatim fidelity.
3. Use rolling summaries only for earlier conversation continuity, with quality, version, and compression-boundary controls.
4. Maintain typed and auditable working state for the minimum execution-critical fields: current entity, current constraints, and current reply-preference hint.
5. Enforce safe entity inheritance, explicit replacement, ambiguity handling, multi-entity handling, scoped constraint updates, and temporary reply-preference semantics.
6. Assemble stage-specific context so route, rewrite, planner, executor/verifier, synthesis, and report paths receive only the memory they need.
7. Convert sufficiently supported user-side interaction signals into LTM candidates asynchronously, without delaying or failing the foreground answer.
8. Keep user-confirmed structured profile data authoritative. Model-inferred profile suggestions must never overwrite it automatically.
9. Govern inferred memories through schema validation, user-evidence validation, deduplication, conflict detection, scope, recency, versioning, promotion, expiry, deletion, and audit.
10. Retrieve only a small, relevant, tenant-scoped, active memory set and apply it as default background, never as current financial evidence or permission to expand tool execution.
11. Support user-visible inspection, correction, deletion, and forgetting for memory that affects future behavior.
12. Make each state change, retrieval, injection, retry, fallback, rejection, and background task traceable without exposing secrets or unnecessary private content.
13. Accept explicit natural-language memory commands in the normal chat path, including correcting confirmed profile fields, adding or changing text preferences, deleting a specific memory, and requesting broader forgetting, with confirmation where the requested action is ambiguous or high impact.
14. Run the final acceptance path against the real Dockerized memory infrastructure and explicitly configured real model provider; when the financial conversation scenario requires market evidence, the protected live case also uses the configured real Tushare provider.

## 6. Scope

### 6.1 In Scope

The analysis and eventual migration must cover the following requirement modules.

**STM-01 — Preflight and context budget**

- Estimate current-turn context pressure before expensive workflow stages.
- Use explicit configured budgets, output reserve, safety margin, and model/deployment effective limits.
- Trigger compression by policy rather than on every turn.
- Separate turn-level history governance from per-stage context budgets.

**STM-02 — Recent raw-message tail**

- Preserve a bounded, ordered, verbatim recent-message tail for pronouns, exact constraints, and transient instructions.
- Define a configurable default and a verified fallback policy; the historical “10 turns” value is a candidate baseline, not yet a frozen constant.
- Keep the durable message store authoritative.

**STM-03 — Rolling summary and compaction**

- Summarize only the older message range outside the protected raw tail.
- Record summary version, compressed message boundary, source range, quality status, and generation metadata.
- Prevent failed, stale, unsupported, or low-quality summaries from overwriting a last-good summary.
- On compaction failure, preserve foreground availability and expand safe raw context where budget permits.

**STM-04 — Typed working state**

- Define typed contracts for `active_entity`, `constraints`, and `reply_preference_hint` rather than using an unbounded dictionary or free-form summary.
- Store field source, scope, confidence where applicable, source message, update time, and state version.
- Keep current entity distinct from long-term interests or holdings.

**STM-05 — Entity resolution and inheritance**

- Resolve authoritative entities before route selection.
- Allow inheritance only for supported follow-ups and compatible, sufficiently reliable previous entities.
- Replace on an explicit new entity, clear or suppress inheritance for concept questions or explicit negation, and clarify unresolved ambiguity.
- Preserve candidate entities for comparisons and ambiguous mentions without silently selecting one.

**STM-06 — Constraint and reply-preference updates**

- Extract constraints and reply preferences from user evidence at the appropriate controlled-workflow stage.
- Apply typed add, override, clear, expire, and no-update semantics.
- Distinguish current-turn, session-segment, and potential long-term scope.
- Ensure soft style preferences never suppress required financial risk or safety content.

**STM-07 — State merge, versioning, concurrency, and audit**

- Apply field-local deterministic merge rules after model extraction and schema validation.
- Reject stale writes and late background results using optimistic versions or an equivalent concurrency contract.
- Record auditable before/after changes and reason codes without persisting private payloads unnecessarily.

**STM-08 — Context Gateway and stage-specific injection**

- Keep route context minimal and protected from historical-interest pollution.
- Allow rewrite to receive only compact, relevant preference background after route and entity are known.
- Prevent LTM from expanding planner tools beyond the current route, constraints, and evidence contract.
- Keep executor and verifier focused on plans and evidence.
- Let synthesis use accepted evidence plus a compact, governed profile/memory view.
- Define must-keep and droppable context classes, token budgets, and observable drop reasons.

**STM-09 — Redis hot-state cache**

- Integrate Redis for small, hot, rebuildable snapshots such as Working State, recent tail, last-good summary, compact confirmed profile, and safe task/lock metadata selected during design.
- The durable store remains authoritative; cache entries require tenant-aware keys, bounded size, versions, TTL, invalidation, stale rejection, cache-aside recovery, and fail-open-to-durable-store behavior.
- Redis unavailability must not corrupt state or make the foreground conversation unavailable when PostgreSQL remains healthy.
- Financial facts, arbitrary tool payloads, raw full history, and final model answers must not be treated as authoritative Redis memory.

**STM-10 — STM evaluation and observability**

- Evaluate field transitions and intermediate traces, not only final-answer quality.
- Cover safe inheritance, explicit switch, concept-query non-inheritance, ambiguity, multi-entity comparison, scoped constraints, preference override, compaction failure, stale writes, and context pruning.
- Preserve a reproducible offline regression set and separate any protected live evaluation from default CI.

**LTM-01 — Content boundary and precedence**

- Separate user-confirmed structured profile data from model-inferred text memories.
- Use runtime precedence: current explicit instruction/working state, confirmed profile, promoted inferred memory, non-effective candidate, then generic default policy, subject to system safety rules.
- Treat raw history and summaries as evidence sources or retrieval inputs, not automatically effective LTM.

**LTM-02 — Authoritative structured profile**

- Restrict high-impact investment-profile fields to explicit user creation or confirmation.
- Make profile fields viewable, editable, versioned, attributable, and deletable.
- Model-generated profile suggestions remain candidates until explicit confirmation.

**LTM-03 — Candidate extraction and durable scheduling**

- Trigger candidate extraction outside the foreground response through a durable, idempotent task boundary.
- Bind each task to the correct user, session, summary/state versions, source-message range, trace, prompt/schema versions, and idempotency identity.
- Support retryable, skipped-no-signal, terminal-failure, and recoverable-stuck-task states.

**LTM-04 — Candidate schema and evidence gate**

- Permit only defined candidate kinds and typed scope/status values.
- Require user-side evidence or user-triggered state events; assistant text and unsupported summary claims cannot independently establish memory.
- Record normalized content, source references, first/last seen times, confidence inputs, conflict grouping, and decision reason.

**LTM-05 — Deep governance and promotion**

- Score candidates using reproducible evidence such as repeated occurrence, unique contexts, active days, explicit wording, recency, contradiction, and source quality.
- Deduplicate equivalent candidates and identify mutually conflicting candidates before promotion.
- Keep high-impact structured-profile suggestions confirmation-only.
- Define bounded promotion, rejection, supersession, expiry, and re-evaluation semantics.

**LTM-06 — Storage and retrieval**

- Preserve tenant isolation, metadata filters, active/deleted status, scope, source, version, and audit metadata.
- Integrate Mem0 as the semantic-memory provider and PostgreSQL/pgvector as the Dockerized vector-capable persistence foundation, while keeping authoritative business status, provenance, version, deletion, and governance fields under project-controlled contracts.
- Reuse the historical Mem0 integration only where it satisfies current provider isolation, ownership filtering, error handling, deletion, observability, and testability requirements.
- Retrieval combines mandatory deterministic tenant/status/scope filters with lexical matching, semantic similarity, and bounded rule-based reranking; it must return a small token-budgeted result set with retrieval reasons and scores suitable for trace inspection.

**LTM-07 — Conflict, freshness, correction, and forgetting**

- Prefer newer explicit user instructions over older inferred memories.
- Detect contradictory memories rather than injecting both blindly.
- Support soft deletion or equivalent reversible governance where required, hard deletion where policy requires it, downstream invalidation, and audit-safe redaction.
- Prevent deleted, expired, conflicted, or unconfirmed memories from entering active context.

**LTM-08 — Stage-specific retrieval and injection**

- Skip formal LTM retrieval during route unless a later verified requirement proves it safe.
- Build stage-specific retrieval queries only from already-confirmed current-turn state.
- Keep rewrite injection compact, planner usage non-expansive, and synthesis/report usage bounded by scope and token budgets.
- LTM can alter emphasis or presentation but cannot replace current financial evidence.

**LTM-09 — User controls, privacy, and projection**

- Provide a governed way for users to inspect which memories affect future answers, correct them, delete them, and request forgetting.
- Support the same core controls through authenticated APIs, the existing frontend memory experience, and explicit natural-language commands in the ordinary chat entry path.
- Direct user commands may update confirmed profile fields or user-owned text memories after boundary validation; model inference alone cannot silently obtain the same authority.
- Any human-readable file projection or profile summary is a derived view, not an independent source of truth.
- Define privacy classification, retention, encryption/access expectations, and trace/log redaction before implementation.

**LTM-10 — LTM evaluation and observability**

- Evaluate extraction precision, unsupported-memory rate, deduplication, conflict resolution, promotion precision, retrieval relevance, scope leakage, stale-memory usage, deletion effectiveness, and downstream instruction adherence.
- Trace foreground and background stages with stable run/task identifiers, versions, statuses, timings, reason/error codes, and safe artifact references.

**Cross-module reconciliation deliverables**

- A module mapping from the two interview documents to current target-repository code, historical `Finance` code, current evidence status, gap, and recommended ownership boundary.
- Identification of dormant or duplicate modules and confirmation of the single production entry path.
- A later tradeoff record for storage, cache, worker/queue, retrieval, schema, user-control, and rollout choices.
- A frozen, one-milestone-at-a-time migration plan with tests, rollback, review, and delivery gates.
- A final implementation-to-interview mapping that marks every claimed module as verified, partial, or deferred and links each verified claim to code, tests, and reproducible evidence.

### 6.2 Out of Scope

- Business-code implementation during Requirement Definition and Codebase Reconnaissance.
- Treating historical benchmark numbers, test counts, cache metrics, latency, or model claims as current evidence.
- Copying the historical runtime wholesale or maintaining a long-lived old-to-new adapter.
- A second conversation orchestrator, permanent dual-write path, or parallel memory source of truth.
- Automatic model control over confirmed high-impact financial profile fields.
- Caching or reusing final financial answers as memory.
- Using LTM as financial evidence, an authorization source, or a reason to bypass tool/evidence governance.
- Production deployment, production data writes, or production user-memory migration without a separately approved migration and rollback procedure.
- Commit, push, pull request, merge, release, branch-protection changes, or deployment unless explicitly authorized for the relevant delivery step. Issue #22 and the working branch were explicitly authorized and already created.
- Declaring the implementation complete merely because files or module stubs exist; final completion requires the acceptance evidence in Section 10.

### 6.3 Unknown Scope

- The exact supported Mem0 SDK and embedding-provider versions that are compatible with the target Python stack and Docker environment.
- Whether Redis also owns background-task coordination/locking in the first complete delivery or remains limited to hot-state cache and idempotency assistance.
- The exact data-retention duration, encryption-at-rest policy, export format, and hard-deletion SLA for personal financial profile data.
- Whether report mode consumes the unified memory services in the same release or only shares contracts and repositories while conversation mode is the verified public path.
- The numeric quality thresholds for extraction precision, promotion precision, retrieval relevance, cache performance, and E2E latency; these require target-repository baselines before they can become gates.

## 7. Constraints

### 7.1 Hard Constraints

- `Finance-agent-Skills` is the sole maintained source of truth; `Finance` is evidence and reference only.
- Directly refactor the target architecture; do not build a long-lived compatibility adapter, forwarding layer, dual runtime, or dual source of truth.
- Integrate with the existing controlled conversation workflow and thin HTTP/WebSocket entry points.
- Current explicit user input and current-turn state must outrank remembered preferences.
- Memory must not create or alter financial facts, override accepted evidence, bypass verifier/controller rules, or broaden tool permissions.
- Every persisted or cached object must be tenant/user scoped. Cross-user or cross-session leakage is unacceptable.
- Secrets, API keys, authorization headers, cookies, full private prompts, and unnecessary private financial content must not appear in terminal output, logs, traces, test fixtures, or committed artifacts.
- Configuration and credentials must use the typed settings boundary and safe environment variables; a real `.env` must never be committed.
- Docker and local-development configuration may add Redis, Mem0, pgvector, workers, health checks, migrations, and required open-source dependencies. New dependencies must be pinned/locked, documented, scanned, and justified in the tradeoff record.
- Existing locally configured LLM, embedding, reranking, and Tushare credentials may be consumed through the target repository's typed settings for protected live verification. Values must not be printed, copied into committed files, embedded in images, or exposed in artifacts.
- Default tests and CI must not call paid models, Tushare production endpoints, or production services. The final delivery additionally requires a separately invoked protected live E2E using the configured real model and real Dockerized memory services; real Tushare is required only for the selected financial-data scenario. The run must use isolated test identities/data, bounded cost/rate, no production writes, cleanup, and redacted reporting.
- Each implementation milestone must include behavior characterization, focused unit/contract tests, integration coverage, offline evaluation where relevant, Compose E2E for the affected user path, trace evidence, independent review, and a documented revert path.
- Every milestone remains independently reversible. “一步到位” means all approved capabilities are delivered in one program, not that they are implemented as one unreviewable commit or one destructive schema change.
- Persisted schemas, public APIs, prompts, model schemas, tool schemas, and evaluation datasets that affect compatibility or reproducibility are versioned contracts.
- No historical metric can be presented as a current result without a reproducible run and artifact in the target repository.

### 7.2 Soft Constraints

- Prefer the smallest architecture that satisfies reliability and auditability while preserving a credible enterprise engineering story.
- Reuse proven target-repository abstractions before importing historical code.
- Prefer one authoritative state model and one orchestration path over duplicated convenience layers.
- Keep foreground response latency independent from best-effort LTM extraction and promotion.
- Explain decisions and milestone acceptance in beginner-friendly Chinese while retaining production-grade code and tests.

## 8. Stakeholders and Impact

- End user: receives contextually coherent and personalized answers without stale or cross-user memory pollution.
- Project owner/interview candidate: needs an implementation that maps truthfully to the documented interview narrative and can be explained module by module.
- Maintainer/reviewer: needs narrow diffs, typed contracts, traceable state transitions, reproducible tests, and reversible migrations.
- Frontend client: may consume profile, memory, session, status, or control APIs whose compatibility must be verified.
- Backend controlled workflow: gains memory inputs and background events without losing its existing routing, evidence, and failure boundaries.
- Database/cache/vector/model providers: may receive new schemas or load; final choices require later tradeoff analysis.
- CI/CD and operations: require offline-safe defaults, explicit live-test gates, migrations, health checks, metrics, and rollback evidence.

## 9. Engineering Quality Requirements

### 9.1 Interface Documentation and Types

- Public routes, application services, workflow nodes, workers, repositories, model-provider adapters, memory schemas, and evaluation interfaces require typed contracts and Chinese Google-style docstrings consistent with repository rules.
- Core STM/LTM state must not be an unconstrained `dict[str, Any]`.
- Every state field whose type cannot express source, scope, version, privacy, persistence, or expiry must document those semantics.
- Machine-consumed statuses, actions, conflict states, and error reasons use stable enums or codes.

### 9.2 Architecture and Module Ownership

- Protocol handlers validate/authenticate/map responses only.
- Application/workflow code owns use-case orchestration and stage ordering.
- Domain models/rules own memory types, precedence, scope, conflict, merge, and promotion rules.
- Infrastructure adapters own PostgreSQL, cache, vector/memory provider, model-provider, scheduler/worker, and file projection details.
- Prompts and schemas are explicit, versioned boundaries.
- Evaluation and observability remain separable from production business rules while consuming the same contracts.

### 9.3 Configuration, Secrets, Constants, and Prompts

- Load and validate environment-dependent settings once through typed configuration.
- Keep stable business rules and enums in code; expose operational thresholds only when deployment variation is justified.
- Commit only safe examples and document every required setting, default, validation failure, and live-test gate.
- Version prompts and structured-output schemas that affect extraction, summary, or evaluation reproducibility.

### 9.4 Terminal Output, Logging, Tracing, and Artifacts

- Terminal output remains concise and reports only progress, status, identifiers, and safe artifact paths.
- Structured logs and traces use stable fields such as `stage`, `run_id`/`trace_id`, `task_id`, `session_id` in a safe representation, `status`, `elapsed_ms`, versions, counts, `error_code`, and artifact path.
- Model calls, state transitions, compaction, cache decisions, retrieval, injection, background tasks, retries, conflicts, promotion, deletion, and fallbacks must be traceable.
- Large prompts, outputs, evidence spans, and evaluation diagnostics belong in access-controlled/redacted artifacts only when required.

### 9.5 Validation, Errors, Retry, State, and Compatibility

- Validate all external/model inputs before they affect state.
- Fail closed for ambiguous high-impact memory updates and fail open to safe current context when optional cache or background memory work fails.
- Retry only transient failures, with bounded attempts, elapsed-time budget, idempotency, and explicit terminal states.
- Preserve foreground answer availability when compaction or LTM candidate extraction fails, except when the current request cannot fit safely and requires clarification or degradation.
- Persisted-state and API changes require forward migration, rollback/revert handling, compatibility analysis, and realistic failure tests.
- A feature flag may protect staged rollout, but it must not become a permanent duplicate implementation or hide an untested path.

## 10. Success Criteria

### 10.1 Functional Criteria

- Every STM and LTM requirement module has a documented mapping to target code, historical evidence, current gap, and future owner.
- The final implemented chain preserves current entity, scoped constraints, preference hints, recent exact dialogue, and earlier summary without unsafe inheritance.
- Confirmed profile and promoted memories are retrieved and injected only at allowed stages and under the defined precedence.
- Candidate extraction, governance, retrieval, correction, deletion, and background failure behavior are observable and testable.
- Redis, PostgreSQL/pgvector, Mem0, the memory worker, the backend, and the frontend can be started through the documented Compose topology with health/readiness checks and without manual in-container patching.
- A user can state, switch, and clear an entity/constraint/preference across turns; the resulting typed Working State and Rolling Summary are persisted, versioned, and visible in safe trace/test evidence.
- A user can explicitly update a confirmed profile field, create or change a text preference, inspect the effective memory, delete a specific item, and request forgetting through the ordinary chat path; subsequent conversations reflect the accepted change within the defined consistency boundary.
- No candidate, stale cache item, deleted/conflicted memory, or assistant-only statement can silently become effective memory.

### 10.2 Compatibility Criteria

- Existing authenticated REST/WebSocket conversation contracts remain unchanged unless an explicitly versioned API change is approved.
- Existing controlled route, tool, evidence, verifier/controller, and synthesis contracts continue to operate.
- Existing sessions and messages remain readable through a tested data migration or backward-readable schema strategy selected later.
- Frontend changes, if required, use documented API contracts and do not depend on database internals.

### 10.3 Reliability Criteria

- Cache, compaction, extraction, vector retrieval, or background-worker failure cannot corrupt authoritative state or crash the foreground conversation path.
- Duplicate, late, or replayed tasks do not create duplicate or stale effective memories.
- Concurrent requests for one session cannot silently overwrite newer state with older results.
- Deletion and correction prevent affected memories from subsequent active retrieval within a defined and tested consistency boundary.

### 10.4 Observability Criteria

- A single conversation trace can show memory inputs, versions, state changes, context decisions, retrieval/injection decisions, and safe failure/fallback status.
- Background tasks correlate to the originating trace/session versions and expose retry/terminal states.
- Metrics distinguish current verified results from historical targets and can reproduce any resume/interview claim adopted later.

### 10.5 Testing Criteria

- Offline unit and contract tests cover typed models, merge/precedence, validation, version rejection, conflict, scope, expiry, and redaction.
- Integration tests cover database transactions, task idempotency, retrieval filters, deletion, and controlled-workflow injection with fake providers.
- Contract tests cover Redis key/version/TTL/invalidation behavior and Mem0 provider add/search/update/delete normalization without requiring real providers.
- Offline memory evaluation covers representative multi-turn STM and cross-session LTM bad cases with fixed fixtures, trace/state grading, and regression reporting.
- Compose E2E covers a complete multi-turn STM scenario, compaction/token-budget scenario, candidate-governance scenario, cross-session semantic retrieval scenario, natural-language profile/text-memory mutation scenario, deletion/forgetting scenario, and dependency-failure degradation scenario using deterministic local/fake providers by default.
- Protected live E2E calls the configured real LLM against the real Dockerized PostgreSQL/pgvector, Redis, Mem0, worker, backend, and frontend/API path. It verifies at least one STM extraction/compaction case and one LTM extract-store-retrieve-update/delete case. A selected financial scenario also calls configured real Tushare so the memory path is checked inside the controlled evidence chain rather than in isolation.
- Live artifacts must record provider/model identifiers, prompt/schema versions, timings, statuses, and safe hashes/IDs, while redacting credentials and private payloads. Tests must clean up isolated users/sessions/memories or produce an explicit cleanup report.
- Required formatting, linting, type checks, focused tests, regression, and E2E gates are documented in the frozen plan before implementation.

## 11. Risks and Mitigations

- **Narrative drift:** Interview documents may describe aspirational or historical behavior. Mitigation: evidence-label every mapping and rerun metrics in the target repository.
- **Memory pollution:** Temporary or assistant-generated content may become permanent. Mitigation: user-evidence gate, typed scope, candidates before promotion, and current-turn precedence.
- **State races:** Late summary or worker writes may overwrite newer conversation state. Mitigation: versioned snapshots, idempotency, optimistic concurrency, and stale rejection.
- **Cross-tenant leakage:** Cache keys or vector filters may omit user scope. Mitigation: mandatory tenant/user filters, negative isolation tests, and authorization at every read/write boundary.
- **Hidden dual runtime:** Copying old services may create a second orchestrator. Mitigation: freeze one application owner and prohibit adapters/dual writes.
- **Large delivery surface:** Redis, Mem0, vector retrieval, state, workers, APIs, frontend, and E2E can create a broad failure surface. Mitigation: freeze one architecture and deliver it through ordered, independently reversible milestones with cumulative gates.
- **Foreground instability:** Model extraction or memory providers may delay chat. Mitigation: asynchronous LTM work, strict timeouts, bounded retries, and safe fallback.
- **Privacy leakage:** Financial profile content may enter logs, traces, fixtures, or Git. Mitigation: data classification, redaction, safe artifacts, secret scanning, and deletion tests.
- **False confidence from tests:** Mock-only tests may pass while live provider behavior fails. Mitigation: default deterministic CI plus explicit protected live E2E with separate reporting.
- **Irreversible schema change:** Persistent-state migrations can strand existing sessions. Mitigation: forward/rollback migration design, backups, compatibility checks, and milestone-level revert plans.

## 12. Open Questions

1. - Question: Which inferred memories can auto-promote, and which require user confirmation?
   - Why it matters: It defines the safety boundary between useful personalization and unauthorized profile mutation.
   - Suggested default: Confirmed investment-profile fields always require the user; narrowly scoped response preferences may auto-promote only after strong, reproducible evidence and remain user-deletable.

2. - Question: What retention, encryption, access, export, and hard-deletion policy applies to personal financial profiles and source evidence?
   - Why it matters: It changes schemas, audit design, artifacts, backups, and user-control APIs.
   - Suggested default: Minimize stored evidence, encrypt transport/storage through platform facilities, restrict access by user, support visible deletion, and avoid logging raw private content until policy is confirmed.

3. - Question: Must report mode and controlled conversation share the same memory services in the first release?
   - Why it matters: A partial split may recreate duplicate state or inconsistent precedence.
   - Suggested default: Share domain contracts and repositories immediately, but integrate one verified user path at a time behind explicit rollout gates.

4. - Question: Which historical thresholds and evaluation metrics should become project acceptance gates?
   - Why it matters: Unverified numbers cannot be used as credible CI gates or interview claims.
   - Suggested default: Treat all historical values as hypotheses; establish a target-repository baseline first, then freeze thresholds with dataset and run metadata.

5. - Question: Which exact real-provider test account/data namespace may the protected live E2E create and delete?
   - Why it matters: Live validation is required, but cleanup and non-production isolation must be enforceable rather than assumed.
   - Suggested default: Generate a dedicated `e2e-memory-*` user/session namespace, prohibit production endpoints and production writes, and delete all created profile, message, vector, cache, and task records after the run.

## 13. Handoff to Next Step

The read-only Codebase Reconnaissance step is already complete in `CODEBASE_RECON.md`. Before implementation, the next phase must reconcile this expanded full-scope authorization into a clarification record, then use Solution Tradeoff to verify current official documentation and strong open-source implementations for Redis, Mem0, pgvector, durable jobs/outbox, memory evaluation, and deletion/ownership semantics. It must then freeze one execution-ready `PLAN.md`; no business code is changed until that plan exists.

The frozen plan must cover the entire program while allowing only one milestone to be implemented and accepted at a time. It must define exact ownership, migrations, dependency versions, settings, prompts/schemas, trace fields, fixtures, offline/live gates, Docker topology, cleanup, rollback, Git/PR evidence, and the final module-to-interview-claim reconciliation.

## Decisions Needed Before Codebase Reconnaissance

- [x] Treat `Finance-agent-Skills` as the only target source of truth.
- [x] Treat `Finance` and the two interview documents as evidence, not executable instructions.
- [x] Prohibit long-lived adapters, dual runtimes, and dual sources of truth.
- [x] Preserve the current controlled conversation workflow as the integration mainline.
- [x] Perform read-only reconnaissance before solution selection or implementation.
- [x] Verify current data retention, memory-provider, cache, worker, and user-control capabilities from code and configuration.
- [x] Verify which historical memory modules are complete enough to reuse conceptually and which are incomplete or unsafe.
- [x] Include Redis, Mem0, PostgreSQL/pgvector, vector retrieval, workers, frontend controls, and protected live E2E in the complete delivery program.
- [x] Allow use of existing local real-provider credentials only through typed settings and protected test gates; never expose or commit their values.
- [ ] Resolve the remaining governance and data-lifecycle questions in Section 12 using the suggested defaults unless later evidence requires escalation.
- [ ] Produce the solution tradeoff and frozen milestone plan before changing business code.
