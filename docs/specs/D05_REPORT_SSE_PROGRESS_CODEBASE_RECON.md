# CODEBASE_RECON.md

## 1. Reconnaissance Target

Requirement source:

- `docs/specs/D05_REPORT_SSE_PROGRESS_REQUIREMENT_SPEC.md`
- GitHub Issue #50：`[D05] Stream authoritative report progress with polling fallback`
- 用户冻结的 D05 目标：报告阶段优先通过 SSE 实时展示，SSE 不可用时对同一任务自动降级到既有轮询，不提前实现 D06 的 Redis 幂等、持久化快照和跨实例恢复。

Focus areas:

- 报告创建、后台执行、LangGraph 节点事件、数据库状态更新、状态查询、详情、历史与下载的完整调用链。
- SSE 可使用的权威状态来源、认证/任务所有权、终态、顺序、保活、断连和资源清理边界。
- 前端报告 transport、轮询生命周期、任务隔离、状态归并和进度组件。
- Nginx、Vite、Compose、离线 E2E、Protected Live 和 CI 的现有能力。
- D03/D04 已落地主链中可以复用的强类型事件、严格解析、单调 reducer、清理和脱敏模式。
- 历史 `Finance` 目录与远端 `feature/redis-integration-phase1` 中未合并的 SSE 实现，只作为行为和失败案例证据。

Out-of-scope reminders:

- 不在 D05 引入 Redis 状态、幂等键、跨实例 pub/sub、完整事件重放或持久化恢复；这些属于 D06。
- 不修改报告 Prompt、分析 Agent 分工、金融结论策略、数据库 Schema、登录协议或 D03/D04 对话流。
- 本阶段只读勘察，不运行测试、真实 API 或功能实现。
- 用户未跟踪的 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` 保持原样。

## 2. Project Overview

Project type: 模块化单体；Vue SPA 与 FastAPI API 通过同一 Nginx 入口交付，报告模式复用仓库内 LangGraph 多 Agent 运行时。

Languages: Python、TypeScript/Vue、SQL、Nginx/Compose YAML。

Frameworks: FastAPI、Starlette、SQLAlchemy Async、Pydantic v2、LangGraph/LangChain、Vue 3、Pinia、Axios、Vite、Vitest、Pytest。

Runtime / package manager: `pyproject.toml` 冻结 Python `>=3.12,<3.13` 并使用 uv；前端使用 Node 20/npm。生产 `docker/Dockerfile.backend` 当前仍以 Python 3.11 为基础镜像，与根项目声明存在版本差异。

Main service type: ASGI Web API；报告生成由 FastAPI `BackgroundTasks` 调用进程内异步函数执行。

Frontend/backend split: `frontend/` 负责页面、transport 和 UI；`backend/` 负责 HTTP/鉴权/持久化/任务调度；`Financial-MCP-Agent/src/agents/` 负责报告 Agent 节点。

Test framework: Pytest/Unittest、Vitest、FastAPI TestClient、隔离 PostgreSQL/Redis 的 Compose E2E。

Deployment clues: 生产 Compose 的 Uvicorn 命令未设置多 worker，当前镜像是单进程；Nginx `/api/` 统一代理且读取超时为 300 秒，但未关闭代理缓冲，也没有报告 SSE 专用 location。

Confirmed facts:

- 当前主线不存在 `StreamingResponse` 报告入口，也不存在前端报告 SSE consumer；报告页只轮询 `/api/report/status/{task_id}`。
- `reports` 表是现有权威任务记录，保存 `task_id/status/progress/content/error_msg`，但不保存公开阶段、事件序号、更新时间或传输状态。
- 后台任务消费真实 `app.astream_events(...)`，在若干 LangGraph 节点结束时写数据库进度，并最终保存 Markdown 正文或失败状态。
- Docker 与本地开发代理都把 `/api` 转发到 FastAPI；当前生产 Uvicorn 配置为单 worker。
- 默认 CI 已覆盖 Python、前端、Compose 配置和 Offline Compose E2E，但离线 E2E 没有报告旅程。
- 远端 `feature/redis-integration-phase1` 的 commit `8ef46f0` 包含旧 SSE hooks，但不属于 `origin/main`，也没有对应 GitHub PR。

Assumptions:

- D05 可以继续以现有 `reports` 行作为跨请求权威状态，而不新增 Schema；具体事件投影方式需在后续 Clarification/Tradeoff 冻结。
- “EventSource-compatible”解释为标准 SSE wire format；由于现有认证使用 Bearer header，浏览器 consumer 预计需要支持请求头的 `fetch` 流读取，而不是原生 `EventSource` query token。

## 3. Directory Structure Summary

| Path | Apparent role | Relevance | Notes |
| --- | --- | --- | --- |
| `backend/routers/report.py` | 报告 HTTP 协议、认证、所有权和响应映射 | 核心 | 当前直接调度后台任务并读取 ORM。 |
| `backend/services/agent_service.py` | 报告工作流编译、初始状态、后台执行和状态写入 | 核心 | 一个文件同时拥有 workflow factory、state builder、runner 与外部日志生命周期。 |
| `backend/schemas/report.py` | 报告公开 REST Schema | 核心 | 状态和进度仍为宽泛 `str/int`，无 SSE 协议模型。 |
| `backend/db/models.py` | `Report` 持久化模型 | 核心权威状态 | 无阶段、sequence、updated_at；D05 禁止迁移。 |
| `frontend/src/composables/useReport.ts` | 报告创建、轮询、详情和本地状态 | 核心 | 单个 composable 内用 `setInterval` 轮询，无 cleanup。 |
| `frontend/src/api/index.ts` | Axios、Bearer header 与前端 API 类型 | 核心 | Axios 拦截器会注入 Bearer；独立 fetch 需显式复用安全 token 读取。 |
| `frontend/src/views/ReportView.vue` | 报告页面入口和视图切换 | 核心 | 仅 `onMounted`，没有 `onUnmounted`。 |
| `frontend/src/components/report/ReportProgress.vue` | 百分比与五步展示 | 核心 UI | 通过固定阈值从数字推断步骤，不接收权威阶段。 |
| `docker/nginx/default.conf` | 生产前端和 `/api` 反代 | 核心部署 | 未关闭 SSE buffering；通用 300 秒 read timeout。 |
| `tests/e2e/offline_app.py` | Compose 离线测试应用装配 | 测试核心 | 只替换聊天外部 Ports，未为报告提供确定性运行时。 |
| `tests/e2e/test_offline_compose_stack.py` | 生产前端/Nginx/FastAPI/PostgreSQL HTTP 旅程 | 测试核心 | 当前无报告创建、状态、SSE 或下载断言。 |
| `tests/e2e/test_live_controlled_chat_chain.py` | 显式真实模型/只读数据与脱敏 artifact 模式 | Live 参考 | 当前只覆盖聊天，可复用保护开关、隔离 DB、计数、hash 和 artifact 约束。 |
| `backend/application/chat/`、`backend/routers/chat.py` | D03/D04 协议无关事件流与 WebSocket 映射 | 模式参考 | 已有 typed events、sequence、唯一终态、背压、断连清理和安全投影。 |
| `D:/FinanceProject/Finance/backend/services/report/` | 历史报告 SSE/Redis 实现 | 历史证据 | 不是运行时依赖，不可 import 或整体复制。 |

## 4. Entry Points

### 4.1 Startup Entry

Confirmed:

1. `docker/Dockerfile.backend` 使用 `uvicorn backend.main:app --host 0.0.0.0 --port 8000` 启动单进程服务。
2. `backend/main.py` 的 lifespan 初始化数据库、可选 Memory Redis/Worker 和 Trace，然后注册 `report.router` 到 `/api/report`。
3. 生产前端由 Nginx 提供静态文件，并把 `/api/` 代理到 `backend:8000`；Vite 开发服务器采用同一路径代理。
4. `frontend/src/main.ts` 挂载 Vue 应用，路由 `/report` 进入 `ReportView.vue`。

### 4.2 Request / Task Entry

Confirmed current request entry:

1. `ReportView.handleGenerate()` 调用 `useReport.generateReport(command)`。
2. `reportApi.generate()` 经 Axios `POST /api/report/generate`，拦截器从 localStorage 读取 Bearer token。
3. `generate_report()` 校验 `body.user_id` 与 `AuthContext`，创建 `pending/0` 的 `Report` 行，把 `run_report_task()` 注册为 `BackgroundTasks`，返回 `task_id/report_id`。
4. 前端拿到任务后只启动每 2 秒一次的 `setInterval`，请求 `/api/report/status/{task_id}`。
5. `run_report_task()` 把状态置为 `running/10`，解析标的后写 `20`，消费 LangGraph 节点结束事件写若干固定进度，最后写 `completed/100/content` 或 `failed/0/error_msg`。
6. 前端在 `completed` 后请求 `/api/report/{report_id}` 并显示 Markdown；历史、客户端 Blob 下载和删除使用既有 REST API。

Not found:

- 报告 SSE 路由、公开事件 Schema、服务端保活、前端 SSE parser、transport 状态或报告 stream cleanup。

## 5. Relevant Call Chain

```text
ReportView.handleGenerate(command)
-> useReport.generateReport(command)
-> reportApi.generate(command, user_id)
-> POST /api/report/generate + Authorization: Bearer ...
-> report router: require_auth -> ensure_user_access -> ensure User
-> INSERT reports(task_id, report_id, status=pending, progress=0)
-> FastAPI BackgroundTasks.add_task(run_report_task)
-> ReportTaskResponse(task_id, report_id, pending)
-> frontend _startPolling() / every 2 s
-> GET /api/report/status/{task_id}
-> SELECT Report by task_id -> owner check -> ReportStatusResponse

run_report_task(task_id, report_id, command, user_id)
-> initialize_execution_logger()
-> UPDATE Report running/10
-> _build_initial_state() -> resolve_stock() -> AgentState
-> UPDATE Report stock/company/progress=20
-> _get_workflow(): start -> 4 parallel analysts
-> optional memory/STM nodes -> summarizer -> optional memory write -> END
-> app.astream_events(initial_state)
-> selected on_chain_end -> UPDATE Report fixed progress
-> root state -> final_report/report_path
-> execution artifact + UPDATE Report completed/100/content
   OR exception -> UPDATE Report failed/0/raw error_msg

polling observes completed
-> GET /api/report/{report_id}
-> Markdown renderer / local Blob download / history refresh
```

Confirmed segments:

- HTTP、鉴权、报告 ORM、BackgroundTasks、LangGraph event stream、最终正文与前端轮询的每一段都已在代码中找到直接证据。
- 后端节点进度表为 analyst `35/50/65/80`、memory read `85`、summarizer `95`、memory write `98`；表中节点只有在识别到指定 `on_chain_end` 时写入。
- `ReportProgress.vue` 当前以 `20/40/55/70/90` 阈值推断“基本面/技术面/估值/新闻/汇总”，与后端节点进度表不是同一合同。

Inferred segments:

- 四个 analyst 并行结束，`_update_report(progress=固定值)` 没有 max/CAS 保护，因此较晚完成但固定值更小的节点可以把数据库进度回退。
- LangGraph event 解析优先使用 `event.name`，只有 name 为空才使用 `metadata.langgraph_node`；若运行时 name 是函数名而 metadata 才是图节点名，部分权威节点进度会被漏掉。
- `setInterval(async ...)` 不等待上一轮结束；状态请求超过 2 秒时可能并发重叠并以到达顺序覆盖 UI。

Unknown segments:

- 当前锁定 LangGraph 版本在真实报告中的确切 event name/metadata 组合与四个并行节点完成顺序，现有测试只覆盖根图最终状态提取。
- 当前 Nginx buffering 下长响应能否逐事件及时到达浏览器；必须由后续 Compose 验收证明。
- 真实报告一次执行的稳定模型/工具调用次数、总耗时和费用上限；Protected Live 需要先加审计计数和总超时。

## 6. Related Files

### 6.1 Definitely Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/routers/report.py` | 报告 HTTP 边界 | 新 SSE 入口、认证、所有权、响应头和断连都在此映射 | Candidate modification | High |
| `backend/schemas/report.py` | REST/SSE 公开合同 | 需要有限状态、阶段、事件 envelope 和安全错误 | Candidate modification | Medium |
| `backend/services/agent_service.py` | 权威工作流事件与状态写入 | 当前唯一真实节点事件源，并存在进度回退/原始错误问题 | Candidate modification or narrow extraction | High |
| `backend/db/models.py` | 报告权威持久化 | 证明可用字段和 D05 无 Schema 边界 | Read-only unless later evidence expands scope | High |
| `frontend/src/api/index.ts` | 前端公共类型与认证 token 来源 | 需要 SSE 类型/transport 调用，不能把 token 放 URL | Candidate modification | Medium |
| `frontend/src/composables/useReport.ts` | 报告连接和轮询所有权 | 需要主 SSE、显式 fallback、单调归并与清理 | Candidate modification/refactor | High |
| `frontend/src/views/ReportView.vue` | 页面生命周期 | 需要卸载、任务切换和 fallback UI 绑定 | Candidate modification | Medium |
| `frontend/src/components/report/ReportProgress.vue` | 用户进度展示 | 当前固定阈值不是权威阶段 | Candidate modification | Medium |
| `docker/nginx/default.conf` | SSE 代理传输 | 当前 buffering/connection header 不适合证明实时 flush | Candidate modification | High |
| `tests/e2e/offline_app.py` | 确定性完整应用装配 | 报告外部模型/工具必须替换，HTTP/Application/LangGraph/DB 保持真实 | Candidate modification | Medium |
| `tests/e2e/test_offline_compose_stack.py` | Compose HTTP E2E | 需证明 Nginx 下 SSE 主路径、fallback 和最终报告 | Candidate modification | Medium |
| `.github/workflows/ci.yml` | 默认交付门禁 | 后续新增 report 触达路径和测试命令可能需要纳入静态检查 | Candidate modification | Medium |
| `.github/workflows/live-e2e.yml` | Protected Live | D05 要增加显式真实报告 job/test | Candidate modification | High |

### 6.2 Probably Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/config.py` | typed Settings | 只有证明需要时才增加最少保活/观察间隔/Live timeout 配置 | Candidate modification | High |
| `backend/.env.example` | 安全部署文档 | 若新增可部署设置需同步安全示例 | Candidate modification | Medium |
| `backend/db/database.py` | Session factory | 长连接不能长期占用请求 Session；状态观察可能需短会话 | Candidate use, likely no modification | High |
| `Financial-MCP-Agent/src/utils/state_definition.py` | 报告 AgentState | 离线 LangGraph fake 节点和真实输出结构需要保持兼容 | Read-only | Medium |
| `Financial-MCP-Agent/src/utils/execution_logger.py` | 报告运行 artifact | Live 验收需隔离并避免正文进入提交 artifact | Candidate patch only if necessary | High |
| `frontend/src/router/index.ts`、`frontend/src/stores/authStore.ts` | 路由/退出登录 | 连接必须随页面与登录生命周期关闭 | Candidate inspection/test | High |
| `frontend/vite.config.ts` | 开发代理 | 需要验证本地 SSE 透传；通常无需改动 | Candidate verification | Low |
| `docker/docker-compose.offline.yml` | 隔离运行环境 | 需要确定性报告开关、artifact 路径或服务环境 | Candidate modification | Medium |
| `backend/test_agent_service.py` | 根图 event 解析回归 | 可扩展工作流进度/唯一执行保护 | Candidate modification | Medium |
| `backend/test_report_download.py` | 既有下载兼容 | 必须保持通过 | Regression only | Low |

### 6.3 Supporting Context

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/application/chat/use_case.py` | 协议无关事件和背压 | 展示 Application-owned stream、唯一终态和取消传播模式 | Reuse pattern, not code coupling | Medium |
| `backend/routers/chat.py`、`backend/schemas/chat.py` | D03/D04 typed stream | 展示 Pydantic envelope、sequence、安全投影、断连清理和结构化日志 | Reuse pattern | Medium |
| `frontend/src/composables/useChat.ts` | 严格 parser 与连接 cleanup | 展示 task/request 隔离、sequence 校验和终态收口 | Reuse pattern | Medium |
| `frontend/src/stores/chatStore.ts` | 单调 reducer | 展示终态不回退、旧请求事件隔离 | Reuse pattern | Low |
| `tests/e2e/test_live_controlled_chat_chain.py` | Protected Live 合同 | 展示显式开关、隔离 SQLite、调用计数、hash 和脱敏 artifact | Reuse test pattern | High |
| `D:/FinanceProject/Finance/backend/services/report/*` | 历史实现 | 证明曾尝试 SSE/Redis，但暴露边界缺陷 | Read-only evidence | High |
| commit `8ef46f0` | 未合并旧实现 | 包含 SSE location、heartbeat、listener cleanup 等局部思路 | Selective reference only | High |

### 6.4 Out of Scope

| Path / Area | Reason |
| --- | --- |
| `backend/infrastructure/memory/redis_cache.py` 与当前 Memory Redis | D05 不复用 Memory 热缓存承载报告真相或广播；报告 Redis 属于 D06。 |
| 数据库 migrations 和 `Report` 新字段 | Requirement 明确禁止 D05 Schema 迁移。 |
| `Financial-MCP-Agent/src/agents/*` Prompt、模型与工具策略 | D05 只投影已有权威阶段，不重写报告研究逻辑。 |
| `backend/routers/chat.py` 和 D03/D04 前端业务代码 | 只复用工程模式，不修改聊天协议。 |
| Skills、STM/LTM、Portfolio 和 Auth 协议 | 只做回归，不扩大 D05 功能边界。 |
| 历史 `Finance` 仓库运行时 | 只能提供证据，不能加入 import、依赖或生产镜像。 |

## 7. Existing Patterns to Reuse

| Pattern | Example file | Why reuse it |
| --- | --- | --- |
| Pydantic 有版本的公开 envelope、关联 ID 和正序 sequence | `backend/schemas/chat.py` | 防止匿名字典、乱序和前后端协议漂移。 |
| API 只做协议映射，Application 拥有事件生命周期 | `backend/routers/chat.py`、`backend/application/chat/use_case.py` | 避免 SSE/Request 对象侵入报告工作流。 |
| 唯一终态、断连竞争、确定性取消/关闭上游 | `backend/routers/chat.py` | 防止生成器、监听任务和连接泄漏。 |
| 严格运行时 parser、关联 ID/sequence 检查 | `frontend/src/api/index.ts`、`frontend/src/composables/useChat.ts` | malformed/跨任务事件应触发安全 fallback，而不是污染 UI。 |
| 终态不回退、旧请求不覆盖新请求 | `frontend/src/stores/chatStore.ts` | 报告 SSE 与轮询必须汇聚到一个单调 reducer。 |
| typed Settings 单入口与安全 `.env.example` | `backend/config.py`、`backend/.env.example` | 仅在确有部署差异时增加最少参数。 |
| 生产前端 + Nginx + 真 FastAPI + PostgreSQL，外部 Ports 用 fake | `tests/e2e/offline_app.py`、`docker/docker-compose.offline.yml` | 可证明完整入口和持久化，同时保持默认零费用。 |
| 显式 Live 开关、隔离 DB、调用计数、hash、脱敏 artifact | `tests/e2e/test_live_controlled_chat_chain.py` | 防止伪 Live、费用失控和秘密/正文进入证据。 |
| SSE 专用 `proxy_buffering off` 与 `X-Accel-Buffering: no` | 历史 commit `8ef46f0` | 可作为代理配置线索，但必须重新实现和 Compose 验证。 |

历史实现不能整体复用，Confirmed reasons:

- 它把长期 JWT 写入 SSE query string，违反当前安全约束。
- 它用 `dict[str, Any]`、无协议版本/sequence 的进程内 queue 传输状态。
- 它把 Redis 幂等、Redis 状态、SSE 和管理接口合成约 8000 行单提交，跨越 D05/D06 边界。
- 前端直接 `JSON.parse as ReportStatusResponse`，没有严格字段校验、任务关联校验、显式 fallback 状态或卸载 cleanup。
- 旧分支基于当前主线之前的备份历史，缺少后来 D03/D04、Memory 与受控主链提交，且从未创建 PR。

## 8. Data Flow and State

### 8.1 Input Data

- `ReportGenerateRequest.command`: 用户自然语言报告指令，当前只有必填字符串，无长度/空白边界。
- `ReportGenerateRequest.user_id`: 客户端携带用户 ID，后端通过 Bearer token 的 `AuthContext.user_id` 比对。
- `task_id/report_id`: 后端 UUID 字符串；路径参数当前仍是未校验的 `str`。

### 8.2 Intermediate State

- `AgentState.data`: query、时间、company/stock、四类分析、最终正文等；属于内部敏感运行状态，不能进入 SSE。
- `finished_nodes`: 仅当前 `run_report_task()` 内存中的去重集合，不持久化。
- `node_progress`: 节点名到固定百分比映射；不是公开 typed contract。
- 前端 `taskId/reportId/status/progress/report/errorMsg/isGenerating` refs；没有 transport mode、last sequence、active task generation 或 cleanup handle 的公开状态。

### 8.3 Persistent State

`Report` 当前保存：

- `id`, `task_id`, `user_id`, optional `session_id`
- `stock_code`, `company_name`, `content`
- `status`: 注释约定 `pending/running/completed/failed`
- `progress`: 0–100 的约定值，但数据库和 Pydantic 没有范围约束
- `error_msg`: 当前写入原始异常字符串
- `created_at`

Not found: `current_stage`、`sequence`、`updated_at`、heartbeat、SSE cursor、idempotency key、任务 lease 或事件表。

### 8.4 Output Data

- 创建响应：`task_id/report_id/status`。
- 状态响应：`task_id/status/progress/report_id?/error_msg?`。
- 详情响应：包含最终 Markdown 全文和基础元数据。
- 历史列表：最多 50 条，可按公司/代码内存过滤。
- 下载：HTTP Markdown 响应以及前端从已获取正文生成的 Blob。
- Current Not found: SSE frame、阶段标签、transport mode/fallback reason、事件序号和安全错误码。

### 8.5 Potential Data Mismatch Points

1. 后端节点进度 `35/50/65/80/...` 与前端 UI 阈值 `20/40/55/70/90` 各自定义，页面步骤不是同一个权威合同。
2. 并行 analyst 直接写固定百分比可能回退；失败又强制回到 0，当前没有单调状态规则。
3. `event.name or metadata.langgraph_node` 可能漏认节点；缺少真实 LangGraph event characterization。
4. 状态 API 和 SSE 若各自定义投影，将产生两套终态/错误语义；后续必须共享同一 snapshot projector。
5. 现有状态 API 把 `str(exc)` 原样返回 `error_msg`，可能暴露 Provider、路径、Prompt 或内部异常。
6. 状态/详情路由先按 task/report 查询，再做 owner check；“存在但属于别人”返回 403，“不存在”返回 404，可泄露资源存在性。
7. 前端 async `setInterval` 可能重叠，迟到响应能覆盖新状态；轮询错误被无限吞掉，页面可永久停留在生成中。
8. `loadReport()` 不停止正在运行的轮询；用户查看历史报告后，旧生成任务的迟到状态可再次覆盖当前页面。
9. 页面只有 `onMounted`，卸载、退出登录或路由切换时没有停止轮询；D05 若照搬旧 SSE 还会增加连接泄漏。
10. `run_report_task()` 在找不到 root final state 时再执行一次 `ainvoke()`；现有测试只证明常见 root event 可提取，未证明所有支持版本不会产生重复模型/工具执行。
11. `ExecutionLogger` 是全局运行时，而报告 API 没有 D06 重复提交/任务治理；并发报告可能产生 artifact/全局状态竞争，D05 只能记录风险，不能偷做幂等治理。

## 9. External Dependencies

| Dependency | Where called | Input | Output | Error handling / fallback |
| --- | --- | --- | --- | --- |
| SQLAlchemy async DB (SQLite/PostgreSQL) | report router、`run_report_task` | 用户/任务/状态/正文 | 权威 `Report` 行 | 任务异常写 `failed`；状态查询 DB 失败无专门安全映射。 |
| LangGraph | `backend/services/agent_service.py` | `AgentState` | 节点 events 与 final state | 无 events 时 `ainvoke`; root state 缺失时再次 `ainvoke`。 |
| OpenAI-compatible model | 四个 Agent 与 summarizer | Prompt/工具上下文 | 分析与最终报告 | Agent 内部自行捕获部分异常；顶层最终归为 raw failed。 |
| MCP/A 股数据服务 | 报告 analyst nodes | 标的和查询 | 金融工具结果 | 节点可产生错误文本/最小结果；顶层只验证 `final_report` 非空。 |
| Memory/STM nodes | `_get_workflow()` feature flags | user_id/AgentState | 个性化上下文/写回 | 动态图形随设置变化，公开阶段不能假设所有节点必定存在。 |
| JWT Bearer auth | `AuthMiddleware`/`require_auth` | Authorization header | `AuthContext` | 缺失/无效 401，跨用户 403；原生 EventSource 无法设置 header。 |
| Nginx/Vite proxy | `/api` | HTTP 长连接 | 浏览器响应流 | 当前 Nginx 无 SSE buffering 配置；300 秒后会超时。 |
| Browser streaming API | Future frontend transport | Bearer header + task id | SSE text chunks | 浏览器 `fetch` 原生支持 header/AbortController；仓库暂无 parser/实现。 |
| Redis | 当前只用于 Memory 热缓存 | Memory keys | 可丢弃缓存 | 报告 D05 禁止依赖；D06 单独设计。 |

## 10. Tests and Evaluation Assets

### 10.1 Existing Tests

- `backend/test_agent_service.py`: 仅验证 `LangGraph` 根结束事件提取和普通节点事件忽略。
- `backend/test_report_download.py`: 仅验证中文下载文件名和 header 注入防护。
- `tests/contract/test_api_contract.py`: 健康和聊天 REST 合同；无报告合同。
- `frontend/src/composables/__tests__/useChat.streaming-v2.spec.ts`: 可参考连接、sequence、协议错误和页面退出测试方式。
- `frontend/src/stores/__tests__/chatStore.controlled-execution.spec.ts`: 可参考单调终态和旧请求隔离。
- `tests/e2e/test_offline_compose_stack.py`: 真 Nginx/FastAPI/PostgreSQL，但当前只覆盖 chat/memory。
- `tests/e2e/test_live_controlled_chat_chain.py`: 真实模型/只读 Tushare 的保护模式，但当前没有真实报告测试。
- 历史 `Finance/backend/tests/test_report_sse.py`: 只验证旧内存生成器、token query 和简单完成事件，不能作为 D05 验收。

### 10.2 Coverage Gaps

- 无报告创建/状态/详情/history 的完整 API 合同和 owner negative cases。
- 无真实 LangGraph 节点 event shape、并行完成顺序、进度单调和唯一执行测试。
- 无 SSE wire 格式、headers、初始快照、业务阶段、heartbeat、终态、断连 cleanup 测试。
- 无 frontend strict parser、同任务 reducer、初始/中途失败 fallback、无重复 POST、timer/AbortController cleanup 测试。
- 无 Nginx buffering/逐事件时序证明。
- Offline Compose 没有报告 fake external ports 或最终 `Report` DB 断言。
- 无 protected real report test、调用预算、总超时和脱敏 artifact。

### 10.3 Candidate Test Locations

- `tests/unit/report/test_progress_contracts.py`: 有限阶段、状态转换、投影脱敏、sequence/终态。
- `tests/contract/test_report_stream_contract.py`: 认证/所有权、安全 404、SSE headers/wire/heartbeat/终态。
- `tests/integration/test_report_progress_stream.py`: 隔离 DB 中工作流写入与 SSE/轮询同一 snapshot。
- `backend/test_agent_service.py`: 真实 event shape characterization、单调进度和不重复执行。
- `frontend/src/api/__tests__/reportStreamingContract.spec.ts`: 严格 parser 和未知字段/乱序拒绝。
- `frontend/src/composables/__tests__/useReport.streaming.spec.ts`: SSE 主路径、首连/中途错误 fallback、无二次 generate、任务切换和 cleanup。
- `tests/e2e/offline_app.py` + `tests/e2e/test_offline_compose_stack.py`: 真 LangGraph 装配 + deterministic Agent nodes、Nginx SSE 与 fallback 两条旅程。
- `tests/e2e/test_live_report_progress_chain.py`: 一条显式真实模型 + 只读金融数据报告。

### 10.4 Visible Test Commands

Repository-declared order:

```powershell
uv lock --check
uv run --locked ruff check <frozen touched paths> tests
uv run --locked pyright <frozen touched paths> tests
uv run --locked pytest <focused D05 tests> -q
uv run --locked pytest backend -q
uv run --locked pytest Financial-MCP-Agent -q -m "not live"
uv run --locked pytest -q
Set-Location frontend
npm.cmd ci
npm.cmd run lint -- --quiet
npm.cmd run type-check
npm.cmd run test -- --run
npm.cmd run build
Set-Location ..
docker compose -f docker/docker-compose.yml config --quiet
docker compose -f docker/docker-compose.offline.yml config --quiet
docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e
docker compose -f docker/docker-compose.offline.yml down -v --remove-orphans
```

Protected Live 必须使用单独显式开关和 D05 专用测试文件；本阶段未运行任何命令。

## 11. Logging and Observability

### 11.1 Existing Logs

- `run_report_task()` 在开始、标的解析、完成和失败时记录 `task_id`，并创建 ExecutionLogger artifact。
- LangGraph Agent 各自记录模型、MCP 和输出信息；部分仍使用 f-string/`print`，格式与脱敏不统一。
- 状态每次写数据库时没有稳定 `stage/status/elapsed_ms/error_code` 结构化日志。
- 当前没有 SSE connected/disconnected/heartbeat/terminal 或前端 fallback 观测。

### 11.2 Missing Logs

- `report.progress.stream` 的 connection id/task id、transport、stage、sequence、status、elapsed_ms、disconnect reason。
- `report.progress.fallback` 的 reason、同 task 关联和收口结果。
- 工作流节点到公开阶段的稳定低基数映射记录。
- 唯一终态、终态后事件丢弃、malformed/late event 计数。
- 原始异常到安全 `error_code` 的内部/公开分离。

### 11.3 Observability Risks

- `error_msg=str(exc)` 同时落库并公开，可能泄露敏感上下文。
- 若日志直接打印 SSE data，会泄露用户、异常或报告内容；事件必须白名单投影。
- 当前部分报告 Agent 会日志或 `print` 完整 Agent 输出，不能把这些既有内部输出复用为 SSE 数据源。
- 无 task-level updated_at/sequence 持久化；D05 的连接级 sequence 不能被表述为 D06 级断线重放能力。
- 前端轮询异常完全吞掉，用户和日志都无法知道 transport 已经失效。

### 11.4 Output-channel Separation

| Channel | Current implementation | Stable fields / format | Redaction | Gaps |
| --- | --- | --- | --- | --- |
| User/API result | REST task/status/detail/Markdown | `task_id/status/progress/report_id/error_msg` | Partial | raw `error_msg`；无阶段/错误码/transport。 |
| Terminal progress | Agent 和 backend `print` | 自由文本 | Missing | 可能含完整分析；不适合作公开进度源。 |
| Logs | module logger + ExecutionLogger | 部分含 task id | Partial | 无统一 stage/status/elapsed/error_code；部分完整输出。 |
| Traces | 报告 ExecutionLogger，聊天另有 typed Trace | execution id/artifacts | Partial | 报告进度与 SSE/fallback 尚不能关联。 |
| Artifacts | final report、execution logs、Live chat JSON | 文件路径/报告正文/hash | Mixed | D05 Live 需要只提交低敏 hash/计数，不提交报告全文。 |

## 12. Engineering Baseline Recon

| Area | Status | Evidence | Gap / implication |
| --- | --- | --- | --- |
| API/orchestration/domain/infrastructure boundaries | Partial | Router 调 `run_report_task`，DB/Agent 分属模块 | `agent_service.py` 同时拥有 graph、state、persistence、artifact；报告无 Application/Port。 |
| Agent/workflow/tool/prompt/model/memory/evaluation boundaries | Partial | Agent 节点和 LangGraph 明确；配置控制 STM/LTM | 报告节点直接构建模型/MCP，离线替身和进度 observer 边界不明确。 |
| Docstrings, types, and key intent comments | Partial | 现有公共函数有部分 docstring/typing | report schemas 用宽泛 str/int；`_update_report(**kwargs)` 无类型；旧风格注释较多。 |
| File-section navigation vs module separation | Partial | 路由/服务使用稳定章节 | `agent_service.py` 责任过多；历史拆分不能直接搬入。 |
| Typed configuration and secret handling | Established | `Settings` + `.env.example` + Axios Bearer | SSE 需要安全 header transport；禁止旧 query token。 |
| Error, retry, fallback, and state semantics | Missing | 当前只有轮询偶发错误静默继续 | 无 SSE fallback、轮询终止预算、单调进度、安全错误码、唯一终态合同。 |

## 13. Risk Areas

| Area | Why risky | Likely touched? | Recommended handling |
| --- | --- | --- | --- |
| JWT/任务所有权 | 流式认证错误可造成 token 泄露或跨用户报告探测 | Yes | 保持 Bearer header；单查询 owner scope；负向 contract；绝不 query token。 |
| 报告数据库状态 | SSE 与 polling 必须读取同一真相且不迁移 Schema | Yes | 最小写入改动；事务后投影；D05 不引入双写缓存。 |
| 并行工作流进度 | 节点乱序可回退或漏事件 | Yes | 先 characterization；冻结单调聚合，不按完成顺序伪造阶段。 |
| 外部模型/MCP | 真实报告昂贵、慢且可能部分失败 | Yes | 默认 fake；Live 一任务、只读、超时、调用计数、隔离 DB。 |
| SSE 长连接 | 代理缓冲、断连、Session/生成器泄漏 | Yes | 专用 headers/Nginx；短 DB session；disconnect/abort cleanup tests。 |
| 前端 transport 竞态 | SSE、polling、历史切换和卸载会互相覆盖 | Yes | 一个 task-scoped reducer；AbortController + serial polling；终态锁。 |
| 公开错误与日志 | 当前 raw exception 和 Agent output 可能泄密 | Yes | 固定 error code/message；详细异常只留脱敏内部日志。 |
| 历史 SSE 分支 | 代码过时且混合 D05/D06 | No direct reuse | 只复用验证过的局部思路，重新实现并测试。 |
| Redis/幂等/多实例 | 容易把 D06 偷渡进 D05 | No | 这一领域 D05 保持只读；需要时停止并进入 D06。 |
| Nginx production config | 错误 header/buffering 会让单测绿但产品无实时效果 | Yes | Compose 下验证事件到达时序和 fallback。 |

## 14. Unknowns and Assumptions

### 14.1 Unknowns From Missing Code Access

- None. 当前仓库、Git 历史和本地历史 `Finance` 报告相关代码均可读；未读取真实 `.env`、生成报告正文和日志内容，以避免秘密/隐私暴露。

### 14.2 Unknowns From Incomplete Requirement

- 公开阶段最终选择 4、5 还是更多个，以及并行 analyst 是否展示为一个聚合阶段或四个独立步骤。
- fallback 提示需要持久展示到终态还是只显示一次；Requirement 只要求用户可观察。
- SSE 首事件/空闲/总连接等待的具体时间预算。
- D05 是否同步收敛旧 `/status` 的跨用户存在性和 raw error 暴露，还是只保证新 SSE 并另立兼容修复；从安全验收看建议同一 snapshot projector 一并收敛。

### 14.3 Unknowns From Ambiguous Architecture

- D05 是直接把 workflow events 送入进程内 observer，还是由 SSE 观察 `reports` 权威行变化。前者延迟低但当前多请求/多 worker 不可靠，后者不新增 D06 基础设施但属于服务端短周期状态观察。
- 不新增持久化阶段字段时，阶段是从已有进度映射，还是在单进程内保留非权威细粒度事件。只有前者可在当前 DB 上跨请求一致，后者不得宣称恢复能力。
- `astream_events` 在锁定版本中的 node name 必须由后续 characterization 测试确认。

### 14.4 Assumptions

- D05 的可靠底线优先于最低延迟：SSE 丢失或协议错误时必须立即转为同任务 REST polling。
- 连接级 sequence 足以防止当前页面乱序；跨连接 replay/cursor 由 D06 承担。
- 公开阶段只表达稳定用户价值阶段，不暴露 Agent 函数名、Prompt、工具参数或原始输出。
- 现有生产单 worker 是 D05 可验证环境，但实现不应以未声明的进程内 queue 作为唯一真相。

## 15. Handoff to Next Step

Next step should use the Requirement Clarification Skill and produce `D05_REPORT_SSE_PROGRESS_CLARIFICATION_QUESTIONS.md`.

It should clarify:

- 公开阶段采用稳定聚合阶段还是四个 analyst 独立状态；默认候选为 `QUEUED/PREPARING/ANALYZING/SYNTHESIZING/FINALIZING/COMPLETED/FAILED`，并允许 feature-flag 节点归并。
- D05 在无 Schema/Redis 的前提下，是否以 `reports` 权威 snapshot 的服务端观察作为 SSE 来源，以避免进程内 queue 成为真相；D06 再替换为 durable snapshot/pub-sub。
- 使用带 Bearer header 和 AbortController 的 fetch-SSE consumer，并保持标准 SSE wire format；明确拒绝原生 EventSource query token。
- sequence 只保证单连接递增；重连先发当前权威 snapshot，不承诺历史 replay，然后继续 SSE 或 fallback polling。
- 旧状态 API 的 raw `error_msg` 和 403/404 资源探测是否在 D05 同步收敛到共享安全 projector。
- fallback UX、首事件超时、heartbeat、观察间隔、总等待与轮询退避/终止预算的具体默认值。
- 并行进度的单调规则以及失败时是否保留最后进度而不是回到 0。
- Protected Live 的单任务预算、总超时、允许的只读工具、期望调用计数和 artifact 字段。
- 历史 `8ef46f0` 明确作为 rejected baseline，仅允许复用 SSE header/heartbeat/listener cleanup 的概念。

It should consider these files/modules in later solution design:

- `backend/routers/report.py`
- `backend/schemas/report.py`
- `backend/services/agent_service.py`
- 新的、边界清晰的 `backend/application/report/`（是否创建由 Tradeoff 决定）
- `frontend/src/api/index.ts` 或独立 report streaming transport
- `frontend/src/composables/useReport.ts`
- `frontend/src/views/ReportView.vue`
- `frontend/src/components/report/ReportProgress.vue`
- `docker/nginx/default.conf`
- D05 unit/contract/integration/frontend/Compose/Live 测试资产

It should require explicit user approval before modifying these high-risk areas:

- `backend/db/models.py` 或任何 migration（当前默认禁止）。
- JWT 协议、token 存储或 Auth middleware 的兼容行为。
- Redis、幂等、跨实例状态或持久化恢复（必须转入 D06）。
- 报告 Prompt、真实模型/工具策略和生产部署 worker 拓扑。
- 超出一条受保护报告任务的真实付费/外部调用。
