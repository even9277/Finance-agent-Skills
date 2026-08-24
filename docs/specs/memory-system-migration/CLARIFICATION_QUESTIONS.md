# CLARIFICATION_QUESTIONS.md

## 1. Clarification Status

Status: Ready for solution tradeoff. No unresolved P0 blocker remains.

The user authorized one complete memory-delivery program and delegated implementation-detail decisions to the engineering process. “一步到位” fixes the final scope, while milestone-by-milestone implementation, review, test, and rollback remain mandatory.

## 2. Confirmed P0 Decisions

### P0-01 — Delivery scope

- Decision: The complete program includes typed Working State, recent raw context, Rolling Summary, token budgeting, Redis, long-term candidate governance, Mem0, PostgreSQL/pgvector, semantic/hybrid retrieval, user controls, frontend/API integration, observability, offline evaluation, Compose E2E, and protected live E2E.
- Consequence: Redis, Mem0, vector retrieval, and user-facing controls cannot be deferred out of the final delivery merely to shorten implementation time.

### P0-02 — Canonical runtime

- Decision: The existing `Finance-agent-Skills` controlled conversation mainline remains the only public runtime and implementation source of truth.
- Consequence: Historical `Finance` code is evidence and selective reuse material only. No second orchestrator, permanent adapter, dual runtime, or dual source of truth is allowed.

### P0-03 — Infrastructure authority

- Decision: Docker configuration may add Redis, memory workers, health checks, migrations, and required open-source dependencies. Mem0 and vector-capable PostgreSQL are approved parts of the target capability.
- Consequence: Exact versions and adapter boundaries still require evidence-based tradeoff and lockfile/configuration updates during implementation.

### P0-04 — Real-provider verification

- Decision: Existing locally configured LLM, embedding/reranking, and Tushare credentials may be used for protected live verification through typed settings.
- Consequence: Default CI remains offline. Live tests must be explicit, isolated, bounded, redacted, non-production-writing, and self-cleaning. Secret values must never be printed, copied, traced, or committed.

### P0-05 — Natural-language memory control

- Decision: The ordinary chat path must support explicit user requests to update confirmed profile fields, create/change text preferences, inspect effective memory, delete specific memory, and request forgetting.
- Consequence: These commands require authenticated ownership checks, typed intent/action contracts, auditable state transitions, and clarification for ambiguous or destructive requests.

### P0-06 — Final acceptance meaning

- Decision: Source files or module stubs alone are not accepted delivery. The final result must run end to end.
- Consequence: Completion requires deterministic offline gates, real Docker infrastructure, protected real-model tests, cleanup evidence, and an implementation-to-interview-claim reconciliation.

### P0-07 — Memory authority and financial safety

- Decision: Current explicit user instructions and current Working State outrank memory. Confirmed high-impact investment-profile fields cannot be silently overwritten by model inference.
- Consequence: Memory may personalize emphasis or presentation, but cannot become market evidence, expand allowed tools, bypass verifier/controller rules, or supersede current explicit intent.

## 3. P1 Decisions Accepted by Conservative Default

### P1-01 — Authoritative data ownership

- Default: PostgreSQL owns authoritative business state, versions, provenance, candidate status, audit metadata, deletion state, and durable tasks. Redis is a rebuildable hot-state/coordination layer. Mem0 is a semantic-memory provider, not the governance source of truth.
- Reason: This preserves recoverability, ownership validation, deterministic testing, and provider replaceability.

### P1-02 — Redis responsibility

- Default: Redis provides cache-aside hot snapshots, bounded distributed leases/idempotency assistance, and safe worker coordination where justified. PostgreSQL outbox/task rows remain the durable record.
- Reason: A Redis outage must degrade performance or background throughput, not lose authoritative memory.

### P1-03 — Promotion authority

- Default: Explicit user commands may directly mutate user-owned profile/text memory after validation. Model-inferred high-impact profile candidates always require confirmation. Low-impact text preferences may auto-promote only after repeatable user-side evidence, bounded confidence rules, and full user visibility/deletion.
- Reason: This balances useful personalization with resistance to memory pollution.

The field-level authority contract is frozen as follows:

| Field / memory kind | Authoritative source | Model candidate allowed | Auto-promotion | Scope / expiry | Current-turn precedence and deletion |
| --- | --- | --- | --- | --- | --- |
| `risk_level` | Explicit user command, UI/API edit, or user confirmation | Yes | Never | Persistent until superseded/deleted | Current explicit instruction wins for the turn; deletion makes it immediately non-effective |
| `investment_horizon` | Explicit user command, UI/API edit, or user confirmation | Yes | Never | Persistent until superseded/deleted | Current explicit instruction wins; old inferred candidates cannot restore it |
| `expected_return_min/max` | Explicit user command, UI/API edit, or user confirmation | Yes | Never | Persistent until superseded/deleted | Current explicit instruction wins; numeric validation is mandatory |
| `sectors`, `watchlist` | Explicit user command, UI/API edit, or user confirmation | Yes | Never | Persistent and item-addressable until superseded/deleted | Current entity does not mutate these fields implicitly; deletion is owner-scoped |
| Real holdings/positions | Portfolio/account domain only | No Memory authority | Never | Governed by the Portfolio/account source of truth | Memory cannot overwrite, infer, or expose these as account facts |
| `user_reported_position_context` | Explicit user statement or confirmation | Yes, as labelled text context only | Never | Time-bounded and source-labelled | Cannot act as portfolio truth, market evidence, valuation input, or tool authorization |
| Persistent financial constraints | Explicit user command, UI/API edit, or user confirmation | Yes | Never | Persistent until superseded/deleted | Current-turn/session Working State overrides without silently rewriting LTM |
| Current `constraints` | Current user message through validated Working State extraction | Not an LTM candidate by default | Not applicable | `this_turn` or `session_segment`; deterministic expiry | Current explicit wording wins; expiry/clear produces an audit event |
| Current `reply_preference_hint` | Current user message through validated Working State extraction | May seed a text-memory candidate | Never as structured profile | `this_turn` or `session_segment`; deterministic expiry | Current explicit wording wins over any older preference |
| Text response preference | Explicit user command, or repeated user-side evidence | Yes | Allowed only after deterministic repeat/unique-context/recency/conflict gates | Bounded scope; expires or is superseded by policy | Current hint wins; visible targeted deletion disables retrieval immediately |
| Text topic interest | Explicit user command, or repeated user-side evidence | Yes | Allowed only with topic/entity/task scope and the same deterministic gates | Bounded time/topic scope; expires or is superseded | Cannot change active entity or expand tools; visible targeted deletion disables retrieval immediately |

Assistant text, tool output, market data, and unsupported summary claims may provide debugging context but can never independently establish or promote any field above. Portfolio/account data remains outside the Memory authority boundary.

### P1-04 — Retention and deletion baseline

- Default: Confirmed profile/text memories remain until user deletion or supersession. Unpromoted candidates default to 30 days, auto-promoted inferred text to 90 days, pending destructive confirmations to 10 minutes, and safe audit metadata to 180 days; all are typed settings with validation. Deletion removes active retrieval immediately and schedules provider/vector hard deletion with durable retry. Audit records never retain deleted raw private content.
- Reason: These values create reproducible project behavior without pretending to be legal or production SLA requirements. Deployment-specific retention, encryption-at-rest, backup erasure, export, and hard-delete SLA remain a separate policy decision.

### P1-05 — Report-mode boundary

- Default: Conversation and report mode share domain contracts and authoritative repositories. This delivery activates, tests, and accepts memory injection only in the controlled conversation path. Report-mode injection and report E2E require a later separately scoped milestone; no duplicate report-only memory runtime may be created.
- Reason: The user's immediate target is the controlled conversation mainline. Making the deferred runtime boundary explicit prevents the plan from claiming report behavior that it does not verify while shared ownership prevents later divergence.

### P1-06 — Quality thresholds

- Default: Historical metrics are hypotheses only. Initial milestones establish reproducible baselines; numeric CI gates are frozen only after the target-repository dataset and runner produce evidence.
- Reason: Unsupported historical percentages cannot serve as engineering or interview claims.

### P1-07 — Live-test namespace and cleanup

- Default: Protected live tests create dedicated `e2e-memory-*` users, sessions, tasks, Redis keys, and vector records; they verify cleanup and fail the run if residual active data remains.
- Reason: Real providers are authorized, but production user data and uncontrolled writes are not.

## 4. P2 Decisions Deferred Without Blocking Implementation

- The final numeric latency, cache-hit, extraction-precision, promotion-precision, and retrieval-relevance targets are deferred until baselines exist.
- A user data export format is deferred; inspect/correct/delete/forget remains required.
- Multi-region Redis/PostgreSQL deployment, production autoscaling, and production disaster recovery are deferred; local/CI Compose reliability and rollback remain required.
- Report-mode memory injection and full report-mode E2E are deferred to a separately scoped milestone; this program verifies only shared contracts/repositories and the controlled-conversation runtime.

## 5. Required Solution-Tradeoff Questions

The solution phase must decide, with official and repository evidence:

1. How project-owned PostgreSQL governance records map to Mem0 IDs and pgvector storage without dual authority.
2. Whether Mem0 should use its supported PostgreSQL/pgvector backend directly or sit behind a project adapter with a separate governed index lifecycle.
3. Which Redis data structures, TTL/version format, invalidation rules, and lease semantics satisfy fail-open cache behavior.
4. How durable PostgreSQL outbox tasks, Redis worker coordination, retries, idempotency, and stuck-task recovery interact.
5. Which hybrid retrieval stages are deterministic filters, lexical recall, vector recall, reranking, and token-budget packing.
6. How natural-language memory commands are distinguished from ordinary financial questions and authorized before mutation.
7. How compaction, extraction, embedding, retrieval, mutation, deletion, and forgetting are represented in logs, traces, metrics, and redacted artifacts.
8. Which dependency versions, migrations, Compose services, health checks, offline fakes, and live gates are supportable in the current repository.

## 6. Handoff

Proceed to `SOLUTION_TRADEOFF.md`. No business code, dependency installation, database migration, or runtime configuration change is allowed until the tradeoff is complete and `PLAN.md` freezes the selected direction.
