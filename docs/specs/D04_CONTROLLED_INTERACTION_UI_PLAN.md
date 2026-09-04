# PLAN.md

## 1. Plan Metadata

- Plan name: D04 受控交互与执行状态 UI
- Task type: New Feature + Test/Evaluation + Engineering Governance + Interview Demo Alignment
- Status: Complete; final merge identity is recorded by PR #49 and `origin/main`
- Target executor: Codex
- Related artifacts:
  - `docs/specs/D04_CONTROLLED_INTERACTION_UI_REQUIREMENT_SPEC.md`
  - `docs/specs/D04_CONTROLLED_INTERACTION_UI_CODEBASE_RECON.md`
  - `docs/specs/D04_CONTROLLED_INTERACTION_UI_CLARIFICATION_QUESTIONS.md`
  - `docs/specs/D04_CONTROLLED_INTERACTION_UI_SOLUTION_TRADEOFF.md`
- Tracking: GitHub Issue #48
- Repository root: `D:/FinanceProject/Finance-agent-Skills`
- Current branch: `feat/d04-controlled-interaction-ui`
- Base: `origin/main` after merged D03
- Created date: 2026-09-03

## 2. User-facing Purpose

After this change, the user should be able to在对话页面看到 Agent 已校验的执行计划、每个步骤和工具调用的真实进度、证据是否充分、当前请求状态，并能主动停止仍在运行的请求；最终回答继续使用 D03 真流式展示。

The current problem is领域层已经有完整 Planner/Validator/Executor/Verifier/Replan 状态，但这些状态大多只进入内部 Trace。公开流只传开始、正文、完成或失败；前端只有文本气泡和 Skill 确认。因此文档中的“计划、步骤、工具、证据可观测”目前不是可运行产品能力。

The success of this plan can be observed by真实启动页面后，固定金融问题在最终文本前依次出现 validated plan、step/tool 状态和 verification summary；错误、PARTIAL、replan、取消、无工具和并发隔离都有自动化证据；真实模型/Tushare 测试和全量回归通过，PR CI 全绿并可通过单个 squash revert 回滚。

## 3. Inputs Reviewed

- REQUIREMENT_SPEC.md: 冻结 D04-C01～C08、默认离线/显式 Live、安全投影和 D05/D06 边界。
- CODEBASE_RECON.md: 确认真实 Gap 位于 Workflow/Executor -> Application stream，而非只有 Vue 组件缺失。
- CLARIFICATION_QUESTIONS.md: 冻结 5 类控制帧、状态枚举、plan revision、stop、HTTP fallback、Live 数量和脱敏边界。
- SOLUTION_TRADEOFF.md: 选择 Option B typed async progress observer；拒绝事后伪进度和完整框架迁移。
- Code files: `backend/application/chat/**`、`backend/routers/chat.py`、`backend/schemas/chat.py`、`Financial-MCP-Agent/src/conversation/**`、前端 chat API/composable/store/view/components。
- Tests: conversation unit/contract、WS E2E/Live、frontend parser/composable/store/component、CI/Compose。
- External references:
  - LangGraph custom progress streaming: https://docs.langchain.com/oss/python/langgraph/streaming
  - AG-UI lifecycle events: https://github.com/ag-ui-protocol/ag-ui/blob/main/docs/sdk/js/core/events.mdx
  - Pinia actions: https://pinia.vuejs.org/core-concepts/actions.html
  - FastAPI WebSocket lifecycle: https://github.com/fastapi/fastapi/blob/master/docs/en/docs/reference/websockets.md

## 4. Final Unified Direction

This iteration will增加协议无关 typed async progress observer：领域 Workflow 在 validated plan、verification、replan 和选定阶段发布权威事件，Executor 在真实 step/tool 调用边界发布开始/完成事件；Application 将它们白名单投影为 D04 stream events，并复用 D03 同一 ack queue；Router 映射为 `chat-stream-v2` Pydantic 帧；前端 strict parser 分发到 request-scoped Pinia reducer，再由受控面板组件展示；`useChat` 提供可见 stop，关闭当前 Socket 并进入本地 CANCELLED，同时后端 D03 取消链回滚。

This iteration will not修改 Planner/Validator/Verifier/Controller 决策、Prompt、Skills、工具权限、Memory、报告、数据库、Redis、认证、部署拓扑或生产依赖；不公开 raw trace、Prompt、工具参数/结果、Evidence facts 或思维链；不做跨刷新恢复、heartbeat、replay、AG-UI/LangGraph runtime 迁移或 Playwright 引入。

The plan follows Option B from the frozen solution tradeoff and the repository rule of one issue/branch/PR/squash commit per deliverable.

## 5. Planning Assumptions

- Assumption: 当前页面只允许一个 active streaming request；Store 仍按 request ID 建模以拒绝迟到事件，并为未来多请求扩展保留边界。
- Assumption: 跨刷新恢复留给 D06；D04 在切换/重新加载会话时清理不匹配的执行状态。
- Assumption: `trace_summary` 只覆盖用户有价值的低基数阶段，不逐条公开所有内部 WorkflowEvent。
- Assumption: Tool display/argument/result summary 由稳定代码白名单生成，不需要配置项。
- Assumption: Tushare/模型现有凭证可用于 protected Live；若外部服务不可用，不能伪造通过，但继续完成离线验收并记录精确阻塞。
- Assumption: 当前 Nginx 300 秒超时足够，D04 不需要 heartbeat。
- Assumption: D03 全量基线为后端 364 tests、前端 15 tests；Milestone 0 仍需重新运行聚焦基线确认当前分支状态。

## 6. Changed Surface

| Surface | Involved? | Why | Risk | Verification |
| --- | --- | --- | --- | --- |
| Frontend | Yes | 新 parser/state/components/stop | High | Vitest、lint、vue-tsc、build、browser |
| Backend API | Yes | 新 v2 可选控制帧 | High | Pydantic/contract/WS E2E |
| Database | No | D04 不持久化过程状态 | High if touched | `git diff` 确认无 models/migrations |
| Cache | No | 恢复/幂等属 D06 | High if touched | `git diff` 确认无 Redis 改动 |
| Agent runtime | Yes | 新 typed progress observer | High | unit/workflow/stream/cancel tests |
| Tool calling | Yes, lifecycle only | 真实工具开始/完成事件 | High | executor observer tests；工具选择/权限回归 |
| RAG / Memory | No behavior change | 既有控制帧必须兼容 | Medium | memory/skill control regression |
| MCP | No | 当前受控链 Provider 不改 | Medium if touched | scope review |
| Skills | No behavior change | plan 展示会引用 Skill 生成计划，但不改 spec/router | High if touched | Skill tests/evals regression |
| Tests | Yes | 锁定 D04-C01～C08 | Low | red baseline then green/full gates |
| Observability | Yes | 用户摘要 + frame lifecycle artifact | Medium | redaction/log/artifact assertions |
| Security/Auth | No behavior change | public payload和 stop 必须保持用户/请求隔离 | High | negative payload + auth regressions；不改 middleware |
| Build/Deployment | No planned change | 既有 WS/Compose 足够 | Medium | frontend build、compose config/E2E |

## 7. Repository Context

### 7.1 Relevant Entry Points

- Backend startup: `backend/main.py:app`; chat router prefix `/api/chat`。
- WebSocket: `backend/routers/chat.py::chat_stream` at `/api/chat/stream`。
- Application: `backend/application/chat/use_case.py::ControlledChatUseCase.stream/_execute`。
- Domain: `Financial-MCP-Agent/src/conversation/workflow.py::ControlledConversationWorkflow.run`。
- Tool execution: `Financial-MCP-Agent/src/conversation/execution.py::ControlledExecutor.execute/_run_step`。
- Frontend: `frontend/src/views/ChatView.vue::handleSend` -> `frontend/src/composables/useChat.ts::sendMessageStream`。
- Store: `frontend/src/stores/chatStore.ts`。
- Current rendering: `ChatWindow.vue` + `ChatInput.vue` + `SkillConfirmationCard.vue`。

### 7.2 Relevant Call Chain

```text
ChatView -> useChat -> WebSocket Router -> ControlledChatUseCase.stream
-> ControlledConversationWorkflow.run
-> Plan -> Validate -> Execute(ToolPort) -> Verify -> Controller -> optional Replan
-> Synthesis stream -> Application ack queue -> Router v2 sequence
-> frontend strict parser -> composable dispatch -> Pinia reducer -> D04 components
```

### 7.3 Existing Patterns to Reuse

- Immutable dataclass/enum contracts under `src/conversation`。
- Optional dependency injection through constructor Ports。
- D03 `_ChatStreamObserver` queue(maxsize=1) + acknowledgement。
- Router Pydantic-only public serialization and sequence ownership。
- `_skill_confirmation_schema` style explicit public projection。
- frontend `parseWsFrame` runtime validation and discriminated union。
- Pinia setup store actions and FakeWebSocket Vitest。
- `SkillConfirmationCard` typed props/emits component style。
- protected Live gate, temporary DB, audit wrappers and redacted artifact。

### 7.4 Current Test Structure

- Python unit: `tests/unit/conversation/`。
- Public API contract: `tests/contract/`。
- Integration: `tests/integration/`。
- E2E/live: `tests/e2e/`，`live` default excluded。
- Frontend: co-located `__tests__/*.spec.ts` with Vitest/jsdom。
- CI: scoped Ruff/Pyright, backend/Agent/evals/root pytest, frontend lint/type/build/test, Docker build/Compose E2E。

### 7.5 Current Observability Structure

- Domain `WorkflowEvent` -> `SkillTraceSink` -> local JSONL + optional Langfuse。
- Trace is best-effort and must remain independent from stream correctness。
- Application/Router logs include request/session/stage/status/chunk/TTFT/elapsed/error but no content。
- Live acceptance artifact stores non-sensitive provider/mode/count/timing/hash/status。

## 8. Scope Control

### 8.1 In Scope

- Domain typed progress event/observer for stage, validated plan, step/tool lifecycle, verification and replan。
- Application safe projection and D03 stream queue integration。
- `chat-stream-v2` Pydantic/TypeScript frames and runtime validation。
- Request-scoped Pinia execution state with monotonic transitions and stale-event rejection。
- ControlledExecutionPanel and minimal child components as needed。
- ChatInput/ChatView visible stop and user-cancel semantics。
- Offline unit/contract/frontend/E2E, Compose, protected Live and browser acceptance。
- README/D04 acceptance/governance documentation、Issue #48、PR/review/merge。

### 8.2 Out of Scope

- D05 report SSE/polling fallback。
- D06 Redis idempotency/snapshot/reconnect/duplicate protection/status query。
- Database schema/migrations/persistent execution history。
- WebSocket authentication/query token redesign。
- Prompt、Skill discovery/routing/spec、tool permission/catalog、Evidence rule/model Judge 改动。
- Full AG-UI/LangGraph runtime、message queue、multi-instance broadcasting。
- Raw trace/debug/COT display、full args/results/facts。
- Heartbeat、replay/resume、Playwright、新生产依赖。

### 8.3 Allowed Files / Modules

- Governance/docs:
  - `docs/specs/D04_CONTROLLED_INTERACTION_UI_*.md`
  - `README.md`
- Domain progress and execution:
  - `Financial-MCP-Agent/src/conversation/contracts.py`
  - `Financial-MCP-Agent/src/conversation/ports.py`
  - `Financial-MCP-Agent/src/conversation/workflow.py`
  - `Financial-MCP-Agent/src/conversation/execution.py`
  - optional new `Financial-MCP-Agent/src/conversation/progress.py`
- Backend Application/API:
  - `backend/application/chat/contracts.py`
  - `backend/application/chat/use_case.py`
  - `backend/application/chat/factory.py`
  - optional new `backend/application/chat/progress.py`
  - `backend/schemas/chat.py`
  - `backend/routers/chat.py`
  - `backend/infrastructure/chat/testing.py` only for deterministic test support
  - `tests/e2e/offline_app.py` only if constructor wiring requires it
- Frontend:
  - `frontend/src/api/index.ts`
  - optional new `frontend/src/types/chatExecution.ts`
  - `frontend/src/composables/useChat.ts`
  - `frontend/src/stores/chatStore.ts`
  - optional new `frontend/src/stores/chatExecutionState.ts`
  - `frontend/src/views/ChatView.vue`
  - `frontend/src/components/chat/ChatInput.vue`
  - `frontend/src/components/chat/ChatWindow.vue` only for composition/layout if necessary
  - new D04 files under `frontend/src/components/chat/`
- Tests:
  - `tests/unit/conversation/test_controlled_interaction_projection.py` (new candidate)
  - `tests/unit/conversation/test_chat_stream_use_case_contract.py`
  - `tests/contract/test_controlled_chat_contract.py`
  - `tests/contract/test_skill_confirmation_public_contract.py` only if expected frames expand
  - `tests/e2e/test_websocket_streaming_chain.py`
  - `tests/e2e/test_live_controlled_chat_chain.py`
  - D04-adjacent new/updated frontend `__tests__/*.spec.ts`
- CI:
  - `.github/workflows/ci.yml` only if existing glob/commands do not execute new tests; expected no change
  - `.github/workflows/live-e2e.yml` only if D04 Live needs safe artifact wiring; otherwise read-only

### 8.4 Forbidden Changes

- Do not perform unrelated refactor.
- Do not reformat unrelated files.
- Do not modify generated files or build artifacts, including tracked TypeScript build-info changes.
- Do not add dependencies unless explicitly approved.
- Do not change database schema, models, migrations, retention or persistence semantics.
- Do not change existing REST response schema; D04 only adds optional WebSocket v2 frame types.
- Do not modify authentication, authorization, JWT, WebSocket token transport or middleware.
- Do not modify secrets, `.env`, credentials, Docker/production deployment config or real user data.
- Do not delete user data or the unrelated untracked `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md`.
- Do not weaken, skip, xfail or remove existing tests/security checks to make D04 pass.
- Do not remove or repurpose Trace/logging safety checks.
- Do not change Planner, Validator, Controller, Evidence rules, Skills, Prompt or tool governance behavior.
- Do not emit raw WorkflowEvent attributes, ToolPlan arguments, idempotency keys, ToolObservation facts or exceptions to clients.
- Do not create a second stream runtime, dual protocol, post-hoc fake progress, Redis state or persistent progress ledger.
- Do not touch files outside allowed scope without stopping for approval.

## 9. Interfaces and Dependencies

| Interface / Dependency | Current Role | Planned Change | Compatibility Requirement | Validation |
| --- | --- | --- | --- | --- |
| `ConversationProgressObserver` (new) | None | Optional async domain progress port | REST/no observer is no-op; no FastAPI dependency | type/unit/workflow tests |
| Domain progress union (new) | None | typed stage/plan/step/tool/verification/replan facts | internal versioned finite union | pyright + unit tests |
| `ControlledConversationWorkflow.run` | Runs entire controlled chain + content callback | Accept optional progress observer and await at authority points | Existing callers unchanged by default | existing workflow/evals + new tests |
| `ControlledExecutor.execute` | Executes validated DAG | Accept optional observer and publish real step/tool lifecycle | Tool selection/results unchanged | concurrent/failure/timeout tests |
| `ChatStreamEvent` | start/delta/completed/failed | Add safe D04 Application events | D03 event semantics unchanged | application contract tests |
| `_ChatStreamObserver` | D03 text queue/ack | Implement/receive progress projection into same queue | one queue, cancellation/commit unchanged | ack/send failure/cancel tests |
| `chat-stream-v2` | public WS envelope | Add optional typed control frames | same envelope/sequence/end/error | Pydantic/WS/frontend contract |
| `parseWsFrame` | strict runtime parser | Validate five new frame kinds and payloads | reject malformed/unknown/raw | Vitest negative tests |
| `chatStore` execution actions | None | Own request-scoped plan/steps/tools/evidence/lifecycle | existing message/skill/memory state unchanged | reducer tests |
| `useChat` | Socket/sequence/frame dispatch | Dispatch D04 and expose `stopStreaming` | D03 text/fallback remains | FakeSocket tests |
| `ControlledExecutionPanel` | None | Render safe view model, no protocol logic | optional absence must not break chat | component tests/browser |
| OpenAI-compatible Provider | Real text stream | No change | same one-call behavior | protected Live regression |
| Tushare Tool Provider | Real read-only facts | No behavior change; lifecycle observed around call | no raw payload emitted | live + redaction |
| Trace Sink | internal best-effort events | No role change | failure remains non-blocking | trace regression |
| Repository/UoW | atomic final messages | No change | disconnect/technical failure rollback | integration/E2E |

## 10. Engineering Implementation Contract

| Category | Files / modules | Required behavior or documentation | Verification | Status |
| --- | --- | --- | --- | --- |
| Architecture and dependency direction | conversation progress/ports/workflow/execution; backend application/router; frontend api/composable/store/components | Domain cannot import backend/Web; Application projects; Router maps; Store reduces; components render | import review, pyright/vue-tsc, tests | Required |
| Docstrings, types, field meaning, and section navigation | all modified Python/TS public interfaces | Chinese Google-style docstrings for Python public types/methods; finite enums/unions; describe IDs/revision/privacy/failure; intent comments at validation/redaction/cancel | review, Ruff/Pyright/vue-tsc | Required |
| Configuration, env, secrets, constants, and prompts | config/env/prompt remain unchanged; stable projection constants in code | no new env/config; no secrets; display/error/argument whitelist in owned module; no Prompt edits | diff + redaction tests | Required |
| Terminal output, logs, traces, metrics, and artifacts | Application/Router logs, SkillTrace, Live artifact | request/session/run, frame kinds/counts, per-tool elapsed, status/error/hash; no content/prompt/token/raw payload; Trace stays independent | tests + artifact inspection | Required |
| Validation, errors, retry/fallback, state, and compatibility | Pydantic/TS parser, observer/queue, reducer, stop | Validator-only plan; Verifier-only sufficiency; observer failure/cancel rollback; per-ID monotonic state; HTTP fallback explicit degraded; single terminal | unit/contract/E2E | Required |
| Tests, Agent evaluation, and handoff evidence | pytest/Vitest/Compose/Live/browser/docs | tests first; D04-C01～C08; default offline; max 2 protected Live; full regression; PR/CI/review/squash merge evidence | command table and acceptance report | Required |

## 11. Test and Validation Strategy

### 11.1 Existing Tests to Run

- `.venv/Scripts/python.exe -m pytest tests/unit/conversation/test_controlled_components.py tests/unit/conversation/test_evidence_control_synthesis.py -q`
- `.venv/Scripts/python.exe -m pytest tests/unit/conversation/test_chat_stream_use_case_contract.py tests/contract/test_controlled_chat_contract.py tests/contract/test_skill_confirmation_public_contract.py -q`
- `.venv/Scripts/python.exe -m pytest tests/e2e/test_websocket_streaming_chain.py -q`
- `.venv/Scripts/python.exe -m pytest backend -q`
- `.venv/Scripts/python.exe -m pytest Financial-MCP-Agent -q -m "not live"`
- `.venv/Scripts/python.exe -m pytest -q`
- `npm run lint && npm run type-check && npm run test -- --run && npm run build` in `frontend/`
- CI scoped Ruff/Pyright commands from `.github/workflows/ci.yml`。
- Compose config and offline E2E commands。

### 11.2 New or Updated Tests Required

| Candidate test | Behavior | Red before implementation? | Green condition |
| --- | --- | --- | --- |
| new domain progress tests | validated plan only; step/tool starts/ends; verification/replan | Yes | ordered typed events from real authority points |
| `test_controlled_interaction_projection.py` | safe display/argument/result/evidence projection + forbidden fields | Yes | exact whitelist and length limits |
| `test_chat_stream_use_case_contract.py` | progress shares ack queue; send/close cancels; commit ordering | Yes | no event after terminal; rollback on transport failure |
| `test_controlled_chat_contract.py` | Pydantic v2 frame shape/sequence/parallel/failure | Yes | exact frame lifecycle and no internal fields |
| `test_websocket_streaming_chain.py` | full offline plan->tool->verify->delta->end | Yes | D04 order, closed statuses, DB text equality |
| Live controlled chat | real model/Tushare D04 controls | Yes | real frames, no fake post-hoc order, redacted artifact |
| frontend parser contract | all five frames + malformed/forbidden negatives | Yes | strict parse/null behavior |
| chat Store execution spec | request/revision/ID/monotonic/duplicate/stale/cancel | Yes | deterministic reducer state |
| useChat streaming spec | dispatch + stop + fallback cleanup + existing frames | Yes | correct actions and socket close semantics |
| ControlledExecutionPanel spec | plan/step/tool/evidence/PARTIAL/replan/no data | Yes | readable stable DOM with text rendering |
| ChatInput/ChatView spec | visible stop and emit | Yes | stop only during streaming, send state unaffected |

### 11.3 Manual Smoke Tests

1. Start backend and frontend; login with local test account.
2. Ask `请分析贵州茅台当前是否值得继续跟踪，并说明证据限制`.
3. Confirm validated plan appears before tools, states change visibly, evidence summary precedes/aligns with final answer, text streams in same assistant message.
4. Repeat with a case that returns missing/partial evidence; confirm failed tool and PARTIAL/INSUFFICIENT are not shown as success.
5. Start a request and click `停止生成`; confirm UI becomes cancelled without appending network-error text; server log shows disconnect/cancel and DB has no assistant final message for that turn.
6. Trigger Skill confirmation; confirm the existing confirmation card still works and no fake plan appears before confirmation.
7. Check desktop and narrow viewport for overflow, accessible button label and scroll behavior.

### 11.4 Agent/RAG/Tool Evaluation, if applicable

- Reuse deterministic controlled chain cases for normal, missing evidence and recoverable replan。
- Protected Live max two parameterized cases:
  - real model + real Tushare `stock-first-pass` fixed read-only query。
  - real model + deterministic missing/limited tool path or no-tool path, without another paid market call。
- Do not assert model wording. Assert route/plan/step/tool/verification lifecycle, terminal status, content hash/DB equality and non-leakage。
- No new synthetic success-rate metric; report only observed pass/fail, event counts and timing.

### 11.5 Expected Terminal / Logs / Trace / Artifacts

- Stable correlation: `request_id/session_id/trace_id/run_id`。
- D04 evidence: event kind sequence, plan revision count, step/tool terminal counts, verification sufficiency/claim level, terminal status, elapsed/TTFT/content hash。
- Log failures with stable `error_code` and exception type only; no raw message/args/results/prompt/token。
- Live artifact should add event type list/counts and closed lifecycle summary, while preserving D03 provider/mode/timing/hash fields。
- Test/browser screenshots, if created, must not contain credentials or private profile data and should be stored only when needed for acceptance。

### 11.6 Acceptance Criteria

| Behavior / Risk | Test or Check | Command / Method | Expected Result |
| --- | --- | --- | --- |
| Validator-only plan | domain/application unit | focused pytest | no preview for invalid plan; valid preview precedes execution |
| Real step/tool lifecycle | executor + WS E2E | focused pytest | STARTED/RUNNING before actual call; terminal reflects observation |
| Parallel safety | unit/contract | focused pytest | global sequence valid; per-ID state monotonic; no cross-step overwrite |
| Evidence correctness | verifier projection | focused pytest | sufficiency/claim/missing derived only from VerificationResult |
| Replan | deterministic E2E | focused pytest | revision increments; old history retained; new steps added |
| Failure/PARTIAL | failing tool E2E | focused pytest | tool failed; verification limited; stream_end PARTIAL or safe failure |
| Stop/cancel | frontend + backend disconnect | Vitest + pytest | visible stop; no network-error text; generator cancelled/transaction rollback |
| No-tool/Skill confirm | regressions | pytest/Vitest | no fake cards; existing confirmation works |
| Protocol security | schema/parser/redaction | pytest/Vitest | malformed rejected; forbidden fields absent |
| Frontend UX | component/browser | Vitest + live page | readable controls, no key overflow, text still streams |
| D03 compatibility | existing streaming suite | pytest/Vitest | sequence/hash/chunks/terminal unchanged |
| Full regression | all gates | full commands | no new failure |
| Real APIs | protected Live | explicit live command | <=2 cases, real model and Tushare path pass; artifact redacted |
| Delivery | GitHub | PR checks/review | issue linked, CI green, self/independent review resolved, squash merge |

## 12. Milestones

### Milestone 0: Safety and Baseline Check

**Goal:** Confirm branch, user changes, allowed surface, D03 baseline and test commands before implementation.

**Files / Modules:** Read-only repository status, plan artifacts, relevant tests and CI; update only this plan and a Milestone 0 report after checks.

**Implementation Intent:** Verify current branch starts at origin/main after D03, preserve the untracked D01 document, confirm no overlapping user edits, and run focused D03/domain/frontend baselines.

**Tests / Checks:** `git status --short --branch`、`git diff --check`、focused domain/Application/WS pytest、focused frontend v2/Skill tests、gh issue view #48。

**Expected Result:** Baseline green; only D04 governance docs plus unrelated D01 untracked; no hidden scope.

**Stop Condition:** Any allowed source file contains unknown user changes, focused baseline fails for non-environment reasons, branch/base is wrong, or P0 decision becomes unresolved.

**Rollback Note:** No source code change. Remove only D04 governance docs if abandoning; never touch D01.

**Handoff Evidence:** Commands/results, branch/base, status, baseline counts, issue URL, updated Progress/Decision/Discoveries.

### Milestone 1: Lock D04 Tests and Red Baseline

**Goal:** Add precise failing tests for public/internal contracts before behavior implementation.

**Files / Modules:** Allowed Python and frontend test files; minimal type/schema stubs only if required to make tests collect, but no production behavior.

**Implementation Intent:** Encode validated-plan gate, progress event order, step/tool lifecycle, safe projection, replan, PARTIAL, stop, parser/reducer/component behavior and compatibility. Failures must map one-to-one to missing D04 capability.

**Tests / Checks:** Narrow pytest/Vitest commands; Ruff/Pyright/vue-tsc on test contracts if collectable.

**Expected Result:** Documented red baseline with only expected D04 failures; existing D03/Skill/Memory tests stay green.

**Stop Condition:** Tests require out-of-scope persistence/auth/dependency changes, or failures reveal the frozen requirement contradicts actual business semantics.

**Rollback Note:** Test-only diff can be reverted without source impact.

**Handoff Evidence:** Test files, expected failure list/count, mapping to D04-C01～C08, unchanged regression results.

### Milestone 2: Implement Domain and Application Progress Stream

**Goal:** Produce authoritative typed progress and route it through the D03 backpressured Application stream.

**Files / Modules:** conversation contracts/progress/ports/workflow/execution; backend application contracts/use_case/progress/factory; adjacent Python tests.

**Implementation Intent:** Add optional async observer; publish validated plan before execute, real step/tool boundaries, verification and replan; build explicit safe projections; put all public events through the existing ack queue. REST/no observer remains unchanged; Trace stays separate.

**Tests / Checks:** Domain observer/projection/Application stream tests, existing Planner/Executor/Verifier/replan and D03 transaction/cancel suites, scoped Ruff/Pyright.

**Expected Result:** Python red tests turn green; progress order and cancellation are proven without public Router/UI workarounds.

**Stop Condition:** Requires changing domain financial rules, ToolPort contract behavior, database/Redis/auth/Prompt, a new dependency, or causes two failed repair attempts.

**Rollback Note:** No data migration; revert new progress modules and narrow signature additions together.

**Handoff Evidence:** Changed files/diff, focused command results, event examples without sensitive fields, cancellation/rollback proof, governance updates.

### Milestone 3: Public v2 Frames and Frontend Controlled UI

**Goal:** Map progress to `chat-stream-v2`, consume it safely, render controlled execution, and expose stop.

**Files / Modules:** backend schema/router; frontend api/types/composable/store/view/components; Python/TS contract/component tests.

**Implementation Intent:** Add five Pydantic/TS frame types; preserve Router sequence/terminal; strict parse; request-scoped monotonic Store actions; ControlledExecutionPanel; stop closes active WS as user cancellation and prevents error-text fallback.

**Tests / Checks:** WS contract/E2E, frontend parser/store/composable/component, Skill/Memory/Context compatibility, lint/type/build, scoped Ruff/Pyright.

**Expected Result:** D04-C01～C08 work in deterministic full chain; UI components receive only typed safe props; D03 text streaming unchanged.

**Stop Condition:** Requires persistent history, auth redesign, raw payload exposure, new UI/test dependency, or violates current visual architecture.

**Rollback Note:** Backend new frames and frontend consumer must be reverted atomically; protocol version remains v2.

**Handoff Evidence:** Frame sequences, DOM assertions, stop/cancel evidence, no-leak assertions, build results, governance updates.

### Milestone 4: Full Verification, Live E2E, Browser and Narrow Fixes

**Goal:** Prove the completed D04 across full offline gates, Compose, real APIs and actual UI; fix only concrete D04 failures.

**Files / Modules:** Allowed tests/live artifact/docs and narrowly implicated D04 source files.

**Implementation Intent:** Run narrow-to-wide checks; extend protected Live assertions; start frontend/backend for browser smoke; review payloads/logs. No new features.

**Tests / Checks:** full scoped Ruff/Pyright, backend/Agent/evals/root pytest, frontend lint/type/test/build, compose config + rebuilt offline E2E, max two protected Live, browser desktop/narrow/stop/Skill confirm, `git diff --check`.

**Expected Result:** All acceptance criteria have real evidence; no regressions; artifact redacted; services cleaned up.

**Stop Condition:** Same concrete failure remains after two focused repair attempts, external credentials unavailable for Live, Docker unavailable, or required fix is outside scope. Environment blockers must be reported; never fake pass.

**Rollback Note:** Revert only the failing D04 slice if safe; otherwise revert branch/PR as one unit. Stop services and clean isolated test resources without touching user data.

**Handoff Evidence:** Complete command matrix/counts, Live artifact summary, browser observations/screenshots if safe, failures/fixes, remaining risks.

### Milestone 5: Documentation, Review, PR and Merge

**Goal:** Align repository truth, complete review and deliver D04 to main.

**Files / Modules:** README, D04 acceptance/execution reports, plan governance, Git metadata/PR; source only for review-proven narrow fixes followed by re-verification.

**Implementation Intent:** Update stale README D03/D04 statement, write acceptance report, self-review security/state/concurrency, independent review if available, commit only D04 files, push, open PR linked to #48, resolve review/CI, squash merge, verify origin/main.

**Tests / Checks:** final diff/status, secrets/generated file scan, relevant full gates if code changes after review, GitHub PR checks, merge commit verification.

**Expected Result:** One reviewable D04 squash commit on main, Issue #48 closed by PR, no D01/unrelated files included, rollback documented.

**Stop Condition:** CI/review reveals unresolved correctness/security issue, branch contains unrelated work, GitHub auth/permission fails, or merge would violate branch protection.

**Rollback Note:** Before merge, close PR/abandon branch; after merge, create revert PR for the single D04 squash commit. No schema/config rollback needed.

**Handoff Evidence:** Commit SHA, PR URL, review findings/resolutions, CI results, merge SHA, origin/main verification, final retrospective.

## 13. Execution Protocol

- Execute exactly one milestone at a time.
- Start each milestone by restating its goal and allowed files.
- Run `git status --short` before editing.
- Do not overwrite user changes, especially untracked D01 documentation.
- Do not modify files outside allowed scope.
- Do not move to the next milestone without reporting evidence in the milestone execution report and updating this plan.
- If a required change is outside scope, stop and ask for approval.
- If tests fail, inspect the narrowest relevant logs and fix only the concrete issue.
- If two consecutive repair attempts fail, stop and produce `D04_CONTROLLED_INTERACTION_UI_MILESTONE_<N>_BLOCKED.md`.
- Do not claim completion without verification evidence.
- Update Progress, Decision Log, Surprises & Discoveries, and Outcomes & Retrospective as work proceeds.
- Satisfy the applicable Engineering Implementation Contract and report `Not applicable` categories explicitly.
- Tests are written/locked before corresponding behavior; do not weaken assertions after implementation.
- Default commands remain offline. Run Live only with the existing explicit switch and never echo credentials.
- After type/build commands, do not stage generated `*.tsbuildinfo` or build outputs.
- Review the diff before each wider test phase and before staging.

## 14. Rollback Plan

Before implementation, rollback is simply discarding the unexecuted plan. During implementation, each milestone should be isolated so it can be reverted independently.

- Branch strategy: all D04 work stays on `feat/d04-controlled-interaction-ui`, linked to Issue #48; never commit on main.
- User work: preserve `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` and any new unrelated changes; stage explicit D04 paths only.
- Milestone rollback:
  - M1: revert only D04 tests/stubs.
  - M2: revert domain/application observer and projection together.
  - M3: revert backend public frames and frontend consumer/UI atomically.
  - M4: remove only isolated test artifacts and revert narrow fixes if invalid.
  - M5: before merge close/abandon PR; after merge use a revert PR for the one squash commit.
- Config rollback: Not applicable; D04 must not change env/deploy config.
- Database rollback: Not applicable; no Schema or data migration.
- Dependency rollback: Not applicable; no dependency change permitted.
- Stop rather than continue if rollback would require destructive Git commands, touch user data, or cross forbidden scope.

## 15. Progress

- [x] Milestone 0: Safety and Baseline Check
- [x] Milestone 1: Lock or Add Tests / Reproduction
- [x] Milestone 2: Implement Core Change
- [x] Milestone 3: Add Validation, Error Handling, and Observability / Frontend UI
- [x] Milestone 4: Verification and Narrow Fixes
- [x] Milestone 5: Documentation and Handoff
  - Completed: 2026-09-04
  - Evidence: PR #49；code HEAD `d9d6b98` 的四项 GitHub Actions 全绿；D01 不在 PR；squash merge 与最终 main SHA 以不可变 PR 记录为准。

## 16. Decision Log

| Date | Decision | Reason | Source |
| --- | --- | --- | --- |
| 2026-09-03 | Use Option B typed async progress observer | Only option satisfying real-time authority, D03 backpressure and safe projection without framework migration | Solution Tradeoff |
| 2026-09-03 | Keep `chat-stream-v2` and add optional typed frames | Existing envelope/sequence was designed for control events and has no field conflict | Clarification D04-Q02 |
| 2026-09-03 | Separate domain progress, Application projection, Router mapping and Trace | Different failure/security semantics; prevents Trace becoming public API | Recon/Tradeoff |
| 2026-09-03 | Public plan only after Validator success | Planner draft is not executable or safe to present as accepted | Requirement/Clarification |
| 2026-09-03 | Independent step/tool lifecycles with stable IDs and plan revision | Handles parallel execution and replan without array-position inference | AG-UI pattern + local DAG |
| 2026-09-03 | Store owns monotonic reducer; components render only | Matches local Pinia pattern and prevents UI inference | Clarification/Pinia docs |
| 2026-09-03 | Include visible stop, map user stop to local CANCELLED + backend rollback | Productizes D03 cancellation without new resume protocol | Clarification D04-Q17/Q18 |
| 2026-09-03 | Current-page process state only; recovery deferred to D06 | No persisted request-event relation exists; avoid scope collision | Clarification D04-Q15 |
| 2026-09-03 | No new dependencies/heartbeat/Playwright | Existing stack can verify requirement; no proxy timeout evidence | Tradeoff |
| 2026-09-03 | Max two protected Live cases, one real Tushare | Control API cost while proving full real chain and degradation | Requirement/Clarification |
| 2026-09-03 | Accept the D03 focused baseline as the D04 implementation starting point | Branch and `origin/main` both resolve to `eb0549b`; 30 focused Python tests and 13 focused frontend tests pass | Milestone 0 execution |
| 2026-09-03 | Lock D04 contracts with delayed Python imports and behavior-first frontend assertions, without production stubs | Preserves one red failure per missing capability while keeping production behavior untouched in M1 | Milestone 1 execution |
| 2026-09-03 | Treat pre-start WebSocket failure as a rejected streaming attempt eligible for HTTP fallback | Current internal resolve makes `ChatView` fallback unreachable; rejecting only before `stream_start` avoids duplicate execution after partial progress | D04-Q19 + M1 test evidence |
| 2026-09-03 | Publish progress through an optional typed domain observer and project it in Application before the shared D03 ack queue | Keeps REST/no-observer behavior unchanged, preserves cancellation/backpressure, and prevents raw domain or Trace objects from becoming public payloads | Milestone 2 execution |
| 2026-09-03 | Emit tool `STARTED` only after the Executor obtains its concurrency permit; emit direct `SKIPPED` for dependency/dedup paths | Makes UI lifecycle correspond to real ToolPort execution and avoids fabricated calls | Milestone 2 execution |
| 2026-09-03 | Keep Router support out of M2 even though real WS flows now encounter the new Application event | The frozen atomic backend/frontend protocol slice belongs to M3; M2 proves the six remaining reds are all at `_present_chat_stream` | Milestone 2 execution |
| 2026-09-03 | Validate every D04 public frame with a dedicated Pydantic model and a strict TypeScript allowlist parser | Preserves the Router-as-adapter boundary and rejects accidental raw tool/domain payloads before Store mutation | Milestone 3 execution |
| 2026-09-03 | Make Pinia the only current-request execution state owner and reject request/session mismatches plus terminal regressions | Parallel steps and late frames cannot corrupt the active request or re-open completed work | Milestone 3 execution |
| 2026-09-03 | Reject only pre-start WebSocket failure for HTTP fallback and reuse the optimistic user row without duplicating it | Provides deterministic fallback while preventing a second execution after any server progress | Milestone 3 execution |
| 2026-09-03 | Hide the controlled panel until an authoritative control event exists, except for explicit `UNAVAILABLE` | Clarification/static paths must not display a fabricated validated-plan card | Milestone 3 execution |
| 2026-09-04 | Hide ChatView auxiliary sidebars below 1024px and preserve the controlled chat mainline | Browser evidence showed the two fixed 256px sidebars reduced the 390px input to zero width | Milestone 4 execution |
| 2026-09-04 | Allow a default-off deterministic model delay only in offline test wiring | Actual stop UI needs a stable authority-event window without adding a production dependency or paid call | Milestone 4 execution |
| 2026-09-04 | Make protected Live accept evidence-driven `PARTIAL` while requiring frame/terminal consistency | Real Tushare can omit a dimension; correct degradation is a success condition, not a fake failure | Milestone 4 execution |
| 2026-09-04 | Defer only local Compose runtime evidence to M5 GitHub Actions | Both Compose configs are valid, but Docker Desktop 4.86.0 crashes on an inaccessible host reparse point before repository code runs | Milestone 4 execution |
| 2026-09-04 | Approve the D04 implementation after final scoped self-review | Architecture, state/concurrency, cancellation, public payload redaction, generated files and secret scans found no blocking issue; final approval remains conditional on PR CI including Compose | Milestone 5 review |
| 2026-09-04 | Keep D01 outside every D04 stage and commit | The untracked D01 requirement belongs to another delivery and must not enter Issue #48 | User-change protection |
| 2026-09-04 | Fix D04 type aliases instead of upgrading the production image | GitHub Actions proved the Python 3.11 backend image rejected PEP 695 syntax; `TypeAlias` keeps the same contract without deployment/dependency expansion | PR #49 CI diagnosis |
| 2026-09-04 | Use PR #49 as the immutable final merge record | A commit cannot truthfully contain its own future squash SHA; the committed report records pre-merge evidence while GitHub and `origin/main` record the resulting identity | Milestone 5 delivery |

## 17. Surprises & Discoveries

| Finding | Impact | Action |
| --- | --- | --- |
| Domain already has strong plan/verification/replan contracts | D04 can project real state without changing financial logic | Reuse contracts; add observer only |
| `WorkflowEvent` is emitted during run but Trace Sink is sync/best-effort | Reusing it for WS would lose backpressure and mix public/internal contracts | Keep separate typed async progress observer |
| Executor returns observations only after each layer | Final result cannot provide real tool-start UI | Add observer at `_run_step` call boundaries |
| Domain `StepStatus` has only result states | UI PLANNED/RUNNING/REPLANNED/CANCELLED must not mutate result semantics | Define separate progress/public status enum |
| Frontend parser rejects all unknown frames | Backend D04 cannot be deployed alone without UI consumer | Treat backend/frontend v2 additions as one atomic deliverable |
| README still says WebSocket is not provider streaming | Repository truth is stale after D03 | Correct in M5 with D04 status |
| The first parallel frontend baseline invocation returned only Vitest startup output without an exit code | That invocation cannot be treated as test evidence, even though no failure was printed | Re-ran the same six files with verbose Vitest; 13 tests passed with exit code 0 |
| `sendMessageStream` catches a constructor/connect failure and resolves instead of rejecting | `ChatView.handleSend` never reaches its documented HTTP fallback for this failure class | Lock a test that requires pre-start rejection plus `UNAVAILABLE` process state; implement in M3 |
| A missing Vue component fails the Vitest suite during Vite import analysis rather than as two individual assertions | The failure still precisely identifies the absent D04 panel, but its two rendering cases cannot collect until M3 | Record as an intentional M1 red-suite limitation; do not add a fake production component in the test-only milestone |
| Existing real-workflow WebSocket tests now stop before content because Router deliberately rejects the new Application progress event | Domain/Application behavior is correct, but the backend/frontend protocol slice cannot be deployed independently | Keep six Router/E2E tests explicitly red in M2 and close them atomically in M3 |
| Using the shell-resolved `python.exe` produced no test output because it is the WindowsApps launcher | An exit code from that launcher is not valid verification evidence | Use the repository `.venv\Scripts\python.exe` and `.venv\Scripts\ruff.exe` for all recorded checks |
| The D03 midstream-failure E2E asserted an exact three-frame sequence | D04 correctly inserts safe control frames before the first text delta, making that old shape assertion stale while rollback semantics remain valid | Update the assertion to require start, ordered controls, one delta, safe error and zero persisted messages |
| `vue-tsc -b` rewrites the tracked `tsconfig.node.tsbuildinfo` with the bundled TypeScript version | Generated metadata would create an unrelated diff | Restore the original tracked content after every type/build command and keep it out of delivery |
| Initial client state exists before the first authoritative progress frame | Rendering it immediately would falsely label a connecting/clarification request as a validated plan | Gate the panel on real control content; still render the explicit HTTP-fallback `UNAVAILABLE` state |
| At 390px, AppLayout's two fixed sidebars leave the chat input with zero width | The page has no horizontal overflow but is unusable, so CSS-only overflow checks are insufficient | Hide auxiliary sidebars for this view below 1024px and assert actual input geometry in browser |
| A one-chunk deterministic provider completes before browser automation can click stop | Browser evidence would be flaky even though unit semantics are correct | Add a default-off test-only chunk delay and wait for the authority-backed panel before stopping |
| The real Tushare run lacked `financial_indicator` evidence | A hard `SUFFICIENT` Live assertion incorrectly rejects the system's intended safe degradation | Assert `sufficiency`, missing dimensions, limitation and terminal status as one coherent contract |
| Docker Desktop repeatedly exits before engine creation | Local Compose runtime cannot exercise repository code; reset/destructive work would be disproportionate | Record exact host failure and require the M5 GitHub Actions Compose job before merge |
| Uvicorn WebSocket connection logging can expose a query token | D04 payload redaction does not solve transport/logging secrecy | Keep auth redesign out of D04 and carry a dedicated security follow-up |
| The first PR CI run failed in the Python 3.11 production image while Python 3.12 quality checks passed | D04 used PEP 695 aliases that the packaging smoke import could not parse | Replace both touched stream aliases with `typing.TypeAlias`; 3.11 syntax, focused tests and all four rerun jobs passed |
| GitHub Copilot review could not run because the account quota was exhausted | No independent automated review findings were available | Record the limitation honestly; rely on the requested systematic Codex self-review and mandatory CI, without fabricating approval |

## 18. Outcomes & Retrospective

- What changed: D04 now provides the complete chain from Workflow/Executor authority points through Application safe projection, Pydantic `chat-stream-v2` frames, strict TypeScript parsing, request-scoped Pinia reduction, controlled execution rendering, visible user stop and a usable narrow layout. README and acceptance evidence now match the running behavior.
- What was verified: 15 focused D04 Python tests, 377 root offline tests and 27 frontend tests pass; scoped Ruff/Pyright, ESLint/vue-tsc and production build pass. A real-model + real-Tushare run proves control-frame ordering/redaction and safe `PARTIAL` degradation. Browser checks prove desktop/narrow rendering, stop and Skill confirmation. PR #49 then passed Python、frontend、production Docker packaging and full Offline Compose E2E on GitHub Actions after the Python 3.11 compatibility fix.
- What remains risky: the repository has historical full-scope Ruff/Pyright debt, dependency advisories, WebSocket query-token logging debt and local Docker Desktop corruption. GitHub Actions proved repository Docker/Compose correctness, so the remaining Docker failure is host-specific.
- What should be improved next: do not extend D04. Continue with D05 only after PR #49 is squash-merged and `origin/main` resolves to its merge commit.

## 19. Deferred Work

- D05 report SSE with polling fallback.
- D06 Redis idempotency/state snapshot/reconnect recovery/duplicate submit/status query.
- Persistent/refreshable execution cards and event replay.
- Full AG-UI/LangGraph event runtime or cross-mode unified event bus.
- Heartbeat/idle timeout, multi-instance broadcast and checkpointing.
- Raw trace/debug/COT UI and complete generation/tool child spans.
- WebSocket auth query/access-log security task.
- Browser automation dependency adoption.

## 20. Handoff to Small-step Implementation

Milestone 5 is complete. PR #49 is the immutable delivery record; its final squash commit and `origin/main` verification are recorded externally because a commit cannot contain its own future SHA. Do not start D05/D06 or touch the unrelated D01 file until PR #49 is merged and the remote main identity is verified.
