# CODEBASE_RECON.md

## 1. Reconnaissance Target

Requirement source: `docs/specs/D03_WEBSOCKET_TRUE_STREAMING_REQUIREMENT_SPEC.md`

Focus areas:

- WebSocket 请求入口、认证和当前公开帧顺序。
- `ControlledChatUseCase`、受控工作流和模型 Provider 的回答生成链。
- 对话事务、消息持久化、取消和异常语义。
- 前端 WebSocket 消费、Pinia 状态和增量渲染能力。
- Trace、离线测试、Compose E2E 和 protected live E2E。

Out-of-scope reminders:

- 不勘察或设计 D04 控制卡片、D05 报告 SSE、D06 Redis 幂等。
- 不修改 Skills 路由、工具策略、记忆算法、Prompt 或报告工作流。
- 本阶段不修改代码、不运行测试、不调用真实 API。

## 2. Project Overview

Project type: Confirmed，前后端分离的模块化单体金融 Agent。

Languages: Python 3.12、TypeScript、Vue SFC。

Frameworks: FastAPI、SQLAlchemy、LangChain/OpenAI-compatible、自定义 Controlled Workflow、Vue 3、Pinia、Vite。

Runtime / package manager: Python 使用 uv 与 `uv.lock`；前端使用 npm 与 `package-lock.json`。

Main service type: FastAPI REST + WebSocket 对话服务，Vue/Nginx 前端。

Frontend/backend split: `frontend/` 与 `backend/` 分离；领域工作流位于 `Financial-MCP-Agent/src/conversation/`。

Test framework: Pytest、Vitest、Docker Compose E2E；未发现 Playwright/Cypress/Selenium。

Deployment clues: Nginx 已为 `/api/` 配置 WebSocket Upgrade，读取超时为 300 秒；GitHub Actions 有离线 CI 与手工触发的 protected live E2E。

Confirmed facts:

- 当前分支为 `main`，勘察时 HEAD 为 `ada9da6`。
- `README.md` 明确说明当前 WebSocket 发送终态文本帧，不是 Provider 逐 token streaming。
- `langchain-openai` 锁定版本为 1.6.0，当前生产适配器只调用 `ChatOpenAI.ainvoke()`。
- 真实 LLM + Tushare Live E2E 已存在，但只验证 HTTP 完整响应。

Assumptions:

- 当前正式使用的 OpenAI-compatible Provider 是否完整兼容 streaming 尚未通过 Live 调用证明。
- D03 后前后端可以同版本发布，但是否需要旧协议过渡仍需用户确认。

## 3. Directory Structure Summary

| Path | Apparent role | Relevance | Notes |
| --- | --- | --- | --- |
| `backend/routers/chat.py` | REST/WS 协议适配 | Direct | 当前 WS 在 Use Case 完成后发送完整文本 |
| `backend/application/chat/` | 对话应用编排与事务 Port | Direct | REST/WS 共用唯一 `ControlledChatUseCase` |
| `backend/infrastructure/chat/` | 模型、工具、Repository、Trace 适配 | Direct | Model Provider 当前返回完整字符串 |
| `Financial-MCP-Agent/src/conversation/` | 受控领域工作流 | Direct | Synthesis 当前是一次 await 调用 |
| `frontend/src/composables/useChat.ts` | WebSocket 生命周期与帧消费 | Direct | 已能追加普通文本帧 |
| `frontend/src/stores/chatStore.ts` | 前端消息与 streaming 状态 | Direct | 已有占位消息和增量追加方法 |
| `frontend/src/components/chat/ChatWindow.vue` | Markdown 渲染和流式光标 | Direct | 已可显示正文增长，但缺少内容变化滚动测试 |
| `tests/contract/` | REST/WS 公开合同 | Direct | 当前锁定“一个完整正文帧”的旧协议 |
| `tests/e2e/` | 离线与 protected live 纵向验收 | Direct | Live 目前只走 HTTP |
| `.github/workflows/` | 离线 CI 与手工 Live CI | Supporting | 已有凭证隔离和显式开关 |
| `docker/nginx/default.conf` | 前端代理与 WebSocket Upgrade | Supporting | 当前代理能力足够承载 WS |

## 4. Entry Points

### 4.1 Startup Entry

- 后端：`backend/main.py` 构造 FastAPI，挂载 `chat.router` 到 `/api/chat`。
- 前端：`frontend/src/main.ts` 启动 Vue；`ChatView.vue` 是对话页面。
- Docker：Nginx 将 `/api/` 代理至后端，并开启 WebSocket Upgrade。

### 4.2 Request / Task Entry

- 前端 `ChatView.handleSend()` 优先调用 `useChat.sendMessageStream()`。
- 浏览器连接 `/api/chat/stream`，Token 当前通过 WebSocket URL query parameter 传递。
- `backend.routers.chat.chat_stream()` 接受连接、认证、校验一轮 JSON 请求并调用唯一聊天 Use Case。

## 5. Relevant Call Chain

```text
ChatView.handleSend
-> useChat.sendMessageStream
-> WebSocket /api/chat/stream
-> chat_stream
-> authenticate_websocket / ChatMessageRequest validation
-> build_chat_use_case
-> ControlledChatUseCase.execute
-> SqlAlchemyConversationRepository.prepare_turn
-> optional memory command / memory retrieval
-> ControlledConversationWorkflow.run
-> context -> entity -> route -> rewrite -> permission -> plan
-> validate -> execute tools -> verify -> controller -> optional replan
-> AnswerContextPack
-> ControlledSynthesizer.synthesize
-> ModelPort.synthesize
-> OpenAICompatibleModelProvider.synthesize
-> ChatOpenAI.ainvoke
-> complete string
-> ConversationResult
-> apply working state / save assistant / outbox / commit
-> ChatOutcome
-> session_id frame
-> optional skill_confirm / memory_command
-> one complete raw text frame
-> optional context_update
-> done
-> frontend appends the complete text once
```

Confirmed segments:

- REST 和 WS 共用 `ControlledChatUseCase`。
- `ModelPort.synthesize()` 的返回类型是 `str`。
- Workflow 在 `await synthesizer.synthesize(pack)` 后才发 Synthesis/Termination Trace。
- Repository 在完整结果产生后保存助手消息和 Outbox，再由 Application 提交。
- Router 只在 Use Case 返回后发送正文。
- 前端已把非 JSON 帧当作 token 追加，但当前实际只收到一个完整正文帧。

Inferred segments:

- 要实现真实 streaming，必须在 Provider、Workflow/Application 和 WebSocket 之间新增可取消的增量传播合同；只修改 Router 无法获得上游 chunk。
- 如果发送发生在最终事务提交前，客户端可能看到尚未形成权威持久化终态的文本，需要冻结失败/取消后的持久化语义。

Unknown segments:

- 当前 configured Provider 对 `ChatOpenAI` streaming 的兼容程度。
- Starlette/FastAPI 在当前调用方式下能否在没有并发 receive 的情况下及时感知客户端断连；现有代码不能证明。

## 6. Related Files

### 6.1 Definitely Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/routers/chat.py` | WS Presenter | 当前帧顺序、错误和断连处理 | candidate modification | High |
| `backend/application/chat/use_case.py` | 单轮事务编排 | 工作流、持久化、提交与回滚边界 | candidate modification | High |
| `backend/application/chat/contracts.py` | 应用输出合同 | 当前只有最终 `ChatOutcome` | candidate modification | High |
| `Financial-MCP-Agent/src/conversation/ports.py` | Model Port | 当前 `synthesize() -> str` | candidate modification | High |
| `Financial-MCP-Agent/src/conversation/synthesis.py` | 最终模型调用 | 当前只消费完整字符串 | candidate modification | High |
| `Financial-MCP-Agent/src/conversation/workflow.py` | 领域编排 | Synthesis 与唯一终态所有者 | candidate modification | High |
| `backend/infrastructure/chat/providers.py` | 真实模型适配 | 当前调用 `ainvoke` | candidate modification | High |
| `backend/infrastructure/chat/testing.py` | Fake Model/Tool | 需要可控 chunk、异常和取消替身 | candidate modification | Medium |
| `frontend/src/api/index.ts` | WS 帧类型与解析 | 当前正文/控制混用字符串 | candidate modification | High |
| `frontend/src/composables/useChat.ts` | WS 生命周期 | 当前追加正文，但失败/取消语义不足 | candidate modification | High |
| `frontend/src/stores/chatStore.ts` | 流式 UI 状态 | 需要稳定完成/失败/部分状态 | candidate modification | Medium |
| `frontend/src/components/chat/ChatWindow.vue` | 增量渲染 | 用户可见验收入口 | candidate modification | Medium |
| `tests/contract/test_controlled_chat_contract.py` | WS 兼容合同 | 当前断言一个完整正文帧 | candidate modification | High |
| `tests/e2e/test_live_controlled_chat_chain.py` | protected live | 可复用真实 LLM/Tushare 隔离模式 | candidate modification | High |

### 6.2 Probably Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/infrastructure/chat/repository.py` | 原子消息持久化 | 需确认 partial/cancel 的落库语义 | read carefully / possible modification | High |
| `backend/infrastructure/chat/trace.py` | Workflow Trace Adapter | 需补 TTFT/chunk/终止观测 | candidate modification | Medium |
| `Financial-MCP-Agent/src/conversation/contracts.py` | WorkflowEvent/TerminalStatus | 可能扩展流式观测合同 | candidate modification | High |
| `backend/application/chat/factory.py` | 生产依赖装配 | 可能装配 streaming-capable Provider | candidate modification | Medium |
| `backend/config.py` | Typed Settings | Live/timeout 配置所有者 | candidate modification only if required | Medium |
| `backend/middleware/auth.py` | WebSocket 身份认证 | 会话隔离必须保持 | read-only unless explicitly approved | High |
| `docker/nginx/default.conf` | WS 代理 | 已支持 Upgrade，需确认无需修改 | read-only first | Medium |
| `.github/workflows/live-e2e.yml` | Live CI | 可扩展受保护 WS Live 测试 | candidate modification | High |

### 6.3 Supporting Context

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `pyproject.toml` | Python 依赖与 marker | 已有 `live/e2e/contract` 分层 | candidate modification only if new dependency approved | Medium |
| `uv.lock` | 锁定依赖 | 当前 `langchain-openai`/`openai` 版本证据 | normally generated only | Medium |
| `frontend/package.json` | 前端测试依赖 | 当前仅 Vitest，无浏览器自动化 | candidate modification only if approved | Medium |
| `tests/e2e/offline_app.py` | Compose Fake Ports 装配 | 可复用真实工作流/隔离外部依赖模式 | candidate modification | Medium |
| `tests/e2e/test_offline_compose_stack.py` | 前端代理完整链 | 当前只走 HTTP | candidate modification | Medium |
| `README.md` | 运行和能力边界 | 已明确当前非真流式 | candidate documentation update | Low |

### 6.4 Out of Scope

| Path / Area | Reason |
| --- | --- |
| `backend/services/agent_service.py`、`backend/routers/report.py` | 属于报告模式；`astream_events` 不能直接当作当前 Chat 主链 |
| Portfolio 模块 | D10 范围 |
| Skill 路由、Planner、Verifier、工具治理策略 | D03 不改变金融决策 |
| Memory 检索、压缩、LTM 治理算法 | D03 只保护事务和最终持久化语义 |
| Prompt 与评测数据 | D03 不改变回答质量合同 |

## 7. Existing Patterns to Reuse

| Pattern | Example file | Why reuse it |
| --- | --- | --- |
| Port/Adapter 分离 | `conversation/ports.py`, `providers.py` | 可隔离 Provider streaming 差异 |
| REST/WS 共用 Use Case | `application/chat/use_case.py` | 避免复制金融主链 |
| Typed terminal/event contracts | `conversation/contracts.py` | 可复用稳定状态和错误码 |
| Fake Provider | `infrastructure/chat/testing.py` | 可确定性测试 chunk、失败与取消 |
| 脱敏 Trace Sink | `infrastructure/chat/trace.py` | 可扩展低风险流式指标 |
| Protected live marker | `test_live_controlled_chat_chain.py` | 已有显式开关、临时 DB、真实只读 API |
| Frontend discriminated union | `frontend/src/api/index.ts` | 适合表达稳定 WS 事件 |
| Pinia streaming placeholder | `chatStore.ts` | 已具备增量展示基础 |
| Nginx WS Upgrade | `docker/nginx/default.conf` | 无需重新引入代理方案 |

## 8. Data Flow and State

### 8.1 Input Data

- WebSocket JSON：`user_id`、`message`、可选 `session_id`、可选 `explicit_skill`。
- Token 当前来自 URL query parameter 或 Authorization header。

### 8.2 Intermediate State

- `ChatCommand`、`PreparedChatTurn`、`ConversationRequest`。
- `AnswerContextPack` 只含验收证据。
- `WorkflowEvent` 仅在阶段完成时形成。
- 当前没有 typed content chunk、chunk sequence 或 stream lifecycle state。

### 8.3 Persistent State

- `prepare_turn()` flush 用户消息，但不提交。
- 完整 `ConversationResult` 产生后保存助手消息、Working State 和 Outbox。
- Application 统一提交；取消/异常由 `BaseException` 分支回滚。
- 当前不保存单个 chunk，也没有 partial transport result 的持久化模型。

### 8.4 Output Data

- JSON 控制帧：`session_id`、可选 `skill_confirm`、`memory_command`、`context_update`、`done`、`error`。
- 回答正文：原始文本帧，没有事件类型、序列号、状态或协议版本。

### 8.5 Potential Data Mismatch Points

- 正文若恰好是带 `type` 的 JSON，前端可能误当控制帧。
- Router 未向 `ChatCommand` 注入 `request_id`；工作流 trace/run ID 直到内部运行后才产生。
- `session_id` 当前在完整 Use Case 返回后才发送，不能在长任务开始时提供权威关联。
- `done` 不包含业务状态；前端不能区分 SUCCEEDED/PARTIAL/FAILED/CANCELLED。
- 客户端部分展示与数据库最终持久化之间没有显式一致性合同。
- 前端 `sendMessageStream()` 主要 resolve 而非 reject，注释所称 HTTP fallback 不可靠。

## 9. External Dependencies

| Dependency | Where called | Input | Output | Error handling / fallback |
| --- | --- | --- | --- | --- |
| OpenAI-compatible LLM | `providers.py` | System/Human messages | 当前完整模型消息 | timeout=30, max_retries=1；无 streaming 合同 |
| Tushare | `TushareToolProvider` | 已校验只读 ToolCall | Evidence facts | 分类为 timeout/transient/permanent |
| Tavily Web News | ReadOnlyToolProvider | Web 新闻调用 | 弱证据 | 有独立 timeout/quota；非 D03 主路径 |
| PostgreSQL/SQLite | Repository | 会话、消息、状态、Outbox | 原子终态 | Application rollback/commit |
| Redis | Memory cache | 会话上下文加速 | 可降级缓存 | 不是 D03 权威状态 |
| Langfuse | Trace exporter | 脱敏 Trace | 可选外部观测 | 失败不得阻断业务 |
| Nginx/Vite proxy | frontend transport | HTTP/WS | 代理连接 | 已支持 Upgrade |

## 10. Tests and Evaluation Assets

### 10.1 Existing Tests

- `tests/contract/test_controlled_chat_contract.py`：锁定 WS 旧帧顺序和安全错误。
- `tests/contract/test_skill_confirmation_public_contract.py`：锁定 `skill_confirm` + 文本 + done。
- `tests/e2e/test_controlled_chat_chain.py`：Fake Ports 的真实 Workflow 纵向链。
- `tests/e2e/test_offline_compose_stack.py`：Vue/Nginx/FastAPI/PostgreSQL 代理链，但仅 HTTP。
- `tests/e2e/test_live_controlled_chat_chain.py`：真实 LLM + Tushare + 临时 SQLite + Trace，但仅 HTTP。
- 前端现有 Vitest 主要覆盖 Skill Confirmation 和 Store，不覆盖 streaming 生命周期。

### 10.2 Coverage Gaps

- 无异步 chunk Fake Provider。
- 无 WS 增量、顺序、Unicode、终止唯一性合同测试。
- 无首 chunk 前失败、部分 chunk 后失败、取消和双会话隔离测试。
- 无 WebSocket protected live E2E。
- 无自动浏览器流式测试基础设施。
- 无 TTFT/chunk count Trace 验收。

### 10.3 Candidate Test Locations

- `tests/unit/conversation/`：Provider/stream contract 与重组。
- `tests/contract/test_controlled_chat_stream_contract.py`：WS 公开事件合同。
- `tests/e2e/test_controlled_chat_stream.py`：Fake Ports 的 WS 离线完整链。
- `tests/e2e/test_live_controlled_chat_stream.py`：显式 protected live WS。
- `frontend/src/api/__tests__/`：事件解析。
- `frontend/src/stores/__tests__/`：stream lifecycle。
- `frontend/src/composables/__tests__/`：WebSocket 消息、失败、done 和关闭。

### 10.4 Visible Test Commands

- 默认 Python：`uv run --locked pytest -q`，配置自动排除 `live`。
- 前端：`npm run lint`、`npm run type-check`、`npm run test -- --run`、`npm run build`。
- Compose：`docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e`。
- Protected live：已有 `RUN_PROTECTED_LIVE_E2E=true ... -m live` 模式。

## 11. Logging and Observability

### 11.1 Existing Logs

- Workflow 阶段包含 sequence、trace_id、run_id、session_id、stage、status、elapsed_ms、error_code。
- JSONL Trace 和可选 Langfuse exporter 已有脱敏边界。
- Router 内部异常只对客户端返回稳定错误码和安全文案。

### 11.2 Missing Logs

- 上游首 chunk 时间、服务端首发送时间、chunk count、TTFT、stream terminal reason。
- disconnect/cancel 的 request/session/trace 安全关联。
- Provider streaming 能力或降级模式。

### 11.3 Observability Risks

- 当前 Synthesis span 只在完整生成结束后记录，无法证明真实 streaming。
- 不应逐 chunk 写正文，否则产生敏感数据和日志放大。
- WS Token 使用 query parameter，存在进入代理访问日志的既有风险；D03 默认不改 Auth，但后续公开部署需单独治理。

### 11.4 Output-channel Separation

| Channel | Current implementation | Stable fields / format | Redaction | Gaps |
| --- | --- | --- | --- | --- |
| User/API result | JSON 控制 + 原始完整正文 | 部分 typed TS union | 正文直接给用户 | 无 typed delta/terminal status |
| Terminal progress | 后端启动摘要 | 非统一 | 部分安全 | 非 D03 主目标 |
| Logs | Python logger | error_code/error_type 等 | 不回传内部异常 | 缺 streaming 指标 |
| Traces | JSONL/Langfuse | trace/run/stage/status | key-based redaction | 无 chunk/TTFT |
| Artifacts | 可选 Trace Artifact | 路径配置化 | 默认关闭正文捕获 | 无 Live stream 摘要 |

## 12. Engineering Baseline Recon

| Area | Status | Evidence | Gap / implication |
| --- | --- | --- | --- |
| API/orchestration/domain/infrastructure boundaries | Established | Router→Use Case→Workflow→Adapter | Streaming 会跨层，不能放在 Router 业务判断中 |
| Agent/workflow/tool/prompt/model/memory/evaluation boundaries | Established | 明确目录与 Ports | Model Port 只支持完整字符串 |
| Docstrings, types, and key intent comments | Established | 主链大量中文 Google-style docstring | WS 输出后端仍是原始 dict/text |
| File-section navigation vs module separation | Established | 职责大体按模块分离 | `useChat.ts` 已偏长，D03 应保持窄改 |
| Typed configuration and secret handling | Established | `Settings`、`.env.example`、GitHub Secrets | Live streaming 开关/凭证不得散落读取 |
| Error, retry, fallback, and state semantics | Partial | Provider timeout/retry、Use Case rollback | disconnect 不能及时取消；无 transport partial 状态 |

## 13. Risk Areas

| Area | Why risky | Likely touched? | Recommended handling |
| --- | --- | --- | --- |
| Model Port contract | 影响生产/Fake Provider 与 Workflow | Yes | 先锁合同和测试，再改实现 |
| Public WS protocol | 前端和现有 Contract 依赖旧顺序 | Yes | 版本化、前后端原子升级，不长期双轨 |
| Transaction/persistence | 用户可能看到未提交内容 | Yes | 明确业务 PARTIAL 与传输失败的区别 |
| Cancellation/billing | 断连后可能继续真实模型计费 | Yes | 必测取消传播和任务清理 |
| Session/user isolation | 并发 chunk 可能串流 | Yes | 两会话隔离测试 |
| Auth token | query token 可能进入日志 | No by default | 本任务保持只读，单独安全事项 |
| Markdown `v-html` | 模型 HTML 可能带 XSS | Possibly UI file touched | 不扩大范围；单独安全评审 |
| Live APIs | 成本、限流、外部波动 | Test only | 显式开关、两条只读用例、最多一次瞬时重试 |
| Generated lockfiles | 依赖变更会产生大 diff | Only if browser dependency approved | 无明确需要不新增 Playwright |

## 14. Unknowns and Assumptions

### 14.1 Unknowns From Missing Code Access

- None；本次已访问 D03 相关本地代码。

### 14.2 Unknowns From Incomplete Requirement

- 传输失败后的部分正文是否持久化。
- 是否要求自动浏览器 Live E2E。
- 是否需要 D03 可见“停止生成”按钮。

### 14.3 Unknowns From Ambiguous Architecture

- Provider 不支持 streaming 时的公开降级行为。
- 是否保留旧 raw-text WS 协议。
- 工具执行阶段是否需要 heartbeat/processing 事件。
- 权威 session/request 标识应在何时暴露给客户端。

### 14.4 Assumptions

- HTTP 非流式接口保持完整响应。
- 前后端可以同一版本发布。
- 业务 `TerminalStatus.PARTIAL` 是一个完整受控回答；传输中断产生的残缺文本不是同一含义。
- D03 不新增数据库 Schema。

## 15. Handoff to Next Step

下一步进入 Requirement Clarification，产出 D03 的 `CLARIFICATION_QUESTIONS.md`。

需要澄清：

- 新 WS 协议及旧客户端兼容策略。
- chunk 展示与事务提交/回滚的一致性。
- 断连、取消、非 streaming Provider 和非模型回答的行为。
- Live E2E 是分层验收还是新增浏览器自动化依赖。

后续方案需重点考虑：

- `conversation/ports.py`、`synthesis.py`、`workflow.py`。
- `application/chat/use_case.py`、`contracts.py`。
- `routers/chat.py`、`providers.py`、`testing.py`、`trace.py`。
- `frontend/src/api/index.ts`、`useChat.ts`、`chatStore.ts`、`ChatWindow.vue`。
- WS Contract、离线 E2E、protected live E2E 和前端 Vitest。

修改公开协议、事务持久化、认证或新增浏览器依赖前必须获得用户明确确认。
