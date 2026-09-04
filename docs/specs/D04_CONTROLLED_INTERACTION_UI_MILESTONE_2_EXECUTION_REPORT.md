# D04 Milestone 2 Execution Report

## 1. Milestone

- Name: Implement Domain and Application Progress Stream
- Status: `SUCCEEDED`
- Date: 2026-09-03
- Branch: `feat/d04-controlled-interaction-ui`
- Base: `eb0549bccb4e6ae9c14f18dc49168bae6a3b6676`
- Issue: [#48 Add controlled plan, step, tool, and evidence interaction UI](https://github.com/even9277/Finance-agent-Skills/issues/48)

## 2. Frozen Contract

- Goal: produce authoritative typed progress from Workflow/Executor and route its safe Application projection through the D03 acknowledged stream.
- Allowed production area: `Financial-MCP-Agent/src/conversation/{progress,execution,workflow}.py` and `backend/application/chat/{contracts,progress,use_case}.py`.
- Allowed verification area: adjacent D04 and existing conversation/Application tests plus this report and plan governance.
- Forbidden area preserved: Router/public schema, frontend production, database, Redis, authentication, Prompt, Skills, tool selection/permission rules, dependencies and deployment configuration.
- Expected milestone boundary: domain/Application tests green; Router and frontend tests remain red until M3.

## 3. Implementation Delivered

### 3.1 Domain authority

- Added protocol-independent step/tool lifecycle enums and typed events for Trace summary, validated plan preview, step status, tool status and verification summary.
- `ControlledExecutor.execute` keeps its original behavior by default and accepts an optional async observer plus plan revision.
- Step `RUNNING` comes from the Executor. Tool `STARTED` is emitted only after obtaining the real concurrency permit and immediately before `ToolPort.execute`.
- Success and normalized failure close both tool and step lifecycles. Dependency/dedup paths emit direct `SKIPPED` with attempt `0` and never fabricate `STARTED`.
- Provider exception text is never stored in a progress event; only normalized observations and stable `ErrorCode` values cross the boundary.
- Workflow publishes plan preview only after Validator success, uses revision `1` for the initial plan and increasing revisions for valid replans, and publishes verification only from `VerificationResult`.

### 3.2 Application safety and ordering

- Added explicit Application stream event contracts without changing REST output or persistence models.
- Added a field-by-field safe projector. It exposes fixed display labels, an allowlist of harmless parameters, bounded subject summaries, fact counts and fixed limitation/error text.
- It does not serialize raw arguments, fact values, Provider source/error text, idempotency keys, permission hashes, Trace attributes, prompts or model payloads.
- `_ChatStreamObserver.on_progress` sends every projected event through the same `maxsize=1` queue and acknowledgement used by D03 content deltas. This preserves one ordered stream, transport backpressure and cancellation propagation.

## 4. Engineering Contract Review

| Category | Result |
| --- | --- |
| Architecture ownership | Passed: domain event production, Application projection and transport mapping remain separate modules |
| Interfaces/types/docs | Passed: public and cross-module contracts are typed; changed public methods and helpers have Chinese responsibility/boundary documentation |
| Configuration/secrets | Not applicable: no setting, environment variable or secret was added |
| Observability | Passed: progress reuses authoritative state transitions; internal Trace remains independent and no raw attributes are exported |
| Failure/cancellation | Passed in M2 scope: Provider failures normalize to stable codes; observer cancellation remains uncaught and reaches the Application rollback boundary |
| Persistence/data | Not applicable: no schema, migration, repository behavior or durable state changed |
| Dependencies | Not applicable: no production or test dependency changed |

## 5. Verification Evidence

### 5.1 Target behavior

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/conversation/test_controlled_interaction_progress.py tests/unit/conversation/test_controlled_interaction_projection.py -vv
```

Result: `8 passed in 1.34s`.

This proves finite lifecycle contracts, real Executor ordering, failure redaction, direct skip semantics, Validator-plan projection safety, Verifier-only sufficiency and shared Application queue ordering.

### 5.2 Focused regression

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/conversation/test_controlled_interaction_progress.py tests/unit/conversation/test_controlled_interaction_projection.py tests/unit/conversation/test_controlled_components.py tests/unit/conversation/test_tool_governance.py tests/unit/conversation/test_evidence_control_synthesis.py tests/unit/conversation/test_chat_stream_use_case_contract.py tests/contract/test_controlled_chat_contract.py tests/contract/test_skill_confirmation_public_contract.py -q
```

Result: `41 passed, 1 warning in 6.50s`.

The existing no-observer Executor/Verifier/replan behavior, D03 stream transaction/cancel behavior and prior control events remain green. A separate real-workflow replan regression also passed: `1 passed in 1.26s`.

### 5.3 Static checks

```powershell
.\.venv\Scripts\ruff.exe check <six changed production files> <two M2 test files>
uv run --locked pyright <six changed production files> <two M2 test files>
```

Result: Ruff `All checks passed!`; Pyright `0 errors, 0 warnings, 0 informations`.

### 5.4 Intentional M3 red boundary

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/conversation/test_controlled_interaction_progress.py tests/unit/conversation/test_controlled_interaction_projection.py tests/contract/test_controlled_interaction_public_contract.py tests/e2e/test_websocket_streaming_chain.py -q --tb=no -p no:logging
```

Result: `9 passed, 6 failed, 44 warnings in 7.32s`.

The six failures are intentionally outside M2: public Presenter tests fail at `backend/routers/chat.py` with `RuntimeError("unsupported application chat stream event")`, and real-workflow WebSocket tests terminate at the same absent mapping. The clarification/no-tool path remains green because it emits no fake execution cards. Router/Pydantic and frontend production must be changed atomically in M3.

Warnings are pre-existing Starlette/httpx and naive `datetime.utcnow()` deprecations.

## 6. Review Findings and Repairs

- First static pass found one unused `EvidenceDimension` import in the new projector. It was removed; the repeated Ruff/Pyright gates are green.
- A shell-resolved WindowsApps `python.exe` produced no trustworthy test output. Those invocations were excluded from evidence and all recorded tests use the repository virtual environment.
- Diff review confirmed that raw domain serialization is absent and Router/frontend/persistence/config were not modified in M2 production code.
- Existing WebSocket E2E failure was traced to the deliberately absent M3 Presenter branch, not to content generation or transaction behavior. It is recorded as expected red and was not bypassed with a temporary adapter.

## 7. Changed Files

- `Financial-MCP-Agent/src/conversation/progress.py`
- `Financial-MCP-Agent/src/conversation/execution.py`
- `Financial-MCP-Agent/src/conversation/workflow.py`
- `backend/application/chat/contracts.py`
- `backend/application/chat/progress.py`
- `backend/application/chat/use_case.py`
- D04 plan governance and this report

M1 test files remain part of the uncommitted D04 branch work. The unrelated `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` remains untracked and untouched.

## 8. Rollback

No data or configuration rollback is needed. Revert the six M2 production files together so Workflow never emits an event unknown to Application. Keep M1 tests/governance unless the complete D04 effort is abandoned. Do not modify the user-owned D01 file.

## 9. Handoff

Milestone 2 is complete. Milestone 3 may begin only as a separate execution step. It must implement public Router/Pydantic mapping and frontend consumption/UI/stop atomically, then turn the six recorded Python reds and frozen frontend reds green.
