# M9 Milestone Execution Report

## Result

`COMPLETED` for implementation and local acceptance; the final squash merge and branch cleanup complete the delivery.

## Acceptance Evidence

| Item | Command / Evidence | Result |
| --- | --- | --- |
| Rebuilt offline Compose E2E | `docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e` | `148 passed, 1 skipped, 39 deselected, 3 xfailed` |
| Root regression | `uv run --locked pytest -q` | `249 passed, 6 skipped, 5 deselected, 3 xfailed` |
| Agent project | `uv run --locked pytest Financial-MCP-Agent -q -m "not live"` | `33 passed, 4 deselected` |
| Offline eval smoke | `uv run --locked pytest tests/evals -q -m "eval_smoke and not live"` | `24 passed` |
| Frontend gates | `npm run lint && npm run type-check && npm run build && npm run test -- --run` | pass |
| Protected live acceptance | `RUN_PROTECTED_LIVE_E2E=true uv run --locked pytest tests/e2e/test_live_controlled_chat_chain.py -q -m live` | `1 passed` |

## Protected Live Evidence

- Real OpenAI-compatible model synthesis was called exactly once; only accepted evidence is used for the final answer.
- Real read-only Tushare observations were collected for `600519.SH`; every observation source starts with `tushare:` and carries facts.
- The journey used an isolated temporary SQLite database and an isolated JSONL trace path; no production database or shared data was touched.
- The 12-stage controlled trace (context → entity_resolution → route → rewrite → permission → plan → validate → execute → verify → controller → synthesis → termination) was asserted with one trace_id and one run_id, final status `SUCCEEDED`.
- Redaction assertions passed: the question text, model API key, and Tushare token do not appear in serialized trace records.
- Local SOCKS-only proxy environment: the run succeeded after temporarily removing `ALL_PROXY` while keeping the HTTP proxy; no dependency change was required. CONTRIBUTING documents both the `socksio` and `ALL_PROXY` options.

## Documentation Delivered

- `README.md`: updated the dialogue-mode summary, added a `记忆系统（受控记忆主链）` section with commands/observability/acceptance matrix, and corrected the “已实现工程点” memory bullet.
- `CONTRIBUTING.md`: added the memory E2E acceptance journey and the local live-run proxy note.
- `MODULE_EVIDENCE_MAP.md`: maps interview modules (STM/LTM/commands/observability) to code paths, tests, and merged PRs (#29/#31/#33/#36/#39/#41).
- M9 `PLAN.md` and this report.

## Delivery Steps

Issue #42 → branch `feat/42-memory-delivery-closure` → PR → CI (offline only) → review → squash merge → close Issue → delete branch → verify clean `main`.

## Residual Risk

- Playwright browser-level E2E remains a future improvement; current E2E exercises the real frontend proxy via HTTP.
- Process-local memory metrics are not yet exported to an aggregation backend.
- npm audit still reports one critical advisory not upgraded in this migration scope.
- Protected live CI requires the `protected-live-e2e` environment secrets; local runs require explicit switch and real credentials.