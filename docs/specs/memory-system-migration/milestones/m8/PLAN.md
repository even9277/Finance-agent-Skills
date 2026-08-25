# M8 PLAN: Memory Observability, Failure Hardening, and Offline Evaluation Gates

## Goal

Make every foreground/background memory operation diagnosable through one safe stage contract and make known failure modes reproducible in offline tests. This milestone must not change financial workflow semantics or make Redis/Mem0 required for correctness.

## Scope

- Add typed low-cardinality memory stages and statuses for preflight, state extraction/merge, compaction, candidate extraction/governance, indexing, retrieval/injection, mutation/deletion, cache and worker lifecycle.
- Add a trace adapter that correlates a memory event with a trace/run reference while excluding raw command text, memory content, user identifiers, credentials, and provider payloads.
- Add process-local counters with a stable snapshot contract for outcome, provider, cache, retry and dead-letter diagnostics.
- Emit observations at the command/retrieval boundary and at summary, governance, and semantic-index worker outcome boundaries without changing transaction ownership.
- Convert the stable-stage characterization contract from a strict xfail to a normal test and add redaction/metric tests.
- Add versioned offline STM/LTM/failure fixtures and a deterministic eval smoke gate; extend CI only with offline commands.
- Update the top-level migration plan, interview evidence map, and this milestone report.

## Non-goals

- No new model/provider dependency, live API call, real Tushare call, network Mem0 call, or production deployment.
- No change to PostgreSQL authority, Redis fail-open semantics, pending-command safety, worker retry policy, or financial planner/tool behavior.
- No raw prompt/reply capture and no user-memory export in artifacts.

## Acceptance

1. `MemoryStage` and `MemoryStatus` are typed and stable; all required stages are declared in one source of truth.
2. Trace/log output contains only safe stage/status/error/count/version/timing/reference fields; redaction tests prove sensitive keys and content are absent.
3. Metrics snapshot is deterministic, bounded, resettable in tests, and does not expose payloads.
4. Failure matrix covers cache/provider outage, retry exhaustion/dead-letter, stale lease/replay, malformed payload, partial derived deletion, and worker restart/recovery with explicit statuses.
5. Versioned offline eval covers STM state transitions, LTM candidate governance/retrieval/deletion, command lifecycle, and observability stage presence.
6. Maintained Ruff/Pyright, backend/agent/eval/root regression, frontend gates, Compose config, and rebuilt offline Compose E2E pass.

## Allowed files

- `backend/application/memory/observability.py`
- `backend/infrastructure/memory/observability.py`
- `backend/application/chat/use_case.py`, `backend/application/chat/factory.py`
- `backend/services/stm_compaction_worker.py`, `backend/services/ltm_governance_worker.py`, `backend/services/semantic_index_worker.py`
- `Financial-MCP-Agent/src/tools/skill_trace.py`
- `tests/unit/memory/**`, `tests/contract/test_memory_characterization_contract.py`, `tests/integration/*memory*`, `tests/evals/memory/**`, `.github/workflows/ci.yml`
- `docs/specs/memory-system-migration/**`

## Rollback

Revert the M8 commit/PR and disable the observation adapter; existing memory behavior and PostgreSQL authority remain unchanged. Never remove failure handling or delete audit data to restore a green test.

## Delivery

Use Issue #40 and branch `feat/40-memory-observability-evals`; require focused review, all CI gates, squash merge, Issue closure, remote branch deletion, and clean `main` verification.

## Progress

- [x] Observability contract, trace adapter, metrics, and health surface
- [x] Foreground and worker observation wiring
- [x] Redaction, metrics, and fail-open tests
- [x] Versioned LTM offline evaluation fixtures and gate
- [x] CI additions and local/Compose verification
- [x] Milestone report and delivery closure

## Handoff

M8 is complete on branch `feat/40-memory-observability-evals`. Open PR, require CI and review, squash merge to `main`, close Issue #40, delete the short branch, verify clean `main`, then proceed to M9.