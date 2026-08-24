# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: 2 — Typed Memory Domain, Versioned Migrations, and Transactional Outbox Foundation
- Issue: [#26](https://github.com/even9277/Finance-agent-Skills/issues/26)
- Branch: `feat/26-memory-domain-outbox`
- Status: Complete locally; GitHub delivery pending
- Date: 2026-08-25

## 2. Development Standards Read

- `PLAN.md`: Read completely; M2 was the first unchecked milestone and M3+ behavior remained forbidden.
- Personal and repository `AGENTS.md`: Read; enforced the Spec Coding chain, one milestone, typed boundaries, Chinese documentation, safe settings/secrets, offline defaults, Review/CI, and rollback evidence.
- `CONTRIBUTING.md`: Applied Issue/branch, validation, isolated Compose, review, and squash-merge rules.
- `PYTHON_AGENT_ENGINEERING_STANDARD.md`: Read completely; applied application/domain/infrastructure separation, transaction ownership, typed state, stable errors, structured persistence, and test evidence requirements.
- Small-step implementation skill and all referenced development, execution, testing/failure, diff/commit, and report instructions: Read completely.
- Nested development instructions: No more-specific `AGENTS.md`, `AGENTS.override.md`, `CLAUDE.md`, Cursor rule, or Copilot instruction was found in the changed scope.

## 3. Files Inspected

- Chat application/repository path: `backend/application/chat/**`, `backend/infrastructure/chat/**`, route/factory, and controlled workflow contracts.
- Existing database path: `backend/db/database.py`, `backend/db/models.py`, configuration, startup lifespan, and legacy incremental DDL.
- Existing memory path: `Financial-MCP-Agent/src/memory/**`, backend memory bridge/routes/schemas, STM context/worker/task models, and current profile/LTM behavior.
- Test and CI path: `.github/workflows/ci.yml`, `docker/docker-compose.offline.yml`, `docker/Dockerfile.e2e`, controlled-conversation tests, memory characterization/eval, and offline Compose E2E.
- Frozen requirements/recon/clarification/trade-off/plan artifacts and the two supplied memory interview documents were used as design evidence; historical `Finance` remained read-only.

## 4. Files Modified

- `Financial-MCP-Agent/src/memory/contracts.py`, `policy.py`, `__init__.py`: Added versioned typed memory contracts, stable enums/errors, safe Outbox payload, and high-impact authority policy.
- `backend/application/memory/**`: Added the caller-transaction memory repository port.
- `backend/infrastructure/memory/**`: Added SQLAlchemy Working State and Outbox persistence without internal commit/rollback.
- `backend/application/chat/contracts.py`, `use_case.py`, `backend/infrastructure/chat/repository.py`: Propagated typed Working State and placed user/assistant messages, state, and Outbox in one transaction.
- `backend/db/models.py`: Added eight normalized `memory-v1` ORM tables and their Alembic ownership list.
- `alembic.ini`, `backend/migrations/**`, `backend/db/migration_runner.py`: Added revision environment, additive revision `20260824_01`, runner, downgrade path, and operator notes.
- `backend/db/database.py`: Preserved legacy bootstrap, excluded Alembic-managed tables from `create_all`, upgraded the revision at startup, and replaced exception-swallowing PostgreSQL DDL with pre-inspection.
- `pyproject.toml`, `uv.lock`: Added only direct dependency `alembic>=1.14,<2`, resolved to 1.19.1 with Mako/MarkupSafe transitively.
- `tests/unit/memory/test_contracts.py`, `tests/integration/test_memory_migrations.py`, `tests/integration/test_memory_transactional_outbox.py`: Added domain, migration, legacy-read, atomicity, rollback, idempotency, owner isolation, constraint classification, and same-session concurrency acceptance.
- `tests/e2e/test_offline_compose_stack.py`: Added direct isolated-PostgreSQL evidence for Working State/Outbox, cross-user rejection, same-session concurrency, core ORM/revision schema parity, and downgrade/re-upgrade after the real HTTP turn.
- `backend/requirements.txt`: Added Alembic to the dependency source actually installed by the regular backend image.
- `.github/workflows/ci.yml`: Added every maintained M2 path to changed-scope static gates and a regular backend-image build/import smoke gate.
- Memory characterization/eval files: Converted only the typed Working State M2 tripwire to supported; seven later-milestone tripwires remain.
- `docs/specs/memory-system-migration/PLAN.md` and this report: Recorded governance, decisions, evidence, risks, and M3 handoff.

## 5. Implementation Summary

M2 establishes PostgreSQL as the memory authority without claiming later memory behavior. `memory-v1` defines typed Working State, field events, Rolling Summary metadata, authoritative records, candidates, audit events, Outbox tasks, provider references, commands, retrieval results, stable statuses, and stable error codes. High-impact profile fields cannot obtain inferred authority through the domain policy.

The foreground chat repository now uses the same `AsyncSession` for both messages, initial Working State, and a `TURN_COMMITTED` Outbox task. The memory repository only `flush`es; the chat repository exposes transaction methods, while the application use case decides when to `commit` or `rollback`. The Outbox payload contains session/message row identifiers and state version only—no message text, prompt, profile, credential, or provider payload. Cross-field validation plus authoritative session/message ownership checks prevent cross-user or cross-session task references, and a deterministic `(user_id, idempotency_key)` uniqueness contract prevents duplicate tasks.

Eight new tables are owned only by Alembic. A blank installation first creates legacy tables through the existing bootstrap, then applies revision `20260824_01`; existing installations skip present legacy columns safely and run the same revision. Downgrade is supported only for isolated development/test databases and removes only M2 tables. No production or user database was migrated.

## 6. Diff Summary

- Direct dependency delta: Alembic only; Redis, Mem0, pgvector, worker/provider activation, and Live configuration remain absent.
- Public HTTP request/response and frontend behavior are unchanged.
- No adapter, dual-write, compatibility runtime, old-provider activation, production deployment, `.env`, secret, generated trace, log, database, or cache artifact is included.
- New mainline tasks write only `memory_outbox_tasks`; legacy LTM tasks are not dual-written.

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
| --- | --- | --- |
| `uv lock --check` and `uv sync --locked --no-install-project --group dev` | Lock/install reproducibility | Passed; 102 packages resolved, Alembic 1.19.1 |
| `python -m py_compile ...` | New/changed Python syntax | Passed |
| Changed-scope `ruff check ...` | Maintained-scope lint gate | Passed, zero findings |
| Changed-scope `pyright ...` | Maintained-scope type gate | Passed, zero errors/warnings |
| Full `ruff check backend Financial-MCP-Agent/src tests` | Repository debt comparison | 81 existing errors, equal to frozen baseline |
| Full `pyright backend Financial-MCP-Agent/src tests` | Repository debt comparison | 80 existing errors and 6 warnings, equal to frozen baseline |
| Focused memory/domain/migration/transaction/eval tests | M2 behavior and remaining tripwires | Passed: 26 passed, 7 intentional strict xfails |
| `pytest tests/integration/test_memory_transactional_outbox.py -q` | Atomicity, rollback, idempotency, owner isolation, constraint classification, same-session concurrency | Passed |
| Controlled-mainline regression | Existing conversation behavior | Passed: 49 |
| `pytest backend -q` | Backend regression | Passed: 11 |
| Offline eval smoke | Deterministic evaluation | Passed: 14 |
| `pytest -q -rxX` | Default root regression, Live excluded | Passed: 152 passed, 2 skipped, 5 live deselected, 7 intentional strict xfails |
| Isolated `docker compose ... up --build --abort-on-container-exit --exit-code-from offline-e2e` | Nginx/FastAPI/PostgreSQL/Alembic/HTTP/DB/Trace E2E | Passed: 96 passed, 1 skipped, 7 intentional strict xfails; command and test container exited 0 |
| Direct Alembic invocation without target or downgrade authorization | Migration-target and destructive-operation safety | Both negative paths failed closed before schema mutation, as required |
| `docker build -f docker/Dockerfile.backend ...` plus image import smoke | Regular backend packaging | Passed; image imports Alembic 1.19.1 and `upgrade_database` |
| `alembic history` | Revision graph | Passed: `<base> -> 20260824_01 (head)` |
| Final independent read-only review | P0/P1/P2 and prior-finding closure | Passed; no remaining P0, P1, or P2; recommended commit/PR |
| `git diff --check`, dependency, commit-boundary, secret, and artifact review | Delivery hygiene | Passed before delivery closure |

## 8. Test Results

- Passed: Typed contracts and automatic authority policy; upgrade/downgrade/re-upgrade; PostgreSQL core ORM/revision parity; legacy session/message readability; successful atomic commit; full rollback on injected commit failure; deterministic duplicate rejection; same-session concurrency; cross-user and same-user cross-session State/Outbox rejection; stable constraint-error classification; regular backend packaging; controlled/backend/eval/root regressions; PostgreSQL Compose row-level E2E.
- Intentional xfail: Seven strict assertion-only tripwires owned by M3, M5, M6, and M7/M8. The M2 typed Working State tripwire is now an ordinary passing contract.
- Live/provider use: Not run. Compose explicitly set model/Tushare credentials empty, disabled Mem0/STM workers, and used fake model/tool ports with a real database/application/workflow path.
- Warnings: Existing Starlette/httpx and naive-UTC deprecations remain; no warning was converted into success or hidden.

## 9. Failures and Fixes

### PostgreSQL startup diagnostic

- Finding: The legacy incremental DDL caught duplicate-column exceptions, but PostgreSQL kept the surrounding transaction aborted and produced follow-on startup errors.
- Root cause: Catching a database exception in Python does not restore a failed PostgreSQL transaction.
- Fix: Inspect column existence before `ALTER`, translate legacy `DATETIME` declarations to PostgreSQL `TIMESTAMP`, and stop swallowing real cleanup errors.
- Rerun: PostgreSQL startup completed cleanly and Alembic applied the head revision.

### Compose assertion repairs

- Failure: The new PostgreSQL row assertion expected lowercase `turn_committed`, then lowercase `pending`.
- Root cause: The test duplicated enum values instead of consuming the stable domain contracts; persisted values were correctly `TURN_COMMITTED` and `PENDING`.
- Fix: Import `OutboxTaskKind`, `OutboxTaskStatus`, and `MEMORY_SCHEMA_VERSION` into the E2E test.
- Rerun: Exact Compose gate passed with 96 passed, 1 skipped, and 7 intentional xfails.

### Independent-review remediation

- Finding: The first independent review identified six release-blocking gaps: Outbox cross-field/owner authority, same-session first-state races, over-broad `IntegrityError` classification, unsafe Alembic target fallback, conflicting memory authority states, and incomplete PostgreSQL downgrade/schema proof.
- Root cause: The initial tests emphasized the successful transaction path and did not assert every tenant, concurrency, migration-operator, and persisted-contract invariant.
- Fix: Added domain cross-field validators, authoritative owner checks and composite tenant foreign keys, session row locking plus atomic turn-count updates, constraint-specific error mapping, fail-closed `MIGRATION_DATABASE_URL`, automatic record authority validation, and real PostgreSQL schema/downgrade/re-upgrade acceptance.
- Rerun: Focused checks, root regression, and rebuilt Compose all passed; the original findings were resubmitted to a second independent review.

### PostgreSQL schema-test correction

- Failure: The first rebuilt Compose run reported one failure while comparing ORM columns with migrated PostgreSQL columns.
- Root cause: The acceptance test compared SQLAlchemy `Column` objects with string column names.
- Fix: Compare `orm_table.columns.keys()` with inspected database names.
- Rerun: The full rebuilt Compose gate passed with 96 passed, 1 skipped, and 7 intentional xfails.

### Second independent-review remediation

- Finding: The second review found two P1 packaging/migration-safety gaps and four P2 evidence/authority/documentation gaps: the regular backend image omitted Alembic; direct CLI downgrade bypassed helper authorization; same-user cross-session references and Working State source authority lacked negative tests; schema-parity wording was too broad; and the memory package header described a nonexistent dual-track runtime.
- Root cause: The regular image used `backend/requirements.txt` while offline E2E used `pyproject.toml`, and safety enforcement/documentation had been concentrated in the helper/happy-path boundary.
- Fix: Added Alembic to the regular runtime manifest and a CI image smoke; guarded direct downgrade in Alembic env plus the revision; added authoritative Working State source checks and same-user cross-session State/Outbox rejection; narrowed parity claims to the asserted core structure; updated the memory package architecture header.
- Rerun: Migration/transaction tests passed 11/11, regular backend image built and imported Alembic 1.19.1, focused memory tests passed 26 with 7 intentional xfails, root regression passed 152 with documented skips/xfails, and rebuilt Compose passed 96 with one skip and seven intentional xfails. Final independent re-review found no remaining P0/P1/P2 and recommended commit/PR.

## 10. Scope Compliance

- Exactly one milestone executed: Yes, M2 only.
- Allowed files only: Yes.
- Forbidden M3+ behavior avoided: Yes; no state extraction/merge, compaction, Redis, governance worker, Mem0/pgvector retrieval, command UI, or production deployment.
- User work preserved: Yes; branch started from clean merged `main` commit `fb47b56`.
- Production/paid/external writes: None.
- Rollback: Revert the eventual squash commit; run tested Alembic downgrade only on an isolated database. Production/user-data downgrade remains prohibited.

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
| --- | --- | --- |
| Architecture and dependency direction | Satisfied | Domain contracts -> application port -> SQLAlchemy adapter; chat use case owns transaction |
| Types, docstrings, comments, contracts | Satisfied | Typed immutable domain records, stable enums/errors, Chinese Google-style documentation, zero changed-scope Pyright |
| Configuration and secrets | Satisfied | Alembic has no fallback URL, requires dedicated `MIGRATION_DATABASE_URL`, and requires explicit isolated downgrade authorization at CLI/revision boundaries; no `.env` or usable credential; Compose provider credentials empty |
| Data and rollback | Satisfied | Additive normalized tables, revision graph, downgrade/re-upgrade, legacy readability, no production mutation |
| Failure and concurrency semantics | Satisfied | Full rollback, duplicate rejection, concurrent-turn isolation, no internal memory commit |
| Logs, traces, and artifacts | Satisfied for M2 | Safe row-reference payload and existing trace ID propagation; no private content in Outbox/trace |
| Tests and evaluation | Satisfied | Unit/contract/integration/eval/root/PostgreSQL Compose evidence |

## 12. Risks Remaining

- Working State is an initialized typed authority but does not yet extract or merge entities, constraints, or temporary preferences; M3 owns that behavior.
- Rolling Summary metadata exists, but compaction enqueue/worker/CAS/last-good behavior remains M3.
- Redis, candidate promotion, Mem0/pgvector, natural-language commands, frontend controls, and full memory Trace stages remain deliberately absent until their owning milestones.
- The initial Alembic revision expects legacy tables; operators must use `init_db()` for a completely blank database or explicitly bootstrap the legacy baseline before running Alembic directly.
- Application-startup migration is acceptable for the current single-replica deployment, but a multi-replica production rollout needs a dedicated migration job or advisory lock before horizontal scaling.
- Full-repository static debt remains 81 Ruff and 80 Pyright errors under Issue #20; changed M2 scope is clean.

## 13. PLAN.md Updates

- Progress: Marked M2 complete locally with exact migration, transaction, regression, and Compose evidence; GitHub delivery remains pending.
- Decision Log: Recorded normalized Working State, Alembic/legacy bootstrap ownership, safe row-reference Outbox, dependency timing, no-dual-write task authority, repository-enforced message authority, same-session serialization, fail-closed migration targeting/downgrade, and production-image CI coverage.
- Surprises & Discoveries: Recorded PostgreSQL failed-transaction behavior, both independent-review rounds/remediation, split dependency manifests, SQLite locking limits, direct PostgreSQL row/schema evidence, and generated-artifact cleanup.
- Outcomes & Retrospective: Set M3 as the next unchecked milestone and preserved every M3+ limitation explicitly.

## 14. Suggested Commit Message

```text
feat(memory): add typed domain and transactional outbox (#26)

- add memory-v1 contracts and reversible Alembic schema
- commit messages, Working State, and Outbox atomically
- verify rollback, idempotency, concurrency, and PostgreSQL E2E
```

## 15. Handoff to User

Milestone 2 implementation, local acceptance, and independent review are complete. GitHub CI/merge closure remains before delivery; do not begin Milestone 3 in this execution turn.
