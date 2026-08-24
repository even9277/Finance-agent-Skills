# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: 4 — Redis Hot-State Cache and Worker Coordination
- Issue: [#30](https://github.com/even9277/Finance-agent-Skills/issues/30)
- Branch: `feat/30-memory-redis-cache`
- Status: Local implementation, acceptance, and independent review complete; GitHub delivery pending
- Date: 2026-08-25

## 2. Development Standards Read

- Read the complete frozen `PLAN.md`, repository/personal `AGENTS.md`, `CONTRIBUTING.md`, testing and architecture documents, the personal Python/Agent engineering standard, and the complete `small-step-implementation` skill with all referenced execution/testing/diff/report rules.
- Confirmed M4 was the first unchecked milestone. M5 candidate governance, M6 Mem0/pgvector, memory commands/UI, protected live providers, production deployment, and public/schema-breaking changes remained forbidden.
- No nested instruction file imposed a different rule in the changed scope.

## 3. Files Inspected

- Chat transaction path: factory, use case, ports/contracts, SQLAlchemy conversation repository, memory repository, REST/offline application construction, and session/message/profile models.
- STM path: context budget, summary Outbox worker apply/commit boundary, startup/shutdown lifecycle, and health endpoint.
- Legacy profile path: backend memory bridge/router and historical `MemoryService` profile commit points, used only to attach post-authority cache invalidation without starting M5 governance.
- Delivery path: both dependency manifests, lock file, Dockerfiles, production/offline Compose, CI static/packaging/E2E gates, characterization dataset, and prior milestone reports.

## 4. Files Modified

- `backend/application/memory/cache.py`: Added typed cache values, lookup statuses/error codes, bounded config, and the optional cache port.
- `backend/infrastructure/memory/{redis_cache,runtime}.py`: Added versioned Redis envelopes, hashed scoped keys, TTL, corruption/staleness rejection, fail-open commands, fenced fill leases, safe metrics/health, and lifecycle ownership.
- Chat/memory repositories and factories: Added version-checked cache-aside reads, bounded single-flight fallback, post-commit context/state publication, compact-profile reads, and explicit dependency injection.
- STM/profile write paths: Invalidated derived context/profile entries only after authoritative changes.
- Legacy memory write bridge: Removed private identifiers, profile values, provider payloads, and raw exception text from the M4 profile/add/update/delete paths; closed its prior Ruff/Pyright debt and added the full file to CI static gates.
- `backend/config.py`, `.env.example`, dependency manifests, and lock: Added validated optional Redis settings and redis-py 8.1.0 without changing real `.env` files.
- Compose/CI: Added digest-pinned ephemeral Redis 7.4.10 services, real integration environment variables, health/config wiring, and normal-image imports.
- Tests/eval/E2E: Added key/TTL/version/owner/corruption/outage/lease/concurrency/config/health/full-chain assertions and one supported characterization case.
- `PLAN.md` and this report: Recorded M4 evidence, decisions, discoveries, rollback, remaining risk, and M5 handoff.

## 5. Implementation Summary

Redis is a disposable accelerator, never an authority. Every key uses a stable namespace and SHA-256-derived tenant/resource references rather than raw identifiers. Every JSON envelope carries cache schema, kind, owner/resource references, and an authoritative version. The adapter accepts a value only when all fields and the PostgreSQL-derived version match; otherwise it deletes/ignores the entry and the repository loads PostgreSQL.

The chat repository caches the committed uncompressed tail plus running summary using `(turn_count, summary_version)`, the versioned Working State using `state_version`, and the compact profile using `updated_at`. The comparatively expensive context-tail cache fill uses a finite `SET NX EX` lease with a unique token and compare-and-delete release. A context contender waits once for a small configured interval and then independently queries PostgreSQL, preserving availability. Working State/profile misses use direct version-checked database fallback without coordination delay. New context/state snapshots are published only after the foreground database commit. Summary compaction and explicit profile writes invalidate their derived entries only after authoritative success.

The Redis adapter catches connection/timeout/command failures, emits low-cardinality `stage/status/error_code/error_type` logs, and returns `DEGRADED` rather than raising into the chat use case. `/api/health` keeps the application healthy while exposing an additive `memory_cache` component with safe status/counters only. PostgreSQL Outbox ownership, recovery, retry, and fencing are unchanged; Redis Streams, persistence volumes, and a second task authority were not added.

## 6. Dependency and Image Evidence

- `uv pip install --dry-run "redis>=8.1,<9"` resolved exactly redis-py 8.1.0; the final lock contains 103 packages.
- The regular Python 3.11 backend image installed redis-py 8.1.0 from `backend/requirements.txt` and imported the Redis adapter/runtime with Alembic and STM Worker.
- Official Redis image tag `7.4.10-alpine` was inspected, pulled, and executed locally as Redis server 7.4.10. Both Compose files pin multi-platform digest `sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2`.
- Compatibility references: [Docker Official Redis image](https://hub.docker.com/_/redis), [redis-py repository](https://github.com/redis/redis-py), and [redis-py package metadata](https://pypi.org/project/redis/).

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
| --- | --- | --- |
| `uv lock --check` | Reproducible dependency graph | Passed; 103 packages |
| Maintained-scope Ruff and Pyright | New cache/config/repository/worker/test boundaries | Passed; zero findings |
| Focused cache/config/eval/STM/Outbox tests | Contracts and relevant regressions | Passed |
| Real Redis integration on isolated local container | TTL/isolation/invalidation/corruption; SQL-authority outage fallback; three-kind inner-version tampering; lease expiry/token fencing; concurrent context single-flight | Passed: 6 |
| `pytest backend -q` | Backend regression | Passed: 11 |
| `pytest Financial-MCP-Agent -q -m "not live"` | Agent regression | Passed: 33; 4 live deselected |
| `pytest tests/evals -q -m "eval_smoke and not live"` | Offline eval | Passed: 19 |
| `pytest -q` | Final root regression | Passed: 214, skipped: 6, live deselected: 5, strict xfail: 6 |
| Frontend lint/type-check/build | Unchanged frontend regression and production bundle | Passed; existing chunk warning only |
| Both Compose config checks | Production/offline manifest validity | Passed |
| Rebuilt offline Compose | Real Redis/PostgreSQL/FastAPI/Nginx/Vue; PostgreSQL fallback, HTTP/cache, migration and controlled-chat journeys | Passed: 125, skipped: 1, deselected: 32, strict xfail: 6 |
| Normal backend image build/import | Separate runtime manifest parity | Passed; Alembic 1.19.1 and redis-py 8.1.0 |
| Manual same-session Redis-stop journey | Runtime fail-open and explicit degradation | HTTP 200, same session, `DEGRADED/UNAVAILABLE` |
| `git diff --check`, generated-file check, and manual secret/artifact review | Delivery hygiene | Passed after final rebuilt Compose and evidence update |

## 8. Failures and Fixes

- The first real Redis test called `DEL` with zero keys during cleanup. The production path was correct; the fixture now guards the empty list, and both real integration cases pass.
- The first root regression found the exact health-response contract had not been updated for the additive component. The contract now freezes the disabled shape, and the final root run passes.
- The first manual outage seed script printed a non-existent response `status` field after already completing the request. The session evidence was preserved; the corrected second command verified HTTP status, session continuity, and degraded health.
- Frontend build rewrote tracked TypeScript build metadata to the local compiler version. The generated change was restored and is excluded from the milestone diff.
- During the E2E migration downgrade check, the already-running STM worker briefly logged the known missing-table degradation while the test intentionally removed M2 tables. The E2E remained green and re-upgraded successfully; coordinating worker pause around an operator downgrade remains deployment-procedure work, not a Redis authority issue.
- Independent review found that the first cache decoder trusted the outer envelope version without cross-checking the typed inner value. All three cache kinds now require both versions to match and have real-Redis tamper negatives.
- Independent review found missing behavioral evidence around real lease expiry/fencing, concurrent cold fills, PostgreSQL fallback, post-authority invalidation, and rollback publication order. Six real-Redis tests plus focused summary/profile/transaction tests now lock these boundaries; the rollback tripwire executes the production repository and injects failure only at `AsyncSession.commit`.
- Independent review found that Compose initially hard-coded the rollback switch and that two production files were absent from CI static scope. The setting is now host-overridable and machine-checked; the lifecycle, bridge, and legacy memory service are all zero-error maintained paths.

## 9. Scope and Engineering Contract Compliance

- Exactly M4 executed; no candidate extraction/governance, Mem0, pgvector, new public command/UI, database migration, paid/live provider, or production write was introduced.
- PostgreSQL remains sufficient with Redis disabled, empty, corrupted, stale, or stopped. Rollback is `ENABLE_REDIS_CACHE=false`, removal of the Compose service/seam, and deletion of namespaced keys; no authoritative data recovery is required.
- Configuration is typed and documented; Redis URL/password never enters health, logs, tests, or reports. Cache payloads and raw identifiers are not logged.
- New public/cross-module Python interfaces have types and Chinese responsibility/failure documentation. Maintained scope is zero-error under Ruff/Pyright.
- The existing HTTP health contract changed additively; database schema, authentication, REST/WS chat request/response, and durable task contracts did not change.

## 10. Risks Remaining

- Metrics are in-process operational counters; cross-replica aggregation, latency SLOs, load/soak tests, alerting, and dashboards remain M8/M9.
- Cache-aside still performs a small authoritative version read by design; this optimizes large JSON/tail/profile retrieval while preserving correctness, not eliminating PostgreSQL from the request path. Only context-tail cold fills use single-flight because they are the expensive/concurrency-sensitive query; Working State/profile misses deliberately fall back directly.
- Historical read/semantic-memory paths outside this milestone still have legacy logging style; every M4 profile/add/update/delete path and its database helpers were redacted. Naive-UTC deprecation warnings and frontend chunk warnings remain visible rather than being hidden by unrelated refactors.
- Candidate governance, Mem0/pgvector retrieval, memory commands/UI, and protected live-provider closure remain M5-M9 and cannot be claimed from M4.

## 11. Suggested Commit Message

```text
feat(memory): add fail-open Redis hot cache (#30)

- cache versioned context, working state, and compact profiles
- keep PostgreSQL authoritative across corruption and outage
- verify real Redis, Compose E2E, packaging, and fail-open behavior
```

## 12. Handoff

M4 local implementation and validation are complete. Independent review confirmed P0/P1/P2 are zero, so the branch is ready for commit/push/PR/CI/squash merge. After merge, M5 is the only permitted next milestone.
