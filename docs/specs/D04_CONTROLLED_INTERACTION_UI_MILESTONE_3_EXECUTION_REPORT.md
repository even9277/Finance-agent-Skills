# D04 Milestone 3 Execution Report

## 1. Milestone Executed

- Milestone: Public v2 Frames and Frontend Controlled UI
- Status: `SUCCEEDED`
- Date: 2026-09-03
- Branch: `feat/d04-controlled-interaction-ui`
- Base: `eb0549bccb4e6ae9c14f18dc49168bae6a3b6676`
- Issue: [#48 Add controlled plan, step, tool, and evidence interaction UI](https://github.com/even9277/Finance-agent-Skills/issues/48)

## 2. Development Standards Read

- `docs/specs/D04_CONTROLLED_INTERACTION_UI_PLAN.md`: M3 goal, allowed public/frontend surface, checks and stop conditions.
- `AGENTS.md`: repository architecture, test, security, Git and Definition-of-Done rules.
- `CONTRIBUTING.md`: local validation order, complete-chain expectations and generated-file handling.
- `C:/Users/27411/.codex/PYTHON_AGENT_ENGINEERING_STANDARD.md`: applicable boundary typing, documentation, error and verification rules.
- Small-step references: testing/failure handling and milestone report template.
- Nested instructions: none found below the repository root.

## 3. Files Inspected

- `backend/application/chat/contracts.py`: M2 event inputs and finite lifecycle values.
- `backend/schemas/chat.py`: existing v2 envelope and safe terminal/control schemas.
- `backend/routers/chat.py`: single Presenter, sequence ownership and cancellation boundary.
- `frontend/src/api/index.ts`: existing v2 union and strict parser.
- `frontend/src/stores/chatStore.ts`: current chat/stream/Skill state ownership.
- `frontend/src/composables/useChat.ts`: WebSocket lifecycle, fallback and session correlation.
- `frontend/src/views/ChatView.vue`: controlled-panel and stop composition point.
- `frontend/src/components/chat/ChatInput.vue`: visible user action boundary.
- D04 Python and frontend M1 tests: frozen acceptance behavior.

## 4. Files Modified

- `backend/application/chat/contracts.py`: tightened validated-plan and claim-level types discovered by M3 static checking.
- `backend/schemas/chat.py`: added five bounded Pydantic control-frame schemas.
- `backend/routers/chat.py`: mapped five Application events to globally sequenced v2 frames.
- `frontend/src/api/index.ts`: added D04 frame types and strict field/lifecycle validation.
- `frontend/src/stores/chatStore.ts`: added current-request monotonic controlled execution state and actions.
- `frontend/src/composables/useChat.ts`: dispatched control frames, added stop and safe pre-start fallback.
- `frontend/src/components/chat/ControlledExecutionPanel.vue`: rendered plan history, steps, tools and evidence limitations.
- `frontend/src/components/chat/ChatInput.vue`: added the streaming-only visible stop action.
- `frontend/src/views/ChatView.vue`: composed the panel/stop and avoided duplicate fallback user messages.
- `tests/e2e/test_websocket_streaming_chain.py`: retained D03 rollback assertion while accepting D04 controls before text.
- Two existing frontend M1 tests: added compile-time fixture annotations and no-fake-card coverage without changing behavioral expectations.
- D04 plan governance and this report.

## 5. Implementation Summary

The same real execution that produces the final answer now sends validated plan, step, tool, trace summary and evidence-verification events over `chat-stream-v2`. Router assigns one global sequence and Pydantic validates every public field. The frontend rejects malformed/extra raw fields, associates events with one request/session, preserves completed history across replan, and renders only authority-backed content.

User stop closes the active WebSocket, marks running step/tool state `CANCELLED`, marks unstarted planned steps `SKIPPED`, preserves completed work and adds no connection-error text. A failure before `stream_start` rejects to `ChatView` for one HTTP fallback; any failure after start terminates locally and never launches a duplicate request. Clarification/static paths with no control events render no fake plan card.

## 6. Diff Summary

- Protocol: five additive v2 frame types; existing stream/context/memory/Skill frames unchanged.
- State: one request-scoped Pinia object; no component-local duplicate execution state.
- Security: D04 parser rejects unknown fields such as raw `arguments`; UI receives safe summaries only.
- Persistence/config/dependencies: unchanged.

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| `.venv\Scripts\python.exe -m pytest <D04 unit, contract, WS E2E files> -q` | Complete offline D04 backend/public chain | `15 passed, 71 warnings in 8.02s` |
| `.venv\Scripts\python.exe -m pytest <expanded conversation/Skill/stream set> -q` | D03, Skill, replan and transaction compatibility | `43 passed, 71 warnings in 9.30s` |
| `.venv\Scripts\ruff.exe check <M3 Python files>` | Python lint/import quality | Passed |
| `uv run --locked pyright <M3 Python files/tests>` | Python public contract typing | `0 errors, 0 warnings` |
| `npm.cmd exec -- vitest run <nine D04/D03/Skill files> --reporter=verbose` | Parser, reducer, composable, component and compatibility | `9 files / 25 tests passed` |
| `npm.cmd run lint -- --quiet` | Frontend lint | Passed |
| `npm.cmd run type-check` | Vue/TypeScript contract checking | Passed |
| `npm.cmd run build` | Production frontend build | Passed; 403 modules transformed |
| `git diff --check` | Whitespace hygiene | Passed |

Warnings are pre-existing Starlette/httpx and naive `datetime.utcnow()` deprecations. The Vite dynamic/static import warning for `frontend/src/api/index.ts` is pre-existing and does not fail the build.

## 8. Test Results

- Passed: public frame order/redaction, real multi-step chain, replan revision, clarification with zero execution frames, midstream rollback, strict parser, parallel/out-of-order Store updates, stale request isolation, visible stop, HTTP fallback, Skill confirmation compatibility and production build.
- Failed: none after the permitted narrow repairs.
- Not run in M3: full repository suites, Compose, protected Live and browser inspection; assigned to M4 by the frozen plan.
- Limitations: browser visual/responsive behavior and real Provider latency remain unproven until M4.

## 9. Failures and Fixes

- Failure: initial Pyright reported three Router arguments broader than Pydantic literals. Root cause: Application dataclass annotations did not express already-frozen `validated/status/claim_level` invariants. Fix: narrowed annotations; rerun passed with zero findings.
- Failure: the old D03 midstream-failure E2E expected exactly start/delta/error. Root cause: D04 legitimately adds control frames before text. Fix: retained terminal/redaction/rollback assertions and required verification before delta; rerun passed.
- Failure: initial `vue-tsc` rejected broad literal inference in M1 fixtures and a step interface overriding `PLANNED`. Root cause: compile-time fixture inference, not runtime behavior. Fix: used explicit test fixture types and `Omit<..., 'status'>`; rerun passed.
- Invalid verification command: `-p no:logging` removed the pre-existing `caplog` fixture. It was excluded as evidence and rerun with repository defaults: 43 passed. No source/test repair was made for this invocation error.

## 10. Scope Compliance

- Allowed files only: Yes.
- Forbidden changes avoided: Yes.
- User changes preserved: Yes; `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` remains untracked and untouched.
- Dependencies changed: No.
- Database/config/auth/Prompt/Skills/Memory/tool governance changed: No.
- API changed: additive `chat-stream-v2` control frames explicitly authorized by D04; existing frame shapes and REST response are unchanged.

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
|---|---|---|
| Architecture and dependency direction | Satisfied | Router maps typed Application events; Store owns UI state; components only render |
| Docstrings, types, field meaning, section navigation | Satisfied | Pydantic/TS finite contracts and Chinese boundary documentation |
| Configuration, secrets, constants, prompts | Satisfied | stable enum/allowlist code only; no setting, secret or Prompt change |
| Terminal output, logs, traces, artifacts | Satisfied | existing structured Router terminal logs retained; no raw payload logging |
| Validation, errors, retry/fallback, state, compatibility | Satisfied | strict parser, request/session isolation, terminal monotonicity, one pre-start fallback, stop semantics |
| Tests, evaluation, and handoff evidence | Satisfied for M3 | unit/contract/real offline WS/component/build evidence recorded; M4 gates explicitly deferred |

## 12. Risks Remaining

- Production topology/browser rendering has not yet been exercised. Mitigation: M4 Compose and browser desktop/narrow checks.
- Real model/Tushare timing and event closure have not yet been exercised. Mitigation: at most two protected Live cases with redacted artifacts in M4.
- Full Skill/Memory/Context repository regression has not yet run. Mitigation: frozen M4 full gate matrix.

## 13. PLAN.md Updates

- Progress: M3 marked complete.
- Decision Log: recorded strict public validation, Store ownership, fallback and no-fake-card decisions.
- Surprises & Discoveries: recorded stale D03 frame assertion, generated tsbuildinfo behavior and pre-authority UI state.
- Outcomes & Retrospective: replaced M2 status with completed offline D04 chain and M4 risks.

## 14. Suggested Commit Message

```text
feat(chat): expose controlled execution progress

- stream validated plan, step, tool and verification frames
- render request-scoped progress with visible cancellation
- verify offline backend and frontend contracts
```

No commit was created in M3; D04 delivery is assigned to M5.

## 15. Handoff to User

Milestone 3 is complete. I will not proceed to Milestone 4 unless explicitly asked to continue.
