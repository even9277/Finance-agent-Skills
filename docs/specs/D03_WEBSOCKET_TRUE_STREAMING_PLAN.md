# PLAN.md

## 1. Plan Metadata

- Plan name：D03 WebSocket 真实流式输出
- Task type：前后端协议与 Agent Runtime 改造
- Status：Frozen for implementation
- Target executor：Codex
- Related artifacts：同目录下 D03 Requirement、Recon、Clarification、Solution Tradeoff
- Repository root：`D:\FinanceProject\Finance-agent-Skills`
- Baseline branch：`main`
- Target branch：`feat/d03-websocket-true-streaming`
- Created date：2026-08-30

## 2. User-facing Purpose

改造后，用户在真实模型仍在生成时持续看到同一条助手消息增长。WebSocket 使用 v2 结构化事件；最终拼接内容与持久化消息一致且不重复。断连、模型失败、传输失败和提交失败不会留下完整助手消息。Skills、memory、工具治理、报告模式和 HTTP 对话语义不得回归。

## 3. Inputs Reviewed

- `D03_WEBSOCKET_TRUE_STREAMING_REQUIREMENT_SPEC.md`
- `D03_WEBSOCKET_TRUE_STREAMING_CODEBASE_RECON.md`
- `D03_WEBSOCKET_TRUE_STREAMING_CLARIFICATION_QUESTIONS.md`
- `D03_WEBSOCKET_TRUE_STREAMING_SOLUTION_TRADEOFF.md`
- 核心代码：`backend/routers/chat.py`、`backend/application/chat/use_case.py`、`backend/infrastructure/chat/providers.py`、`Financial-MCP-Agent/src/conversation/{ports,synthesis,workflow}.py`、前端 API/composable/store/window。
- 测试：controlled chat/skill contract、fake providers、live controlled chain、前端 skill contract tests。
- 外部参考：FastAPI WebSocket/TestClient、OpenAI Streaming、LangChain `ChatOpenAI.astream`。

## 4. Final Unified Direction

本轮建立供应商无关模型增量和应用层流式事件契约。Provider 产生 chunk；Workflow 累积完整答案；UseCase 管理事务；Router 映射 v2 并传播断连取消；HTTP 与 WebSocket 共享执行核心；前端只消费结构化事件。不事后切片、不建立第二条工作流、不改 Prompt/Skills/memory/tool/database、不增加消息队列或 D04 UI。

## 5. Planning Assumptions

- OpenAI-compatible 服务是否真实分块必须由 live E2E 证明。
- 前后端原子升级，不保留长期裸文本兼容。
- 默认测试离线；live 由 `RUN_PROTECTED_LIVE_E2E=true` 和凭证保护。
- 当前未跟踪 D01/D03 文档均属用户工作，禁止覆盖或删除。

## 6. Changed Surface

| Surface | Involved? | Why | Risk | Verification |
| --- | --- | --- | --- | --- |
| Frontend | 是 | v2 delta 消费 | 中 | Vitest、浏览器 |
| Backend API | 是 | WS v2 | 高 | contract |
| Database | 行为边界 | commit/rollback | 高 | integration |
| Cache | 否 | 超范围 | 低 | regression |
| Agent runtime | 是 | 模型增量 | 高 | unit/integration/live |
| Tool calling | 规则不改 | 防回归 | 中 | contract/live |
| RAG / Memory | 规则不改 | 共享链 | 中 | regression |
| MCP | 规则不改 | live 工具链 | 中 | Tushare live |
| Skills | 规则不改 | 控制事件升级 | 中 | skill contract |
| Tests | 是 | 新协议/失败语义 | 高 | CI |
| Observability | 是 | TTFT/chunk/终态 | 中 | trace assertions |
| Security/Auth | 不改 | 延后 | 中 | existing auth |
| Build/Deployment | 配置不改 | 原子版本 | 低 | build/compose |

## 7. Repository Context

### 7.1 Relevant Entry Points

- `backend/routers/chat.py::chat_stream`
- `backend/application/chat/use_case.py`
- `backend/infrastructure/chat/providers.py`
- `Financial-MCP-Agent/src/conversation/ports.py`
- `Financial-MCP-Agent/src/conversation/synthesis.py`
- `Financial-MCP-Agent/src/conversation/workflow.py`
- `frontend/src/api/index.ts`
- `frontend/src/composables/useChat.ts`
- `frontend/src/stores/chatStore.ts`
- `frontend/src/components/chat/ChatWindow.vue`

### 7.2 Relevant Call Chain

`ChatView -> useChat.sendMessageStream -> /api/chat/stream -> ControlledChatUseCase -> ControlledConversationWorkflow -> ControlledSynthesizer -> OpenAICompatibleModelProvider -> ChatOpenAI`

### 7.3 Existing Patterns to Reuse

Port/Adapter、UseCase/UoW、`TerminalStatus`、workflow trace sequence、frontend streaming placeholder、protected live E2E。

### 7.4 Current Test Structure

pytest、Vitest、ruff、pyright、eslint、vue-tsc/build；live workflow 手动触发且默认排除。

### 7.5 Current Observability Structure

已有 `trace_id/run_id/session_id/stage/status/sequence/elapsed_ms`；新增流式指标但不记录正文。

## 8. Scope Control

### 8.1 In Scope

模型异步增量、内部事件类型、WS v2、sequence/hash/chunk_count、断连取消/事务回滚、前端增量消费、离线/live/browser 验收和 D03 文档。

### 8.2 Out of Scope

停止按钮、heartbeat、续传/回放、多实例广播、数据库迁移、Prompt/Skills/memory/tool 规则、报告模式统一、WebSocket auth 改造。

### 8.3 Allowed Files / Modules

- `backend/routers/chat.py`、`backend/schemas/chat.py`
- `backend/application/chat/**`、`backend/infrastructure/chat/**`
- `Financial-MCP-Agent/src/conversation/**`
- `frontend/src/api/index.ts`、`frontend/src/composables/useChat.ts`、`frontend/src/stores/chatStore.ts`、`frontend/src/components/chat/ChatWindow.vue` 和相邻测试
- `tests/unit/**`、`tests/contract/**`、`tests/integration/**`、D03 live E2E
- 必要时 `.github/workflows/live-e2e.yml`
- `docs/specs/D03_*`

### 8.4 Forbidden Changes

- 不做无关重构或全局格式化；不修改生成物。
- 不新增依赖、数据库 schema、Prompt、Skill/Memory/Tool 规则、auth、密钥、`.env` 或部署配置。
- 不删除数据、弱化测试/安全检查/trace。
- 不长期保留裸文本/v2 双协议，不绕过受控工作流。
- 不触碰范围外文件；如确有必要必须停止并重新评审。

## 9. Interfaces and Dependencies

| Interface | Current Role | Planned Change | Compatibility | Validation |
| --- | --- | --- | --- | --- |
| `ModelPort` | 完整字符串 | 异步内部增量 | Provider 无关 | fake/provider tests |
| Synthesizer | 等待全文 | 消费并累计增量 | 最终结果不变 | unit |
| Chat UseCase | 完整执行提交 | 统一流式执行核心 | HTTP 共用 | HTTP regression |
| `/api/chat/stream` | 控制帧+裸文本 | v2 JSON | 原子升级 | WS contract |
| Frontend parser | JSON/裸文本 | typed v2 union | 不重复全文 | Vitest |
| Repository/UoW | 成功提交 | 保持边界 | 技术失败回滚 | integration |
| LangChain `astream` | 未使用 | chunk 来源 | live 证明 | protected live |

## 10. Engineering Implementation Contract

| Category | Required behavior | Verification | Status |
| --- | --- | --- | --- |
| Architecture | Provider/Workflow/UseCase/Router/Frontend 分层，HTTP/WS 单核心 | code review/tests | Required |
| Docs/types | Python/TS 公共事件显式类型；Python Google-style docstrings | pyright/vue-tsc | Required |
| Config/secrets | 不新增或泄漏凭证，不改 Prompt | diff/CI | Required |
| Logs/traces | TTFT、chunk_count、chars、elapsed、终止原因、error_code，无正文 | assertions/manual | Required |
| Errors/state | end/error 互斥；技术失败/取消回滚；业务 PARTIAL 提交 | integration | Required |
| Tests/evidence | offline default、live gated、browser acceptance | full gates | Required |

## 11. Test and Validation Strategy

### 11.1 Existing Tests to Run

- `uv run --locked pytest tests/contract/test_controlled_chat_contract.py -q`
- `uv run --locked pytest tests/contract/test_skill_confirmation_public_contract.py -q`
- `uv run --locked pytest backend -q`
- `uv run --locked pytest Financial-MCP-Agent -q -m "not live"`
- `uv run --locked pytest -q`
- CI 中的 ruff/pyright 命令
- `npm run lint && npm run type-check && npm run build && npm run test -- --run`

### 11.2 New or Updated Tests Required

Fake Provider 多 chunk/单 chunk 降级、Synthesizer 拼接、WS v2 生命周期/sequence/hash/count、skill_confirm 共存、模型/发送/commit 失败、断连取消回滚、业务 PARTIAL、frontend parser/store/error、protected live WebSocket。

### 11.3 Manual Smoke Tests

启动前后端，发送长回答问题，观察同一消息多次增长且无重复；刷新确认历史一致；生成中关闭连接确认未留下完整助手消息；Skill 澄清卡正常。

### 11.4 Agent/RAG/Tool Evaluation

live 用例必须通过完整受控链并至少触发只读 Tushare 工具，不能只测纯模型问答。

### 11.5 Expected Terminal / Logs / Trace / Artifacts

`request_id/session_id/trace_id/run_id/ttft_ms/chunk_count/output_chars/elapsed_ms/terminal_status/disconnect_reason/error_code`；禁止正文、Prompt、Token 和敏感工具参数。

### 11.6 Acceptance Criteria

| Behavior / Risk | Test / Method | Expected Result |
| --- | --- | --- |
| 真实流式 | protected live WS | >=2 非空 delta，首 delta 早于 end |
| 内容一致 | contract/integration/live | 拼接=持久化消息 |
| 顺序 | WS contract | sequence 严格递增 |
| 不重复 | protocol/frontend | end 无正文 |
| 技术失败 | failure tests | error 且回滚 |
| 业务 PARTIAL | workflow | end 且持久化 |
| 断连 | disconnect | 取消并回滚 |
| HTTP/Skills | existing contracts | 语义不回归 |
| 工程质量 | lint/type/build/tests | 全通过 |

## 12. Milestones

### Milestone 0: Safety and Baseline Check

**Goal:** 创建 D03 分支，确认状态、测试基线和范围。

**Files / Modules:** 只读检查和 D03 治理报告；不修改源代码。

**Implementation Intent:** 从 `main` 创建 `feat/d03-websocket-true-streaming`，保留未跟踪文档。

**Tests / Checks:** git status/branch、两个后端契约测试、现有前端 skill 测试。

**Expected Result:** 基线可复现，无覆盖风险。

**Stop Condition:** 目标源文件有未知用户改动或核心基线失败。

**Rollback Note:** 可删除未提交功能分支；不得删除用户文档。

**Handoff Evidence:** 分支、status、命令、结果。

### Milestone 1: Lock Tests and Protocol Contract

**Goal:** 先冻结 v2、增量端口和失败语义。

**Files / Modules:** 测试、协议类型、Fake Provider。

**Implementation Intent:** 新测试在旧实现上因缺少真流式而失败，不放宽断言。

**Tests / Checks:** 聚焦 pytest/Vitest。

**Expected Result:** 测试准确覆盖生命周期、拼接、回滚和前端。

**Stop Condition:** 需要迁移或新依赖。

**Rollback Note:** 独立回滚测试契约。

**Handoff Evidence:** 失败基线和原因。

### Milestone 2: Implement Core Streaming Runtime

**Goal:** 打通 Provider -> Workflow -> UseCase 增量链。

**Files / Modules:** conversation ports/synthesis/workflow、chat provider/use_case。

**Implementation Intent:** typed chunk/event、累计全文、HTTP 共用核心。

**Tests / Checks:** provider/synth/workflow/HTTP regression。

**Expected Result:** fake 多 chunk 逐个发出，最终语义一致。

**Stop Condition:** 需新依赖、Prompt 修改或复制工作流。

**Rollback Note:** 独立回滚 runtime 文件。

**Handoff Evidence:** diff、types、focused tests。

### Milestone 3: WebSocket v2, Cancellation and Observability

**Goal:** 完成 Router v2、取消、回滚和指标。

**Files / Modules:** router/schema/application observability/WS tests。

**Implementation Intent:** Router 不做业务推理；终态互斥；发送/断连传播取消。

**Tests / Checks:** WS lifecycle/disconnect/failure/commit rollback。

**Expected Result:** 技术中断不持久化，协议正确。

**Stop Condition:** 需 auth/schema 改造。

**Rollback Note:** 前端切换前可独立回滚。

**Handoff Evidence:** frame examples/tests/trace fields。

### Milestone 4: Frontend v2 Consumption

**Goal:** typed 解析并渐进更新消息。

**Files / Modules:** API/composable/store/ChatWindow/tests。

**Implementation Intent:** sequence 校验、end/error 区分、去除裸文本依赖。

**Tests / Checks:** Vitest/eslint/vue-tsc/build。

**Expected Result:** 多 delta 更新同一消息，无重复，错误可见。

**Stop Condition:** 需要 D04 UI。

**Rollback Note:** 与后端 v2 原子回滚。

**Handoff Evidence:** tests/build。

### Milestone 5: Full Verification, Live Acceptance and Handoff

**Goal:** 全回归、live、浏览器、review 和文档闭环。

**Files / Modules:** live E2E、D03 文档和窄修复。

**Implementation Intent:** 不扩功能，只修验收暴露的 D03 问题。

**Tests / Checks:** full pytest/ruff/pyright/frontend/live/browser。

**Expected Result:** 所有验收标准有证据。

**Stop Condition:** 外部凭证不可用时记录精确阻塞，继续完成离线验收。

**Rollback Note:** 分支级回滚，无迁移。

**Handoff Evidence:** 验收报告、风险、建议 commit。

## 13. Execution Protocol

- 一次只执行一个里程碑；开始前运行 `git status --short` 并复述范围。
- 不覆盖用户改动、不越界、不弱化断言。
- 测试失败先查最窄日志；同一问题两次修复仍失败则停止报告。
- 每个里程碑更新 Progress、Decision Log、Discoveries、Outcomes，并产生报告。
- 用户已授权持续推进；一个里程碑报告完成后，下一次续跑进入下一个里程碑。

## 14. Rollback Plan

所有实现位于 `feat/d03-websocket-true-streaming`。禁止 `git reset --hard`/覆盖式 checkout；每里程碑窄 diff；无 DB/依赖/配置迁移；前后端 v2 一起交付回滚；保留现有用户文档；范围外改动必须停止。

## 15. Progress

- [x] Milestone 0: Safety and Baseline Check
  - Completed: 2026-08-30
  - Evidence: branch `feat/d03-websocket-true-streaming`; backend contracts 9 passed; frontend contracts 6 passed.
- [x] Milestone 1: Lock Tests and Protocol Contract
  - Completed: 2026-08-30
  - Evidence: ruff and contract type checks pass; expected red baseline is 10 backend failures and 2 frontend failures, each mapped to an unimplemented D03 capability.
- [x] Milestone 2: Implement Core Streaming Runtime
  - Completed: 2026-09-01
  - Evidence: focused ruff passed; targeted pyright 0 errors; core streaming/runtime regression 46 passed; backend 11 passed; Agent subtree 33 passed; REST/Skill non-WS contracts 5 passed.
- [x] Milestone 3: WebSocket v2, Cancellation and Observability
  - Completed: 2026-09-01
  - Evidence: focused ruff passed; targeted pyright 0 errors; WS/Application failure suite 18 passed; combined D03 core/WS regression 33 passed; backend 11 passed; Agent subtree 33 passed.
- [x] Milestone 4: Frontend v2 Consumption
  - Completed: 2026-09-01
  - Evidence: frontend lint passed; vue-tsc passed; targeted v2/Skill tests 7 passed; full frontend suite 14 passed; production build succeeded.
- [x] Milestone 5: Full Verification, Live Acceptance and Handoff
  - Completed: 2026-09-02
  - Evidence: full pytest 364 passed; frontend 15 passed plus lint/type/build; protected Live WebSocket 2 passed with real model and real Tushare; browser same-message growth/reload/rollback verified; final review approved.

## 16. Decision Log

| Date | Decision | Reason | Source |
| --- | --- | --- | --- |
| 2026-08-30 | Option B | 真流式且保留边界 | Tradeoff |
| 2026-08-30 | 原子升级 v2 | 避免双协议 | Clarification |
| 2026-08-30 | 技术失败回滚，PARTIAL 提交 | 区分终态 | Clarification |
| 2026-08-30 | offline 默认，live 显式 | 凭证/成本安全 | CI |
| 2026-08-30 | 不新增 Playwright | Vitest+人工足够 | Clarification |
| 2026-08-30 | 在独立 `feat/d03-websocket-true-streaming` 分支实施 | 遵守仓库一个交付一个短分支规则 | AGENTS.md / Milestone 0 |
| 2026-08-30 | Application 使用 `Started/ContentDelta/Completed/Failed` 强类型事件 | 让 Router 只做 v2 映射，并让技术失败在回滚后可安全表达 | Milestone 1 tests |
| 2026-08-30 | 公共协议版本固定为 `chat-stream-v2`，sequence 由 Router 对所有公开帧统一编号 | 业务控制帧与内容帧必须共享一条严格顺序 | Clarification / Milestone 1 |
| 2026-08-30 | 非模型或无上游 chunk 的回复降级为一个 content delta | 保持统一协议且不做事后切片 | Clarification / Milestone 1 |
| 2026-09-01 | `ModelPort` 只暴露供应商无关 `stream_synthesize`，完整回答由同一增量流聚合 | 防止保留完整调用与增量调用两条运行时 | Milestone 2 |
| 2026-09-01 | Application 使用容量 1 的确认式事件队列，并在消费端确认上一事件后才继续上游 | 仅有有界队列仍可能在 WebSocket 发送失败前提前提交；显式确认可把传输背压传播到事务和模型 | Milestone 2 |
| 2026-09-01 | 持久化前强校验全部 delta 拼接值与领域 `result.reply` 完全一致 | 防止流式可见正文与会话历史分叉或重复 | Milestone 2 |
| 2026-09-01 | `ModelSynthesisError` 越过领域安全失败终态，由 Application 统一回滚并映射安全流失败 | Provider 技术失败不能伪装成可提交业务回答 | Milestone 2 |
| 2026-09-01 | WebSocket Router 只消费 `ControlledChatUseCase.stream()`，并在数据库会话作用域内完成整个发送生命周期 | 保持 HTTP/WS 单执行核心，同时避免流期间 Repository 会话提前释放 | Milestone 3 |
| 2026-09-01 | 所有公开帧由 Pydantic `chat-stream-v2` Schema 构造，sequence 由单连接 Router 状态统一递增 | 禁止裸文本、任意字典和控制帧独立计数导致的协议漂移 | Milestone 3 |
| 2026-09-01 | Router 使用 `aclosing` 包裹 Application generator，发送/断连异常原样退出并立即关闭上游 | 让传输失败确定性触发模型取消和未提交事务回滚，而不是依赖异步生成器 GC | Milestone 3 |
| 2026-09-01 | Completed/Failed 映射并发送唯一终态后立即 return | 禁止终态之后出现晚到 chunk 或重复终态 | Milestone 3 |
| 2026-09-01 | WS 日志只记录 request/session、stage/status、chunk_count、output_chars、TTFT、elapsed、disconnect/error code | 满足可诊断性且不输出回答正文、Prompt 或敏感载荷 | Milestone 3 |
| 2026-09-01 | 前端 `parseWsFrame` 只返回通过完整 envelope 和事件载荷校验的 `WsStreamV2Frame` | 防止 legacy/private/畸形 JSON 被当作正文或控制事件执行 | Milestone 4 |
| 2026-09-01 | 每轮浏览器生成并发送 request_id，消费端同时校验 request/session/sequence/chunk_index | 防止跨请求串流、乱序、重复或晚到帧污染当前助手消息 | Milestone 4 |
| 2026-09-01 | 同一占位助手消息只接受 `content_delta`；`stream_end` 正常完成，`stream_error`/协议/连接失败在原消息标记错误 | 保留部分可见内容并明确失败，同时避免创建多个 chunk 消息 | Milestone 4 |
| 2026-09-01 | 既有 Skill/Memory/Context/Compression 消费只在 v2 envelope 内保留 | 原子移除旧协议而不回归现有控制能力 | Milestone 4 |
| 2026-09-02 | Router 同时运行 presenter 和 receive-side disconnect watcher | 仅依赖下一次发送无法及时发现浏览器离开，可能继续模型生成 | Milestone 5 browser review |
| 2026-09-02 | 前端在页面退出和 Vue scope dispose 时关闭活动 WebSocket | Promise 局部连接此前没有组件生命周期所有权 | Milestone 5 browser review |
| 2026-09-02 | Live Trace 接受正常链或一次受控 replan 后终止 | 真实金融数据可能触发冻结的有界补证路径，不能把合法 replan 误判为协议失败 | Milestone 5 live |
| 2026-09-02 | 保持先数据库提交、后发送 `stream_end` | commit failure 不得向客户端宣告成功；跨 DB/网络原子 ACK/outbox 属于 D03 排除范围 | Final review |

## 17. Surprises & Discoveries

| Finding | Impact | Action |
| --- | --- | --- |
| `astream` 可退化为单次调用 | 代码不能证明真流式 | live 检查多个 delta |
| 当前长任务期间不 receive | 断连发现不及时 | M3 加断连观察 |
| Store 已有 placeholder/append | UI 改动可收敛 | 复用现有模式 |
| FastAPI TestClient 基线出现 Starlette/httpx 弃用警告 | 不影响当前契约，但未来依赖升级需处理 | D03 不新增依赖或扩大范围，记录为既有风险 |
| 当前前端 `parseWsFrame` 接受任意带 type 的 JSON | Provider 私有事件或遗留 done 帧可能绕过协议版本约束 | Milestone 4 改为严格 v2 白名单解析 |
| 当前 WS Router 总是调用 `execute()` 并在一次错误帧后关闭 | 无法消费 Application 增量，且没有 v2 生命周期 | Milestone 3 切换 `stream()` 并统一事件信封 |
| 单纯 `Queue(maxsize=1)` 不能证明上一帧已成功发送，执行任务仍可能越过发送失败并提交 | Router 传输失败与数据库提交存在竞态 | Application 事件增加显式 acknowledgement；M3 必须用 `aclosing`/显式关闭把发送异常传播为取消 |
| 非模型分支和记忆命令不会产生 Provider chunk | 若不处理会出现 started 后直接 completed，且断连无法约束提交 | Application 在提交前把权威回复降级为单个 delta，并执行相同内容一致性校验 |
| v2 输入校验可能发生在 Application 生成 request/session 之前 | 若沿用旧 error 帧会破坏原子协议升级 | Router 为边界失败生成低敏关联 ID 和 `unavailable` session，并发送 sequence=1 的 v2 `stream_error` |
| Application 事件原先把技术失败码声明为裸 `str` | 公开 Schema 即使有限枚举，跨层仍可能传入任意字符串 | 新增单值 `ChatStreamFailureCode`，Router 只映射其稳定值 |
| 旧 parser 对任意带 `type` JSON 返回成功，composable 对 `null` 直接当裸 token 追加 | legacy done、Provider 私有帧或畸形输入可绕过协议并污染回答 | 删除 `WsControlFrame` 和裸 token fallback，未知/畸形帧触发可见协议失败 |
| 旧 WS 请求没有 request_id | 客户端无法证明响应属于当前轮，也无法做严格 sequence 隔离 | 使用前端生成的非敏感稳定 request_id，并要求所有响应关联字段一致 |
| `vue-tsc -b` 会把 tracked `tsconfig.node.tsbuildinfo` 改成本地 TypeScript 版本 | 生成缓存会制造与功能无关的 diff | 每次 type/build 后只恢复该生成文件；不改依赖或 lockfile |
| 宿主机 `ALL_PROXY=socks5h` 但未安装 SOCKS transport | Live 请求在进入业务链前失败 | 仅对验收进程移除 ALL_PROXY，保留 HTTPS proxy；不修改仓库配置 |
| 浏览器离开后 Router 只依赖 send-side 异常时无法及时发现断连 | 模型任务和事务可能继续占用资源 | 新增并发 receive-side disconnect watcher，并用 1 秒内关闭 generator 的合同测试锁定 |
| Vite 代理环境未稳定显示最终 disconnect access log | 人工日志不能单独证明部署代理 close-frame 行为 | 以取消合同和数据库零脏提交验收；生产代理补做可观测性 smoke |
| Uvicorn access log 会包含现有 WS query token；通知接口持续 404 | 存在敏感日志和运行噪声，但均不属于 D03 流式职责 | 记录后续 auth/logging 与通知接口任务，不在本轮越界修改 |
| 全仓 Ruff/Pyright 分别有 97/70 个既有错误 | 不能宣称仓库级静态门禁全绿 | D03 changed-file Ruff/Pyright 零问题；历史债务独立治理 |

## 18. Outcomes & Retrospective

- What changed：Provider、Workflow、Application、WebSocket v2 和前端严格消费者形成单一真流式链；M5 进一步补齐 receive-side 断连观察和前端生命周期关闭。
- What was verified：后端全量 364 passed；前端 15 passed 且 lint/type/build 通过；两条 protected Live（真实模型，其中一条真实 Tushare）通过；浏览器证明同一消息多次增长、刷新一致和未完成轮次无脏提交。
- What remains risky：现有 WS query token 可能进入 access log、通知 404、部署代理 close-frame 观测、全仓历史 Ruff/Pyright 债务和既有 bundle warning。
- What should be improved next：独立治理 WebSocket 认证/日志脱敏和通知接口；在真实部署代理补一次 disconnect trace smoke；D04 再实现可见停止按钮和控制面。

## 19. Deferred Work

D04 stop、heartbeat、续传/回放、队列、chunk 账本、auth query 改造、Markdown 增量优化、多实例和报告事件统一。

## 20. Handoff to Small-step Implementation

Milestone 0—5 已全部完成。D03 实现和验收证据见 `D03_WEBSOCKET_TRUE_STREAMING_ACCEPTANCE_REPORT.md` 与 Milestone 5 报告；当前只剩 Git 提交、推送和 PR 远端交付。
