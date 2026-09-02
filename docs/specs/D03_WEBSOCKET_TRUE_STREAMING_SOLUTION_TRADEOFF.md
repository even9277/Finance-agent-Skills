# SOLUTION_TRADEOFF.md

## 1. Tradeoff Context

D03 要把当前“模型完整生成后通过 WebSocket 一次性发送全文”的伪流式链路，改为模型仍在生成时持续向浏览器发送增量内容。改造必须保留现有受控对话工作流、Skills、记忆、工具治理、证据校验和事务语义。

## 2. Inputs Reviewed

- REQUIREMENT_SPEC.md：`D03_WEBSOCKET_TRUE_STREAMING_REQUIREMENT_SPEC.md`
- CODEBASE_RECON.md：`D03_WEBSOCKET_TRUE_STREAMING_CODEBASE_RECON.md`
- CLARIFICATION_QUESTIONS.md：`D03_WEBSOCKET_TRUE_STREAMING_CLARIFICATION_QUESTIONS.md`
- User decisions：用户接受澄清文档中的推荐默认值，并要求继续完成实施与验收。
- External sources：FastAPI WebSocket 与测试文档、OpenAI Streaming 文档、LangChain `ChatOpenAI` reference/source。

## 3. User Decisions and Defaults

### 3.1 Confirmed Decisions

- 前后端原子升级到结构化 WebSocket v2，不长期保留裸文本双协议。
- 最小生命周期事件为 `stream_start`、`content_delta`、`stream_end`、`stream_error`；现有业务控制事件进入同一信封。
- 每个事件含 `protocol_version`、`request_id`、`session_id`、`sequence`。
- `stream_end` 含终态、`chunk_count`、内容哈希，不重复发送完整回答。
- 业务 `TerminalStatus.PARTIAL` 是可持久化的正常完成；供应商、传输、取消等技术性部分输出不持久化为完整助手消息。
- 客户端断连取消未完成生成并回滚本轮；D03 不增加停止按钮、heartbeat、断线续传和回放。
- 不支持流式的 Provider 显式降级为单个 delta，禁止事后切片伪装流式。
- 默认自动化测试不调用付费服务；真实 LLM/Tushare WebSocket E2E 由显式开关保护。

### 3.2 Conservative Defaults Used

- 不新增数据库表、生产依赖、消息队列、部署组件或 Prompt 配置。
- 不增加 Playwright；前端自动测试继续使用 Vitest，真实页面采用人工浏览器验收。
- 首个 delta 之后不做应用层自动重放，避免重复内容与副作用。

### 3.3 Blocking Decisions

无未解决 P0 决策。

## 4. Core Decision Point

决定真实流式应通过跨层回调式最小补丁、协议无关的应用层流式契约，还是可回放的长期事件基础设施实现。

## 5. Reference Sources and Repository Evidence

### 5.1 Official Docs

#### Source: FastAPI WebSockets

**Link:** https://fastapi.tiangolo.com/advanced/websockets/

**What was inspected:** JSON/Text 发送、`WebSocketDisconnect` 与连接关闭处理。

**Relevant practice:** 断连通过后续 receive/send 被观测；当前路由在长任务期间不再 receive，因此需要适配层断连观测。

**Reusable part:** Partially reusable

**Fit for this task:** Router 负责传输与取消传播，FastAPI 类型不进入工作流和 Provider。

#### Source: FastAPI Testing WebSockets

**Link:** https://fastapi.tiangolo.com/advanced/testing-websockets/

**What was inspected:** `TestClient.websocket_connect()` 的协议测试方式。

**Relevant practice:** 可在默认 CI 中离线验证消息生命周期、顺序与关闭行为。

**Reusable part:** Directly reusable

**Fit for this task:** 用于 WebSocket v2 契约测试。

#### Source: OpenAI Streaming Responses

**Link:** https://developers.openai.com/api/docs/guides/streaming-responses

**What was inspected:** delta、completed、error 生命周期。

**Relevant practice:** 增量事件必须在完整响应结束前被消费，正常终态与错误终态应明确区分。

**Reusable part:** Partially reusable

**Fit for this task:** 借鉴生命周期，不向客户端泄漏供应商专有事件。

#### Source: LangChain streaming contract

**Link:** https://reference.langchain.com/python/langchain-core/language_models/chat_models/BaseChatModel/disable_streaming

**What was inspected:** `astream` 在禁用或不支持流式时可能退化为 `ainvoke`。

**Relevant practice:** 代码调用 `astream` 不能单独证明真实上游流式，必须用 live E2E 检查多个非空 chunk。

**Reusable part:** Directly reusable with verification

**Fit for this task:** Provider 使用现有 LangChain 能力，live gate 证明供应商行为。

### 5.2 Open-source Repositories

#### Source: LangChain ChatOpenAI implementation

**Link:** https://github.com/langchain-ai/langchain/blob/master/libs/partners/openai/langchain_openai/chat_models/base.py

**What was inspected:** 异步流式实现、chunk 类型和 OpenAI-compatible 边界。

**Relevant practice:** 在 Provider 边界消费 SDK chunk，并转换为项目内部模型增量。

**Reusable part:** Partially reusable

**Fit for this task:** 无需新增 SDK，但兼容服务必须真实验证。

### 5.3 Local Project Patterns

| Local pattern | Evidence | How to reuse |
| --- | --- | --- |
| Port/Adapter | `ModelPort` 与 `OpenAICompatibleModelProvider` 已分离 | 端口定义供应商无关增量 |
| 单一受控工作流 | HTTP/WS 均进入 `ControlledChatUseCase` | 禁止新建简化流式链 |
| Unit of Work | 助手结果完成后 commit | 正常完成提交，技术失败/取消回滚 |
| Typed terminal result | `ConversationResult`、`TerminalStatus` | 保留业务 PARTIAL 语义 |
| Trace events | 已有 run/session/stage/status/elapsed | 补充 TTFT、chunk_count、终止原因 |
| Frontend placeholder | Store 已能创建和追加 streaming message | 改为消费 typed delta |
| Protected live E2E | 已有真实 LLM、Tushare、临时 SQLite | 扩展到真实 WebSocket |

## 6. Reusable Patterns

### 6.1 Directly Reusable Patterns

FastAPI `send_json`/WebSocket TestClient、现有 Unit of Work、前端 streaming placeholder、protected live 开关和 trace 标识。

### 6.2 Partially Reusable Patterns

`ChatOpenAI.astream()`、OpenAI delta/end/error 生命周期、现有 skill/memory 控制帧。

### 6.3 Conceptual References Only

报告模式的 `astream_events` 只作为事件化参考；其状态和工具链与受控对话不同，不能直接替代当前 runtime。

### 6.4 Not Suitable for This Iteration

完整答案后切片、Router 直连模型、Redis/Kafka/broadcaster、chunk 持久化、断线续传、长期双协议和新增 Playwright。

## 7. Solution Options

### 7.1 Option A: Minimal Fix

**What changes:** 向 Provider/Workflow 传入回调，获得 chunk 时直接回调 Router。

**What does not change:** UseCase 和最终结果大体保持。

**Benefits:** 改动小、回滚容易。

**Costs:** 回调跨越多层，HTTP/WS 容易分叉。

**Risks:** WebSocket 异常污染业务层，背压、取消和扩展语义不清。

**Testing burden:** 中。

**Rollback difficulty:** 低。

**Engineering impact:** 架构边界一般；类型和观测分散；失败语义容易混合。

**When to choose it:** 一次性演示，不适合当前企业级工程口径。

### 7.2 Option B: Structured Improvement

**What changes:** 增加内部模型增量和应用流式事件契约；Provider 转换 chunk，Workflow/Application 累积完整结果，WS 映射 v2，HTTP 消费同一执行核心。

**What does not change:** 路由、规划、工具、证据、记忆、Prompt 和数据库业务规则。

**Benefits:** 真流式、单一业务链、供应商与传输解耦、终态和回滚可测试。

**Costs:** 涉及后端多个明确边界和前端协议，需要分层测试。

**Risks:** commit 可能在 delta 已显示后失败；兼容供应商可能单 chunk；断连取消需严谨实现。

**Testing burden:** 中高。

**Rollback difficulty:** 低至中；无迁移，前后端原子回滚。

**Engineering impact:** 符合现有 Port/UseCase/UoW；新增显式类型、指标和失败语义。

**When to choose it:** 当前项目阶段和面试工程叙事的最合适方案。

### 7.3 Option C: Long-term Architecture Direction

**What changes:** 建立持久化事件流/队列，拆分生成、分发、恢复和回放。

**What does not change:** 领域规则可复用，但执行架构重写。

**Benefits:** 多实例、续传、回放和独立扩展。

**Costs:** 队列、事件存储、幂等、清理、迁移和运维成本高。

**Risks:** 把 D03 扩张为分布式一致性问题。

**Testing burden:** 高。

**Rollback difficulty:** 高。

**Engineering impact:** 全链路重大改造。

**When to choose it:** 明确出现多实例续传需求后。

**Decision:** Deferred。

### 7.4 Option D: Observation-first Option

**What changes:** 只增加 Provider 能力探针、TTFT 和 chunk 观测。

**What does not change:** 用户仍一次性获得全文。

**Benefits:** 低风险验证兼容供应商。

**Costs:** 不完成 D03。

**Risks:** 停在诊断阶段。

**Testing burden:** 低。

**Rollback difficulty:** 低。

**When to choose it:** 作为 Option B 的首个验证门，不作为最终方案。

## 8. Decision Matrix

| Dimension | A Minimal | B Structured | C Long-term | D Observation |
| --- | --- | --- | --- | --- |
| Scope | 小-中 | 中 | 大 | 小 |
| Development Cost | 低-中 | 中 | 高 | 低 |
| Risk | 中高 | 中 | 高 | 低 |
| Reusability | 中 | 高 | 高 | 中 |
| Fit to Requirement | 部分 | 完整 | 过度 | 不完整 |
| Local Pattern Fit | 中 | 高 | 低 | 高 |
| Test Burden | 中 | 中高 | 高 | 低 |
| Rollback Difficulty | 低 | 低-中 | 高 | 低 |
| Long-term Maintainability | 中低 | 高 | 高但过重 | 中 |
| Engineering-standard fit | 一般 | 高 | 高但不经济 | 未交付 |
| Recommendation | 不选 | **选择** | 延后 | 验证门 |

## 9. Recommended Solution

Selected option：Option B。

Why selected：满足真实流式并保持单一受控链路、事务、类型和可观测性边界。

Why not the other options：A 跨层污染，C 超范围，D 不交付用户行为。

Local patterns reused：ModelPort、Provider、ControlledChatUseCase、UoW、TerminalStatus、trace、前端 placeholder、protected live E2E。

External practices reused：异步 chunk、delta/end/error 生命周期、FastAPI WebSocket 测试、live 能力验证。

Remaining risks：供应商单 chunk、断连传播、delta 后 commit 失败、Markdown 高频渲染。

What must be verified later：多 delta、拼接与持久化一致、hash/count、失败回滚、PARTIAL 提交、HTTP/Skills/memory/tool 无回归。

## 10. Unified Technical Direction

使用单一受控执行核心和协议无关流式事件：Provider 输出内部增量，Workflow 累积最终答案，Application 管理事务与终态，WebSocket Adapter 管理 v2 映射和断连，HTTP 聚合同一执行核心，前端仅消费结构化事件。禁止 Router 直连模型、完整答案切片、双工作流、长期双协议、数据库迁移和消息队列。后续必须有离线分层测试、protected live LLM+Tushare WebSocket E2E、真实浏览器验收，以及不含正文的 TTFT/chunk_count/elapsed/termination 指标。

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| `astream` 单 chunk | live 长回答验证至少两个非空 delta |
| 断连后仍生成 | Adapter 并发观察断连并取消应用任务 |
| delta 后 commit 失败 | `stream_error`，不发 `stream_end`，事务回滚 |
| 重复/乱序 | 请求内严格 sequence，前后端测试 |
| HTTP/WS 漂移 | 共享执行核心 |
| PARTIAL 被误判 | 区分业务 TerminalStatus 与技术失败 |
| 重试重复输出 | 首 delta 后禁止应用层重放 |
| 日志泄漏 | 只记长度、数量、哈希、状态和耗时 |

## 12. Verification Direction

### 12.1 Engineering Contract for Plan Freezing

- Architecture：Provider/Workflow/Application/Router/Frontend 分层，HTTP/WS 单一核心。
- Interfaces：模型增量、流式事件和前端 union 均为显式类型，Python 公共接口同步类型与 Google-style docstring。
- Configuration：协议版本/事件枚举在代码中；不改 Prompt、密钥、生产配置。
- Observability：记录 request/session/run、TTFT、chunk_count、output_chars、elapsed、终态和 error_code，不记录正文。
- State：`stream_end`/`stream_error` 互斥；技术失败/取消回滚；业务 PARTIAL 提交；无首 delta 后重放。
- Tests：Provider、Workflow、WS、disconnect、failure、PARTIAL、frontend、HTTP regression、protected live、browser acceptance。

## 13. Deferred Work

D04 停止按钮、heartbeat、断线续传/回放、Redis/队列、chunk 账本、WebSocket auth query 改造、Markdown 增量优化、多实例连接和报告/对话事件总线统一。

## 14. Handoff to Plan Freezing

按 Option B 生成自包含执行计划；仅允许修改对话流式链、前端消费者、相关测试和 D03 文档；禁止 Prompt/Skills/memory/tool/database/deployment 扩张；必须包含离线、live、浏览器、回滚和可观测性门禁。
