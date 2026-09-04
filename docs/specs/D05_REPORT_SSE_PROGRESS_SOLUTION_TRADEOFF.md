# SOLUTION_TRADEOFF.md

## 1. Tradeoff Context

D05 要解决的不是“把现有 2 秒轮询换一个接口名”，而是让报告生成的真实阶段、单调任务进度和安全终态以可取消、可降级、可观测的方式到达浏览器。当前报告任务以数据库 `Report` 记录为最终权威，但只保存粗粒度 `status/progress/content/error_msg`；LangGraph 四个分析节点真实并行，现有固定节点百分比会因完成顺序不同而回退；前端轮询存在首次等待、请求重叠、永久静默重试和连接未清理问题。

本轮必须同时守住两条边界：一是 D05 不引入数据库迁移、Redis、多实例广播或事件重放，不能虚构跨进程可靠性；二是阶段事件必须来自真实执行边界，不能由前端按百分比推断，也不能把 LangGraph 原始事件、异常、Prompt 或报告正文作为进度协议透传。方案需要为 D06 的 Redis snapshot/pub-sub/idempotency 演进保留端口，但当前部署仍以数据库快照为恢复权威。

## 2. Inputs Reviewed

- REQUIREMENT_SPEC.md: `docs/specs/D05_REPORT_SSE_PROGRESS_REQUIREMENT_SPEC.md`
- CODEBASE_RECON.md: `docs/specs/D05_REPORT_SSE_PROGRESS_CODEBASE_RECON.md`
- CLARIFICATION_QUESTIONS.md: `docs/specs/D05_REPORT_SSE_PROGRESS_CLARIFICATION_QUESTIONS.md`
- User decisions: 按完整 Spec Coding 流程推进 D05；允许端到端测试和真实 API；先冻结验收标准，再开发、Review、提交、推送、创建 PR 并合并。
- External sources:
  - FastAPI Server-Sent Events: https://fastapi.tiangolo.com/tutorial/server-sent-events/
  - FastAPI SSE implementation: https://github.com/fastapi/fastapi/blob/master/fastapi/sse.py
  - Nginx HTTP Proxy Module: https://nginx.org/en/docs/http/ngx_http_proxy_module.html
  - WHATWG HTML Server-Sent Events: https://html.spec.whatwg.org/multipage/server-sent-events.html
  - MDN Using the Fetch API: https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch
  - MDN AbortController: https://developer.mozilla.org/en-US/docs/Web/API/AbortController
  - Vue Composition API Lifecycle Hooks: https://vuejs.org/api/composition-api-lifecycle.html
  - sse-starlette implementation reference: https://github.com/sysid/sse-starlette/blob/main/sse_starlette/sse.py

## 3. User Decisions and Defaults

### 3.1 Confirmed Decisions

- 协议冻结为 `report-progress-v1`，业务事件只有 `stream_ready`、`stage_update`、`task_terminal`；heartbeat 使用 SSE comment，不进入业务 reducer。
- Envelope 包含 `protocol_version/task_id/report_id/sequence/emitted_at/type`，所有字段显式建模并严格校验。
- 阶段集合为 `PREPARING`、四个并行分析阶段、可选 `PERSONALIZATION`、`SYNTHESIZING`；阶段状态为 `RUNNING/SUCCEEDED/FAILED/SKIPPED`，任务终态独立表达。
- 四个分析节点按“已完成数量”推进 20→35→50→65→80，不能按节点身份绑定百分比；进度只能单调增加。
- 数据库 `Report` 是任务状态恢复和最终内容的权威；D05 不做 schema migration。
- 浏览器用 `fetch` 携带现有 Bearer header，流式解析 SSE，并用 `AbortController` 清理；禁止把 token 放到 query string。
- SSE 首帧 5 秒内到达；heartbeat 15 秒；SSE 失败后切换串行 polling，间隔按 2/4/8/15 秒退避，连续 5 次失败才结束观察，总观察上限 15 分钟。
- 新任务、切换历史报告、组件卸载、页面离开、登出和任务终态都必须释放 SSE/polling；D05 不增加任务取消能力。
- SSE 对不存在任务和非所有者统一返回 404；未认证返回 401。`/status` 保持现有路径和字段兼容，错误内容改成安全投影，并可新增 `error_code`。
- protected Live 只跑一条真实报告，单例超时 12 分钟，不对整份报告自动重试，只保存脱敏摘要、阶段序列、耗时和 hash artifact。

### 3.2 Conservative Defaults Used

- 当前生产 Compose 只有一个 Uvicorn worker，因此允许进程内 publisher 作为低延迟加速层；它不是恢复权威，也不承诺多 worker 广播。
- 连接建立前先用短生命周期数据库会话完成鉴权和所有权校验；不能让 request-scoped DB session 占据整个长连接。
- 连接后立即从数据库投影一次 `stream_ready` 快照；订阅事件期间定期从数据库 reconcile，弥补连接前竞态、进程内事件丢弃和无订阅者时期。
- 慢客户端不能反压报告业务任务；订阅队列使用有界 latest-event 语义，满时替换旧非终态通知，客户端最终由数据库快照收敛。
- public `sequence` 由每个 SSE 连接的 presenter 生成，用于单连接去重和单调 reducer；D05 不承诺跨重连全局 sequence 或 `Last-Event-ID` 重放。
- `task_terminal` 必须在数据库终态提交后发布；连接时若数据库已终态，首个 `stream_ready` 后立即发送终态并关闭。
- FastAPI 最低依赖声明应与原生 SSE 引入版本对齐到 `>=0.135,<1`，锁文件继续固定当前 `0.141.1`；不新增第三方 SSE 依赖。
- 错误只暴露稳定 `error_code` 和面向用户的安全 message；原始异常保留在服务端脱敏结构化日志，不进入响应、SSE 或测试 artifact。

### 3.3 Blocking Decisions

None. P0 的协议、认证、状态权威、降级、清理、测试成本和 D06 边界均已冻结。

## 4. Core Decision Point

核心决策是报告进度应采用哪一种事实来源和分发模型：只从数据库轮询并包装成 SSE、完全依赖进程内推送，还是建立“真实执行边界产生 typed event + 数据库权威快照恢复 + SSE presenter 投影”的混合模型。这个选择同时决定并行阶段是否真实、慢消费者是否影响任务、断线后能否收敛，以及 D06 引入 Redis 时是否需要重写业务节点。

## 5. Reference Sources and Repository Evidence

### 5.1 Official Docs

#### Source: FastAPI Server-Sent Events

**Link:** https://fastapi.tiangolo.com/tutorial/server-sent-events/

**What was inspected:** FastAPI 0.135 起内置的 `EventSourceResponse`、`ServerSentEvent`、async generator/Pydantic data、`event/id` 字段、自动 ping、缓存与代理缓冲响应头、断连取消检查。

**Relevant practice:** SSE 应由框架负责正确 wire framing、JSON 编码、`text/event-stream`、15 秒 comment ping 和连接取消，而业务层只产出 typed domain/application event。

**Reusable part:** Directly reusable

**Fit for this task:** 当前 lock 为 FastAPI 0.141.1，能力可直接使用；只需把声明的最低版本从早于该能力的 0.115 调整到 0.135，避免 Docker 环境解析到不支持原生 SSE 的版本。

#### Source: Nginx HTTP Proxy Module

**Link:** https://nginx.org/en/docs/http/ngx_http_proxy_module.html

**What was inspected:** `proxy_buffering` 默认开启、关闭后同步向客户端传递响应，以及上游 `X-Accel-Buffering: no` 对缓冲行为的控制。

**Relevant practice:** 长连接事件流必须显式关闭代理缓冲，不能只依赖应用端及时 yield。

**Reusable part:** Directly reusable

**Fit for this task:** 为报告 events 路径配置专用 location，关闭 buffering/cache 并保留足够读取超时；FastAPI 同时自动返回 `X-Accel-Buffering: no`，形成双重保障。

#### Source: WHATWG HTML Server-Sent Events

**Link:** https://html.spec.whatwg.org/multipage/server-sent-events.html

**What was inspected:** `text/event-stream` MIME、event stream 字段、comment 行、event ID 和 `Last-Event-ID` 的标准语义。

**Relevant practice:** heartbeat 应使用 comment；业务事件应使用明确 `event/id/data`，而不是自定义换行 JSON；重连重放必须有独立、可持久的 event ID 语义。

**Reusable part:** Partially reusable

**Fit for this task:** wire format、comment heartbeat 和 per-connection ID 直接采用；跨连接 `Last-Event-ID` replay 因没有持久事件日志而明确推迟到 D06。

#### Source: MDN Using the Fetch API and AbortController

**Link:** https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch and https://developer.mozilla.org/en-US/docs/Web/API/AbortController

**What was inspected:** `fetch` 的 request options/headers、`Response.body` 的 `ReadableStream` 增量处理、`TextDecoderStream`，以及 `AbortSignal` 可取消 fetch、响应体消费和流。

**Relevant practice:** 浏览器可在完整响应结束前逐块消费 UTF-8 body，并通过单个 abort signal 统一结束网络请求和 stream reader。

**Reusable part:** Directly reusable

**Fit for this task:** 现有认证依赖 `Authorization: Bearer`，因此使用 `fetch` 明确注入 header 比原生 `EventSource` 更匹配；组件/任务生命周期统一调用 abort，随后再决定是否启动 polling fallback。

#### Source: Vue Composition API Lifecycle Hooks

**Link:** https://vuejs.org/api/composition-api-lifecycle.html

**What was inspected:** `onUnmounted` 对定时器、DOM listener 和 server connection 等手工副作用的清理责任。

**Relevant practice:** composable 创建的 stream、timer 和 listener 必须在 owning component 卸载时显式清理。

**Reusable part:** Directly reusable

**Fit for this task:** `ReportView` 应在卸载时调用统一 stop-observation 动作；同一动作也服务任务切换、终态和登出，避免多套释放逻辑。

### 5.2 Open-source Repositories

#### Source: FastAPI SSE Implementation

**Link:** https://github.com/fastapi/fastapi/blob/master/fastapi/sse.py

**What was inspected:** 官方实现对 `ServerSentEvent` 的 Pydantic/JSON 编码、header 处理、producer/keepalive task 生命周期，以及 routing 层 cancellation checkpoint 和容量 1 内部 channel。

**Relevant practice:** 框架的传输任务使用结构化并发并在每次 yield 后检查取消；业务端不应自行拼接 SSE 字符串或复制 keepalive 实现。

**Reusable part:** Directly reusable

**Fit for this task:** 直接依赖已安装 FastAPI 内置实现，减少自研 framing、heartbeat 和断连泄漏风险；应用 publisher 仍保持协议无关。

#### Source: sse-starlette

**Link:** https://github.com/sysid/sse-starlette/blob/main/sse_starlette/sse.py

**What was inspected:** 社区实现的 ping、send timeout、client disconnect、server shutdown 和并发 task 管理。

**Relevant practice:** SSE 需要完整连接生命周期，而不仅是返回一个无限 generator；关闭、超时和 ping 应被明确建模。

**Reusable part:** Conceptual only

**Fit for this task:** FastAPI 当前已经内置满足本轮需要的 SSE 实现，引入 `sse-starlette` 会增加生产依赖和重复抽象，因此只作为实现成熟度对照，不采用。

#### Source: Historical Finance Report SSE Branch

**Link:** local `origin/feature/redis-integration-phase1` at commit `8ef46f0`

**What was inspected:** 旧版内存 queue manager、query-token EventSource、heartbeat、初始 payload、Redis status 和 Nginx buffering 配置。

**Relevant practice:** 连接后先发快照、heartbeat、订阅释放和代理禁缓冲是有效概念；认证、类型、持久化边界和前端 parser 必须重新设计。

**Reusable part:** Partially reusable

**Fit for this task:** 旧分支与 main 历史分叉且一次混入约 8k 行 Redis/admin/idempotency 改造，不能 cherry-pick；仅复用经过当前需求重新验证的概念，禁止复制 query token、任意 dict、unsafe JSON cast 或 Redis 大包。

### 5.3 Local Project Patterns

| Local pattern | Evidence from CODEBASE_RECON.md | How to reuse |
| --- | --- | --- |
| 数据库 Report 任务权威 | `backend/routers/report.py`、`backend/db/models.py` | 连接首帧、reconcile、终态和 fallback 都读取同一投影，不建立第二真相源 |
| BackgroundTasks + application service | `backend/routers/report.py`、`backend/services/agent_service.py` | Router 只创建任务；service 在真实 LangGraph stage 边界发布进度 |
| D03/D04 typed public contracts | `backend/application/chat/*`、`backend/schemas/chat.py` | 报告也分离内部 event 与 Pydantic public frame，禁止 Router/前端推断 |
| D03 容量 1 stream/backpressure 经验 | `backend/application/chat/use_case.py` | 复用有界队列和结构化关闭思想，但报告 publisher 不阻塞长任务，采用 latest-event/reconcile |
| strict TypeScript parser | `frontend/src/api/index.ts`、D04 progress parser | 逐字段校验 protocol/type/enum/ID/sequence，不以类型断言信任网络 |
| Pinia/composable ownership | chat Store、`frontend/src/composables/useReport.ts` | composable 管网络副作用；单 reducer 管任务、阶段、sequence、transport 状态；组件只渲染 |
| protected Live artifact | `tests/e2e/test_live_controlled_chat_chain.py` | 复用显式 gate、凭证检查、脱敏结构化 artifact、hash 和独立超时 |
| 现有 Nginx `/api/` 代理 | `nginx/nginx.conf` | 为 SSE 子路径增加更具体规则，不改变普通 API 代理语义 |

## 6. Reusable Patterns

### 6.1 Directly Reusable Patterns

- FastAPI 原生 `EventSourceResponse`/`ServerSentEvent`、15 秒 ping、取消检查、`no-cache` 和 `X-Accel-Buffering: no`。
- 数据库 Report 的 task ownership、状态、progress、content 与终态更新事务。
- D03/D04 的 typed Python contract、Pydantic public projection、TypeScript strict parser、单 reducer 和生命周期清理分层。
- 前端现有 Bearer token 来源与 API base URL 规则；SSE fetch 显式使用同一 token，不复制认证存储。
- pytest fake provider、Vitest、Compose 路径和 protected Live 的凭证 gate/artifact 规范。
- Nginx 更具体 location、关闭 proxy buffering 的官方配置方式。

### 6.2 Partially Reusable Patterns

- 旧分支的 initial snapshot、heartbeat、subscribe/finally cleanup：保留目标语义，重新实现 typed contract、安全 auth 和 bounded queue。
- D03 容量 1 backpressure：聊天 token 事务需要消费者确认；报告后台任务不能被浏览器拖慢，因此只复用“有界资源”原则，改为非阻塞 latest notification + DB reconcile。
- LangGraph `astream_events`：用于识别真实节点开始/结束，但只映射白名单 node name；不能把 raw event/metadata/data 暴露给 publisher。
- `/status`：保持字段兼容并成为 polling fallback，但与 SSE 共享安全 snapshot projector 和单调 progress 规则。

### 6.3 Conceptual References Only

- WHATWG `Last-Event-ID` 跨重连恢复；D05 没有持久 event log，不能宣称 replay。
- sse-starlette 的 send timeout/shutdown 完整性；本轮由 FastAPI 内置实现承担。
- Redis snapshot/pub-sub/stream、幂等提交和多 worker 广播；接口方向为 D06 预留，当前不落地。
- AG-UI/LangGraph 通用运行事件总线；报告只需要小型稳定协议，无需引入完整 agent UI 标准。

### 6.4 Not Suitable for This Iteration

- 纯前端按百分比阈值推断“当前阶段”或把 polling 动画称为实时进度。
- 纯进程内状态作为恢复权威、无数据库首帧，或对当前单 worker 实现声称多实例可靠。
- 从 URL query 读取 JWT、记录带 token 的 URL，或把 Authorization/异常/报告正文写进日志和 artifact。
- 手工字符串拼接 SSE、复制框架 heartbeat，或引入新的 SSE/Redis 生产依赖。
- 在 D05 一并做 Redis、数据库 event table、幂等键、任务取消、跨刷新 replay、管理员接口。
- 直接 cherry-pick 历史 `feature/redis-integration-phase1` 大包。

## 7. Solution Options

### 7.1 Option A: Minimal Fix — Database-Polling SSE Wrapper

**What changes:** 新增 SSE endpoint；generator 每隔固定时间查询 `Report`，当 status/progress 改变时发事件；前端改为 fetch SSE，失败回原轮询。

**What does not change:** LangGraph/service 不发布真实 stage lifecycle；数据库模型不变。

**Benefits:** 实现量小；数据库天然支持当前部署之外的 worker；断线后可以恢复最终状态。

**Costs:** SSE 服务端仍在轮询数据库，增加长连接查询；只能看到粗粒度百分比，不能可靠表达并行节点 RUNNING/SUCCEEDED；实时性受轮询间隔限制。

**Risks:** 把传输形式变化误当成真实事件流；仍需用百分比反推阶段，会与 Claim 和 D05-T02 冲突；大量客户端放大数据库压力。

**Testing burden:** Medium；需测 endpoint、DB polling、终态和前端 fallback，但无法建立真实节点因果证据。

**Rollback difficulty:** Low；无迁移，可撤回 endpoint/前端。

**Engineering impact:**

- Architecture/module ownership: Router/generator 同时承担查询、差异比较和传输，application 边界偏弱。
- Documentation/types: 仍需 Pydantic/TS 协议，但 stage 只能推断。
- Configuration/secrets/prompts: auth 沿用；新增 polling interval 常量。
- Terminal/logging/tracing/artifacts: 可记录连接/查询次数，阶段真实性不足。
- Errors/retry/state: DB 临时错误和 stream 断开需要重试/关闭；业务任务不受客户端影响。

**When to choose it:** 只要求减少前端请求代码、只展示 task status/progress，且不要求真实并行阶段时。当前不选。

### 7.2 Option B: Structured Improvement — Typed Event Accelerator + Authoritative DB Snapshot

**What changes:** 在报告 application/service 边界定义 protocol-agnostic typed stage event 和 publisher port；`run_report_task` 只在真实准备、节点开始/完成、个性化、汇总和终态边界发布。进度写库采用按完成数量计算的单调规则。进程内 hub 以有界、非阻塞 latest notification 向当前单 worker 的订阅者加速；SSE endpoint 先鉴权/所有权校验，再发送数据库快照，随后消费 hub 并定期数据库 reconcile，终态后关闭。前端 fetch parser/reducer/cleanup 管理 SSE，失败后进入严格串行 polling fallback。Nginx 为该路径关闭 buffering。

**What does not change:** Report 表结构、BackgroundTasks、LangGraph 拓扑、四分析器并行、Prompt、模型/工具、报告内容格式、认证方式和普通 history/detail/download API。

**Benefits:** 阶段来自真实运行；低延迟且不让慢浏览器阻塞报告；连接前/事件丢失/已完成任务都由 DB 快照收敛；公共协议与 LangGraph/raw error 解耦；D06 可替换 publisher/snapshot adapter 而不改业务阶段。

**Costs:** 中等跨后端、前端和代理修改；需处理 subscribe/register 竞态、进度单调、重复/迟到事件、任务切换和 SSE parser chunk 边界。

**Risks:** 进程重启或另一个 worker 的中间 stage event 不可见；subscriber queue 丢弃可能跳过非终态细节；DB 与 publish 顺序错误会制造短暂倒退；LangGraph event name 映射若不严格会误识别节点。

**Testing burden:** High but bounded；需要 contract、publisher、service stage、route auth/stream、frontend parser/reducer/lifecycle、fallback、Nginx/Compose 和一条 protected Live。

**Rollback difficulty:** Low/Medium；无数据迁移、无新服务，通过一个 squash merge 原子回滚前后端/Nginx/依赖下限即可。

**Engineering impact:**

- Architecture/module ownership: service owns authoritative transition facts；application progress module owns typed events/hub/safe snapshot；Router owns auth and SSE projection；composable owns I/O；store/reducer owns UI state。
- Documentation/types: Python enum/dataclass/protocol/Pydantic 与中文 Google-style docstring；TS discriminated union/parser；协议和阶段常量版本化。
- Configuration/secrets/prompts: 无新 secret/Prompt；heartbeat、首帧、reconcile、poll backoff、总时限作为集中稳定常量；FastAPI 最低版本对齐。
- Terminal/logging/tracing/artifacts: 结构化记录 task/report/stage/status/elapsed/error_code/transport，不记录 token、正文、Prompt、raw payload；Live artifact 只存阶段、耗时和 hash。
- Errors/retry/state: publish 非阻塞且不改变报告成败；DB commit 先于可恢复通知；SSE 断开只停止观察；fallback 有界退避；terminal reducer 锁定、progress 取 max。

**When to choose it:** 需要真实可解释进度、当前单 worker 可低延迟推送、又要用数据库保证恢复并为 D06 留出演进边界时。适合当前 D05。

### 7.3 Option C: Long-term Architecture Direction — Redis Snapshot/Pub-Sub/Replay

**What changes:** 引入 Redis-backed task snapshot、分布式 pub-sub 或 stream、幂等提交、event sequence/replay、跨 worker/重启恢复和过期治理；SSE server 订阅 Redis，数据库保留长期报告结果。

**What does not change:** 理想情况下业务 stage publisher port 和 public protocol 保持，底层 adapter 替换。

**Benefits:** 支持多 worker、跨进程实时广播、短期恢复、可扩展事件重放和任务去重；减少数据库 reconcile 压力。

**Costs:** 新服务依赖、配置、凭证、故障模式、TTL/一致性、部署与运维成本；需要 Redis/DB 双写语义和完整恢复测试。

**Risks:** pub-sub 非持久、stream 消费语义、双写顺序、缓存污染、旧快照、重复终态和敏感 payload 留存都需专项设计；易把 D05 扩成 D06 大包。

**Testing burden:** Very High；需要多进程、Redis 故障、重启、重复提交、replay、TTL、并发和迁移测试。

**Rollback difficulty:** High；涉及新基础设施与可能的持久合同。

**Engineering impact:**

- Architecture/module ownership: infrastructure adapter、distributed state coordinator 和 task idempotency 成为新边界。
- Documentation/types: 需定义 durable snapshot/event schema、TTL 和兼容策略。
- Configuration/secrets/prompts: 新 Redis URL/secret/pool/timeout；Prompt 不变。
- Terminal/logging/tracing/artifacts: 需跨实例 correlation、lag、drop/replay 和 Redis 健康指标。
- Errors/retry/state: 明确 DB/Redis 双写、重连、补偿、降级和一致性级别。

**When to choose it:** 部署扩展为多 worker/多实例，且产品需要跨刷新恢复、幂等和 replay 时。Deferred to D06。

### 7.4 Option D: Observation-first Option

**What changes:** 先只增加 LangGraph event characterization、数据库 progress 并发测试、Nginx streaming smoke 和真实报告 trace，不提供新 SSE/UI。

**What does not change:** 用户仍使用现有 2 秒 polling 和阈值推断。

**Benefits:** 实现风险最低；可以进一步量化 event 顺序和代理行为。

**Costs:** 不解决首次等待、重叠 polling、真实阶段缺失和清理泄漏。

**Risks:** 审计继续停留在“知道问题”，代码和用户体验 Claim 仍不闭环。

**Testing burden:** Low/Medium。

**Rollback difficulty:** Low。

**Engineering impact:**

- Architecture/module ownership: 只扩测试/日志，不建立正式进度边界。
- Documentation/types: 无公共协议。
- Configuration/secrets/prompts: 无变化。
- Terminal/logging/tracing/artifacts: 增加观察数据。
- Errors/retry/state: 不改善客户端失败语义。

**When to choose it:** LangGraph 事件或部署拓扑仍未知、无法冻结协议时。当前 Recon 已获得足够证据，因此不选；测试优先仍作为 Option B 的首个里程碑。

## 8. Decision Matrix

| Dimension | Option A Minimal Fix | Option B Structured Improvement | Option C Long-term Architecture | Option D Observation-first |
| --- | --- | --- | --- | --- |
| Scope | Small/Medium | Medium | Large | Small |
| Development Cost | Low | Medium | High | Low |
| Risk | Medium（伪实时/DB 压力） | Medium（竞态/丢通知） | High（分布式一致性） | Low |
| Reusability | Low | High | High | Medium |
| Fit to Current Requirement | Low/Medium | High | Medium（超范围） | Low |
| Local Pattern Fit | Medium | High | Medium | High |
| Test Burden | Medium | High but bounded | Very High | Low/Medium |
| Rollback Difficulty | Low | Low/Medium | High | Low |
| Long-term Maintainability | Low | High | Potentially high | Medium |
| Engineering-standard fit | Medium | High | Medium（当前过度设计） | Medium |
| Recommendation | Reject | Select | Defer to D06 | Reject as final solution |

## 9. Recommended Solution

Selected option: Option B — Typed Event Accelerator + Authoritative DB Snapshot。

Why selected:

- 它是唯一同时满足真实阶段、单调进度、低延迟、断线收敛、安全投影和当前无 Redis 边界的方案。
- 数据库仍是唯一恢复权威，进程内 hub 只是可丢弃通知，因此不会把当前单 worker 实现包装成虚假的分布式能力。
- service/application/router/frontend 的责任清楚，D06 只需替换 publisher/snapshot adapter，不必重写 LangGraph 节点或公共 UI 合同。
- 可直接使用 FastAPI 现有内置 SSE，避免手写 wire protocol或新增依赖；前端 fetch 与现有 Bearer auth 天然兼容。
- 无 schema migration，所有修改可在单 PR 中原子回滚。

Why not the other options:

- Option A 只是“服务器端轮询的 SSE”，无法证明真实并行阶段，也会把数据库变成高频事件总线。
- Option C 是正确的后续方向，但 Redis、幂等、多实例、replay 属于 D06，当前纳入会扩大故障面和测试成本。
- Option D 的证据收集已经完成，不再构成阻塞；只观察不能关闭用户体验 Gap。

Local patterns reused:

- Report 数据库事务和现有 task/user ownership。
- D03/D04 typed contracts、安全 public projection、strict parser、单 reducer、显式 cleanup 和 protected Live artifacts。
- 现有 LangGraph `astream_events` 执行入口和 Compose/Nginx 部署结构。

External practices reused:

- FastAPI 原生 SSE 的 structured lifecycle、ping、取消和防缓冲 header。
- WHATWG `event/id/data` 与 comment heartbeat。
- Nginx 专用 SSE 路径关闭 buffering。
- Fetch `ReadableStream` 增量解析和 `AbortController` 释放；Vue `onUnmounted` cleanup。

Remaining risks:

- 进程内 hub 在多 worker、重启或无订阅时会丢非终态事件，必须在 README/验收中明确，并用 DB reconcile 收敛。
- LangGraph 并行节点完成顺序不确定；所有状态判断必须按 node identity，所有任务 progress 必须按完成数量。
- SSE parser 要正确处理任意 chunk 切分、多行 data、comment、CRLF 和尾部残片。
- 连接建立、订阅注册、数据库快照之间存在竞态，需要以“注册订阅→读取快照→去重/单调 reducer”或等价顺序测试证明无终态悬挂。
- 原生 FastAPI SSE 的最低版本与当前宽松依赖声明不一致，需要在本轮对齐声明并验证生产镜像。

What must be verified later:

- stage event 只来自真实 service/LangGraph 边界，未知 node 不进入 public stream；四分析器并行乱序时 progress 从不回退。
- SSE 鉴权/所有权在响应提交前完成；401/404 与普通 JSON 错误可被前端正确降级，且不泄露 task existence。
- 首帧、heartbeat、终态关闭、慢消费者、订阅 cleanup、数据库 reconcile 和已完成任务连接均在时限内工作。
- `/status` 字段兼容、串行 polling 无重叠、有界退避，SSE/polling 任一时刻最多一种观察传输活跃。
- task/report/sequence/terminal reducer 能拒绝重复、迟到、跨任务和非法帧。
- Nginx/Compose 首帧不被缓冲；真实模型/Tushare 报告产生真实阶段、最终数据库内容和低敏 artifact。

## 10. Unified Technical Direction

- 在报告 application/service 边界建立 `report-progress-v1` 的内部 typed facts、safe snapshot projector 和可替换 publisher port；真实业务 service 发布，不能让 Router 或 Vue 推断阶段。
- 当前 adapter 使用进程内 bounded latest-event hub 加速，数据库 Report 保持唯一恢复权威；SSE 订阅必须结合首帧 DB snapshot 和周期 reconcile，不承诺 replay/multi-worker。
- Router 在开始 streaming 前完成 Bearer auth、用户确保和统一 404 ownership 检查；使用 FastAPI 原生 `EventSourceResponse/ServerSentEvent`，不手拼字符串、不持有长事务。
- 对齐 FastAPI 声明最低版本到原生 SSE 能力版本；为 Nginx 报告 events 子路径关闭 buffering/cache，保留 heartbeat/read timeout。
- 前端用 fetch + Authorization + ReadableStream + AbortController，strict parser 后进入 task-scoped 单调 reducer；SSE 失败才启动串行有界 polling，任何生命周期结束统一 cleanup。
- 先写失败基线和协议/竞态测试，再实现 publisher/service/route/frontend/proxy；验证 unit、contract、Vitest、full regression、Compose streaming 和一条 protected Live。
- 日志和 artifact 只记录 task/report/stage/status/sequence/elapsed/transport/error_code/hash，不记录 token、Prompt、报告正文、raw LangGraph event 或原始异常。
- 不改 Report schema、LangGraph 拓扑、Prompt、工具、memory、任务取消、Redis、幂等、跨刷新 replay；这些分布式恢复能力推迟到 D06。

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| 进程内通知丢失或不跨 worker | DB 首帧 + 15 秒 reconcile + polling fallback；文档限定当前单 worker；D06 替换 adapter |
| subscribe/snapshot 竞态导致错过终态 | 先注册有界订阅再读取 DB snapshot；每次 wake/reconcile 检查终态；并发测试覆盖三种顺序 |
| 并行分析器令百分比回退 | 按完成集合计数计算 20+15×N；数据库写入和前端 reducer 都取单调 max |
| event name 识别错误 | 优先白名单 `langgraph_node` metadata；明确 root/未知 node 忽略；characterization test 固定真实 event shape |
| 慢客户端阻塞报告任务 | publisher `publish` 非阻塞；queue 有界、替换旧非终态；DB 保证最终收敛 |
| 终态先推送后提交 | 先 commit Report 终态，再 publish terminal；失败也保留最后 progress 并安全映射 error |
| Streaming response 已 200 后才发现无权限 | 连接前短 DB 会话完成 auth/ownership；stream generator 不承担访问决策 |
| request DB session 长时间占用 | 预检会话立即结束；reconcile 每次新建短会话，不把 `get_db` session 注入无限 generator |
| SSE chunk 解析错误 | 独立 parser 覆盖 CRLF、跨 chunk、多行 data、comment、EOF、非法 JSON/enum/sequence |
| transport 双开或资源泄漏 | 单 observation controller；切换前 abort/clear timer；`onUnmounted`、terminal、logout、task switch 全覆盖 |
| fallback 形成请求风暴 | 请求完成后才安排下一次 polling；2/4/8/15 秒退避、5 次上限、15 分钟总时限 |
| 错误或 secret 泄露 | public projector 白名单 + stable error_code；forbidden-key/token/raw-exception 负向测试和 artifact 扫描 |
| Nginx 聚合首帧 | 专用 location `proxy_buffering off`/`proxy_cache off`；框架 `X-Accel-Buffering: no`；Compose timing smoke |
| FastAPI 环境解析到旧版本 | `pyproject.toml` 与 backend requirements 最低版本统一到 `>=0.135`，lock/镜像 import smoke 验证 |
| protected Live 成本和抖动 | 显式环境变量 gate、只跑一例、12 分钟、整份报告不重试、失败保留脱敏诊断 artifact |

## 12. Verification Direction

### 12.1 Engineering Contract for Plan Freezing

- Architecture/module ownership: report service owns real transitions and DB commits；application progress boundary owns typed facts/hub/snapshot projection；Router owns auth/SSE；frontend composable owns transport；reducer/store owns state；component owns rendering；Nginx owns proxy streaming。
- Interfaces/docstrings/types: `report-progress-v1` Python enum/dataclass/protocol/Pydantic 与 TypeScript discriminated union；public functions/classes/routes 使用符合仓库语言的 Google-style docstring/type annotations；字段、状态、终态和顺序规则文档化。
- Configuration/secrets/constants/prompts: 无新 secret/Prompt；token 只来自现有 auth store/header；timeout/backoff/heartbeat/reconcile/version 使用集中常量；FastAPI dependency minimum 与 lock 对齐。
- Terminal/logging/tracing/artifacts: 稳定字段至少含 `stage/task_id/report_id/status/elapsed_ms/transport/error_code`；不输出 token、Authorization、正文、Prompt、raw args/results/exception；Live artifact 保存 schema/version、阶段序列、耗时、hash。
- Validation/errors/retry/state: response 前 auth/ownership；unknown/malformed event fail closed 并 fallback；publisher best-effort notification 不改变任务结果；DB terminal authoritative；sequence/stage/progress/terminal 单调；SSE 不自动无限重连；polling 串行有界。
- Tests/evaluation/delivery evidence: D05-T01～T09 最小责任集；后端 unit/contract/route/service、前端 parser/reducer/lifecycle/component、Nginx/Compose timing、full pytest/lint/type/test/build、一条 protected Live、diff/security review、Issue #50、PR、CI、squash merge。

## 13. Deferred Work

- D06 Redis-backed snapshot/pub-sub/stream、跨 worker 广播、幂等提交、重复任务治理、TTL、跨刷新恢复和 `Last-Event-ID` replay。
- 持久化 report event table、完整阶段历史查询、任务取消/暂停/恢复、后台队列/Celery 迁移。
- 多 Uvicorn worker/多实例的实时一致性声明和故障切换。
- 报告正文 token streaming、增量 Markdown、局部报告重试和人工介入。
- 统一 chat/report 的通用 Agent event protocol 或 AG-UI SDK。
- Playwright 等新浏览器测试依赖；本轮以 Vitest、Compose HTTP stream 和人工/现有浏览器能力验收。
- 修复 `/status` 对非所有者与不存在任务的历史差异若会破坏兼容；D05 只要求新 SSE 统一 404，并让 status 错误消息安全化。
- Docker Python 3.11 与根 `requires-python >=3.12` 的仓库级统一；除非本轮镜像验证证明它直接阻塞 D05，否则单独治理。

## 14. Handoff to Plan Freezing

Next step should use the Plan Freezing Skill and produce `PLAN.md`.

The plan should:

- follow selected option: Option B typed event accelerator + authoritative DB snapshot + FastAPI SSE + fetch/polling fallback。
- allow modules/files: report application/progress modules、`backend/services/agent_service.py`、`backend/routers/report.py`、report schemas/tests、`frontend/src/composables/useReport.ts`、report types/store/components/tests、Nginx SSE path、FastAPI dependency declarations、D05 docs/artifacts。
- forbid modules/files: Report schema/migrations、Redis implementation、chat D03/D04 contract、LangGraph topology、prompts、skills/tools/memory policies、auth storage、production secrets、unrelated user files。
- include required tests: D05-T01 protocol/projector；T02 true parallel stage/monotonic progress；T03 publisher race/slow subscriber/cleanup；T04 route auth/ownership/first frame/terminal；T05 parser/reducer；T06 lifecycle/fallback；T07 status compatibility；T08 Nginx/Compose；T09 one protected Live and existing regression。
- include required logs/metrics: task/report/stage/status/sequence/transport/elapsed/error_code、first-frame/terminal timing、poll error count、artifact hash；forbid content/Prompt/token/raw exception。
- include rollback strategy: no migration/new service；one feature branch and squash PR；backend/frontend/Nginx/dependency minimum reverted atomically；old polling code remains usable as fallback during implementation。
- preserve these constraints: DB is recovery authority；publisher non-blocking；progress monotonic；terminal committed before publish；pre-stream auth；one active observer；5-second first frame；15-second heartbeat；bounded polling；single protected Live；D06 boundaries。
- keep these external references in mind: FastAPI native SSE and cancellation；WHATWG event/comment semantics；Nginx buffering rules；Fetch ReadableStream/AbortController；Vue cleanup；historical branch concepts only, never its query-token/untyped implementation。
