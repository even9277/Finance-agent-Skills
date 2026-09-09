# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: 4 — Migrate Consumers and Delete Old Paths
- Status: Complete
- Date: 2026-09-09

## 2. Allowed Scope and Standards

- Allowed: shared Resolver assembly, report thin Adapter, report/CLI/tool/historical consumers, focused tests and governance report。
- Forbidden: interview documents, D07/D08/D10, public API/schema, database, dependencies, frontend, memory and Skill behavior。
- Standards: no dual path, async external I/O, typed stable failure, deterministic-first, low-sensitive output, full caller migration before deletion。

## 3. Files Inspected / Modified

- `backend/infrastructure/chat/entity_resolution.py`: inspected model/catalog ownership; added process-level cached assembly and lazy model client construction。
- `backend/application/chat/factory.py`: production chat now injects `get_entity_resolver()`。
- `backend/services/stock_resolver.py`: replaced unsafe LLM Prompt/parser with stock-only format Adapter。
- `backend/services/agent_service.py`: removed deprecated regex resolver; unresolved entity now blocks state creation。
- `Financial-MCP-Agent/src/main.py`: removed 20-pattern local resolver; CLI awaits the shared report Adapter。
- `Financial-MCP-Agent/src/tools/chat_tushare_tools.py` and `src/agents/skill_executor_node.py`: inspected; both already consume `resolve_stock` and therefore migrated with the Adapter replacement。
- report/contract/factory/live tests: added shared mapping, non-stock rejection, single-path and cache lifecycle assertions。

## 4. Final Call Graph

```text
public chat -> chat factory -> get_entity_resolver -> AuthoritativeEntityResolver
report API -> agent_service -> stock_resolver thin adapter -> get_entity_resolver
CLI -------^                                             |
chat tool -^                                             -> model/catalog ports
legacy executor -----------------------------------------^
```

The only domain strategy is `AuthoritativeEntityResolver`. `stock_resolver` performs no extraction, Prompting or directory lookup; it only requires one stock and converts `601012.SH` to `sh.601012` for the existing report Agent contract。

## 5. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| report/tool/legacy/factory/adapter focused regression | caller migration and fail-closed behavior | 81 passed |
| stock resolver deterministic entry smoke | shared real assembly without network call | Passed; canonical `600519.SH` mapped to `sh.600519` |
| CLI module import from documented Agent working directory | packaging/import reachability | `CLI_IMPORT_OK` |
| Ruff on M4 files + CLI ignoring 3 pre-existing categories | lint | Passed |
| Pyright on M4 surface | cross-layer types | 0 errors |
| static old-path scan | duplicate Prompt/functions/regex tables | 0 matches |
| `git diff --check` | patch whitespace | Passed（仅 CRLF 提示） |

## 6. Failures and Fixes

- The first deterministic report smoke failed while constructing `ChatOpenAI` because the local proxy configured SOCKS but the optional `socksio` package was absent. Root cause: eager model client construction violated deterministic-first even though the query was locally resolvable. Fix: delay client construction until `_invoke`; construction failures are mapped to `EntityModelUnavailableError`. Focused tests and entry smoke then passed。
- The first CLI import probe ran from the workspace root via a custom spec loader and could not resolve the pre-existing `src` package convention. Running from the documented `Financial-MCP-Agent` working directory succeeded; no compatibility shim was added。

## 7. Scope and Risk

- No interview document changed; D01 remains untracked and unstaged。
- No old Resolver compatibility path remains。
- No new dependency or feature flag。
- Remaining validation: full default regression, Compose, protected real model+Tushare, PR/CI/review/merge。

## 8. Handoff

M4 is complete. M5 will run the full offline test/eval/static/Compose gates and only fix failures proven to be caused by D09.
