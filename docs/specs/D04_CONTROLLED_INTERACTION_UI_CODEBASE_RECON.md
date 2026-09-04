# CODEBASE_RECON.md

## 1. Reconnaissance Target

Requirement source:

- `docs/specs/D04_CONTROLLED_INTERACTION_UI_REQUIREMENT_SPEC.md`
- 用户要求补齐 D04 受控交互 UI，并在开发前冻结验收与真实 API E2E 标准。
- `金融Agent项目-统一口径总览.md`、`对话模式与可观测与skills.md`、相关成果点完整阐述中的前端可观测 Claim。

Focus areas:

- 从 `/api/chat/stream` 到受控工作流的公开流式事件链。
- Planner、Validator、Executor、Evidence Verifier、Controller、Replanner 的现有权威状态。
- WebSocket v2 Schema、Presenter、Application 事件流及 Trace Sink。
- 前端协议解析、Socket 生命周期、Pinia 状态、ChatView/ChatWindow/ChatInput 组件归属。
- 现有单元、契约、集成、离线 E2E、Live E2E 和浏览器验收基础。

Out-of-scope reminders:

- 不修改 D05 报告 SSE、D06 Redis/幂等/恢复、Skills/Memory/Prompt/Tool 策略、认证、数据库 Schema 或部署架构。
- 不公开原始 Prompt、思维链、完整工具参数/结果、私有异常或敏感身份信息。
- Recon 只确认事实和 Gap，不在本文件冻结最终实现方案。

## 2. Project Overview

Project type: 前后端分离的模块化单体金融 Agent 应用，包含对话与报告两类业务模式。

Languages: Python 3.12、TypeScript、Vue SFC、少量 Shell/Docker 配置。

Frameworks: FastAPI、Pydantic v2、SQLAlchemy 2、Vue 3、Pinia、Vite、Vitest；领域 Agent 采用自研受控 Workflow，并使用 LangChain/OpenAI-compatible Provider 适配。

Runtime / package manager: Python 使用 uv/`uv.lock`；前端使用 npm/`package-lock.json`；容器使用 Docker Compose。

Main service type: FastAPI HTTP/WebSocket API + Vue SPA；PostgreSQL/SQLite 作为持久化选项，Redis 当前主要用于可丢弃的记忆热缓存。

Frontend/backend split: `frontend/` 为 Vue 客户端，`backend/` 为 API/Application/Infrastructure，`Financial-MCP-Agent/src/conversation/` 为框架无关受控对话领域链。

Test framework: pytest + marker 分层，Vitest + Vue Test Utils，Docker Compose 离线 E2E；当前未安装 Playwright。

Deployment clues: `docker/Dockerfile.backend`、`docker/Dockerfile.frontend`、`docker/docker-compose.yml`、`docker/docker-compose.offline.yml`、Nginx WebSocket 代理。

Confirmed facts:

- `backend/main.py` 在 `/api/chat` 注册对话 Router。
- 前端 Vite 将 `/api` 的 HTTP 与 WebSocket 代理到 `localhost:8000`。
- D03 已将公开流式协议原子升级为 `chat-stream-v2`，并有真实 Provider streaming、断连取消和单一终态测试。
- 受控工作流内部已经实现 Planner、Validator、Executor、Verifier、Controller 和一次有界 Replan。
- 当前公开 WebSocket 类型中没有 `plan_preview`、`step_status`、`tool_status`、`verification_summary` 或 `trace_summary`。
- 当前前端没有计划、步骤、工具和证据展示组件或 Store 状态。

Assumptions:

- D04 不要求跨刷新恢复控制卡片；该能力按需求归入 D06。
- D04 可以在不新增生产依赖和数据库迁移的前提下完成。
- 控制事件仍属于 `chat-stream-v2` 的兼容增量，而不是新协议版本。

## 3. Directory Structure Summary

| Path | Apparent role | Relevance | Notes |
| --- | --- | --- | --- |
| `backend/routers/chat.py` | REST/WS 协议适配与连接生命周期 | Direct | 将 Application 事件映射为 v2 帧并统一编号 |
| `backend/schemas/chat.py` | 公开请求、响应和 v2 帧 Pydantic Schema | Direct | 当前只有文本、终态、上下文、记忆和 Skill 确认帧 |
| `backend/application/chat/` | 唯一聊天用例、事件合同和装配 | Direct | HTTP/WS 共用执行核心；当前应用事件类型不足以实时承载 D04 |
| `backend/infrastructure/chat/` | Provider、Repository、Trace Adapter、测试替身 | Direct/supporting | Trace Sink 可接收工作流阶段；工具 Provider 执行真实 Tushare/Tavily |
| `Financial-MCP-Agent/src/conversation/` | 受控领域主链 | Direct | 权威计划、验证、执行、证据、控制和重规划均在此 |
| `frontend/src/api/index.ts` | 前端 API 和 v2 公共类型/严格解析 | Direct | 当前 union 和 parser 拒绝 D04 新事件 |
| `frontend/src/composables/useChat.ts` | WebSocket 副作用、帧顺序和分发 | Direct | 当前只分发 D03/Memory/Skill/Context/Compression |
| `frontend/src/stores/chatStore.ts` | 会话、消息、streaming 和压缩状态 | Direct | 当前没有请求级执行视图模型 |
| `frontend/src/components/chat/` | 对话展示组件 | Direct | 只有文本、输入、Skill 确认和上下文组件 |
| `frontend/src/views/ChatView.vue` | 对话页组合 | Direct | 当前只组合 ChatWindow、SkillConfirmation、ChatInput 等 |
| `tests/unit/conversation/` | 领域与 Application 单元/合同测试 | Supporting | 已覆盖计划、证据、replan、streaming 和取消 |
| `tests/contract/` | API/WebSocket 公开合同 | Supporting | 已覆盖 v2、Skill 确认、并发隔离和断连 |
| `tests/e2e/` | 离线/Compose/Live 全链验收 | Supporting | D03 Live 已有真实模型和真实 Tushare 基础 |
| `frontend/src/**/__tests__/` | Parser、composable、Store、组件测试 | Supporting | 可沿用 Vitest 与 FakeWebSocket 模式 |
| `docs/specs/controlled-conversation-mainline/` | Claim 到实现的历史审计 | Supporting | 已明确将 D04 卡片标为 Deferred |

## 4. Entry Points

### 4.1 Startup Entry

- Backend: `backend/main.py` 构造 FastAPI，注册 `chat.router` 到 `/api/chat`；README 推荐 `uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload`。
- Frontend: `frontend/src/main.ts` 装配 Vue、Pinia、Vue Router；`frontend/vite.config.ts` 监听 5173 并代理 `/api`，README 推荐 `npm run dev`。
- Compose: `docker/docker-compose.yml` 为生产形态，`docker/docker-compose.offline.yml` 为隔离 PostgreSQL + offline E2E 门禁。

### 4.2 Request / Task Entry

1. `ChatView.handleSend()` 优先调用 `useChat.sendMessageStream()`，异常时才回退 `sendMessage()`。
2. `sendMessageStream()` 创建 request ID、用户乐观消息和 assistant 占位消息，然后连接 `/api/chat/stream`。
3. `backend.routers.chat.chat_stream()` 认证、Pydantic 校验输入，创建数据库 Session 和 `ControlledChatUseCase`。
4. `ControlledChatUseCase.stream()` 包装同一 `_execute()` 核心，当前只输出开始、正文增量、完成或技术失败。
5. `ControlledConversationWorkflow.run()` 完成上下文、实体、路由、改写、权限、规划、校验、执行、证据、控制、重规划、合成与终止。
6. Router 用同一 sequence 将 Application 事件映射为 v2 帧，前端严格解析后更新 Store 和文本组件。

## 5. Relevant Call Chain

```text
ChatInput submit
-> ChatView.handleSend
-> useChat.sendMessageStream
-> WebSocket /api/chat/stream
-> backend.routers.chat.chat_stream
-> build_chat_use_case
-> ControlledChatUseCase.stream / _execute
-> ControlledConversationWorkflow.run
-> ContextBuilder
-> AuthoritativeEntityResolver
-> TwoStageRouter
-> RouteAwareRewriter
-> ControlledPermissionResolver
-> ControlledPlanner
-> PlanValidator
-> ControlledExecutor
-> ToolPort (Tushare / optional web news)
-> EvidenceVerifier
-> RuleController
-> optional BoundedEvidenceReplanner -> Validator -> Executor -> Verifier -> Controller
-> ControlledSynthesizer -> ModelPort.stream_synthesize
-> on_content_delta -> Application event queue with acknowledgement
-> Router Pydantic frame + monotonic sequence
-> frontend parseWsFrame
-> useChat dispatch
-> chatStore
-> ChatWindow / D04 components
```

Confirmed segments:

- 上述调用链从页面到最终文本均有代码和现有测试证据。
- Executor 只接受 `ValidatedToolPlan`，Planner 原始计划不能直接执行。
- Workflow 在 Validator 成功后才将 `current_validated` 交给 Executor。
- Workflow 内部确实生成 `WorkflowEvent` 并实时发送给 `TraceSink`，但不是公开流事件。
- Application 的 `_ChatStreamObserver` 当前只有 `on_started()` 和 `on_content_delta()`。
- Router 当前只在 `ChatStreamCompleted` 到达后追加 Skill、Memory、Context 控制帧再发 `stream_end`。
- 前端 parser 对未知帧返回 `null`，composable 会将其视为协议错误并关闭连接。

Inferred segments:

- D04 必须建立一个面向用户的安全 Projection 边界；直接把 `WorkflowEvent.attributes` 暴露给前端会泄露内部理由/哈希或形成不稳定接口。
- 只有终态 `ConversationResult` 才持有完整 plan/verification，因此仅在 Router 的 Completed 分支投影会失去实时计划/步骤价值。
- 当前 Executor 在每一 DAG layer 完整结束后才返回 `ExecutionResult`；若要求“工具开始/结束”实时显示，需要更细粒度、协议无关的执行观测点。

Unknown segments:

- 当前生产反向代理在长工具阶段是否需要 heartbeat；无事故证据，D04 默认不引入。
- 哪些 Tushare 工具显示名和参数字段适合直接向用户展示；需要在方案阶段冻结白名单。
- 浏览器可访问性与窄屏具体基线尚无自动化工具，后续需实际启动验证。

## 6. Related Files

### 6.1 Definitely Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/application/chat/contracts.py` | Application 流事件合同 | 必须承载 D04 协议无关事件 | candidate modification | High |
| `backend/application/chat/use_case.py` | 事务、背压和事件流 | 必须协调过程事件与提交/取消 | candidate modification | High |
| `backend/routers/chat.py` | WS Presenter | 映射公开帧并保持 sequence/终态 | candidate modification | High |
| `backend/schemas/chat.py` | Pydantic 公开帧 | D04 公共 API 合同 | candidate modification | High |
| `Financial-MCP-Agent/src/conversation/contracts.py` | 权威领域合同 | 现有 plan/observation/verification 可复用 | candidate modification or read-only | High |
| `Financial-MCP-Agent/src/conversation/workflow.py` | 阶段编排和权威状态转换 | 计划、验证、replan、Verifier 的真实发生点 | candidate modification | High |
| `Financial-MCP-Agent/src/conversation/execution.py` | DAG 工具执行 | 工具/步骤开始和完成的真实发生点 | candidate modification | High |
| `Financial-MCP-Agent/src/conversation/ports.py` | Provider/Trace 端口 | 可能承载独立观测端口 | candidate modification | Medium |
| `frontend/src/api/index.ts` | TS 公共帧与 parser | 未声明/接受任何 D04 帧 | candidate modification | High |
| `frontend/src/composables/useChat.ts` | WS 生命周期和分发 | 必须按请求/序列消费 D04 帧 | candidate modification | High |
| `frontend/src/stores/chatStore.ts` | 当前请求状态真源 | 必须归一化计划/步骤/工具/验证状态 | candidate modification | High |
| `frontend/src/views/ChatView.vue` | 页面组合 | 接入执行状态 UI 与停止动作 | candidate modification | Medium |
| `frontend/src/components/chat/ChatInput.vue` | 输入/控制入口 | 目前 sending 时完全禁用，暂无 stop | candidate modification | Medium |
| `frontend/src/components/chat/ChatWindow.vue` | 文本列表 | 需要与执行状态组件形成清晰层级 | candidate modification or read-only | Medium |

### 6.2 Probably Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/application/chat/factory.py` | 生产依赖装配 | 若增加 workflow observer/port 需在此装配 | candidate modification | Medium |
| `backend/infrastructure/chat/trace.py` | 结构化 Trace Adapter | 需继续独立于公开 UI 事件，不应被绕过 | read-only or narrow modification | Medium |
| `backend/infrastructure/chat/testing.py` | Fake Provider/Trace | 新事件测试可复用 | candidate modification | Low |
| `frontend/src/components/chat/SkillConfirmationCard.vue` | 既有受控交互模式 | 可复用组件样式和事件模式 | read-only | Low |
| `frontend/src/assets/main.css` | 全局样式 | 仅在组件局部样式不足时涉及 | candidate modification | Low |
| `tests/e2e/offline_app.py` | Compose 内真实工作流装配 | 如新增 Observer 依赖需同步 | candidate modification | Medium |
| `.github/workflows/ci.yml` | 质量与 E2E 门禁 | 新测试若位于既有路径会自动覆盖 | read-only unless gap found | Medium |
| `README.md` | 运行说明与当前能力 Claim | 当前 WebSocket/D04 描述已过时 | candidate modification | Low |

### 6.3 Supporting Context

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `tests/unit/conversation/test_controlled_components.py` | Planner/Validator/Verifier 单测 | 可复用固定计划和证据夹具 | candidate modification/new adjacent tests | Low |
| `tests/unit/conversation/test_evidence_control_synthesis.py` | failure/replan/accepted-only 测试 | 可证明 D04 投影来自权威结果 | candidate modification/new adjacent tests | Medium |
| `tests/unit/conversation/test_chat_stream_use_case_contract.py` | Application streaming/rollback | 锁定背压、失败、取消和提交顺序 | candidate modification | High |
| `tests/contract/test_controlled_chat_contract.py` | WS v2 Presenter 合同 | 锁定 D04 帧顺序、并发隔离与终态 | candidate modification | High |
| `tests/contract/test_skill_confirmation_public_contract.py` | Skill 确认兼容 | D04 必须保持 | read-only/regression | Medium |
| `tests/e2e/test_websocket_streaming_chain.py` | 离线 WebSocket 全链 | 可增加 D04 全流程断言 | candidate modification | High |
| `tests/e2e/test_live_controlled_chat_chain.py` | 真实模型/Tushare Live | 可扩展为 D04 真实事件验收 | candidate modification | High |
| `tests/e2e/test_controlled_chat_chain.py` | 领域成功/失败/replan | 已有确定性场景 | read-only/reuse fixtures | Medium |
| `frontend/src/api/__tests__/chatStreamingV2Contract.spec.ts` | Parser 合同 | 新帧正反例 | candidate modification | Medium |
| `frontend/src/composables/__tests__/useChat.streaming-v2.spec.ts` | FakeSocket 消费 | 顺序、取消、终态和状态分发 | candidate modification | High |
| `frontend/src/stores/__tests__/chatStore.skill-confirm.spec.ts` | Pinia 测试模式 | 可新增独立 execution store 测试 | read-only/reuse pattern | Low |
| `frontend/src/components/chat/__tests__/SkillConfirmationCard.spec.ts` | Vue 组件测试模式 | 可复用 mount/emits 方式 | read-only/reuse pattern | Low |

### 6.4 Out of Scope

| Path / Area | Reason |
| --- | --- |
| `backend/routers/report.py`、`frontend/src/composables/useReport.ts` | D05 报告 SSE 范围 |
| `backend/infrastructure/memory/redis_cache.py` 及 Redis 配置 | D06 任务状态/幂等治理范围；D04 不新增运行态缓存 |
| `backend/db/models.py`、`backend/migrations/` | D04 不持久化控制卡片，不改 Schema |
| `backend/middleware/auth.py` | WS query token 日志问题已知，但不属于 D04；保持只读 |
| `Financial-MCP-Agent/src/skills/` | D04 不修改发现、路由、权限和 Skill spec |
| `Financial-MCP-Agent/src/prompts/` | D04 不改变回答质量或 Planner Prompt |
| `backend/application/memory/`、`frontend/src/components/memory/` | 保持既有记忆行为，不扩范围 |

## 7. Existing Patterns to Reuse

| Pattern | Example file | Why reuse it |
| --- | --- | --- |
| WebSocket v2 统一信封与 Router sequence | `backend/schemas/chat.py`、`backend/routers/chat.py` | 已验证跨控制帧统一编号、终态唯一和严格关联 |
| Application 有界 queue + acknowledgement 背压 | `backend/application/chat/use_case.py` | 防止发送失败后工作流继续并提前提交 |
| 领域强类型不可变合同 | `Financial-MCP-Agent/src/conversation/contracts.py` | plan、observation、verification 已有可信来源 |
| Validator-only execution | `planning.py`、`validation.py`、`execution.py` | 计划预览必须遵循相同安全边界 |
| 公开安全 Schema 投影 | `_skill_confirmation_schema()`、`_memory_command_schema()` | 已有“领域对象不直接透传”惯例 |
| 结构化低敏 Trace | `backend/infrastructure/chat/trace.py` | 保持内部观测与用户 UI 两个输出通道分离 |
| 前端严格 parser | `frontend/src/api/index.ts::parseWsFrame` | 新事件必须完整校验，不能接受任意对象 |
| Socket 副作用集中在 composable | `frontend/src/composables/useChat.ts` | 组件无需直接管理连接或协议 |
| Store 作为状态真源 | `frontend/src/stores/chatStore.ts` | D04 可用稳定 ID reducer 防止组件局部状态漂移 |
| Vue 可控交互组件 | `SkillConfirmationCard.vue` | 组件只收 typed props 并 emit 用户动作 |
| protected Live test | `tests/e2e/test_live_controlled_chat_chain.py` | 已具备显式开关、真实 Provider、临时 DB、脱敏 artifact |
| CI 分层门禁 | `.github/workflows/ci.yml` | 新增测试放入既有路径即可进入 pytest/Vitest/root/Compose |

## 8. Data Flow and State

### 8.1 Input Data

- 前端发送 `user_id`、`message`、可选 `session_id`、客户端 `request_id`、可选 `explicit_skill`。
- WS token 当前由 `buildWsUrl()` 放在 query string；这是既有 D03 已记录风险，本任务不改。
- FastAPI 先认证与 Pydantic 校验，再构造协议无关 `ChatCommand`。

### 8.2 Intermediate State

- `ConversationRunContext`: `trace_id/run_id/session_id/request_id/budget`。
- `ConversationState`: 按冻结表从 RECEIVED 推进到唯一业务终态。
- `ToolPlan` -> `PlanValidationResult.validated_plan` -> `ExecutionResult` -> `VerificationResult` -> `ControllerDecision`。
- Replan 时构造新 `ToolPlan`，重新校验和执行，最终 `combined_plan` 保存原始与补证步骤。
- `WorkflowEvent` 已包含 stage/status/elapsed/error/低风险 attributes，但只投给 Trace Sink 和最终 `ConversationResult.events`。
- `_ChatStreamObserver` 保存正文 chunks、TTFT、hash 和容量 1 的公开 Application 事件队列。

### 8.3 Persistent State

- Repository 原子保存用户消息、最终 assistant 消息、Working State 和上下文窗口。
- 当前不持久化计划、步骤、工具或验证 UI 状态。
- 本地 Trace JSONL 可记录阶段，但不是 D04 前端恢复账本。
- D04 默认不新增持久化；跨刷新和重连恢复属于 D06。

### 8.4 Output Data

- HTTP `ChatMessageResponse`: reply/session/memory/context/skill confirmation，不含 D04 数据。
- WS `chat-stream-v2`: 当前支持 stream start/delta/end/error、context、memory、skill 和 compression。
- 领域最终 `ConversationResult`: 包含 plan、verification、controller、events 和 tool_call_count，但此时执行已经结束。
- 前端当前只持久显示消息文本、Skill 确认、上下文和压缩状态。

### 8.5 Potential Data Mismatch Points

- `WorkflowEvent.sequence` 与公开 `WsStreamEnvelope.sequence` 是不同序列空间，不能直接复用或混淆。
- 领域 `StepStatus` 只有 SUCCEEDED/FAILED/SKIPPED；D04 所需 PLANNED/RUNNING/REPLANNED/CANCELLED 属于展示生命周期，而非当前结果枚举。
- `ExecutedPlanStep` 只有完成后生成，且 `replanned` 表示该步属于补证执行，不等于“旧步骤被替换”。
- `ToolPlanStep.arguments` 可能包含敏感或内部参数；没有现成前端安全白名单。
- `WorkflowEvent.attributes.reason` 主要为内部英文规则原因，不能未经转换直接展示。
- 前端 `finish()` 当前不保存 terminal status，只用是否 error 决定刷新；D04 若显示 PARTIAL/CANCELLED 必须新增请求级终态状态。
- HTTP fallback 当前不会得到过程事件；若 WebSocket 失败后同步回退，只能降级为最终文本，不应伪造控制卡片。

## 9. External Dependencies

| Dependency | Where called | Input | Output | Error handling / fallback |
| --- | --- | --- | --- | --- |
| OpenAI-compatible LLM | `backend/infrastructure/chat/providers.py` | 版本化系统 Prompt + accepted-only AnswerContextPack | 有序 `ModelSynthesisChunk` | 30s timeout、1 retry；异常包装为 `ModelSynthesisError` 并由 Application 回滚 |
| Tushare | `TushareToolProvider.execute()` | Validator 通过的 `ToolCall` | 归一化 `ToolObservation` | timeout/transient/permanent 分类；Executor 有界重试 |
| Tavily/Web News | `ReadOnlyToolProvider` / `web_search.py` | 仅受控 weak-evidence 工具调用 | `ToolObservation` | 默认关闭；失败进入工具错误/证据降级 |
| SQLAlchemy DB | `SqlAlchemyConversationRepository` | ChatCommand/ConversationResult | 会话、消息、状态快照 | Application 统一 commit/rollback；取消和技术失败回滚 |
| Redis memory cache | memory infrastructure | 记忆派生读取 | 可丢弃 cache | 失败降级 PostgreSQL；D04 不触碰 |
| Langfuse | trace exporter | 已脱敏 WorkflowEvent | 可选远程 Trace | exporter 失败不阻断业务 |
| Browser WebSocket | `useChat.ts` | JSON v2 请求 | 严格 v2 帧 | 协议错误关闭 1002；断连标记本地失败 |

## 10. Tests and Evaluation Assets

### 10.1 Existing Tests

- Planner/Validator/Verifier: `test_controlled_components.py`。
- 工具失败、证据拒绝、Controller 和 Replan: `test_evidence_control_synthesis.py`。
- Application streaming、背压、提交/回滚/取消: `test_chat_stream_use_case_contract.py`。
- WS v2 生命周期、异常、断连、并发隔离: `test_controlled_chat_contract.py`。
- Skill confirmation 公开兼容: `test_skill_confirmation_public_contract.py` + 前端 Vitest。
- 离线 WebSocket 全链: `test_websocket_streaming_chain.py`。
- 领域完整成功/失败/replan: `test_controlled_chat_chain.py`。
- protected Live: `test_live_controlled_chat_chain.py`，目前两例，真实模型，其中一例真实 Tushare。
- Frontend: parser、FakeWebSocket composable、Store 与 Skill 组件测试共 15 例基线。

### 10.2 Coverage Gaps

- 无 D04 控制事件的 Python/Pydantic/TypeScript 合同。
- 无“Validator 成功后才能发 plan preview”的负向测试。
- 无逐步骤/工具 started/completed 的实时顺序测试。
- 无公开参数白名单与敏感字段负向测试。
- 无 Verification/Claim level 用户投影测试。
- 无 replan 版本/旧步骤保留的公开事件测试。
- 无前端 request-scoped execution reducer、重复/迟到事件测试。
- 无 Plan/Step/Tool/Evidence 组件测试。
- 无可见 stop 按钮测试。
- Live E2E 只断言 text v2 与内部 Trace，目前不断言 D04 帧。

### 10.3 Candidate Test Locations

- New: `tests/unit/conversation/test_controlled_interaction_projection.py`
- Update: `tests/unit/conversation/test_chat_stream_use_case_contract.py`
- Update: `tests/contract/test_controlled_chat_contract.py`
- Update: `tests/e2e/test_websocket_streaming_chain.py`
- Update: `tests/e2e/test_live_controlled_chat_chain.py`
- New: `frontend/src/stores/__tests__/chatStore.execution.spec.ts`
- Update: `frontend/src/api/__tests__/chatStreamingV2Contract.spec.ts`
- Update: `frontend/src/composables/__tests__/useChat.streaming-v2.spec.ts`
- New: `frontend/src/components/chat/__tests__/ControlledExecutionPanel.spec.ts`

### 10.4 Visible Test Commands

- `.venv/Scripts/python.exe -m pytest <focused paths> -q`
- `.venv/Scripts/python.exe -m pytest -q`（配置默认排除 live）
- `.venv/Scripts/python.exe -m pytest tests/e2e/test_live_controlled_chat_chain.py -q -m live`（需显式环境开关）
- `.venv/Scripts/ruff.exe check <scoped paths>`
- `.venv/Scripts/pyright.exe <scoped paths>`
- `npm run lint`
- `npm run type-check`
- `npm run test -- --run`
- `npm run build`
- `docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e`

## 11. Logging and Observability

### 11.1 Existing Logs

- Workflow 每个完成阶段生成 `WorkflowEvent`，含 trace/run/session/sequence/stage/status/elapsed/error 和有限 attributes。
- `SkillTraceSink` 映射到本地 JSONL 和可选 exporter。
- WebSocket 终态日志记录 request/session/stage/status/chunk_count/output_chars/TTFT/elapsed/error code。
- Application 技术失败日志不记录正文，保留 error type 与安全关联字段。

### 11.2 Missing Logs

- 无公开控制帧的 frame kind/count/投影失败状态。
- 无工具级 started/completed elapsed 的公开或专用观测合同。
- 无前端可关联的执行状态错误码和 terminal status Store。
- 无“敏感字段被移除”计数；现有红action以测试与底层 Trace sanitizer 为主。

### 11.3 Observability Risks

- 直接重用 Trace attributes 作为 UI payload 会把内部可观测合同误当公共 API。
- 每个步骤/工具都写普通 INFO 日志可能造成高基数与噪声；应只记稳定 ID、状态、耗时和错误码。
- WS query token 可能进入 Uvicorn access log，是 D03 已知未解决风险；D04 不应扩大日志暴露。
- Live artifact 已脱敏，但 D04 新摘要字段需要加入负向泄露断言。

### 11.4 Output-channel Separation

| Channel | Current implementation | Stable fields / format | Redaction | Gaps |
| --- | --- | --- | --- | --- |
| User/API result | REST + v2 WS | request/session/sequence/type + typed payload | Skill/Memory 有安全投影 | 无 D04 过程 payload |
| Terminal progress | FastAPI 启动阶段 print + pytest/npm 输出 | 非统一 | 部分异常只记类型 | 启动输出仍有历史 print，不属 D04 |
| Logs | Python logger | stage/status/error/chunk/elapsed | 不逐 chunk 记正文 | 无 D04 frame summary；WS token access log 风险 |
| Traces | JSONL + optional Langfuse | WorkflowEvent versioned fields | 递归 redaction | 多数阶段只在 Trace，不可直接给用户 |
| Artifacts | protected Live acceptance JSON | provider/model/mode/count/timing/hash/status | 不保存问题/回答/密钥 | D04 需增加事件类型与状态摘要 |

## 12. Engineering Baseline Recon

| Area | Status | Evidence | Gap / implication |
| --- | --- | --- | --- |
| API/orchestration/domain/infrastructure boundaries | Established | Router -> Application -> conversation domain -> Provider/Repository | D04 应沿用分层，不在 Router/组件推断业务 |
| Agent/workflow/tool/prompt/model/memory/evaluation boundaries | Established | `_WorkflowServices`、Ports、Provider、Memory application、eval 目录 | 过程 UI 尚无明确 projection/observer owner |
| Docstrings, types, and key intent comments | Partial | 新主链公共 Python 接口多为中文 docstring + dataclass/Pydantic；前端类型集中 | `api/index.ts` 过长；部分旧注释已过时；D04 新接口需完整说明 |
| File-section navigation vs module separation | Partial | conversation 领域已拆模块；前端 api 单文件集中所有 API | D04 不宜继续把复杂 reducer 全塞入 `api/index.ts` 或 Vue 页面 |
| Typed configuration and secret handling | Partial | `Settings` 集中配置，Provider 使用 SecretStr，Live 显式 gate | `_load_project_env_files` 兼容底层散落 getenv；WS query token 风险仍在 |
| Error, retry, fallback, and state semantics | Established | TerminalStatus、ErrorCode、RunBudget、Executor 有界重试、Application rollback | D04 展示生命周期状态尚未建模；HTTP fallback 只能无过程降级 |

## 13. Risk Areas

| Area | Why risky | Likely touched? | Recommended handling |
| --- | --- | --- | --- |
| Public WebSocket contract | 前后端同时依赖，错误会导致整轮协议关闭 | Yes | 兼容可选帧、Pydantic/TS 双边合同、回归 D03 |
| Transaction/backpressure/cancellation | 过程事件可能改变提交时机或造成任务泄漏 | Yes | 复用 ack queue，测试发送失败与断连回滚 |
| Financial evidence correctness | UI 可能把工具成功误当证据充分 | Yes | 只在 Verifier 后投影 claim/sufficiency，不在前端计算 |
| Tool argument/result privacy | 原始参数、事实或错误可能敏感 | Yes | 明确白名单投影与负向泄露测试 |
| Concurrent DAG/replan | 乱序、并发和补证可能覆盖状态 | Yes | 稳定 step/tool ID + plan revision + reducer 幂等测试 |
| Live API billing/rate limits | 真实模型/Tushare 有成本和波动 | Yes, tests only | 保持显式 gate、最多两例、超时与只读 |
| Authentication/query token | token 可能被 access log 记录 | No | D04 保持只读；另立安全任务 |
| Database/migrations | 改动会扩大回滚难度 | No | D04 禁止触碰 |
| Redis/cache | 状态恢复与多实例是 D06 | No | D04 禁止建立 Redis-only 状态 |
| Markdown `v-html` | UI 新摘要若走 HTML 可能引入 XSS 面 | Potential | 新控制字段按文本渲染，不用 `v-html` |

## 14. Unknowns and Assumptions

### 14.1 Unknowns From Missing Code Access

- None. D04 相关仓库代码、测试、CI 和已提供面试文档均可读取。

### 14.2 Unknowns From Incomplete Requirement

- 用户未指定工具参数摘要的精确字段、中文显示名和最大长度。
- 用户未指定控制面板随每条 assistant 消息归档，还是只显示当前请求。
- 用户未指定 stop 按钮应位于输入框还是执行面板。

### 14.3 Unknowns From Ambiguous Architecture

- 使用新的 workflow observer port、扩展现有 Trace Sink，或为每个阶段传入异步 callback，尚未做方案权衡。
- Executor 的实时 step/tool 事件应由其直接发布，还是由上层根据 layer 调度生成，尚未选择。
- “route/trace summary”是否作为独立帧是文档 Claim，但用户 D04 明确列出的核心是 plan/step/tool/evidence；需在澄清中冻结最小范围。

### 14.4 Assumptions

- Assumption: D04 控制卡片只保存在当前页面生命周期；D06 再做恢复。
- Assumption: 工具调用使用独立 `tool_status`，步骤状态不承载原始工具细节。
- Assumption: 对计划和参数只提供业务摘要，默认显示名采用受控映射而不是内部函数名直出。
- Assumption: 可见 stop 复用关闭当前 WebSocket 的 D03 取消语义。
- Assumption: HTTP fallback 保持仅最终文本的可用性降级，不尝试补发过程卡片。
- Assumption: 不新增 heartbeat，除非后续实际代理测试发现必要。

## 15. Handoff to Next Step

Next step should use the Requirement Clarification Skill and produce `CLARIFICATION_QUESTIONS.md`.

It should clarify:

- 用户可见事件最小集合是否为 plan/step/tool/verification + request lifecycle，route/trace summary 是否一并纳入。
- 展示状态枚举与领域结果枚举的边界，特别是 PLANNED/RUNNING/REPLANNED/CANCELLED。
- 工具显示名、参数摘要白名单、错误摘要和最大长度。
- replan 的 plan revision 与旧/新步骤合并语义。
- 控制面板只保留当前轮还是当前页面内按消息关联；跨刷新明确留给 D06。
- stop 按钮位置和用户动作语义。
- HTTP fallback、无工具路径和缺少控制帧时的降级。
- Live E2E 是扩展 D03 文件还是建立 D04 独立文件，以及最多两例的预算。

It should consider these files/modules in later solution design:

- `Financial-MCP-Agent/src/conversation/{contracts,workflow,execution,ports}.py`
- `backend/application/chat/{contracts,use_case,factory}.py`
- `backend/schemas/chat.py`
- `backend/routers/chat.py`
- `frontend/src/api/index.ts`
- `frontend/src/composables/useChat.ts`
- `frontend/src/stores/chatStore.ts`
- `frontend/src/components/chat/` 和 `frontend/src/views/ChatView.vue`
- 相邻 pytest/Vitest/E2E/Live 文件。

It should require explicit user approval before modifying these high-risk areas:

- 认证/授权与 WebSocket token 传输。
- 数据库模型、迁移或持久化语义。
- Redis、多实例广播、断线恢复和历史重放。
- Prompt、Skill spec、工具权限、金融决策或 Evidence 规则。
- 新生产依赖或部署拓扑。

上述高风险区域均不属于 D04 当前授权范围，应保持只读；如实现证据迫使扩边，必须停止并重新冻结需求。
