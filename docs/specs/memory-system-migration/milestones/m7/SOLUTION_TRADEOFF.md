# SOLUTION_TRADEOFF.md

## 1. Tradeoff Context

M7 需要在不改变 M0-M6 受控金融主链的前提下，增加可审查的自然语言记忆命令、持久化确认、统一 API/WebSocket 结果和前端控制。核心矛盾是：现有旧 memory router/service 已能 CRUD，但其返回和确认语义不足以证明 M5/M6 的 authority、审计、派生一致性、跨会话确认和幂等约束。

## 2. Inputs Reviewed

- REQUIREMENT_SPEC.md: `docs/specs/memory-system-migration/milestones/m7/REQUIREMENT_SPEC.md`
- CODEBASE_RECON.md: `docs/specs/memory-system-migration/milestones/m7/CODEBASE_RECON.md`
- CLARIFICATION_QUESTIONS.md: 本目录，P0/P1 已按安全默认值解决。
- User decisions: 用户授权在不破坏既有功能和完整验收前提下自行决策，要求企业级 GitHub/CI/PR/merge 闭环和真实 Docker E2E。
- External sources: Mem0 OSS `Memory` implementation, LangGraph `types.py` interrupt/Command contracts, OWASP Transaction Authorization Cheat Sheet。

## 3. User Decisions and Defaults

### 3.1 Confirmed Decisions

- deterministic Chinese parser v1；未明确命令不执行副作用。
- PostgreSQL authority 表保存 pending command；Redis/pgvector/Mem0 只能派生。
- pending confirmation 绑定用户、会话、范围快照、指纹、版本和 TTL，一次性消费。
- 旧记忆写 API 收口到同一 authority application contract，保留兼容路径和响应字段。
- REST/WS 使用 additive `memory_command` 结果合同。
- Vitest + Vue Test Utils + Playwright，默认离线/合成数据。

### 3.2 Conservative Defaults Used

- 宽范围 forget 默认“当前用户全部 active 文本记忆”，先预览后确认。
- pending TTL 600 秒；安全元数据默认保留 180 天。
- 受限正文片段最大 160 字符；宽范围预览最多展示 5 条片段。
- 高影响 profile 字段仍 confirmation-only。

### 3.3 Blocking Decisions

None. Remaining P2 choices are deferred and do not block Plan Freezing.

## 4. Core Decision Point

选择记忆命令是继续扩展旧 CRUD 路由、在聊天入口旁边增加独立状态机，还是引入完整 Agent/HITL 框架；同时确定旧写路径如何统一到 M5/M6 authority。

## 5. Reference Sources and Repository Evidence

### 5.1 Official Docs

#### Source: OWASP Transaction Authorization Cheat Sheet

**Link:** https://cheatsheetseries.owasp.org/cheatsheets/Transaction_Authorization_Cheat_Sheet.html

**What was inspected:** significant transaction data must be shown to and acknowledged by the user; server-side enforcement; sequential state transitions; protection against replay/TOCTOU; limited validity window and unique authorization per operation。

**Relevant practice:** confirmation preview must be server-generated from frozen significant data, authorization must be checked again at execution, state transitions must not be skippable, and authorization expires.

**Reusable part:** Directly reusable

**Fit for this task:** forget/delete is a destructive transaction even though it is not a payment. The same server-side, one-shot, time-bounded and frozen-scope principles apply.

#### Source: LangGraph typed interrupt/Command contract

**Link:** https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/types.py

**What was inspected:** `Interrupt`, `Command(resume=...)`, `thread_id`-oriented checkpoint assumptions and the requirement that interrupt/resume depends on persisted state.

**Relevant practice:** human confirmation is represented as a resumable state transition with persisted thread identity, not as an untrusted client boolean.

**Reusable part:** Conceptual only / Partially reusable

**Fit for this task:** M7 already has PostgreSQL sessions and a custom controlled workflow; importing LangGraph runtime would be excessive. We reuse the persisted interrupt/resume idea through a project-owned pending command table.

### 5.2 Open-source Repositories

#### Source: Mem0 OSS Memory implementation

**Link:** https://github.com/mem0ai/mem0/blob/main/mem0/memory/main.py

**What was inspected:** entity scope validation for `user_id`/`agent_id`/`run_id`, rejection of identity fields in free-form metadata, validation of search query/top-k/threshold, and separate add/search/update/delete/history operations.

**Relevant practice:** identity scope must be supplied through validated entity parameters rather than caller-controlled metadata; query and pagination parameters are validated before provider calls.

**Reusable part:** Directly reusable for boundary validation; partially reusable for provider semantics.

**Fit for this task:** M7 should preserve the local PostgreSQL authority but apply the same strict identity/scope validation before any derived provider/cache action.

#### Source: LangGraph OSS typed runtime

**Link:** https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/types.py

**What was inspected:** `Interrupt` carries a stable ID/value; `Command` separates resume from graph update/goto; `interrupt()` documents re-execution and checkpointer dependence.

**Relevant practice:** stable interrupt identity and explicit resume operation make replay and state transitions testable.

**Reusable part:** Conceptual only

**Fit for this task:** The local use case should remain framework-independent and use a database-backed typed contract; only the state-machine principles are retained.

### 5.3 Local Project Patterns

| Local pattern | Evidence from CODEBASE_RECON.md | How to reuse |
| --- | --- | --- |
| Shared REST/WS application result | `ChatCommand`/`ChatOutcome` | Add optional memory command result and keep presenters thin |
| Authority + derived consistency | `AuthorityMutationResult` and M6 retrieval | Return authority status separately from pending/partial provider state |
| Caller-owned transaction | authority/conversation repositories | Commit pending/audit/authority/outbox atomically |
| Versioned migrations | Alembic M2-M6 revisions | Add expand-first pending schema with upgrade/downgrade parity |
| Typed settings and deterministic CI | `backend/config.py`, offline Compose | Keep parser/TTL/range constants versioned and safe by default |
| Safe trace attributes | controlled workflow/M6 context trace | Emit stage/status/count/error fields only |

## 6. Reusable Patterns

### 6.1 Directly Reusable Patterns

- Existing authority repository ownership and transaction boundary.
- Existing `ChatCommand`/`ChatOutcome` protocol-neutral contract.
- Existing user-scoped composite SQL filters and provider post-filtering.
- Existing Outbox idempotency, lease and failure state conventions.
- OWASP server-generated preview, sequential authorization, expiry and replay protections.

### 6.2 Partially Reusable Patterns

- Mem0 identity/query validation: reuse boundary rules, but do not let Mem0 own command authority.
- Existing legacy memory endpoints: retain route compatibility while routing writes through the new application contract.
- Existing frontend optimistic composable: retain Pinia shape where useful, but replace optimistic success with pending/success/error state.

### 6.3 Conceptual References Only

- LangGraph interrupt/checkpoint/resume semantics: useful model for pending confirmation, but no runtime replacement.
- Full HITL or event-sourcing frameworks: useful vocabulary, too heavy for this repository's single-service topology.

### 6.4 Not Suitable for This Iteration

- Independent Mem0 service or external workflow engine.
- Client-controlled `confirm=true` as the authorization source.
- LLM-only parser for destructive actions.
- Redis-only pending token or in-memory confirmation state.

## 7. Solution Options

### 7.1 Option A: Minimal Fix

**What changes:** Add a small parser in the existing chat route and call existing memory service methods; add a boolean confirmation branch for delete-all.

**What does not change:** Existing routes, legacy service, database schema, frontend state and M6 code remain mostly unchanged.

**Benefits:** Lowest initial code cost and quick demo path.

**Costs:** Duplicates authority semantics, leaves ad hoc response shapes, cannot prove replay/cross-session/version safety, and keeps old direct write path.

**Risks:** High risk of destructive bypass, route/workflow coupling, and regression hidden behind green happy-path tests.

**Testing burden:** Low initial, but difficult to prove full requirement; broad negative/E2E gaps remain.

**Rollback difficulty:** Medium because parser side effects would be distributed through legacy service.

**Engineering impact:**

- Architecture/module ownership: route owns too much orchestration; violates target boundary.
- Documentation/types: likely ad hoc dicts and booleans.
- Configuration/secrets/prompts: little change, but versioning weak.
- Terminal/logging/tracing/artifacts: partial command logs, no durable lifecycle.
- Errors/retry/state: boolean confirmation and no durable state machine.

**When to choose it:** Only for a disposable demo, explicitly contrary to the current enterprise-quality requirement.

### 7.2 Option B: Structured Improvement

**What changes:** Add a typed memory command application boundary, deterministic parser/preflight, PostgreSQL pending-command authority, shared REST/WS result mapping, and frontend pending/confirmation state; route legacy writes through authority while preserving compatible paths.

**What does not change:** Controlled finance workflow, Planner/Permission/Evidence, M5 candidate governance, M6 retrieval/provider boundaries, and default offline topology remain intact.

**Benefits:** Satisfies observable command/confirmation behavior, keeps one source of truth, supports rollback, and fits existing repository/application/contracts patterns.

**Costs:** Requires one migration, new contracts/use case/repository tests, frontend test dependencies and a real Compose journey.

**Risks:** Chat transaction ordering and legacy compatibility need careful integration; broad deletion semantics require precise snapshot/version handling.

**Testing burden:** Medium/high but proportional: unit state machine, database/API isolation, REST/WS contract, frontend tests, and Docker E2E.

**Rollback difficulty:** Low/medium with expand-first migration, feature flag/command parser gate, and authority data retained.

**Engineering impact:**

- Architecture/module ownership: parser/contracts/application/infrastructure/presenters/frontend remain explicit.
- Documentation/types: versioned command/response/pending schemas and Google-style docs.
- Configuration/secrets/prompts: typed parser version, TTL, range limits, safe `.env.example`; no new secret.
- Terminal/logging/tracing/artifacts: safe command stage/status/count/reference fields; no content.
- Errors/retry/state: explicit pending state machine, server-side final authorization, idempotency, bounded derived retries.

**When to choose it:** Current M7; it is the smallest direction that can withstand the user's stated interview and enterprise-process expectations.

### 7.3 Option C: Long-term Architecture Direction

**What changes:** Replace or wrap the controlled workflow with a general LangGraph/HITL graph, persistent checkpointer, command interrupts, event-sourced memory mutations, and a dedicated frontend command protocol.

**What does not change:** User-facing goals remain, but most orchestration and persistence boundaries would change.

**Benefits:** General reusable human-in-the-loop framework and richer pause/resume semantics.

**Costs:** Large rewrite, new operational dependency, migration of existing workflow/tests, higher CI/runtime complexity.

**Risks:** Violates M7 scope, can regress financial evidence/tool governance, and makes rollback/data compatibility difficult.

**Testing burden:** Very high; requires graph parity, checkpoint recovery, protocol and multi-service testing.

**Rollback difficulty:** High.

**Engineering impact:**

- Architecture/module ownership: new workflow runtime would compete with existing controlled mainline.
- Documentation/types: many new contracts and framework-specific state types.
- Configuration/secrets/prompts: new checkpointer/provider settings and deployment dependencies.
- Terminal/logging/tracing/artifacts: framework events would need redaction mapping.
- Errors/retry/state: framework semantics could conflict with current custom transaction/outbox rules.

**When to choose it:** Defer to a separately approved architecture program, not M7.

### 7.4 Option D: Observation-first Option

**What changes:** Add parser characterization, command fixtures and trace-only detection without side effects; observe false positives/negatives before enabling writes.

**What does not change:** No user-visible memory mutation or frontend confirmation path.

**Benefits:** Lowest data-integrity risk and strongest evidence for parser coverage.

**Costs:** Does not meet the user's requirement to complete the memory command capability in this milestone.

**Risks:** Delays value and leaves existing unsafe/insufficient CRUD confirmation behavior in place.

**Testing burden:** Low/medium.

**Rollback difficulty:** Low.

**Engineering impact:** Good observability but incomplete functional contract.

**When to choose it:** Use as the first sub-milestone/test layer inside Option B, not as the final M7 direction.

## 8. Decision Matrix

| Dimension | Option A Minimal Fix | Option B Structured Improvement | Option C Long-term Architecture | Option D Observation-first |
| --- | --- | --- | --- | --- |
| Scope | Small but incomplete | M7-complete | Far beyond M7 | Incomplete |
| Development Cost | Low | Medium | Very high | Low/medium |
| Risk | High destructive/compatibility risk | Controlled and testable | High migration risk | Low data risk |
| Reusability | Low | High within current repo | High future, low immediate fit | Medium |
| Fit to Current Requirement | Poor | Strong | Poor | Partial |
| Local Pattern Fit | Poor | Strong | Poor | Strong |
| Test Burden | Misleadingly low | Proportional/high | Very high | Medium |
| Rollback Difficulty | Medium | Low/medium | High | Low |
| Long-term Maintainability | Low | Strong | Potentially strong but expensive | Strong but incomplete |
| Engineering-standard fit | Poor | Strong | Over-engineered | Strong but not deliverable |
| Recommendation | Reject | **Select** | Defer | Use as B's first evidence layer |

## 9. Recommended Solution

Selected option: Option B, with Option D observation-first tests at the start of the implementation milestone.

Why selected: It is the smallest architecture that satisfies the explicit safety and enterprise-process requirements. It reuses existing contracts, authority repository, Outbox, Trace, typed Settings and Compose test topology instead of introducing a second orchestrator or external HITL runtime.

Why not the other options:

- Option A cannot prove one-shot, server-authorized, cross-session/version-safe confirmation and would preserve the authority split.
- Option C is a framework migration that is explicitly out of scope and threatens the stable controlled finance path.
- Option D alone provides evidence but does not deliver the requested user-visible memory operations.

Local patterns reused: `ChatCommand/ChatOutcome`, caller-owned transactions, `AuthorityMutationResult`, M5 candidate confirmation, M6 provider references/Outbox, typed Settings, safe Trace and deterministic Compose.

External practices reused: Mem0 identity/query validation; OWASP server-side transaction authorization, frozen significant data, sequential states, expiry and replay prevention; LangGraph only as conceptual terminology for persisted resumable state.

Remaining risks: old memory service compatibility, exact prepare-turn transaction ordering, frontend package/CI duration, and broad deletion preview privacy.

What must be verified later: unit state machine, migration parity, REST/WS contract, ordinary finance no-tool branch, cross-user/session/version/replay negatives, real Postgres/Redis/derived deletion, frontend component/browser journey, full Compose and GitHub CI.

## 10. Unified Technical Direction

在 `backend/application/memory` 和 `Financial-MCP-Agent/src/memory` 建立版本化 typed command/result/pending 状态合同；在 chat application 的 `prepare_turn` 后、retrieval/finance workflow 前执行 deterministic preflight，命令终态直接返回并阻断 Planner/Permission/Execute。由 PostgreSQL 新增可审查的 pending command authority 和 Alembic migration，调用现有 authoritative repository、audit、Outbox、Redis invalidation 与 M6 derived provider；所有 REST/WS 及前端只消费同一结果合同，旧 memory 路由保留兼容路径但写入收口到 authority。加入状态机、事务、所有权、重放、版本、过期、普通金融回归、前端组件和真实 Docker Compose E2E 证据。不得引入独立 Mem0/HITL 服务、LLM-only destructive parser、Redis-only confirmation 或修改 planner/evidence/production/live provider；日志只保留 stage/status/error/count/reference。

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Parser false positive | Versioned allowlist, ambiguous clarification, no model default, characterization dataset |
| Delete scope TOCTOU | Server-generated frozen target snapshot, expected version checks, final authorization before mutation |
| Replay/cross-user confirmation | Unique command ID/fingerprint, auth/session binding, row lock, terminal-state rejection |
| Legacy write bypass | Route all M7 touched writes through authority use case; add contract test that no direct Mem0 write occurs |
| Finance workflow contamination | Explicit command terminal outcome and `tool_call_count=0`/stage-negative tests |
| Derived lag | Return consistency status, INDEX Outbox retry/dead-letter, authoritative post-filter |
| UI drift | Shared TS contract and browser/API E2E |
| Private data leakage | Redacted preview, no command/content logs, synthetic fixtures, secret/generated scan |

## 12. Verification Direction

### 12.1 Engineering Contract for Plan Freezing

- Architecture/module ownership: API/WS thin; parser/application owns command orchestration; domain contracts own state/error enums; infrastructure owns SQL/locks/outbox/derived; frontend owns presentation state.
- Interfaces/docstrings/types: typed `MemoryCommandIntent`, `PendingMemoryCommand`, `MemoryCommandResult`, stable status/error enums, Google-style docs, additive REST/WS schemas.
- Configuration/secrets/constants/prompts: parser/schema version, 600-second TTL, deletion/preview limits and feature flag in typed Settings; safe `.env.example`; no credentials or live provider defaults.
- Terminal/logging/tracing/artifacts: command stage/status/error/count/latency/reference; no command text, memory body, user ID, token or raw provider payload.
- Validation/errors/retry/state: fail-closed ownership/scope/value checks; server-side final authorization; one-shot pending state; bounded retries only for derived providers; explicit `PENDING/PARTIAL/DEGRADED`.
- Tests/evaluation/delivery evidence: focused unit/contract/integration/eval/frontend/browser tests, full root regression, exact offline Compose E2E, CI, review, PR and merge report.

## 13. Deferred Work

- LLM-based parser quality and multilingual commands.
- Real Mem0/provider/live-model command extraction.
- General LangGraph/HITL runtime or checkpointer replacement.
- Full report-mode memory commands/injection, exports, multi-region and production compliance.
- Production latency/SLA and high-volume deletion soak.

## 14. Handoff to Plan Freezing

Next step should use the Plan Freezing Skill and produce a self-contained M7 `PLAN.md`/milestone section.

The plan should:

- follow selected option: Option B with an observation-first test layer;
- allow modules/files: M7 memory application/domain contracts, chat application contracts/use case/factory, memory router/schemas, authority repository/models/migration, frontend API/store/composable/memory UI, tests/evals/Compose/CI/docs;
- forbid modules/files: planner/permission/evidence/tool implementations, old direct Mem0 client, production `.env`, live provider activation, unrelated frontend or report refactor;
- include required tests: command parser/state, API/WS, transactions/migration, ownership/replay/version/expiry, normal finance path, frontend component/browser and Docker E2E;
- include required logs/metrics: safe stage/status/error/count/reference/duration fields;
- include rollback strategy: feature flag off, stop command branch, preserve authority/audit, downgrade only isolated migration with explicit authorization, rebuild derived indexes;
- preserve constraints: PostgreSQL authority, M5/M6 boundaries, no paid/production default tests, no sensitive logs, GitHub Issue/branch/PR/CI/review/merge;
- keep these external references in mind: OWASP Transaction Authorization, Mem0 identity validation, LangGraph persisted interrupt/resume concepts.
