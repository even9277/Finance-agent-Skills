# SOLUTION_TRADEOFF.md

## 1. Tradeoff Context

D04 的核心不是增加静态卡片，而是让真实受控执行过程以安全、类型化、可取消且有背压的方式到达前端。现有工作流已经拥有权威 Plan、ValidatedPlan、ToolObservation、VerificationResult 和 Replan，但公开 Application stream 只有 started/content/completed/failed；内部 WorkflowEvent 主要服务 Trace，不能直接作为公共 UI API。

本次方案必须在不改变金融决策、Prompt、工具权限、数据库、Redis 和认证的前提下，补齐 plan/step/tool/evidence/trace summary 的实时事件，同时保持 D03 的事务、取消、sequence 和单一终态。

## 2. Inputs Reviewed

- REQUIREMENT_SPEC.md: `docs/specs/D04_CONTROLLED_INTERACTION_UI_REQUIREMENT_SPEC.md`
- CODEBASE_RECON.md: `docs/specs/D04_CONTROLLED_INTERACTION_UI_CODEBASE_RECON.md`
- CLARIFICATION_QUESTIONS.md: `docs/specs/D04_CONTROLLED_INTERACTION_UI_CLARIFICATION_QUESTIONS.md`
- User decisions: 自主推进完整 Spec Coding、真实 API E2E、Review、Issue/PR/merge；验收和测试先于实现；不回归既有功能。
- External sources:
  - LangGraph Streaming official docs: https://docs.langchain.com/oss/python/langgraph/streaming
  - FastAPI WebSocket official reference: https://github.com/fastapi/fastapi/blob/master/docs/en/docs/reference/websockets.md
  - Pinia Actions official docs: https://pinia.vuejs.org/core-concepts/actions.html
  - AG-UI event definitions: https://github.com/ag-ui-protocol/ag-ui/blob/main/docs/sdk/js/core/events.mdx
  - LangGraph runtime repository: https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/runtime.py
  - LangChain streaming cookbook repository: https://github.com/langchain-ai/streaming-cookbook

## 3. User Decisions and Defaults

### 3.1 Confirmed Decisions

- D04 必须真实显示 validated plan、step/tool 生命周期、Evidence summary 和 request lifecycle。
- 继续扩展 `chat-stream-v2`，不建第二协议。
- 加入可见停止按钮，复用 D03 WebSocket 断连取消。
- 默认离线测试，protected Live 最多两条且可调用真实模型/Tushare。
- D04 不做跨刷新恢复、Redis 状态、数据库迁移、Prompt/Skill/Tool policy 改动。
- 公开载荷必须显式白名单投影，不能透传内部对象或 Trace attributes。

### 3.2 Conservative Defaults Used

- 控制状态只保留当前页面生命周期；跨刷新归 D06。
- 工具和步骤使用独立事件与稳定 ID。
- HTTP fallback 仅保留最终文本并明确过程状态不可用，不伪造执行过程。
- 不新增 heartbeat、Playwright 或生产依赖。
- 领域结果枚举保持不变，公共 UI 生命周期使用独立枚举。

### 3.3 Blocking Decisions

None. 所有 P0 产品、安全、持久化和测试边界均已冻结。

## 4. Core Decision Point

决定真实执行进度应从哪里产生并如何进入现有 D03 流：复用内部 Trace、在完成后事后投影，还是建立独立的 typed async progress observer，通过 Application 的有背压事件队列映射到安全公共帧。

## 5. Reference Sources and Repository Evidence

### 5.1 Official Docs

#### Source: LangGraph Streaming

**Link:** https://docs.langchain.com/oss/python/langgraph/streaming

**What was inspected:** v2 统一 stream part、`updates/messages/custom/tasks/debug` 多种模式，以及节点/工具内 custom progress writer。

**Relevant practice:** 用户需要的进度应作为有判别类型的 stream concern 输出；`custom` 用于应用定义的进度，`debug`/完整 state 不适合作为用户公共合同。

**Reusable part:** Partially reusable

**Fit for this task:** 本仓库不是 LangGraph Pregel runtime，但可以直接复用“业务进度独立于 token 与 debug trace、通过 typed stream 输出”的边界思想；不需要改造为 LangGraph stream API。

#### Source: FastAPI WebSocket Reference

**Link:** https://github.com/fastapi/fastapi/blob/master/docs/en/docs/reference/websockets.md

**What was inspected:** WebSocket receive/send/close 能力及 `WebSocketDisconnect` 生命周期。

**Relevant practice:** 连接断开必须作为显式异常/状态处理，发送与接收生命周期需由应用控制。

**Reusable part:** Directly reusable

**Fit for this task:** 现有 D03 已正确实现 receive-side disconnect watcher；D04 只需确保 progress observer 等待和 executor 并发在断连时同步取消，不改 Router 基础模型。

#### Source: Pinia Actions

**Link:** https://pinia.vuejs.org/core-concepts/actions.html

**What was inspected:** Store actions 集中业务状态变更、异步 action 与 action outcome 观察。

**Relevant practice:** 复杂状态转换应由 Store action/reducer 管理，组件只触发动作并渲染状态。

**Reusable part:** Directly reusable

**Fit for this task:** D04 的 request/revision/step/tool 单调状态适合放入现有 setup store actions，而不是 `useChat` 或 Vue 组件局部推断。

### 5.2 Open-source Repositories

#### Source: AG-UI Protocol Repository

**Link:** https://github.com/ag-ui-protocol/ag-ui/blob/main/docs/sdk/js/core/events.mdx

**What was inspected:** Run/Step/Text/Tool lifecycle events、stable IDs、discriminated union 和 state snapshot/delta 分类。

**Relevant practice:** run、step、tool 与文本应是不同生命周期；事件用判别字段和关联 ID；客户端据此归一化状态。

**Reusable part:** Partially reusable

**Fit for this task:** 直接采用完整 AG-UI 会扩大协议和依赖，但其生命周期拆分、ID 关联和 typed union 可缩减映射到现有 `chat-stream-v2`。

#### Source: LangGraph Runtime Repository

**Link:** https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/runtime.py

**What was inspected:** run-scoped Runtime 注入 `stream_writer`、execution info、heartbeat、control，而不是让节点依赖 Web/UI。

**Relevant practice:** 执行进度出口应以运行级依赖注入到工作流/工具边界，业务节点不导入传输协议。

**Reusable part:** Partially reusable

**Fit for this task:** 本仓库已有显式依赖注入和 Ports，可用小型 `ConversationProgressObserver` 达到同样效果；不引入 LangGraph runtime/checkpointer。

#### Source: LangChain Streaming Cookbook Repository

**Link:** https://github.com/langchain-ai/streaming-cookbook

**What was inspected:** typed protocol envelope、按 messages/tools/lifecycle/custom concerns 分流、sequence metadata 和自定义 projection 的方向。

**Relevant practice:** typed events 优于裸 chunk；公共 projection 应与内部状态解耦；消费者不应推断事件来源。

**Reusable part:** Conceptual only

**Fit for this task:** 仓库内容处于新 streaming API 演进方向，不能直接复制；仅支持保持现有 v2 envelope 和显式 projection 的设计判断。

### 5.3 Local Project Patterns

| Local pattern | Evidence from CODEBASE_RECON.md | How to reuse |
| --- | --- | --- |
| D03 Application event queue + ack | `backend/application/chat/use_case.py` | 所有 D04 公开事件进入同一 queue，继续传播发送背压与取消 |
| Router-only Pydantic mapping | `backend/routers/chat.py`、`backend/schemas/chat.py` | Router 不做业务判断，只把安全 Application event 映射为 v2 frame |
| Validator-only execution | `validation.py`、`execution.py` | 只在 validation success 后发 plan preview |
| Domain Ports | `conversation/ports.py` | 新增可选 progress observer protocol，避免导入 backend/WebSocket |
| Immutable typed contracts | `conversation/contracts.py` | 内部进度也用 dataclass/enum，不用任意 dict |
| Trace best-effort side channel | `infrastructure/chat/trace.py` | 保持 Trace 独立，不能让 UI 发送失败被 Trace 语义吞掉 |
| Strict TS parser | `frontend/src/api/index.ts` | 新帧逐字段验证、未知/畸形事件拒绝 |
| Pinia state owner | `frontend/src/stores/chatStore.ts` | 单调 reducer、request/revision/ID 隔离集中在 Store |
| Protected Live E2E | `tests/e2e/test_live_controlled_chat_chain.py` | 复用凭证 gate、临时 DB、真实 Provider 和脱敏 artifact |

## 6. Reusable Patterns

### 6.1 Directly Reusable Patterns

- 现有 D03 v2 envelope、sequence、单一终态和 strict parser。
- Application 容量 1 queue + per-event acknowledgement。
- FastAPI receive-side disconnect watcher 和 generator close 取消传播。
- Pydantic public projection 与前端 TypeScript discriminated union。
- Pinia action 集中状态转移。
- 现有 fake providers、replan/failure fixtures、Live gate 和 CI 分层。

### 6.2 Partially Reusable Patterns

- AG-UI 的 run/step/tool/text lifecycle：只借鉴拆分和 ID，不引入其完整 SDK/协议。
- LangGraph `stream_writer`：用本仓库 Port/observer 实现等价的运行级注入，不依赖 Pregel/checkpointer。
- WorkflowEvent：复用 stage/status 语义，但公开 trace summary 使用显式映射，不透传 attributes 或内部 sequence。

### 6.3 Conceptual References Only

- LangChain 新 streaming channels/projections。
- AG-UI state snapshot/delta，为未来 D06 恢复能力提供演进参考。
- LangGraph heartbeat/checkpointer；当前无空闲超时或恢复需求。

### 6.4 Not Suitable for This Iteration

- 把完整 AG-UI SDK 或 LangGraph runtime 引入主链。
- 使用 `debug`/完整 state/Trace JSONL 直接驱动用户 UI。
- 将事件写入 Redis/数据库再由 WS 轮询；属于 D06 且增加延迟与一致性复杂度。
- 完成后把 `ConversationResult` 展开成伪实时事件。
- 在前端解析最终回答文本或 Trace attributes 推断步骤。

## 7. Solution Options

### 7.1 Option A: Minimal Fix — Completed-result Projection

**What changes:** 在 `ChatStreamCompleted` 到达后，从 `ConversationResult.plan/verification/events` 一次性生成 plan、step、tool、verification 帧；前端增加卡片。

**What does not change:** Workflow/Executor/Application 事件模型不变。

**Benefits:** 代码量最小；几乎不触及并发执行和事务。

**Costs:** 所有过程事件都在执行结束后出现。

**Risks:** 形成伪进度；无法显示 RUNNING、停止时的真实状态或逐工具耗时；与用户和面试 Claim 冲突。

**Testing burden:** Low，但只能验证静态结果，无法满足 D04-C01/C02/C06。

**Rollback difficulty:** Low。

**Engineering impact:**

- Architecture/module ownership: Router/Application 事后拼装，权威时序不足。
- Documentation/types: 仍需公共 Schema/TS types。
- Configuration/secrets/prompts: 无变化。
- Terminal/logging/tracing/artifacts: 事件都紧邻终态，不能证明实时。
- Errors/retry/state: 中途失败/取消没有完整卡片。

**When to choose it:** 只需要“结果解释卡”而非执行进度时；不适合当前 D04。

### 7.2 Option B: Structured Improvement — Typed Async Progress Observer

**What changes:** 在 conversation domain 定义可选、typed、异步 `ConversationProgressObserver` 及有限进度事件；Workflow 在 Validator/Verifier/Replan 等权威点 await 发布，Executor 在每个 step/tool 调用开始和完成时 await 发布。Application 将领域进度显式投影成安全 `ChatStreamEvent` 并进入 D03 同一 ack queue；Router 只映射 Pydantic v2；前端 strict parser -> composable -> Pinia reducer -> 组件。

**What does not change:** 受控业务顺序、Planner/Validator/Verifier/Controller 规则、Trace Sink、HTTP 结果、Repository、数据库、Redis、Prompt、工具权限和 Provider。

**Benefits:** 真正实时；事件来源权威；发送失败/断连继续背压取消；公共投影与内部 Trace 分离；能覆盖并行、失败、replan、stop；为 D06 snapshot 演进保留清晰 typed source。

**Costs:** 中等跨层修改；并行任务事件顺序和 observer 失败语义需要严谨测试。

**Risks:** observer 处理不当可能拖慢工具执行、死锁 queue 或让 REST 路径受影响；过多领域对象传到 Application 可能造成泄露。

**Testing burden:** Medium/High，但与风险成比例：domain observer、Application queue、WS contract、frontend reducer/component、offline/Live E2E。

**Rollback difficulty:** Low/Medium；无数据迁移，可通过单个 squash revert 原子回滚前后端。

**Engineering impact:**

- Architecture/module ownership: Domain owns事实进度；Application owns安全 projection/transport-neutral stream；Router owns Pydantic/sequence；Store owns UI state。
- Documentation/types: 新 public/internal contract 必须 enum/dataclass/Pydantic/TS type + Google-style docstring。
- Configuration/secrets/prompts: 不新增配置或 Prompt；白名单为稳定代码常量。
- Terminal/logging/tracing/artifacts: 保持 Trace，新增低敏 frame counts/status；Live artifact 记录 event kinds/closed lifecycles。
- Errors/retry/state: observer 为可选 no-op；stream observer 失败/取消随业务任务回滚；Trace 仍 best-effort；前端 reducer 强制状态单调。

**When to choose it:** 需要真实过程可见、现有架构可复用、又不希望引入完整新框架时。适合当前 D04。

### 7.3 Option C: Long-term Architecture Direction — Adopt AG-UI/LangGraph Event Runtime

**What changes:** 将聊天输出重构为通用 agent event protocol，可能采用 AG-UI SDK 或 LangGraph v2 streaming/checkpointer，并统一对话、报告、恢复、HITL 和多客户端。

**What does not change:** 理想情况下领域金融规则保持，但传输、状态、前端和持久化大幅变化。

**Benefits:** 标准化生态、内置 run/tool/state lifecycle，长期可与 D05/D06/多 Agent UI 统一。

**Costs:** 高；协议迁移、依赖、前端 SDK、兼容层、checkpoint/state persistence 和全量测试。

**Risks:** 当前自研线性 workflow 与框架模型不完全一致；容易形成双 runtime、破坏 D03、扩大供应链和升级风险。

**Testing burden:** Very High。

**Rollback difficulty:** High。

**Engineering impact:**

- Architecture/module ownership: 重构整个 Agent/UI transport boundary。
- Documentation/types: 新协议和迁移文档大量增加。
- Configuration/secrets/prompts: 可能增加服务/SDK配置；Prompt 本身无需改。
- Terminal/logging/tracing/artifacts: 需重新映射 Trace 与外部协议。
- Errors/retry/state: 需重建 run/checkpoint/reconnect 语义。

**When to choose it:** 对话、报告、HITL、跨设备恢复和多 Agent 都需要统一协议且用户接受专项迁移时。Deferred。

### 7.4 Option D: Observation-first Option

**What changes:** 只增加 Trace/log/test 证明现有阶段，不提供用户 UI。

**What does not change:** 公开协议和前端。

**Benefits:** 风险最低；可建立额外基线。

**Costs:** 不解决用户体验和文档 Gap。

**Risks:** 继续只有内部可观测，用户仍面对黑盒。

**Testing burden:** Low。

**Rollback difficulty:** Low。

**Engineering impact:**

- Architecture/module ownership: 只扩 Trace。
- Documentation/types: 低。
- Configuration/secrets/prompts: 无。
- Terminal/logging/tracing/artifacts: 内部观测增强。
- Errors/retry/state: 无改善。

**When to choose it:** 代码/运行证据不足时。Recon 已获得充分证据，因此不选。

## 8. Decision Matrix

| Dimension | Option A Minimal Fix | Option B Structured Improvement | Option C Long-term Architecture | Option D Observation-first |
| --- | --- | --- | --- | --- |
| Scope | Small | Medium | Large | Small |
| Development Cost | Low | Medium | High | Low |
| Risk | Medium（伪进度） | Medium（并发/取消） | High | Low |
| Reusability | Low | High | High | Medium |
| Fit to Current Requirement | Low | High | Medium | Low |
| Local Pattern Fit | Medium | High | Low | High |
| External Pattern Fit | Low | High（缩减生命周期/stream writer） | High（完整采用） | Medium |
| Test Burden | Low | Medium/High | Very High | Low |
| Rollback Difficulty | Low | Low/Medium | High | Low |
| Observability Improvement | 表面结果 | 用户实时 + 内部独立 | 全面但过度 | 仅内部 |
| Long-term Maintainability | Low | High | Potentially high | Medium |
| Engineering-standard fit | Low | High | Medium（过度设计） | Medium |
| Recommendation | Reject | Select | Defer | Reject |

## 9. Recommended Solution

Selected option: Option B — Typed Async Progress Observer。

Why selected:

- 是唯一同时满足真实进度、权威状态、安全投影、取消传播和现有架构复用的方案。
- 直接复用 D03 ack queue、v2 envelope、strict parser、Pinia 和 protected Live 测试。
- 领域 workflow 不依赖 FastAPI/Vue，Trace 不承担公共传输，职责清楚。
- 无新生产依赖、配置或数据迁移，仍可通过一个 squash commit 回滚。

Why not the other options:

- Option A 只能事后解释，不能证明真实执行进度。
- Option C 适合未来统一协议，但当前会引入框架迁移和双轨风险。
- Option D 已不必要，因为 Recon 已定位事件缺口。

Local patterns reused:

- Conversation Ports + immutable contracts。
- D03 Application queue/ack、Router Pydantic mapping、v2 sequence 和 disconnect cancellation。
- frontend strict parser/composable/Pinia/component 分层。
- pytest/Vitest/Compose/protected Live 分层门禁。

External practices reused:

- LangGraph custom stream 的“进度独立于 token/debug”原则。
- AG-UI 的 run/step/tool/text 分离与 stable ID lifecycle。
- Pinia actions 集中状态转换。
- FastAPI 显式处理 WebSocket disconnect。

Remaining risks:

- 并行 executor 中多个异步进度事件的交错顺序。
- observer backpressure 对工具总超时预算的影响。
- 工具参数/结果投影的白名单完整性。
- 用户取消时客户端无法再收到服务端终态，只能结合本地动作与服务端 rollback 证据验收。
- README 和历史矩阵中 D03/D04 状态可能仍有过时描述。

What must be verified later:

- plan preview 只来自 validation success，且必在对应 tool STARTED 前。
- 每个 step/tool ID 的状态单调且闭合；并行到达不串线。
- progress await 不破坏 D03 ack/commit/cancel；REST 无 observer 时语义不变。
- public projection 和日志/artifact 不包含 forbidden fields。
- frontend stop 不追加错误文本，后台任务与事务在限定时间内取消/回滚。
- real model/Tushare 路径真的产生 control frames，最终回答、数据库和 Trace 一致。

## 10. Unified Technical Direction

- 在 `Financial-MCP-Agent/src/conversation` 建立一个可选、typed、异步、协议无关的 run progress observer；Workflow 只在权威阶段发布，Executor 只在真实 step/tool 调用边界发布。
- 在 `backend/application/chat` 把领域进度显式映射为安全 Application stream event，并复用 D03 同一容量 1 acknowledgement queue；不得复用 best-effort Trace Sink，也不得整体序列化领域对象。
- 在 `backend/schemas/chat.py` 和 Router 中新增 `trace_summary/plan_preview/step_status/tool_status/verification_summary` Pydantic 帧，继续使用 Router-owned v2 sequence 和唯一终态。
- 在前端拆出 D04 事件类型/校验与 request-scoped execution view model；`useChat` 只分发并拥有 stop socket side effect；Pinia actions 实施 request/session/revision/ID 校验和单调状态；Vue 组件只渲染和 emit stop。
- 先建立失败基线测试，再实现；覆盖 validation gate、并行/重复/迟到、失败/PARTIAL、replan、no-tool/Skill confirm、stop/rollback、并发会话、D03 回归和敏感字段负向断言。
- protected Live 最多两例，真实模型和至少一例真实 Tushare；记录低敏 event kinds、闭合状态、TTFT/elapsed/hash，而非 Prompt/正文/原始工具载荷。
- 不改数据库、Redis、auth、Prompt、Skill/Tool policy、Evidence 决策、报告 SSE、跨刷新恢复、heartbeat、Playwright 或生产依赖。

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| progress observer 与 Trace 职责重叠 | 领域 facts 可共享，但接口、失败语义和消费者分离；Trace best-effort，stream observer backpressured |
| 并行事件 nondeterministic | 只要求全局 public sequence + 每 ID 局部单调；Store 按 stable ID 更新，不依赖数组顺序 |
| observer 等待计入工具超时 | 工具单次 timeout 只包 Provider execute；总预算计算需明确是否排除发送等待，并用慢消费者测试 |
| queue deadlock / terminal missing | 沿用 D03 ack 协议；每类事件测试发送失败、generator close 和唯一终态 |
| 原始领域对象泄露 | 单独 public projection，字段白名单、长度限制、forbidden-key/secret 负向测试 |
| replan 误改旧步骤 | plan revision + plan/step ID；已完成 immutable，未执行旧步骤显式 REPLANNED |
| stop 被当网络错误 | composable 区分 user stop 和 unexpected close；本地 CANCELLED，后端断连测试证明 rollback |
| HTTP fallback UI 残留 | fallback 前清理 active execution 并设置 process-unavailable 降级，不伪造状态 |
| 信息过载 | 单面板分层摘要，工具参数/结果默认短文本，不做 raw debug 展示 |

## 12. Verification Direction

### 12.1 Engineering Contract for Plan Freezing

- Architecture/module ownership: Domain owns authoritative progress facts; Application owns safe stream projection/backpressure; Router owns public schema/sequence; composable owns socket; Store owns state; components own rendering only.
- Interfaces/docstrings/types: Python enum/dataclass/protocol/Pydantic + 中文 Google-style docstring；TS discriminated unions/typed view model；所有公开状态枚举冻结并逐字段校验。
- Configuration/secrets/constants/prompts: 不新增配置/Prompt；display/parameter/error whitelist 是稳定代码常量；Live 凭证沿用 Settings 和显式 gate。
- Terminal/logging/tracing/artifacts: 保持现有 Trace；新增 frame kind/count/closed lifecycle 的低敏验收；不记录正文、Prompt、完整 args/results、token。
- Validation/errors/retry/state: validation gate；observer/cancel 异常传播到 Application rollback；Trace failure remains non-blocking；per-ID monotonic frontend reducer；HTTP fallback explicit degradation。
- Tests/evaluation/delivery evidence: tests-first unit/contract/frontend/E2E，full pytest，frontend lint/type/test/build，Compose E2E，最多两条 protected Live，实际浏览器验收，diff/security review，Issue #48、PR、CI、squash merge。

## 13. Deferred Work

- D05 报告 SSE + polling fallback。
- D06 Redis idempotency/state snapshot/reconnect recovery/duplicate submission protection/status query。
- AG-UI/LangGraph 通用协议迁移、对话/报告统一事件总线。
- 跨刷新控制卡片历史、chunk replay、multi-instance broadcast/checkpointer。
- heartbeat/idle-timeout、完整 raw trace/debug UI、generation/tool child spans、在线 score 回流。
- WebSocket auth query token 与 access log 专项安全治理。
- Playwright 或其他浏览器自动化依赖。

## 14. Handoff to Plan Freezing

Next step should use the Plan Freezing Skill and produce `PLAN.md`.

The plan should:

- follow selected option: Option B typed async progress observer + safe Application projection + v2/Pinia/UI。
- allow modules/files: `Financial-MCP-Agent/src/conversation/{contracts,ports,workflow,execution}.py`、`backend/application/chat/{contracts,use_case,factory}.py`、`backend/schemas/chat.py`、`backend/routers/chat.py`、D04 frontend chat modules、相邻 tests/docs/CI only if needed。
- forbid modules/files: report、database/migrations、Redis/memory authority、auth、prompts、skills/tool policies、production credentials、unrelated generated files。
- include required tests: D04-C01～C08、projection redaction、observer/ack/cancel、parallel/replan、parser/reducer/component、offline/Compose/Live/browser and D03 regression。
- include required logs/metrics: request/session/run correlation、frame kinds/counts、per-tool elapsed、terminal/error、artifact hash；无正文/Prompt/secret/raw payload。
- include rollback strategy: one short branch/PR/squash commit, no migration, atomic frontend/backend revert。
- preserve these constraints: Validator-only plan、Verifier-only sufficiency、single runtime、single terminal、default offline、max two protected Live、no new dependency。
- keep these external references in mind: LangGraph custom progress stream、AG-UI lifecycle/stable IDs、Pinia action state ownership、FastAPI disconnect lifecycle；只缩减借鉴，不引入框架。
