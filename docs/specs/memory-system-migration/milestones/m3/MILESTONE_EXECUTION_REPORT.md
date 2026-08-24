# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: 3 — Working State, Token Budget, and Rolling Summary Mainline
- Issue: [#28](https://github.com/even9277/Finance-agent-Skills/issues/28)
- Branch: `feat/28-memory-stm-mainline`
- Status: Local implementation, acceptance, and independent review complete; GitHub delivery pending
- Date: 2026-08-25

## 2. Development Standards Read

- `PLAN.md`: Read completely; M3 was the first unchecked milestone and Redis/LTM/Mem0/UI work remained forbidden.
- Personal and repository `AGENTS.md`: Applied the Spec Coding chain, one-milestone execution, typed boundaries, Chinese documentation, safe settings/secrets, offline-default tests, independent review, CI, and rollback rules.
- `CONTRIBUTING.md`: Applied Issue/branch, validation, offline Compose, review, and squash-merge requirements.
- `C:\Users\27411\.codex\PYTHON_AGENT_ENGINEERING_STANDARD.md`: Applied application/domain/infrastructure separation, transaction ownership, typed state, bounded retries, structured logs, and evaluation requirements.
- `small-step-implementation/SKILL.md` and its development, execution, testing/failure, diff/commit, and report references: Read completely.
- Nested instructions: No stricter `AGENTS.override.md`, nested `AGENTS.md`, `CLAUDE.md`, Cursor rule, or Copilot instruction was found in the changed scope.

## 3. Files Inspected

- Controlled path: `Financial-MCP-Agent/src/conversation/**`, chat application ports/use case, SQLAlchemy chat repository, REST/WebSocket construction path, and fake provider implementations.
- Memory path: `Financial-MCP-Agent/src/memory/**`, backend memory ports/repository, session/message/summary/Outbox models, legacy STM context/support/worker code, settings, and startup lifecycle.
- Verification path: memory unit/contract/integration/eval tests, offline Compose E2E, Dockerfiles, Compose manifests, CI, frontend gates, and migration safety/packaging files.
- Frozen requirements, reconnaissance, clarification, trade-off, `PLAN.md`, prior milestone reports, and supplied short-/long-term-memory interview documents remained the behavior and narrative evidence.

## 4. Files Modified

- `Financial-MCP-Agent/src/memory/contracts.py`, `working_state.py`: Added narrow typed state updates/transitions, field operations/events, summary task payload, idempotency key, and deterministic reducer.
- `Financial-MCP-Agent/src/conversation/{context,entity,constraints,preferences,rewriting,workflow,contracts}.py`: Injected typed Working State into controlled stages, implemented follow-up inheritance/current-input precedence, and returned auditable state updates.
- `backend/application/chat/{ports,use_case}.py`, `backend/application/memory/{ports,context,summary}.py`: Added state/CAS and post-commit compaction seams, context budget policy, summary request/draft validation, and foreground-safe degradation.
- `backend/infrastructure/chat/{repository,testing}.py`, `backend/infrastructure/memory/{repository,summary}.py`: Persisted state events and summary Outbox tasks, applied source/owner/version checks, and added deterministic/OpenAI-compatible summary providers behind typed settings.
- `backend/services/stm_compaction_worker.py`, `stm_context_service.py`: Rebuilt compaction around the unified Outbox, versioned metadata, protected boundaries, bounded retry/dead-letter/stale handling, last-good semantics, and safe logs; retained only context metrics in the legacy context module.
- `backend/services/stm_compaction_support.py`: Removed the obsolete legacy queue/profile-from-summary helper; no compatibility queue or dual-write remains.
- `backend/config.py`, `backend/.env.example`, `docker/docker-compose.offline.yml`: Added validated summary/budget settings and an explicitly deterministic offline E2E configuration with empty live credentials.
- `.github/workflows/ci.yml`: Replaced the removed helper path with every maintained M3 module in Ruff/Pyright gates.
- Memory unit/contract/integration/eval/E2E files: Added state, budget, boundary, valid/failure/stale Worker, concurrency, and full-stack assertions; promoted only the M3 compaction tripwire to supported.
- `docs/specs/memory-system-migration/PLAN.md` and this report: Recorded decisions, discoveries, evidence, risks, and M4 handoff.

## 5. Implementation Summary

The public controlled-chat use case now loads a PostgreSQL-authoritative, versioned Working State before the workflow. Explicit current entities, constraints, reply preferences, and clear instructions become narrow typed updates; pronoun follow-ups may inherit the current entity, but inherited data remains `NOOP` and cannot masquerade as new evidence. The memory repository applies actual field changes with state-version CAS and writes same-version field events in the foreground chat transaction. The current user message continues to outrank every inherited value.

Context packing reserves response, safety, and stage overhead before selecting history. It always keeps the current request, then a contiguous newest raw-message suffix, then the last-good summary only if space remains. Explicit new-topic commands expire inherited session-segment entity, constraint, and reply-preference fields with auditable `EXPIRE` transitions. After the foreground turn commits, the repository may enqueue one idempotent `SUMMARY_COMPACT` Outbox task with frozen source/protected-tail boundaries, expected summary version, prompt version, token estimate, and trace ID. Enqueue failure is logged and rolled back without reversing the committed answer.

The summary Worker is the only new compaction consumer. It validates task ownership, redundant persisted identity, JSON types, summary version, source rows, real protected-tail start, model output, prompt/boundary/count contracts, and protected-tail separation. Every claim receives a unique fencing token; an expired task can be reclaimed, while a late old Worker cannot mutate the new claim's task or summary terminal state. A valid draft writes the snapshot, metadata, compressed flags, task terminal state, and summary-version CAS together. Provider failure retries finitely or dead-letters without overwriting last-good; stale work is cancelled and recorded as `STALE`. The removed legacy helper can no longer infer and write long-term profile fields from summaries.

## 6. Diff Summary

- No dependency, database schema, public HTTP/WebSocket response, authentication, production deployment, or frontend feature contract changed.
- New settings are typed, documented in `.env.example`, and deterministic in offline Compose; no real `.env` or credential was copied.
- No Redis, Mem0, pgvector, candidate governance, memory command/UI, compatibility adapter, duplicate summary queue, or production write was added.
- Logs contain stable stage/status/error/task/trace/version/count fields and do not contain message, prompt, summary, profile, or credential text.

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
| --- | --- | --- |
| `uv lock --check` | Lock reproducibility and no dependency drift | Passed; 102 packages resolved |
| Changed-scope `ruff check ...` | Maintained M3 lint gate | Passed; zero findings |
| Changed-scope `pyright ...` | Maintained M3 type gate | Passed; zero errors/warnings |
| Focused M3 unit/integration/eval command | State, budget, compaction, transaction, provider bootstrap/config, fencing/tamper, and STM eval | Passed: 48 |
| `pytest backend -q` | Backend regression | Passed: 11 |
| `pytest Financial-MCP-Agent -q -m "not live"` | Agent regression without live providers | Passed: 33; 4 live deselected |
| `pytest tests/evals -q -m "eval_smoke and not live"` | Deterministic offline eval gate | Passed: 19 |
| `pytest -q` | Default root regression over the final diff | Passed: 191 passed, 2 skipped, 5 live deselected, 6 intentional strict xfails |
| `npm run lint`, `npm run type-check`, `npm run build` | Frontend regression and production bundle | Passed; existing large-chunk warning only |
| Both `docker compose ... config --quiet` commands | Production/offline manifest validation | Passed |
| Rebuilt offline Compose command | PostgreSQL/Alembic/FastAPI/Worker/Nginx/Vue/HTTP/DB E2E over the final diff | Passed: 114 passed, 1 skipped, 16 deselected, 6 intentional strict xfails |
| `docker build -f docker/Dockerfile.backend ...` and import smoke | Normal runtime packaging | Passed; Alembic, summary adapter, and summary Worker import successfully |
| Broad `ruff check . --statistics` / Pyright JSON summary | Visible legacy/vendor debt inventory | 112 Ruff errors; 79 Pyright errors and 6 warnings, all outside maintained M3 paths |
| `git diff --check` and manual diff/config/log/secret/artifact review | Delivery hygiene | Passed before independent review |

## 8. Test Results

- Passed: deterministic state set/merge/clear/expire/no-op/version/events; typed entity follow-up, explicit switch, and new-topic expiry; instruction precedence; bounded contiguous context; summary schema/source/protected-tail validation; foreground transaction and post-commit durable task; provider bootstrap/config; valid, provider-failed, stale, reclaimed, fenced, and tampered-task Worker behavior; five-case offline STM eval; full regressions and rebuilt Compose.
- E2E evidence: A real isolated PostgreSQL database accepted the migrated schema and durable rows; Nginx proxied the public HTTP chat journey to FastAPI; concurrent turns produced isolated `TURN_COMMITTED` tasks; the deterministic Worker wrote a versioned summary covering only a frozen prefix while preserving the recent raw tail; downgrade/re-upgrade preserved legacy chat rows.
- Not run: Protected Live E2E, real paid/free LLM, real Tushare, Mem0, Redis, pgvector, or production service/write. They are outside M3 and remain explicitly gated.
- Warnings: Existing Starlette/httpx, naive-UTC, and frontend bundle-size warnings remain visible; six strict xfails map to later memory milestones.

## 9. Failures and Fixes

### JSON boundary typing

- Failure: Initial changed-scope Pyright reported JSON `object` values passed through implicit `int`/`str` conversion.
- Root cause: A persisted JSON boundary had domain validation but insufficient static/runtime narrowing.
- Fix: Added strict integer/text field readers that reject booleans, strings-as-integers, and wrong JSON types; removed an unused import and narrowed test values explicitly.
- Rerun: Changed-scope Ruff and Pyright both reported zero findings.

### First rebuilt Compose run

- Failure: Compose reported 2 failed, 102 passed because an integration test counted a summary task as a turn task and E2E hard-coded one scheduler timing outcome.
- Root cause: `ENABLE_STM=true` correctly activated background compaction inside the shared E2E container, while assertions assumed STM was absent or always claimed the earliest eligible two-message prefix.
- Fix: Filtered the transaction test to its owned `TURN_COMMITTED` rows and rewrote E2E acceptance around invariant evidence: current summary-version linkage, source/protected-tail separation, compressed/source equality, retained raw tail, and independent task counts.
- Intermediate rerun: Before the final independent-review hardening, the rebuilt full stack passed with 104 passed, 1 skipped, 7 live deselected, and 6 intentional xfails. The final post-remediation run is the 114-pass result recorded above.

### Independent review hardening

- Findings: Review identified orphaned `PROCESSING` tasks, missing claim fencing, asynchronous provider bootstrap failure, an unsafe fixed lease/timeout relationship, over-broad failure attribution, stale documentation evidence, non-expiring session-segment fields, and insufficient persisted-task identity/protected-tail checks.
- Fixes: Added expired-lease reclaim, a unique per-claim token fenced across load/apply/failure/cancel, synchronous provider construction, positive typed runtime settings plus lease safety validation, precise error codes and trace IDs, explicit new-topic `EXPIRE` transitions, and fail-closed redundant identity/source/tail validation. The normal-image CI smoke now imports the new production Worker and summary adapter.
- Rerun: Changed-scope Ruff/Pyright were zero; 48 focused tests, 191 root tests, the regular-image smoke, and 114 rebuilt Compose tests passed on the final implementation.

## 10. Scope Compliance

- Exactly one milestone executed: Yes, M3 only.
- Allowed files only: Yes; all changes belong to memory domain/application/infrastructure, controlled context/workflow, worker/settings, verification, CI, or milestone governance.
- Forbidden M4+ work avoided: Yes; no Redis, LTM candidate/promotion, Mem0/pgvector, command UI, or broad observability upgrade.
- User work preserved: Yes; the branch began from clean merged `main` commit `df985a0` and no unrelated user change was reverted.
- Dependencies changed: No.
- API/database schema changed: No public API or schema delta; internal typed ports and safe settings changed as frozen by M3.
- Production/paid/external writes: None.
- Rollback: Revert the eventual single squash commit or disable the STM seam; authoritative messages and the prior M2 schema remain readable. Do not restore the legacy profile-from-summary mutation.

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
| --- | --- | --- |
| Architecture and dependency direction | Satisfied | Domain reducer and contracts -> application ports/policies -> SQLAlchemy/model adapters; use case owns foreground/background transaction boundaries |
| Docstrings, types, and field meaning | Satisfied | Immutable typed state/summary contracts, strict JSON boundary, Chinese responsibility/failure comments, zero changed-scope Pyright |
| Configuration, secrets, constants, prompts | Satisfied | One typed Settings source, versioned summary prompt, safe `.env.example`, deterministic Compose, no committed secret |
| Terminal output, logs, traces, artifacts | Satisfied for M3 | Stable `memory.compact` fields and trace ID; no raw user/model/profile payload in logs or Outbox |
| Validation, errors, retry/fallback, state | Satisfied | CAS, idempotency, owner/identity checks, frozen source and real protected tail, last-good, stale cancel, bounded retry/dead-letter, lease reclaim/fencing, foreground-safe enqueue failure |
| Tests, evaluation, and handoff evidence | Satisfied | Unit/contract/integration/eval/root/frontend/packaging/rebuilt PostgreSQL full-stack E2E |

## 12. Risks Remaining

- PostgreSQL is deliberately the only authority; Redis acceleration and optional hot-state coordination belong to M4.
- Candidate governance, long-term extraction, Mem0/pgvector retrieval, memory commands/UI, and final memory Trace/live-provider proof belong to M5-M9 and cannot yet be claimed from code.
- The Worker now retries, reclaims expired leases, and fences late claim owners; richer operational metrics and production multi-replica load evidence remain later hardening requirements.
- Application-startup migration still needs a dedicated migration job or advisory lock before multi-replica production.
- Broad legacy/vendor debt remains 112 Ruff and 79 Pyright errors plus 6 warnings; all maintained M3 paths are zero-error. Existing deprecation and bundle-size warnings remain tracked.

## 13. PLAN.md Updates

- Progress: Marked M3 complete locally with exact static, regression, packaging, and rebuilt Compose evidence.
- Decision Log: Recorded synchronous deterministic Working State, asynchronous unified-Outbox compaction, context precedence, frozen summary contracts, and removal of legacy dual behavior.
- Surprises & Discoveries: Recorded Compose scheduling variability, feature-flag test isolation, and the current broad debt inventory.
- Outcomes & Retrospective: Set Redis-only M4 as the next unchecked milestone and preserved all M5+ exclusions.

## 14. Suggested Commit Message

```text
feat(memory): activate STM and rolling summaries (#28)

- persist typed Working State transitions in controlled chat
- compact frozen history through the unified outbox worker
- verify budget, failure, concurrency, and PostgreSQL Compose E2E
```

## 15. Handoff to User

Milestone 3 local implementation, acceptance, and independent review are complete with zero P0/P1/P2 findings. GitHub CI/merge closure remains before delivery; do not begin Milestone 4 in this execution turn.
