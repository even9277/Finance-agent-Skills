# PLAN.md

## 1. Plan Metadata

- Plan name: D05 报告真实 SSE 进度、受控降级与全链路验收
- Task type: 跨前后端 Agent 报告流式可观测性、可靠性与测试增强
- Status: Frozen for implementation review
- Target executor: Codex / Cursor / Claude Code
- Related artifacts:
  - `docs/specs/D05_REPORT_SSE_PROGRESS_REQUIREMENT_SPEC.md`
  - `docs/specs/D05_REPORT_SSE_PROGRESS_CODEBASE_RECON.md`
  - `docs/specs/D05_REPORT_SSE_PROGRESS_CLARIFICATION_QUESTIONS.md`
  - `docs/specs/D05_REPORT_SSE_PROGRESS_SOLUTION_TRADEOFF.md`
- Repository root: `D:\FinanceProject\Finance-agent-Skills`
- Current branch: `feat/50-report-sse-progress`（tracking `origin/main`，Issue #50）
- Created date: 2026-09-04

## 2. User-facing Purpose

完成后，用户在创建投研报告后应立即看到由真实后台执行产生的阶段变化和单调百分比；正常路径通过 SSE 低延迟到达，连接不可用时明确切到串行、有界退避的 polling，最终仍从数据库收敛到成功或失败。用户切换报告、离开页面、登出或任务结束时不会遗留连接和定时器。

当前问题是报告页只每 2 秒异步轮询一次，首次反馈慢、请求可重叠、错误会无限静默重试、组件卸载不清理；UI 用固定百分比阈值猜测阶段。后端虽然运行真实 LangGraph 节点，但固定 node→progress 映射会在四分析器乱序完成时回退，没有稳定阶段合同、SSE、严格所有权错误语义或安全错误投影。

本计划成功的可观察证据是：同一 `report-progress-v1` 合同贯通 service→application→FastAPI SSE→Nginx→fetch parser→reducer→Vue；四个并行分析器任意完成顺序下 task progress 不回退；首帧、heartbeat、终态、断线 fallback、清理、鉴权与日志脱敏均有自动测试；离线 Compose 和一条受保护真实模型/Tushare 报告通过。

## 3. Inputs Reviewed

- REQUIREMENT_SPEC.md: D05 用户旅程、范围、15 项行为验收、测试成本和 D06 边界。
- CODEBASE_RECON.md: 当前 Report 数据模型、Router/BackgroundTasks/service/LangGraph/前端 polling/Nginx/测试链、历史 SSE 分支和已知风险。
- CLARIFICATION_QUESTIONS.md: 30 项冻结决策、阶段/进度/协议/鉴权/降级/清理/真实 API 规则，以及 D05-T01～T09 最小测试责任。
- SOLUTION_TRADEOFF.md: 已选择 Option B“typed event accelerator + authoritative DB snapshot”，拒绝纯 DB polling SSE，Redis/durable replay 推迟到 D06。
- Code files: `backend/routers/report.py`、`backend/services/agent_service.py`、`backend/db/models.py`、`backend/main.py`、`frontend/src/composables/useReport.ts`、`frontend/src/api/index.ts`、`frontend/src/views/ReportView.vue`、`frontend/src/components/report/ReportProgress.vue`、`nginx/nginx.conf`、依赖清单和相邻 D03/D04 contracts。
- Tests: `tests/contract/test_api_contract.py`、`tests/e2e/offline_app.py`、`tests/e2e/test_offline_compose_stack.py`、现有报告 root event/download 测试、D03/D04 backend/frontend/live 测试模式。
- External references: FastAPI native SSE、FastAPI SSE source、WHATWG SSE、Nginx proxy buffering、MDN Fetch/AbortController、Vue lifecycle、sse-starlette 生命周期对照；具体链接见 tradeoff 文档。

## 4. Final Unified Direction

This iteration will：

- 冻结 `report-progress-v1` 的 typed 内部事实和 Pydantic/TypeScript 公共合同。
- 让报告 service 在真实准备、四分析器、可选个性化、汇总和任务终态边界发布事件；按“完成分析器数量”单调写入 progress。
- 以 Report 数据库记录作为恢复和最终状态唯一权威；用 bounded、非阻塞的进程内 hub 仅做当前单 worker 的低延迟通知。
- 在发送响应头前完成 Bearer 鉴权与统一 404 ownership 校验；用 FastAPI 原生 SSE 发送数据库首帧、hub event 和周期 DB reconcile，终态后关闭。
- 前端以 fetch/ReadableStream/AbortController 消费严格协议；SSE 失败才启用串行、有界 polling；所有生命周期统一 cleanup。
- 为 SSE 路径关闭 Nginx buffering；对齐 FastAPI 最低版本到原生 SSE 可用的 0.135；建立离线、Compose 和一条受保护 Live 验收。

This iteration will not：

- 不迁移 Report 表、不建立 event table、不改 LangGraph 拓扑、Prompt、Skills、tools、memory、报告正文格式或普通历史/详情/下载路径。
- 不实现 Redis、跨 worker pub-sub、幂等、`Last-Event-ID` replay、跨刷新恢复、任务取消/暂停/恢复。
- 不使用 query token、不手工拼 SSE、不引入新生产依赖、不把 raw LangGraph event/异常/Prompt/正文暴露给客户端或 artifact。

The plan follows Option B，并复用 D03/D04 的 typed contract、安全 projection、strict parser、单 reducer、资源 cleanup 和 protected Live artifact 规则；每次只执行一个里程碑。

## 5. Planning Assumptions

- Assumption: 当前生产 Compose 仍是单 Uvicorn worker；若实现期间发现实际启动多 worker，停止并把 publisher 可靠性升级为 P0 决策，不得静默声称支持。
- Assumption: 当前 `uv.lock` 的 FastAPI 为 0.141.1，根与 backend requirements 的最低版本可窄幅调整为 `>=0.135,<1`，不构成新增依赖。
- Assumption: Report schema 的 `status/progress/error_msg/content` 足够承担 D05 snapshot；当前阶段不要求持久化。
- Assumption: 首帧 DB snapshot 与周期 reconcile 可接受；“实时阶段全量历史”不是本轮验收目标。
- Assumption: 进程内 hub 丢弃中间通知不影响报告业务结果；任何终态都必须可从 DB 重新投影。
- Assumption: 新建任务的当前页面是唯一主动观察者常见场景；实现仍需支持多个订阅者，但不为每 task 提供无界缓冲。
- Assumption: protected Live 使用用户已有本机凭证，测试本身不得读取、打印或提交凭证值。
- Assumption: `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` 是用户未跟踪文件，与 D05 无关，所有里程碑必须保留且不得 stage。

## 6. Changed Surface

| Surface | Involved? | Why | Risk | Verification |
| --- | --- | --- | --- | --- |
| Frontend | Yes | fetch SSE、strict parser、reducer、fallback、cleanup、真实阶段 UI | High | Vitest parser/reducer/composable/component + build + browser/Compose |
| Backend API | Yes | 新增受保护 report events endpoint，共享安全 status snapshot | High | route contract、401/404、首帧/终态/stream 测试 |
| Database | Read/write behavior only | 继续保存 task authority，修正单调 progress/安全错误；无 schema | Medium | service transaction、status compatibility、终态 reconcile |
| Cache | No | D05 不使用 Redis/cache | N/A | diff/review 证明未触碰 |
| Agent runtime | Yes, narrow | 从真实 LangGraph event 映射 stage；不改图 | High | fake parallel order + real LangGraph characterization + Live |
| Tool calling | No behavior change | 分析器内部调用保持 | Low | existing regression + Live 最终报告 |
| RAG / Memory | Optional stage observation only | STM/LTM 只映射 PERSONALIZATION，不改策略 | Medium | enabled/disabled stage SKIPPED/SUCCEEDED cases |
| MCP | No | 无 MCP contract 变化 | N/A | diff review |
| Skills | No | 报告进度不改变 Skills | N/A | full regression |
| Tests | Yes | D05-T01～T09 全部需要新/更新覆盖 | High | pytest/Vitest/Compose/Live evidence |
| Observability | Yes | 连接、阶段、fallback、耗时、安全错误码 | Medium | log capture、forbidden-field scan、artifact |
| Security/Auth | Yes, endpoint boundary only | Bearer header、pre-stream ownership、统一 404 | High | 401/404/cross-user/query-token-negative tests |
| Build/Deployment | Yes, narrow | FastAPI minimum、Nginx SSE location、offline report fixture | Medium | lock/import smoke、compose config/image/E2E |

## 7. Repository Context

### 7.1 Relevant Entry Points

- `backend/routers/report.py`: `/api/report/generate`、`/status/{task_id}`、history/detail/download/delete；新 SSE 路径的协议入口和访问控制位置。
- `backend/services/agent_service.py`: `run_report_task` 及 LangGraph `astream_events`；真实 stage 事实、progress DB commit 和终态来源。
- `backend/db/models.py`: `Report` 持久字段；只读合同，不允许 schema 修改。
- `backend/main.py`: Router 注册和应用生命周期；仅在 publisher 需要显式 app 生命周期时窄幅使用。
- `frontend/src/composables/useReport.ts`: 报告生成、观察和加载副作用 owner；当前 polling 问题集中处。
- `frontend/src/api/index.ts`: base URL/Bearer 规则与报告 REST API；SSE parser/client 的相邻边界。
- `frontend/src/views/ReportView.vue`: observation 生命周期 owner。
- `frontend/src/components/report/ReportProgress.vue`: transport/stage/progress 受控展示。
- `nginx/nginx.conf`: `/api/` upstream；需要更具体 report events location。

### 7.2 Relevant Call Chain

1. Vue `ReportView` 调用 `useReport.generateReport`。
2. `POST /api/report/generate` 经 `require_auth`，确保用户并插入 `Report(status=pending, progress=0)`，注册 `run_report_task`，返回 task/report ID。
3. 前端立即启动单一 observation controller，优先 `GET /api/report/events/{task_id}`（最终路径在 contract test 冻结），携带 Bearer header。
4. Router 在 stream response 创建前用短 DB session 验证用户/任务所有权；application snapshot projector 读取 Report。
5. SSE presenter 先发送 `stream_ready`，再消费 task subscription；idle 时查询 DB reconcile，框架单独发送 15 秒 comment heartbeat。
6. `run_report_task` 运行 LangGraph；白名单识别节点的真实 start/end，在 DB progress commit 后发布 typed event；四分析器 progress 按已完成集合计数。
7. presenter 为当前连接生成单调 sequence，映射 `stage_update/task_terminal`；DB 已终态时立即终止 stream。
8. 前端增量 parser 严格验证，再由 task-scoped reducer 处理 sequence、stage、progress、terminal 和 transport state。
9. SSE 在首帧超时、协议/网络/HTTP 错误时清理 reader/controller，进入无重叠 polling；终态、新任务、历史切换、卸载、离开或登出统一 stop。

### 7.3 Existing Patterns to Reuse

- D03/D04 Python immutable/typed contract + Pydantic public projection + strict TS parser。
- D03 async stream 的有界资源与结构化 teardown；报告差异是 publisher 非阻塞、DB 做恢复权威。
- 现有 `require_auth`、`ensure_user_access` 的身份来源，但 SSE 非所有者/不存在必须在响应前统一 404。
- Pinia/composable/component 的副作用、状态、渲染分工。
- `tests/e2e/offline_app.py` deterministic providers、隔离 PostgreSQL/Compose、低敏 trace/assertion。
- protected Live 的显式 `RUN_PROTECTED_LIVE_E2E=true` gate、设置校验、独立 marker 和 artifact redaction。

### 7.4 Current Test Structure

- Python: `tests/unit/`、`tests/contract/`、`tests/integration/`、`tests/e2e/`；根 `pyproject.toml` 配置 pytest/ruff。
- Frontend: colocated `__tests__/*.spec.ts`，命令为 `npm test`、`npm run lint`、`npm run type-check`、`npm run build`。
- Compose: `docker/docker-compose.offline.yml` 启动真 PostgreSQL/FastAPI/Vue-Nginx，外部 provider deterministic；`tests/e2e/test_offline_compose_stack.py` 为入口。
- Live: 现有 chat live 模式可复用 gate/fixture/artifact 规范；D05 新建独立 report live case，默认 skip。
- 当前报告覆盖只有 LangGraph root event 和 download header 等零散断言，没有正式 report SSE contract/frontend/E2E。

### 7.5 Current Observability Structure

- Python 使用标准 logging；当前报告失败写原始 `str(exc)` 到 DB，缺少稳定 error code 和 stage/transport 字段。
- D03/D04 已有 request/session/stage/status/elapsed 等结构化可观测模式与脱敏测试。
- D05 日志至少包含 `stage=report_progress`、`task_id`、`report_id`、`status`、业务 `report_stage`、`transport`、`elapsed_ms`、`error_code`；正文、Prompt、token、Authorization、raw event 和 raw exception 禁止进入公共/持久 artifact。

## 8. Scope Control

### 8.1 In Scope

- typed internal progress facts、publisher/subscription port、bounded in-process adapter、safe snapshot projector。
- 真实 LangGraph 阶段映射、并行完成计数、DB progress 单调和 safe terminal error。
- `report-progress-v1` SSE endpoint、首帧/heartbeat/reconcile/终态、pre-stream auth/ownership。
- `/status/{task_id}` 路径与既有字段兼容、安全错误消息及可选 `error_code`。
- frontend fetch SSE parser/client、task-scoped reducer、transport UI、serial polling fallback、统一 cleanup。
- Nginx report events 路径禁缓冲；FastAPI minimum alignment；offline app/Compose/CI 相邻验证。
- D05-T01～T09 测试、milestone reports、acceptance report、README/测试文档的事实性更新。

### 8.2 Out of Scope

- Report 表/migration、持久 event history、Redis/pub-sub/stream/cache、幂等、重复提交治理。
- 多 worker/multi-instance realtime、重启后中间 event replay、`Last-Event-ID` 恢复、跨刷新 UI state。
- 任务取消/暂停/恢复、后台队列框架迁移、报告正文流式输出。
- LangGraph topology、Prompt、analyst logic、模型/工具选择、Skills、memory policy、MCP、chat D03/D04 protocol。
- 原生 EventSource/query token、AG-UI/LangGraph runtime 重构、新 SSE/Playwright/Redis 依赖。
- Docker Python 版本统一等非直接阻塞的仓库级治理。

### 8.3 Allowed Files / Modules

- 新建 `backend/application/report_progress/`（exact filenames 可在 M1 合同测试中冻结）：contracts、publisher/hub、snapshot/projector；若仓库一致性要求单模块，可使用 `backend/application/report_progress.py`，二选一后记录 Decision Log。
- `backend/services/agent_service.py`
- `backend/routers/report.py`
- `backend/schemas/` 下 report 相邻 schema 或新 `backend/schemas/report.py`
- `backend/main.py`（仅 publisher 生命周期/注入确有需要）
- `pyproject.toml`、`backend/requirements.txt`、`uv.lock`（仅 FastAPI minimum alignment；lock 内容若版本未变应保持最小 diff）
- `frontend/src/api/index.ts` 或新相邻 `frontend/src/api/reportProgress.ts`
- `frontend/src/composables/useReport.ts`
- `frontend/src/views/ReportView.vue`
- `frontend/src/components/report/ReportProgress.vue`
- 新的 report types/store/reducer/parser 文件及其相邻 `__tests__`
- `nginx/nginx.conf`
- `tests/unit/report/`、`tests/contract/test_report_progress_contract.py`、`tests/e2e/offline_app.py`、`tests/e2e/test_offline_compose_stack.py`、新 `tests/e2e/test_live_report_progress.py`
- `.github/workflows/`（仅现有门禁未自动包含新增测试或 Compose config 时）
- `README.md`、`docs/engineering/testing-strategy.md`、本 D05 spec/milestone/acceptance artifacts。

### 8.4 Forbidden Changes

- Do not perform unrelated refactor.
- Do not reformat unrelated files.
- Do not modify generated files or build artifacts；允许正常更新已跟踪 `uv.lock`，禁止提交 `dist/coverage/node_modules`。
- Do not add dependencies unless explicitly approved；FastAPI minimum alignment 不是新增依赖，除此之外出现需求必须停止。
- Do not change database schema or add migrations。
- Do not change existing API response schema incompatibly；`/status` 只能保留原字段并可加向后兼容字段，新 SSE 使用独立 versioned contract。
- Do not modify authentication storage or authorization policy beyond new SSE 的 pre-stream ownership/统一 404。
- Do not modify secrets、`.env`、credentials 或生产 secret values；Nginx 路径配置仅限 SSE 传输。
- Do not delete user data or execute destructive DB/filesystem operations。
- Do not weaken tests、markers、auth/redaction assertions or CI gates。
- Do not remove logging or safety checks；不得通过记录 raw payload 排查问题。
- Do not touch files outside allowed scope without stopping for approval。
- Do not stage、edit、delete 或 rename 用户未跟踪的 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md`。
- Do not cherry-pick `origin/feature/redis-integration-phase1` or copy its query-token、untyped queue、unsafe frontend cast。
- Do not claim multi-worker/durable/replay support；发现当前部署假设不成立时停止。
- Do not change report business output, analyst prompts, tool permissions, Skills, memory write/read policy, chat protocol or download behavior。

## 9. Interfaces and Dependencies

| Interface / Dependency | Current Role | Planned Change | Compatibility Requirement | Validation |
| --- | --- | --- | --- | --- |
| `POST /api/report/generate` | 创建 Report/BackgroundTask | 行为保持；返回后可立即订阅 | 路径、请求、响应不变 | existing + E2E create |
| `GET /api/report/status/{task_id}` | polling 快照 | 共用 safe projector；可加 `error_code` | 原有字段/状态/HTTP 兼容 | contract + fallback |
| `GET /api/report/events/{task_id}` | 不存在 | 新 Bearer-protected SSE endpoint | `report-progress-v1`；401；不存在/非所有者均 404 | route/Compose tests |
| Internal report progress fact | 不存在 | typed enum/dataclass，协议无关 | 不导入 FastAPI/Vue/DB model | unit/type/review |
| Progress publisher/subscription | 不存在 | non-blocking bounded per-task hub | publish 不改变 report outcome；cleanup 无泄漏 | race/slow subscriber tests |
| Report DB snapshot | status/progress/content/error | safe projector/monotonic progress | 无 schema；terminal authoritative | unit/contract/integration |
| LangGraph `astream_events` | 执行/粗 progress | 白名单真实 node start/end 映射 | 图与 node outputs 不变 | characterization/order tests |
| FastAPI | `>=0.115,<1` 声明，lock 0.141.1 | minimum `>=0.135,<1` | 不新增包；root/backend 一致 | lock/import/image smoke |
| Nginx `/api/` | 普通 API 代理 | 更具体 events location 禁缓冲/cache | 普通 API/WS 行为不变 | config + Compose timing |
| Frontend report progress types | 隐式阈值/loose state | strict discriminated union + parser | REST report types 保持 | Vitest malformed/valid cases |
| `useReport` | overlapping setInterval polling | one controller: SSE→bounded polling | public component actions 保持或迁移有测试 | composable lifecycle tests |
| `ReportProgress.vue` | 百分比猜五阶段 | 渲染真实 stage/transport/terminal | 保持 report 页面主要视觉功能 | component snapshots/assertions |
| Live credentials | Settings/env | 只读真实 report case gate | 默认不调用；值不出日志/artifact | skip/gate/redaction tests |

## 10. Engineering Implementation Contract

| Category | Files / modules | Required behavior or documentation | Verification | Status |
| --- | --- | --- | --- | --- |
| Architecture and dependency direction | report progress application module、service、Router、frontend api/composable/reducer/component | dependency 只能 service→protocol port、Router→application、frontend parser→reducer→view；domain fact 不依赖 SSE；DB 是 authority，hub 是 accelerator | import/review + focused architecture tests | Required |
| Docstrings, types, field meaning, and section navigation | 全部新增/修改 Python 和 TS public interfaces | Python Google-style 中文 docstring/type annotations；解释 progress 单位、sequence scope、stage/terminal、queue drop、side effects/failure；TS 不用 `any`/blind cast | ruff/type-check/review | Required |
| Configuration, env, secrets, constants, and prompts | dependency files、progress constants、live test | 集中定义协议/5s/15s/reconcile/backoff/15min；不新增 secret、不改 Prompt；FastAPI minimum root/backend 一致 | grep/diff/lock/config/gate | Required |
| Terminal output, logs, traces, metrics, and artifacts | progress module/service/route/frontend fallback/live artifact | stable stage/task/report/status/transport/elapsed/error_code；first-frame/terminal timing；严禁正文/token/Prompt/raw exception | caplog/forbidden scan/Live artifact hash | Required |
| Validation, errors, retry/fallback, state, and compatibility | Router/projector/parser/reducer/useReport | pre-stream 401/404；strict frame validation；monotonic progress/sequence/terminal；publish best-effort；SSE failure→serial bounded poll；DB terminal wins；status compatible | contract/race/lifecycle/E2E | Required |
| Tests, Agent evaluation, and handoff evidence | tests/unit/contract/e2e/frontend/Compose/D05 docs | D05-T01～T09；默认 offline；1 protected Live；每 milestone report；acceptance matrix、PR review/CI evidence | commands in §11 | Required |

## 11. Test and Validation Strategy

### 11.1 Existing Tests to Run

- 仓库根：`uv run --locked pytest -q`，验证所有 Python unit/contract/integration/e2e 默认离线回归。
- 仓库根：`uv run --locked ruff check .`，验证 Python 风格与静态规则。
- `frontend`：`npm test`，验证既有 D03/D04/chat/memory 与新增 report Vitest。
- `frontend`：`npm run lint && npm run type-check && npm run build`，验证 ESLint、Vue TS 和生产构建。
- 仓库根：`docker compose -f docker/docker-compose.yml config --quiet` 与 offline config，验证部署配置。
- 仓库根：`docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e`，随后必须 `down -v --remove-orphans`，验证真 PostgreSQL/FastAPI/Vue-Nginx 链且清理资源。

### 11.2 New or Updated Tests Required

- D05-T01 Protocol/projector，候选 `tests/contract/test_report_progress_contract.py`：合法三类帧、字段/enum/version/sequence、安全 snapshot/error；实现前应因接口不存在失败，实现后全过。
- D05-T02 True stage/monotonic progress，候选 `tests/unit/report/test_report_task_progress.py`：四分析器至少两种乱序、start/end、optional personalization enabled/disabled、unknown/root event、success/failure；progress 不回退且 terminal 在 DB commit 后。
- D05-T03 Publisher lifecycle，候选 `tests/unit/report/test_progress_hub.py`：subscribe-before/after snapshot 竞态、多 subscriber、queue full、slow/disconnected consumer、cleanup、no-subscriber、terminal notification；business task 不阻塞。
- D05-T04 API route，候选 contract file：Bearer success、无 token 401、无任务 404、cross-user 404、query token negative、首帧 5 秒、event MIME/headers、已终态立即关闭、disconnect cleanup。
- D05-T05 Frontend parser/reducer，候选 `frontend/src/api/__tests__/reportProgressContract.spec.ts` 和 store/reducer spec：任意 chunk、CRLF、多行 data/comment/EOF、malformed JSON/field/enum、duplicate/late/cross-task、progress max、terminal lock。
- D05-T06 Frontend lifecycle/fallback，候选 `frontend/src/composables/__tests__/useReport.progress.spec.ts` 与 component spec：Authorization header、AbortController、first-frame timeout、SSE→poll、串行无重叠、2/4/8/15、5 errors、15min、新任务/历史/卸载/terminal cleanup、transport UI。
- D05-T07 REST compatibility：`/generate` 和 `/status` 原字段不变、安全 error message/optional code，现有 download/history/detail 不回归。
- D05-T08 Proxy/full-stack：扩 `offline_app.py` 与 `test_offline_compose_stack.py`，覆盖 Nginx 下即时首帧、至少真实 fake LangGraph stage、终态/DB 报告、断开/降级、无 secret、普通 API 回归。
- D05-T09 Protected Live：新 `tests/e2e/test_live_report_progress.py`，显式 gate，一条真实模型 + 只读 Tushare report，12 分钟，无 whole-report retry，断言阶段/单调/终态/正文 hash/脱敏 artifact。

### 11.3 Manual Smoke Tests

- 正常生成：登录后输入有效股票，点击生成；5 秒内从“连接中”进入实时阶段，四分析阶段随真实完成更新，百分比不回退，最终展示报告且连接关闭。
- SSE 故障：在开发工具阻断 events 请求或让测试 server 返回 503；UI 明确显示“已降级为轮询”，请求串行且最终报告成功，无重复连接。
- 生命周期：生成中切换一条历史报告再离开页面；Network 面板不保留旧 events 请求，不再更新旧任务状态。
- 失败任务：fake analyst 抛异常；UI 只显示安全错误和最后进度，原始 provider exception 不出现；状态终止，不无限重试。
- 越权：用户 B 请求用户 A task events；响应在 stream 建立前为 404 JSON，不收到任何 task/report 信息。

### 11.4 Agent/RAG/Tool Evaluation, if applicable

- 本轮不改变 Agent 决策质量、RAG、Skills 或 tools，因此不新增离线语义 score 集。
- 必须用 deterministic fake LangGraph 验证阶段真实性和并行乱序；使用一条 protected Live 证明真实模型/Tushare 装配未被 fake contract 掩盖。
- Live 只检查调用成功、阶段序列/单调性、数据库终态、报告非空 hash 和安全 artifact；不把报告文案主观质量作为 D05 gate。

### 11.5 Expected Terminal / Logs / Trace / Artifacts

- 测试终端只输出命令摘要、pass/fail/skip、耗时和 artifact path；不得打印 env value、Bearer、Prompt 或完整报告。
- 后端结构化日志稳定字段：`stage=report_progress`、`task_id`、`report_id`、`status`、`report_stage`、`transport=sse|polling|database`、`elapsed_ms`、可选 `error_code`；连接 open/close/subscriber count/drop/reconcile 使用受限数值。
- 前端只向 UI 暴露 `CONNECTING/LIVE/FALLBACK_POLLING/COMPLETED/FAILED` 等冻结 transport state；控制台不得输出 token/frame data。
- Live artifact 建议路径 `artifacts/live/report-progress/<run-id>.json`，只含 schema/protocol、case ID、model/provider 非敏感标识、stage kinds/states、progress 序列、first-frame/total elapsed、terminal、content hash、redaction check；是否提交 artifact 依仓库既有规则，默认不提交运行产物，只在 milestone report 记录路径/hash。

### 11.6 Acceptance Criteria

| Behavior / Risk | Test or Check | Command / Method | Expected Result |
| --- | --- | --- | --- |
| 公共协议稳定安全 | D05-T01 | `uv run --locked pytest tests/contract/test_report_progress_contract.py -q` | 三类事件严格通过；raw/secret/正文负向断言通过 |
| 真实节点与单调进度 | D05-T02 | focused unit pytest | 两种并行乱序均 20→…→80，永不回退；未知节点忽略 |
| hub 不阻塞且可清理 | D05-T03 | focused unit pytest | 慢/断连 subscriber 不影响任务；队列有界；无残留 |
| auth/ownership/首帧/终态 | D05-T04 | route contract | 401/404 正确；query token 无效；首帧<5s；终态关闭 |
| parser/reducer 抗乱序畸形 | D05-T05 | `npm test -- reportProgress` 或完整 `npm test` | chunk/comment/非法帧处理正确；跨任务/迟到不污染 |
| fallback 与 cleanup | D05-T06 | composable fake timers + component mount | 无重叠；退避/上限正确；所有生命周期清理 |
| REST 向后兼容 | D05-T07 | contract pytest | generate/status/history/detail/download 既有消费者不破坏 |
| FastAPI SSE 能力可用 | dependency/import smoke | `uv run --locked python -c "from fastapi.sse import EventSourceResponse, ServerSentEvent"` | exit 0，root/backend constraint 一致 |
| Nginx 不缓冲 | D05-T08 | config + offline Compose timing | 通过代理及时收到首帧/阶段/终态，普通 API 通过 |
| 默认测试零真实费用 | markers/gate | `uv run --locked pytest -q` | live case skip，未触发真实 Provider |
| 真实装配可用 | D05-T09 | PowerShell: `$env:RUN_PROTECTED_LIVE_REPORT_E2E='true'; uv run --locked pytest tests/e2e/test_live_report_progress.py -q -m live` | 1 passed；12min 内；无 retry；artifact 脱敏 |
| Python 全回归 | existing suite | `uv run --locked pytest -q` + `ruff` | 通过或只保留已登记且与 D05 无关基线 |
| 前端全回归 | existing suite | `npm test; npm run lint; npm run type-check; npm run build` | 全部通过 |
| 可原子交付 | Git diff/PR/CI/review | `git diff --check`、secret scan、GitHub checks | 窄幅 diff；无 D01；review 问题解决；CI green |

## 12. Milestones

### Milestone 0: Safety and Baseline Check

**Goal:** 确认分支、用户文件、依赖/服务工具、真实 changed surface 和既有基线，不改代码。

**Files / Modules:** 只读本 PLAN、四份前置 artifacts、AGENTS/project rules、git/pyproject/package/Compose/相关源码测试。

**Implementation Intent:** 运行 `git status --short --branch`、remote/branch/issue 检查；确认 D01 为用户文件；确认 FastAPI import/version、Node/npm/Docker、test collection、两个 Compose config；记录现有相关 focused tests 结果和已知 baseline。

**Tests / Checks:** git status/diff、`uv run --locked python` import smoke、`uv run --locked pytest` 现有 report 邻近测试（精确 node ids 通过 collect 冻结）、frontend existing tests、Compose config；不跑 Live。

**Expected Result:** 允许范围无冲突；工具链可用；现有问题与 recon 一致；生成 `docs/specs/D05_REPORT_SSE_PROGRESS_MILESTONE_0_EXECUTION_REPORT.md`。

**Stop Condition:** 需要修改的文件含未归属用户变化；不是预期 branch/base；FastAPI/测试/Compose 不可用且无法只读定位；单 worker 假设不成立。

**Rollback Note:** 无实现变更；只删除本里程碑新增报告即可回退，且不得影响 D01。

**Handoff Evidence:** 状态、版本、命令/结果、baseline/skip、allowed surface、blocker、D01 preservation 和 governance 更新。

### Milestone 1: Lock Tests and Public Contracts

**Goal:** 在业务实现前用失败测试冻结协议、真实阶段、竞态、前端 parser/reducer/fallback 和代理验收责任。

**Files / Modules:** 新 report unit/contract/frontend specs，必要测试 fixtures、`offline_app.py`/Compose test skeleton；本 PLAN/report。

**Implementation Intent:** 先建立 typed contract expectations 和 minimal fakes；测试不得复制未来实现算法。将 D05-T01～T08 映射为明确 test IDs；Live test 只建立默认 skip/gate/redaction skeleton，不调用真实 API。

**Tests / Checks:** 收集全部新增测试；运行时应呈现由缺失接口造成的预期失败，而不是 syntax/import/fixture error；现有相邻 tests 继续通过；`git diff --check`。

**Expected Result:** 每个行为有可读失败基线，测试数量保持最小责任集，不为每个字段堆重复测试；生成 M1 report。

**Stop Condition:** 测试必须修改 forbidden surface、需求互相矛盾、test harness 无法表达 SSE chunk/timing、或预期失败破坏全仓 collection。

**Rollback Note:** 可独立移除 M1 新测试/fixtures；不接触业务和数据。

**Handoff Evidence:** tests added、pre-change failure reasons、existing regression results、D05-T01～T09 mapping、governance 更新。

### Milestone 2: Implement Backend Truth, Snapshot, and SSE

**Goal:** 完成真实 service stage、单调 DB progress、typed publisher/snapshot 和受保护 SSE 主链。

**Files / Modules:** `backend/application/report_progress*`、`backend/services/agent_service.py`、`backend/routers/report.py`、report schemas、`backend/main.py`（必要时）、FastAPI dependency declarations/lock、M1 Python tests。

**Implementation Intent:** 先实现内部 enum/dataclass/protocol/safe projector 和 bounded nonblocking hub，再把 publisher 注入 report task；白名单映射真实 LangGraph metadata，按完成集合推进。SSE preflight 短会话鉴权/404，register→snapshot→events/reconcile，DB terminal commit-before-publish；使用 FastAPI native response。保持 `/status` 兼容。

**Tests / Checks:** D05-T01～T04/T07 focused pytest、FastAPI import smoke、ruff relevant files、并发/取消/DB failure tests、existing report API tests。

**Expected Result:** 后端能在无浏览器订阅时正常完成报告；有订阅时首帧/真实 stage/terminal 正确；慢订阅不阻塞；错误安全；生成 M2 report。

**Stop Condition:** 需要 schema/Redis/新 dependency；`astream_events` 无法稳定识别真实 node；解决竞态必须持有长 DB transaction；两次 focused repair 仍失败。

**Rollback Note:** 后端改动与 dependency minimum 为独立 milestone diff；无 migration，可一起 revert；原 status polling 仍作为行为后备。

**Handoff Evidence:** changed files、contract/stage/race/auth test results、DB/publisher ordering evidence、日志字段/脱敏、remaining risks、governance 更新。

### Milestone 3: Implement Frontend Observation and Proxy Delivery

**Goal:** 完成严格 fetch SSE、单 reducer、可见 transport/fallback/cleanup，以及 Nginx 即时传输。

**Files / Modules:** report api/types/parser/reducer/store、`useReport.ts`、`ReportView.vue`、`ReportProgress.vue`、相邻 frontend tests、`nginx/nginx.conf`、offline fixtures/tests。

**Implementation Intent:** parser 正确处理标准 wire/chunk/comment；client 显式 Bearer、首帧 timeout 和 abort；one active observer；SSE 错误才启动串行 polling，遵守退避/次数/总时限；task/report/sequence/terminal 单调。组件只渲染 typed state并触发生命周期动作。Nginx 仅对 events location 禁缓冲/cache。

**Tests / Checks:** D05-T05/T06 frontend specs、lint/type-check/build、Nginx/Compose config、backend route focused test；断言普通 chat WS/API 代理配置不回归。

**Expected Result:** 正常、fallback、task switch、unmount、terminal 全部只有一个活动传输且资源清理；UI 不再按百分比猜阶段；生成 M3 report。

**Stop Condition:** 需更改 auth storage、引入 EventSource/query token/依赖；parser 必须用 unsafe cast；Nginx 变更影响普通 API/WS；两次 focused repair 失败。

**Rollback Note:** frontend/Nginx 可作为同一 milestone revert；后端 endpoint 保留不会影响旧 UI；无持久状态。

**Handoff Evidence:** Vitest/lint/type/build、header/abort/timer assertions、proxy config、UI states、browser/network smoke summary、governance 更新。

### Milestone 4: Offline Full Verification and Narrow Fixes

**Goal:** 用完整离线自动化和 Compose 真代理链验证 D05，并只修复证据明确的问题。

**Files / Modules:** 允许的测试/实现文件，仅限失败定位所需窄改；M4 report。

**Implementation Intent:** 按 narrow→full 顺序运行 D05 focused、Python full、frontend full、Compose config/build/E2E；模拟 SSE 失败验证 fallback；检查日志/artifact forbidden fields；每个 failure 先读日志再改。

**Tests / Checks:** §11 所有默认 offline 命令、`git diff --check`、secret/token/raw content scans、Docker cleanup/`ps -a`；可用浏览器人工验证本地 Compose 页面。

**Expected Result:** D05-T01～T08、全部既有回归和生产构建通过；Compose 首帧未缓冲；资源清理；生成 M4 report。

**Stop Condition:** 同一问题两次 repair 未解决；修复要求超出 allowed surface；Docker 环境错误无法归因于代码；发现安全泄露或数据破坏风险。

**Rollback Note:** 每个 narrow fix 记录对应 failing evidence；可回退单修复或整个 M2/M3，不使用 destructive git 命令，不覆盖用户文件。

**Handoff Evidence:** 完整 command matrix/pass counts/timing、Compose lifecycle、artifact/log scan、fix mapping、remaining skips/risks、governance 更新。

### Milestone 5: Protected Live, Documentation, Review, and Handoff

**Goal:** 完成一条真实报告验收、文档/Claim 证据、独立 review、GitHub PR/CI/merge 交付。

**Files / Modules:** `tests/e2e/test_live_report_progress.py`、D05 reports/artifacts、README/testing docs、必要窄修复；GitHub Issue #50/PR metadata。

**Implementation Intent:** 先确认 gate 和凭证存在性（只判断，不打印），使用隔离测试身份/数据库，一次真实模型 + 只读 Tushare 报告，12 分钟，不重试整报告。补充 acceptance report 与事实性文档。Review 检查 correctness/security/concurrency/leak/compatibility/tests；解决 actionable issues 后再 push/PR/CI/squash merge。

**Tests / Checks:** D05-T09 protected command、artifact redaction/hash、必要 focused regression；最终 Python/frontend/Compose 证据不得过期；`git status/diff --check`、secret scan、`gh pr checks`、独立 diff review。

**Expected Result:** Live 1 passed 或精确外部凭证/provider blocker（不得伪造）；所有 Claim 有代码+测试证据；PR checks green、review 无未解决 P0/P1、squash merge 到 main；生成 M5/acceptance report。

**Stop Condition:** 缺少真实凭证/额度、外部 API 非只读风险、可能触碰生产数据库、Live 连续两次因代码 repair 失败、PR review 发现需扩 scope 的 P0、CI 无法在 allowed scope 修复。

**Rollback Note:** Live 仅隔离数据/只读外部调用；不提交 secrets/runtime artifact。merge 前可 revert branch commits；merge 后用 GitHub revert/single squash revert，不重写 main history。

**Handoff Evidence:** Live case/elapsed/stages/hash/redaction、final acceptance matrix、review findings/fixes、commit/PR/checks/merge URL、governance sections completed。

## 13. Execution Protocol

- Execute exactly one milestone at a time.
- Start each milestone by restating its goal and allowed files.
- Run `git status --short` before editing.
- Do not overwrite user changes，尤其不得 stage `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md`。
- Do not modify files outside allowed scope.
- Do not move to the next milestone without reporting evidence and writing its `D05_REPORT_SSE_PROGRESS_MILESTONE_<N>_EXECUTION_REPORT.md`。
- If a required change is outside scope, stop and ask for approval.
- If tests fail, inspect the narrowest relevant logs and fix only the concrete issue.
- If two consecutive repair attempts fail, stop and produce `D05_REPORT_SSE_PROGRESS_MILESTONE_<N>_EXECUTION_BLOCKED.md`，记录命令、错误、原因、files touched 和所需决策。
- Do not claim completion without verification evidence.
- Update Progress, Decision Log, Surprises & Discoveries, and Outcomes & Retrospective as work proceeds.
- Satisfy the applicable Engineering Implementation Contract and report `Not applicable` categories explicitly.
- 默认不运行真实 API；只有 Milestone 5 且显式 gate/凭证/隔离条件满足才运行一次。
- 所有长运行命令需持续汇报；Compose 无论成功失败都执行安全 cleanup。
- Review diff before each test tier；每行变更必须能映射到需求、失败测试、已证实 bug 或兼容约束。

## 14. Rollback Plan

Before implementation, rollback is simply discarding the unexecuted plan. During implementation, each milestone should be isolated so it can be reverted independently.

- Branch strategy: 只在 `feat/50-report-sse-progress` 开发，基于 `origin/main`；M0～M5 分 milestone 保留窄幅 diff/report，最终 squash PR；不 force-push main、不 destructive reset。
- User changes: 每次 status 显式核对 D01；stage 命令必须列出 D05 文件或使用逐文件 add，禁止 `git add .`；冲突时停止。
- Test-only rollback: M1 测试可独立移除，不影响 runtime。
- Backend rollback: revert report progress module/service/router/dependency minimum；无 schema/data rollback；旧 REST polling 路径保持。
- Frontend/proxy rollback: revert report parser/reducer/composable/UI 与 Nginx specific location；普通 `/api/` 保持。
- Configuration rollback: 只还原 FastAPI lower bound/Nginx events block；不改 env/secrets。
- Database rollback: Not applicable，无 schema migration；测试数据仅存在隔离 DB，由 fixture/Compose teardown 清理。
- Dependency rollback: 无新 package；若 lock 因 minimum alignment 出现意外大 diff，停止而不是提交。
- Live rollback: 外部调用只读且整份不重试；本地隔离记录按 fixture 清理；artifact 不含正文/secret。
- Stop rather than continue when schema/Redis/new service/new dependency/multi-worker support/security policy change becomes necessary, or two repair attempts fail.
- Merge rollback: 使用 GitHub 创建 revert PR 撤销单个 squash commit，保留审计历史；不得 `git reset --hard`/rewrite remote。

## 15. Progress

- [x] Milestone 0: Safety and Baseline Check
  - Completed: 2026-09-04
  - Evidence: branch/HEAD 与 `origin/main` 均为 `8b42b98`；FastAPI 0.141.1 native SSE import 通过；两个 Compose config 通过；后端报告相邻 4 tests、前端 27 tests 通过；详见 `D05_REPORT_SSE_PROGRESS_MILESTONE_0_EXECUTION_REPORT.md`。
- [x] Milestone 1: Lock Tests and Public Contracts
  - Completed: 2026-09-04
  - Evidence: D05-T01～T09 已映射到 5 个 Python / 3 个 frontend 测试文件；Python `1 passed, 10 xfailed, 1 skipped, 1 deselected`，frontend `33 passed`，ruff/lint/type-check 通过；详见 `D05_REPORT_SSE_PROGRESS_MILESTONE_1_EXECUTION_REPORT.md`。
- [x] Milestone 2: Implement Backend Truth, Snapshot, and SSE
  - Completed: 2026-09-04
  - Evidence: `report-progress-v1` contracts/tracker/hub/snapshot、service commit-before-publish、pre-stream auth SSE 已实现；Ruff/uv lock 通过、Pyright `0 errors`、focused `19 passed`、backend/API regression `13 passed`；详见 `D05_REPORT_SSE_PROGRESS_MILESTONE_2_EXECUTION_REPORT.md`。
- [x] Milestone 3: Implement Frontend Observation and Proxy Delivery
  - Completed: 2026-09-04
  - Evidence: strict TS parser + Pinia reducer + fetch SSE/serial polling lifecycle + authoritative stage UI + dedicated Nginx location 已实现；focused `14 passed`、frontend full `41 passed`、lint/type/build、backend SSE route `4 passed`、两套 Compose config、Nginx static contract 与本地浏览器 smoke 通过；详见 `D05_REPORT_SSE_PROGRESS_MILESTONE_3_EXECUTION_REPORT.md`。
- [x] Milestone 4: Offline Full Verification and Narrow Fixes
  - Completed: 2026-09-05
  - Evidence: Docker Desktop 经用户授权升级到 4.89.0 后恢复 Linux engine；首次 Compose 发现并修复契约测试继承 `AUTH_ENABLED=false` 的隔离缺陷，复跑真 PostgreSQL/FastAPI/Vue-Nginx 链路 `288 passed, 3 skipped, 40 deselected, 3 xfailed`、退出码 0；D05-T08 经过 BackgroundTask→真实 LangGraph→DB→SSE→Nginx→详情查询，临时容器/网络/卷清理后 `ps -a` 为空。详见 `D05_REPORT_SSE_PROGRESS_MILESTONE_4_EXECUTION_REPORT.md`，历史阻塞证据保留于 `D05_REPORT_SSE_PROGRESS_MILESTONE_4_EXECUTION_BLOCKED.md`。
- [ ] Milestone 5: Protected Live, Documentation, Review, and Handoff

## 16. Decision Log

| Date | Decision | Reason | Source |
| --- | --- | --- | --- |
| 2026-09-04 | 选择 typed event accelerator + authoritative DB snapshot | 同时满足真实阶段、低延迟、断线收敛且不越界进入 Redis | SOLUTION_TRADEOFF §9 |
| 2026-09-04 | 数据库是恢复权威；进程内 hub 可丢、非阻塞 | 当前单 worker 可加速，慢客户端/无订阅不应影响报告 | CLARIFICATION + tradeoff |
| 2026-09-04 | 协议冻结为 `report-progress-v1` 三类业务事件 | 最小而完整，heartbeat 与业务状态分离 | CLARIFICATION |
| 2026-09-04 | 四分析器进度按完成数量，不按身份 | LangGraph 并行完成顺序不确定，避免回退 | CODEBASE_RECON + CLARIFICATION |
| 2026-09-04 | 使用 FastAPI native SSE，minimum 对齐 `>=0.135` | lock 0.141.1 已具备能力，避免手写/新增依赖 | official docs + local source |
| 2026-09-04 | 前端使用 fetch + Bearer + AbortController | 符合现有 header auth，可严格解析和取消 | MDN + local auth contract |
| 2026-09-04 | SSE preflight 统一 404；不持有长 DB session | 防 task existence 泄露并控制连接资源 | CLARIFICATION |
| 2026-09-04 | SSE 失败后串行有界 polling，不无限自动重连 | 可恢复且避免请求风暴/双传输 | CLARIFICATION |
| 2026-09-04 | 默认 offline，Live 一条/12 分钟/不整份重试 | 控制费用和不确定性，同时证明真实装配 | User + REQUIREMENT_SPEC |
| 2026-09-04 | Redis/idempotency/replay/multi-worker 延后 D06 | 防止 D05 跨基础设施失控 | User gap sequence + tradeoff |
| 2026-09-04 | M0 确认当前 Docker 生产入口为单 Uvicorn worker | `Dockerfile.backend` 未配置 `--workers`，符合进程内 accelerator 的已冻结适用边界 | M0 repository inspection |
| 2026-09-04 | M1 用 Python strict xfail 与 Vitest `it.fails` 冻结未实现合同 | 保持默认回归可运行，同时实现满足后 XPASS 会强制开发者移除缺口标记 | Existing repository characterization pattern |
| 2026-09-04 | 冻结后端目标模块为 `backend.application.report_progress.{contracts,tracker,hub}` | 独立于 HTTP/ORM，便于 M2 复用和 D06 替换 adapter | PLAN architecture contract + M1 tests |
| 2026-09-04 | 冻结前端 parser exports 位于 `@/api`，观察控制仍由 `useReport` 所有 | 与现有 API/composable 边界一致，减少组件副作用 | Local D03/D04 pattern + M1 tests |
| 2026-09-04 | FastAPI SSE endpoint 使用 `response_class=EventSourceResponse` 的直接 async yield，所有权快照由普通 dependency 预检 | 0.141.1 的 native SSE 编码只在路由 generator marker 路径生效；dependency 才能在响应头前返回 401/404 | Installed FastAPI source + M2 contract |
| 2026-09-04 | 全局进程内 Hub 容量为 32，满时替换最旧；数据库仍是恢复权威 | 正常报告约 15 条事件，可保留完整生命周期；异常慢客户端仍有固定内存上限 | M2 self-review + D05-T03 |
| 2026-09-04 | LangGraph 阶段只接受 metadata node 与 event name 一致的顶层事件 | 内部 Runnable 会继承 `langgraph_node`；单看 metadata 会过早结束阶段 | Local real LangGraph characterization |
| 2026-09-04 | 报告失败数据库与公共响应只保存稳定码/安全提示并保留最后进度 | 防原始 Provider/token 文本泄露，且失败不把 progress 重置为 0 | Engineering contract + service integration test |
| 2026-09-04 | 前端协议实现拆为 `api/reportProgress.ts` 严格 parser 与 `stores/reportProgressStore.ts` 单一 reducer | transport 只负责接收/降级，所有 SSE/polling 状态统一验证 task/report/sequence、progress max 和 terminal lock | M3 architecture contract + D05-T05 |
| 2026-09-04 | `useReport` 同时只持有一个活动 `AbortController`，SSE 失败后才创建串行 polling loop | 避免 SSE/polling 双写、重叠请求和旧任务迟到更新；统一处理 timeout/history/unmount/terminal | M3 lifecycle tests + D05-Q18/Q21/Q24 |
| 2026-09-04 | transport 观察失败使用 `OBSERVATION_FAILED`，不伪造报告任务 `failed` | SSE/轮询不可达不等于后台报告失败，用户仍可稍后从历史报告读取权威终态 | D05-Q22/Q25 + component contract |
| 2026-09-04 | Nginx 实际交付文件采用 `docker/nginx/default.conf` 的精确 events location | PLAN 中 `nginx/nginx.conf` 是路径笔误；仓库 Dockerfile 唯一复制的是该文件，普通 `/api/`/WS block 保持不变 | Repository inspection + Compose/static contract |
| 2026-09-04 | offline report fixture 只替换股票解析和外部工作流，并使用真实编译 LangGraph 产生节点事件 | 既隔离付费 Provider，又保留 BackgroundTask、Tracker/Hub、DB、FastAPI SSE 与报告查询真实链路 | M4 D05-T08 |
| 2026-09-04 | 报告事件消费升级为 `astream_events(version="v2")` | 当前 LangGraph 的 v1 根结束事件只给按节点分块的嵌套输出，会把成功报告误判为 `final_report` 缺失；v2 返回完整 state | M4 real compiled LangGraph reproduction |
| 2026-09-04 | 报告股票解析日志不记录原始指令、公司名或股票代码 | 用户输入和持仓线索不应进入终端/日志；仅保留 task、stage、status、error_code | M4 redaction review |
| 2026-09-04 | Docker 修复只原地备份临时 socket 目录，不执行 factory reset/prune/purge | 保留镜像、卷与项目数据且可回滚；同一错误两次复现后按 stop condition 停止 | M4 Docker diagnosis |
| 2026-09-05 | 经用户授权使用官方校验安装包把 Docker Desktop 4.86.0 原地升级到 4.89.0，并再次可恢复地备份损坏 runtime socket 目录 | 新版本仍需移走旧 `dockerInference` 重解析点，但随后 WSL 数据盘迁移和 Linux engine 均成功；未 factory reset/prune/purge | M4 resume evidence |
| 2026-09-05 | 鉴权契约测试显式冻结 `settings.auth_enabled=True` | 所有权隐藏合同不能继承 Compose 的 `AUTH_ENABLED=false` 环境，否则测试结果依赖宿主配置 | First Compose failure + focused repair |
| 2026-09-05 | D05 Live 固定已知股票解析结果，并把旧报告 Agent 的 MCP 工具端口装配为现有只读 Tushare toolkit | D05 验证报告阶段/SSE，不重复验证实体解析；同时确保真实报告证据不是旧数据工具或 fake | M5 protected Live contract |
| 2026-09-05 | Windows protected Live 通过 `uv --with socksio` 临时加载代理依赖，不修改生产 lock | 本机存在 SOCKS proxy，但生产依赖不应因单机验收增加可选包 | Existing testing strategy + M5 preflight |
| 2026-09-05 | 四个旧分析 Agent 的 Prompt/正文终端输出改为长度级 DEBUG 元数据 | Live 证明 INFO/`print` 会输出长 Prompt 与模型正文，违反低敏终端合同 | M5 review finding + privacy unit tests |
| 2026-09-05 | 四个旧分析 Agent 的失败路径只保存错误类型和安全消息 | raw Provider exception 可能携带请求或鉴权信息，不能进入普通日志、Agent state 或 ExecutionLogger | M5 security review + failure privacy tests |
| 2026-09-05 | 首帧 5 秒预算从发起 fetch 开始，并用 observation epoch 丢弃停止后的迟到创建响应 | 响应头悬挂和 generate 竞态都会绕过原 cleanup 语义 | M5 frontend concurrency review + 2 regression cases |
| 2026-09-05 | SSE 在 Hub 注册后立即重新读取一次数据库权威快照 | 关闭首查与订阅间的终态丢失窗口，避免最多 15 秒的终态延迟 | M5 backend concurrency review + race contract |
| 2026-09-05 | Agent 隐私单测显式注入离线占位 Provider 配置 | 测试必须真实进入 fake Agent success/failure 路径，不能隐式依赖开发机 `.env` 或 CI secrets | PR #51 initial Python CI failure |

## 17. Surprises & Discoveries

| Finding | Impact | Action |
| --- | --- | --- |
| 固定 node→progress 在并行乱序时可能回退 | 当前进度和 UI Claim 不可靠 | M2 改为 completed-node count，并做乱序测试 |
| `event.get("name")` 可能遮蔽 `metadata.langgraph_node` | 可能识别错真实节点 | M1 characterization，M2 白名单 metadata 优先 |
| root state 缺失 fallback 可能再次 `ainvoke` 整图 | 潜在重复真实调用/费用 | M0/M1 先锁正常事件形状；若 D05 改动触发该风险，停止并记录，不扩 scope 静默修复 |
| FastAPI lock 0.141.1 有原生 SSE，但声明最低 0.115 | Docker 可能解析到无 SSE 版本 | M2 仅对齐 minimum，验证 root/backend/image |
| 旧 SSE 分支混合 Redis/admin/idempotency 且 query-token | 不可安全复用或 cherry-pick | 仅借鉴首帧/heartbeat/cleanup/Nginx 概念 |
| 当前 offline app 没有 report external-port path | Compose 无法直接验 D05 | M1/M3 增加最小 deterministic report fixture |
| 当前 `/status` 对非所有者和不存在响应不同 | task existence 可被推断 | 新 SSE 必须统一 404；status 兼容边界单独记录 |
| `pytest --collect-only` 只发现 4 个报告相邻回归，前端没有 report 专项测试 | D05 行为没有现成自动化保护 | M1 严格按 D05-T01～T09 增加最小失败基线，不重复堆测试 |
| strict xfail 的 `raises=AssertionError` 会把缺失字段的直接 `KeyError` 当成测试错误 | 目标缺口无法以预期基线表达 | 将字段检查改为 `.get()` 后断言；重跑得到 10 个受控 xfail |
| `vue-tsc -b` 会更新已跟踪的 `frontend/tsconfig.node.tsbuildinfo` 版本缓存 | 若不清理会形成无关生成物 diff | 校验只含 TypeScript version 后恢复到 HEAD；后续每次 type-check 后检查并排除该文件 |
| FastAPI native `EventSourceResponse` 只是路由 marker，实例化后传 async iterator 会退回普通 StreamingResponse 编码 | `ServerSentEvent` 被当普通 chunk，调用 `.encode` 失败 | 改为 endpoint 直接 yield，并把 auth/ownership 移到普通 dependency |
| async-generator endpoint 的函数体在 SSE producer 中执行 | 函数体内抛 404 已晚于响应启动，形成 ExceptionGroup | `_require_sse_snapshot` 在 producer 前预检，function-scope DB session 提前关闭 |
| LangGraph 顶层与内部 Runnable 都携带同一 `langgraph_node` metadata | 只按 metadata 会把内部 chain end 当 analyst 完成 | 要求存在的 event name 与 metadata node 一致；真实小图与回归测试覆盖 |
| SQLAlchemy ORM `Mapped[T]` 不满足可变属性 Protocol 的静态不变性 | snapshot projector 在 Pyright 下出现 3 组类型错误 | projector 改为显式 primitive keyword 参数，避免 ORM 反向进入 application contract |
| `astream_events(version="v1")` 在当前 LangGraph 根结束事件返回按节点分块，而非完整 state | 真实编译工作流会把成功报告误判为内容为空并进入失败终态 | M4 以真实 LangGraph 重现，窄改为 v2 并由 service unit + 本机 HTTP/SSE E2E 验证 |
| PLAN 写的是不存在的 `nginx/nginx.conf`，实际镜像复制 `docker/nginx/default.conf` | 若照字面新增文件，生产镜像不会使用 | M3 只修改 Dockerfile 已引用的唯一配置，并记录路径勘误 |
| WHATWG 流测试复用同一个已取消 `Response.body` 会让第二次连接提前结束 | lifecycle 测试误以为 unmount 未 abort | mock 改为每次 fetch 创建独立 `ReadableStream`；原命令重跑通过 |
| runtime envelope 校验若只返回 boolean，TypeScript 不会收窄字段 | 首次 type-check 出现 `unknown` 不能赋给 typed frame | 将 `hasEnvelope` 定义为类型谓词，不使用 blind cast；type-check/build 通过 |
| Windows 历史 CRLF Vue 文件会被默认 `git diff --check` 把 `\r` 误判为尾随空格 | raw diff check 产生全行假阳性 | 保持仓库原换行，使用精确 `core.whitespace=cr-at-eol` 复核为 0；未改 `.gitattributes`/Git config |
| Docker CLI 可解析 Compose，但 Docker Desktop 4.86 daemon 未监听 Linux engine pipe | 一度无法执行 image `nginx -t` 或真代理运行 | 保留阻塞证据；2026-09-05 升级至 4.89.0 并重建 runtime socket 目录后恢复，完整 Compose 已通过 |
| 本地浏览器首次被已有 cold-start guard 重定向 | 无法直接观察报告页是否挂载 | 仅在系统临时 SQLite 库完成内置测试账号冷启动，报告页/API/console smoke 通过后停止服务；无模型调用 |
| Docker 的旧 `dockerInference` 目录备份并重建后，启动先暴露同类 `docker-secrets-engine/engine.sock`，修复后又立即重建损坏 `dockerInference` | 证明故障是 Windows/Docker Desktop 4.86 主机运行时问题，不是单个旧文件或 Compose 代码 | 保留可回滚备份；用户授权升级 4.89.0 后再次备份旧 socket，Linux engine 恢复并完成 M4 gate |
| 仓库级 `ruff check .` 扫描两个历史子项目后报 94 个既有错误，D05 Python changed surface 为 0 | 不能把全仓 lint 宣称通过，也不应在 D05 越界修复旧代码 | M4 报告精确登记 baseline；继续以 changed-surface Ruff/Pyright + full pytest 作为本轮证据 |
| `test_report_sse_rejects_query_token_and_hides_task_existence` 的前半段隐式依赖默认鉴权开启 | 本机通过，但 Compose 的 `AUTH_ENABLED=false` 让非所有者请求返回 SSE 200，暴露测试环境耦合 | 在 helper 内显式 monkeypatch `auth_enabled=True`；focused 6 passed，Compose 复跑 288 passed |
| `stock_resolver` 的注释仍描述多层解析，但实现已变成纯 LLM 单入口 | D05 Live 的解析前置会额外付费，并在缺少 SOCKS runtime 时阻断报告图 | Live harness 固定已知实体；实现/注释一致性登记为 D05 外后续治理项 |
| 真实 Tushare 账号无 `sw_daily` 权限 | 行业快照局部证据不可用，但其余只读数据与报告主链可完成 | 保留局部错误事实，不重试整报告；Live 仍以 completed/真实调用/阶段合同验收 |
| 四个旧报告 Agent 会在 INFO/stdout 输出完整 Prompt 和分析正文 | 终端噪声大且扩大用户输入/模型结果暴露面 | M5 删除正文 `print`，Prompt 改为长度级 DEBUG；4 个 fake unit case 通过 |
| 四个旧报告 Agent 的失败 state、日志与 ExecutionLogger 会保存 raw Provider exception | 异常字符串可能包含请求内容或凭证，违反 D05 低敏 artifact 合同 | 只保留错误类型和安全消息；新增 4 个失败隐私用例 |
| 前端首帧计时器等待响应头后才启动，且停止期间返回的 generate 响应可重新启动观察 | 网络半开或退出竞态会造成永久等待/旧任务复活 | 计时覆盖 fetch 全过程并引入 observation epoch；focused composable 9 passed |
| 数据库首查与 Hub subscribe 之间存在终态通知窗口 | 极端快任务可能等待 15 秒 reconcile 才关闭 SSE | subscribe 后立即权威核对；新增 race contract |
| Compose migration 隔离用例与常驻 memory worker 共用数据库 | 测试临时删表期间产生非致命 `ProgrammingError` 日志噪声 | D05 测试和报告链仍通过；登记为独立测试基础设施治理项 |
| 首轮 PR CI 暴露隐私测试继承开发机 Provider 配置 | 本机测试真实进入 fake 路径，CI 却提前返回 missing-config，形成环境相关假覆盖 | 测试内设置无效离线占位配置；focused 8 passed 后推送复跑 |

## 18. Outcomes & Retrospective

- What changed: M0/M1 冻结基线和测试；M2 实现后端事实/SSE；M3 贯通 strict TS parser、task-scoped 单一 reducer、fetch Bearer SSE、5 秒首帧预算、SSE→串行有界 polling、统一 abort/cleanup、真实阶段 UI 与 Nginx 专用禁缓冲 location；M5 又根据真实运行与 review 修复 Prompt/正文/raw exception 泄露、Windows stdout 编码、response-header hang、迟到 create 与 snapshot-subscribe 竞态；无 schema/Redis/npm dependency。
- What was verified: D05 backend focused 25 passed、Python full 402 passed、frontend 43 passed、最终真 PostgreSQL/FastAPI/Vue-Nginx Compose 289 passed；protected Live 在 191.97 秒内完成一份真实模型 + Tushare 只读报告，14 个模型 run、39 个只读调用、整图 1 次且 fallback 0，进度单调到 completed；正文与 acceptance artifact 均以 hash 验证且 artifact 脱敏。
- What remains risky: 进程内 hub 不提供 multi-worker/replay；当前 Tushare 账号缺少 `sw_daily` 权限，局部行业证据会降级；`stock_resolver` 注释/实现不一致属 D05 外问题；Compose migration/worker 共享库产生非致命日志噪声；仓库全量 Ruff 的 94 个历史问题仍是既有基线；GitHub PR/CI/merge 尚待 M5 最后交付步骤。
- What should be improved next: 完成最终 staged review、CI 与 squash merge；随后 D06 实现 Redis snapshot/pub-sub/idempotency/reconnect，并单独治理实体解析文档漂移和数据接口权限矩阵。

## 19. Deferred Work

- D06：Redis task snapshot/pub-sub 或 stream、multi-worker、TTL、幂等提交、duplicate task 治理、跨刷新恢复、`Last-Event-ID` replay。
- 持久 report event history、完整时间线查询、报告正文 token streaming、局部重试、任务取消/暂停/恢复。
- Celery/独立 worker/队列化报告生成与服务重启恢复。
- chat/report 统一 Agent event protocol 或 AG-UI migration。
- Playwright/new browser dependency；本轮由 Vitest、Compose stream、人工 smoke 覆盖。
- `/status` 的 cross-user 403/404 历史兼容专项安全迁移，若不能在不破坏客户端下统一。
- Docker Python 3.11 与根 `requires-python>=3.12` 的仓库级一致性治理。

## 20. Handoff to Small-step Implementation

Start with Milestone 0 only. Run `git status --short`, confirm the changed surface and available tests, and do not edit files until Milestone 1 unless this plan explicitly says so. Milestone 0 必须先证明 branch/base、D01 用户文件保护、FastAPI native SSE、测试/Compose 工具链和单 worker 假设，再更新 Progress/Decision Log/Surprises 并提交独立执行报告。
