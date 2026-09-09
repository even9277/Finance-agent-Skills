# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: 5 — Offline, Compose, and Full Regression Verification
- Status: Complete
- Date: 2026-09-09

## 2. Verification Outcome

All offline quality gates passed. D09 did not regress backend, Agent, memory, report governance, WebSocket control frames, frontend contracts or container packaging. Default tests did not run any live-marked provider case。

## 3. Commands and Results

| Gate | Result |
|---|---|
| `pytest tests/unit tests/contract tests/integration tests/e2e -q` | 400 passed, 16 skipped, 6 deselected, 3 xfailed |
| `pytest backend -q` | 11 passed |
| `pytest Financial-MCP-Agent -q -m "not live"` | 33 passed, 4 deselected |
| `pytest tests/evals -q -m "eval_smoke and not live"` | 29 passed |
| `pytest -q` | 473 passed, 16 skipped, 10 deselected, 3 xfailed |
| D09 changed-surface Ruff | Passed |
| D09 changed-surface Pyright | 0 errors, 0 warnings |
| frontend lint / type-check | Passed |
| frontend Vitest | 54 passed across 16 files |
| frontend production build | Passed; only pre-existing chunk-size/dynamic-import warnings |
| production + offline Compose `config --quiet` | Passed |
| offline Compose full stack | 367 passed, 7 skipped, 48 deselected, 3 xfailed |
| Compose cleanup + `ps -a` | containers/network/trace volume removed; empty |
| `git diff --check` | Passed（only line-ending notices） |

## 4. Evaluation and Observability

- Entity eval is expanded from 7 to 12 fixed cases and passed together with route/rewrite/mainline evals。
- Offline Compose emitted `entity_resolution` spans with low-cardinality `resolver_path`, `model_calls`, `repair_count` and `catalog_status`; deterministic explicit-code case reported zero model calls。
- Compose replaces only external model/tool ports for offline safety; application, workflow, repository, PostgreSQL, frontend proxy and Trace paths were real。

## 5. Warnings / Non-blockers

- Existing `datetime.utcnow()` and TestClient deprecation warnings remain outside D09。
- Existing frontend large-chunk and mixed static/dynamic import warnings remain outside D09。
- Expected PostgreSQL unique-key errors were emitted by D06's concurrency/idempotency test and the test passed。
- Frontend build changed tracked `tsconfig.node.tsbuildinfo` from TypeScript 5.9.3 to local 5.7.3; it was restored with an exact narrow patch because it is a generated unrelated change。

## 6. Scope Compliance

- Interview documents: untouched。
- User D01: untracked and unstaged。
- Dependencies/lockfile/database schema/public API/frontend source: unchanged。
- D07/D08/D10: untouched。

## 7. Handoff

M5 is complete. M6 must now execute the single `d09-live-01` protected case with real OpenAI-compatible model and read-only Tushare; a skip or mocked provider will not count as acceptance.
