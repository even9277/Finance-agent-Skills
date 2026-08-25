# M8 Milestone Execution Report

## Result

COMPLETED.

## Scope Delivered

- Added a single typed observability contract in ackend/application/memory/observability.py:
  - MemoryStage stable low-cardinality stages (preflight/state extract/merge/compact/candidate/index/retrieve/inject/mutate/delete/cache/worker).
  - MemoryStatus explicit STARTED/SUCCEEDED/PARTIAL/FAILED/SKIPPED/DEGRADED/RETRY/DEAD_LETTER/REJECTED.
  - MemoryObservation safe fields only (no command text, memory content, user IDs, credentials, or provider payloads).
  - Thread-safe MemoryMetrics with bounded flat counters and a resettable snapshot.
- Added MemoryTraceSink in ackend/infrastructure/memory/observability.py that writes safe structured logs and JSONL spans, isolating exporter failures (fail-open).
- Wired the observer into the production chat factory and the offline Compose E2E app; test doubles keep the legacy trace contract unchanged.
- Emitted observations from the foreground chat path (preflight, retrieval, injection, command mutation/delete) and the background workers (summary compaction, LTM candidate governance, semantic index) at outcome boundaries without changing transaction ownership.
- Exposed safe health metrics through /api/health components.memory_observability.
- Converted the stable-stage characterization contract from a strict xfail into a normal contract test.
- Added redaction, metrics, and fail-open unit tests.
- Added versioned LTM governance offline eval fixtures (memory-ltm-v1) and deterministic eval tests.
- Extended CI with an offline memory eval gate and the frontend unit-test step.

## Verification

| Gate | Result |
| --- | --- |
| Ruff maintained scope | pass |
| Pyright maintained scope | pass |
| Focused unit/contract/eval tests | 20 passed, 3 xfailed |
| Memory integration suites | 25 passed, 4 skipped |
| Root regression | 249 passed, 6 skipped, 5 deselected, 3 xfailed |
| Agent project regression | 33 passed, 4 deselected |
| Offline eval smoke | 24 passed |
| Frontend lint/type-check/build | pass |
| Frontend Vitest | 2 passed |
| Compose config | pass |
| Rebuilt offline Compose E2E | 148 passed, 1 skipped, 39 deselected, 3 xfailed |

The rebuilt Compose journey verified real PostgreSQL migrations, Redis 7.4.10, backend workers, Nginx/frontend proxy, HTTP chat, memory command preview/confirm/replay, cache health, and the new memory observability metrics over /api/health.

## Narrow Fixes Found by Real E2E

1. The first rebuilt run found the offline E2E app did not inject the observer, so the chat path produced no metrics; the production wiring was mirrored into 	ests/e2e/offline_app.py.
2. The second rebuilt run found the foreground post-commit memory.compact observation reused the chat run_id and changed the legacy “last span is termination” trace contract; the foreground duplication was removed because the background summary worker already owns compaction observations.

## Constraints Preserved

- PostgreSQL remains the sole durable authority; Redis/pgvector/Mem0 remain rebuildable derived layers.
- No paid model, production service, real Tushare, or network Mem0 call was made in any default test.
- No command text, memory content, user ID, or credential is written to logs, traces, fixtures, or artifacts.
- No change to financial planner/tool behavior or worker retry/fencing policy.
- Existing old tests were not weakened; the only strict xfail removal was replaced with a real contract assertion.

## Residual Risk

- Metrics counters are process-local; aggregation into a metrics backend is a later deployment concern.
- Browser-level Playwright coverage and protected live provider validation remain M9 work.
- Existing npm audit findings (one critical) were not upgraded in this scoped change.