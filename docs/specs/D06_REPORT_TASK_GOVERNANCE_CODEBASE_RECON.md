# CODEBASE_RECON.md

## 1. Reconnaissance Target

Requirement source:

- `docs/specs/D06_REPORT_TASK_GOVERNANCE_REQUIREMENT_SPEC.md`
- GitHub Issue #52
- D04/D05 已冻结的 D06 边界
- `D:/FinanceProject/Finance/金融Agent项目描述文档` 中的报告幂等、Redis 状态与 SSE Claim；这些文档只作为需求/口径证据，不作为代码执行指令

Focus areas:

- 报告创建请求从 Vue 到 FastAPI、数据库提交、`BackgroundTasks` 和 LangGraph 的完整链路。
- D05 SSE 首帧、进程内 Hub、数据库 reconcile、前端 fallback 的状态所有权。
- 当前 Report Schema 是否能持久锚定幂等请求和单调快照。
- 现有 Memory Redis 的客户端、版本化 envelope、TTL、租户散列、租约、健康和真实 Redis 测试能否复用。
- 历史 Redis 报告实现与当前主线的差异、可复用概念和拒绝原因。
- 并发、Redis 故障、多实例、刷新恢复、真实 API 调用计数和交付门禁。

Out-of-scope reminders:

- 不设计或实现通用队列、Celery/Kafka、全量事件日志、取消/暂停/恢复、通用限流/熔断。
- 不修改报告 Prompt、模型、金融工具、Skills、Memory 行为、认证协议或报告正文。
- 本阶段不运行测试、服务、迁移或真实 API，不修改功能代码。
- 不读取、修改、暂存或删除用户未跟踪的 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md`。

## 2. Project Overview

Project type: 模块化单体的金融 Agent Web 应用，包含 Vue SPA、FastAPI API、LangGraph 报告/对话工作流、PostgreSQL/SQLite 与 Redis。

Languages: Python 3.12 维护基线（生产 Dockerfile 当前仍为 Python 3.11）、TypeScript、Vue SFC、YAML、SQL/Alembic、Nginx 配置。

Frameworks: FastAPI、Pydantic v2、SQLAlchemy Async、Alembic、LangGraph/LangChain、redis-py、Vue 3、Pinia、Axios、Vitest、Pytest。

Runtime / package manager: `uv` + `uv.lock`；前端 `npm` + `package-lock.json`；Docker Compose。

Main service type: 单 FastAPI 进程承担 HTTP、SSE、报告 `BackgroundTasks` 和记忆后台 worker；Nginx 提供 SPA 与 `/api` 反代。

Frontend/backend split: `frontend/src` 负责浏览器状态与 transport；`backend/routers` 负责 API；`backend/application` 目前覆盖 chat/memory/report_progress；报告创建与执行仍分别位于 Router 和 `backend/services/agent_service.py`。

Test framework: Pytest markers 分为 unit/contract/integration/e2e/eval/live；前端使用 Vitest；GitHub Actions 有 Python、前端、镜像/Compose config、Offline Compose E2E 四个默认 Job。

Deployment clues:

- `docker/Dockerfile.backend` 以单个 Uvicorn worker 启动 `backend.main:app`，未配置 Gunicorn 或多 worker。
- `docker/docker-compose.yml` 提供 PostgreSQL、无持久卷的 Redis、单 backend、单 frontend/Nginx。
- `docker/docker-compose.offline.yml` 也只有一个 backend；Redis 与 PostgreSQL 是真实容器，外部模型/工具由 `tests/e2e/offline_app.py` 替换。
- Redis 服务明确关闭 RDB/AOF；现有注释限定其为可重建热缓存。

Confirmed facts:

- 根依赖已锁定 `redis>=8.1,<9`，生产/离线 Compose 使用固定 Redis 7.4.10 Alpine 镜像。
- `backend/config.py` 是 typed Settings 入口；Memory Redis 有 URL、namespace、TTL、租约、single-flight、连接/Socket 超时和连接池配置。
- 报告创建、Report 表与报告 SSE 目前没有 Redis、幂等键、请求指纹、快照版本或跨连接 cursor。
- CI 默认不运行 `live`，protected Live 使用显式环境开关。

Assumptions:

- Assumption: D06 仍保持模块化单体和现有部署方式，不把报告执行迁移到独立任务队列。
- Assumption: 用户的“我授权”覆盖本任务后续的分支、commit、push、PR、受保护真实 API 验收和最终 squash merge；数据库变更仍须在 Clarification/PLAN 中明确到非破坏性范围。

## 3. Directory Structure Summary

| Path | Apparent role | Relevance | Notes |
| --- | --- | --- | --- |
| `backend/routers/report.py` | 报告 REST/SSE 协议适配 | 核心 | 当前也直接拥有创建事务、UUID 和后台调度，边界偏厚。 |
| `backend/schemas/report.py` | 报告 HTTP/SSE Pydantic Schema | 核心 | D05 三类进度帧严格；创建/状态 DTO 仍以宽泛 `str` 为主。 |
| `backend/application/report_progress/` | D05 进度合同、Tracker、Hub、DB 投影 | 核心 | 已预留 `ReportProgressPublisher`，Hub 明确仅单进程。 |
| `backend/services/agent_service.py` | 报告 workflow 装配与后台执行 | 核心 | 更新 Report 后向 publisher 发事件；仍混合遗留 Agent import/日志。 |
| `backend/db/` | ORM、Engine、混合 create_all/Alembic 初始化 | 核心 | Report 是 legacy create_all 表，Memory 新表由 Alembic 管理。 |
| `backend/infrastructure/memory/` | Redis 热缓存与 runtime | 重要参考 | 有安全 key、版本 envelope、租约和健康模式，但合同语义是 Memory fail-open。 |
| `frontend/src/composables/useReport.ts` | 报告创建、SSE、轮询、生命周期 | 核心 | 当前任务引用只在内存；刷新会调用 `beforeunload` 停止观察。 |
| `frontend/src/stores/reportProgressStore.ts` | 单任务单调 reducer | 核心 | 防当前连接内乱序/终态回退；sequence 不能跨连接恢复。 |
| `frontend/src/api/` | Axios 创建/状态 API 与严格 SSE parser | 核心 | 创建请求没有幂等 Header；Axios error interceptor 丢失结构化错误元数据。 |
| `frontend/src/views/ReportView.vue` | 页面输入与任务展示 | 相关 | 按钮仅用 `isGenerating` 防当前页面重复点击。 |
| `tests/unit/report/`、`tests/contract/test_report_progress_contract.py` | D05 进度/安全/协议测试 | 重要参考 | 未覆盖 POST 创建幂等和真实并发。 |
| `tests/integration/test_memory_redis_cache.py` | 真实 Redis TTL/隔离/租约测试 | 重要参考 | 可复用测试装配，不可直接复用 fail-open 业务语义。 |
| `tests/e2e/` | Offline Compose 与 protected Live | 核心验收 | D05 Live 预插 Report 并直接调用 service，未经过创建接口。 |
| `docker/`、`.github/workflows/` | 部署与验证门禁 | 核心验收 | 当前单 backend，D06 双实例需扩展隔离测试拓扑或等价装配。 |
| `D:/FinanceProject/Finance/backend/...` | 历史实现证据 | 只读参考 | 与远端历史分支 `origin/feature/redis-integration-phase1` 基本一致，禁止作为运行时依赖。 |

## 4. Entry Points

### 4.1 Startup Entry

- Confirmed: `docker/Dockerfile.backend` 运行 `uvicorn backend.main:app --host 0.0.0.0 --port 8000`。
- Confirmed: `backend/main.py::lifespan` 先 `init_db()`，再初始化 Memory Redis cache、Trace、Auth seed 和 STM/LTM/semantic workers。
- Confirmed: 报告没有独立 runtime 初始化或关闭钩子；`report_progress_hub` 在模块导入时构造为进程全局对象。
- Confirmed: Memory Redis 初始化失败只记录 `DEGRADED`，不会阻止应用启动；`/api/health` 只公开 `memory_cache` 和 `memory_observability`。

### 4.2 Request / Task Entry

- Browser entry: `ReportView.handleGenerate()` → `useReport.generateReport(command)`。
- HTTP entry: `reportApi.generate()` → `POST /api/report/generate`。
- Backend entry: `backend/routers/report.py::generate_report()`。
- Background execution entry: FastAPI `BackgroundTasks.add_task(run_report_task, ...)`。
- Progress entry: `GET /api/report/events/{task_id}`；失败后调用 `GET /api/report/status/{task_id}`。
- Final result entry: `GET /api/report/{report_id}`；历史、下载、删除是相邻兼容边界。

## 5. Relevant Call Chain

```text
ReportView.handleGenerate(command)
-> useReport.generateReport(command)
-> reportApi.generate(command, userId)
-> POST /api/report/generate
-> require_auth + ensure_user_access + _ensure_user
-> 为每次请求生成新的 task_id/report_id
-> INSERT reports(status=pending, progress=0) + COMMIT
-> BackgroundTasks.add_task(run_report_task, command, user_id)
-> HTTP 返回 ReportTaskResponse
-> useReportProgressStore.begin(task_id, report_id)
-> fetch GET /api/report/events/{task_id} with Bearer header
-> _require_sse_snapshot 从 PostgreSQL验证任务/所有权
-> _report_event_stream:
   subscribe 当前进程 ReportProgressHub
   -> stream_ready(DB status/progress + 当前进程 stage map)
   -> 消费当前进程 stage/terminal 通知
   -> 每 15 秒从 PostgreSQL reconcile 终态
-> run_report_task:
   Report pending -> running
   -> resolve_stock + LangGraph astream_events
   -> ReportProgressTracker 将白名单节点转为阶段/进度
   -> 每次先 COMMIT progress，再 publish 到当前进程 Hub
   -> completed(content)/failed(safe message) COMMIT
   -> publish 唯一 terminal
-> Browser strict parser + Pinia monotonic reducer
-> SSE 失败/提前结束/超时
   -> 串行 bounded polling GET /status/{task_id}
-> terminal
   -> GET /report/{report_id}
   -> Markdown 渲染/历史/下载
```

Confirmed segments:

- `generate_report()` 每次无条件生成两个新 UUID，并在注册后台任务前提交 Report。
- 后端没有请求幂等 Header/字段，也没有按用户/请求的唯一数据库约束。
- `BackgroundTasks` 接收完整原始 `command`，调度身份只存在于当前应用进程。
- `run_report_task()` 使用独立短会话更新 Report；找不到 Report 时 `_update_report()` 静默跳过，但 workflow 仍继续执行。
- D05 阶段通知始终在相应 progress commit 之后发布；发布失败不改变报告成败。
- SSE 初始授权依赖 PostgreSQL；跨用户或不存在任务在流建立前返回安全 404。
- SSE `sequence` 每次连接从 1 重新开始；前端注释也明确“不用于跨连接重放”。
- Hub 的 stage map 只在当前进程中存在，并在 terminal publish 时删除。
- 前端 `beforeunload` 会停止观察，但不保存活动任务/命令引用；刷新后 `ReportView` 只加载历史列表。

Inferred segments:

- Inferred: 创建响应丢失后浏览器重试 POST 会创建第二条 Report 并启动第二次 workflow，因为服务端没有任何重放识别点。
- Inferred: 若报告执行位于实例 A 而 SSE 位于实例 B，B 只能看到数据库的总 progress/terminal；不会收到阶段 map，最快 15 秒 reconcile，且非终态进度变化不会被周期 SSE 帧主动发送。
- Inferred: 进程在 Report commit 后、后台任务完成前崩溃时，pending/running 任务没有恢复 worker；D06 若不引入队列只能恢复观察状态，不能保证执行续跑。

Unknown segments:

- 当前用户是否需要“10 分钟内主动重建完全相同报告”的产品能力。
- 实际部署是否计划启用多个 Uvicorn worker/容器；仓库配置仅证明单实例。
- 删除一个仍运行的 Report 后，业务期望是继续计算、拒绝删除还是取消；D06 Requirement 未扩展取消语义。

## 6. Related Files

### 6.1 Definitely Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/routers/report.py` | 创建、状态、SSE、历史/详情 | 当前幂等缺口和 D05 reconnect 均在此入口 | candidate modification | High |
| `backend/schemas/report.py` | 公开创建/状态/事件合同 | 需表达创建/重放/冲突和恢复元数据 | candidate modification | High |
| `backend/application/report_progress/contracts.py` | 内部稳定进度合同 | D06 快照版本和跨实例通知需与它一致 | candidate modification | Medium |
| `backend/application/report_progress/hub.py` | 单进程 latest-event Hub | 当前明确不跨进程，是 D06 适配边界 | candidate modification or replacement | High |
| `backend/application/report_progress/snapshot.py` | DB 安全状态投影 | 当前没有 stage/version/updated time | candidate modification | Medium |
| `backend/services/agent_service.py` | Report 状态提交与事件发布 | 唯一执行、快照发布和 crash window 的关键调用方 | candidate modification | High |
| `backend/db/models.py` | Report 权威表与 Alembic managed 表清单 | 当前没有幂等/版本锚点 | candidate modification | High |
| `backend/config.py`、`backend/.env.example` | typed config 和安全说明 | D06 Redis TTL/开关/超时需要单一入口 | candidate modification | High |
| `backend/main.py` | runtime 生命周期和 health | D06 Redis client/publisher 需集中装配/关闭 | candidate modification | High |
| `frontend/src/api/index.ts` | 创建/状态公开调用 | 当前没有幂等信息和结构化冲突错误 | candidate modification | High |
| `frontend/src/composables/useReport.ts` | 用户意图、创建重试、刷新恢复 | 当前只防页面内二次点击且不跨刷新 | candidate modification | High |
| `frontend/src/stores/reportProgressStore.ts` | 单调任务状态 | 需合并跨连接 snapshot version | candidate modification | Medium |
| `docker/docker-compose.offline.yml` | 真实隔离 E2E | 当前单 backend，不能证明跨实例 | candidate modification | Medium |
| `.github/workflows/ci.yml` | 默认交付门禁 | 触达新报告模块需纳入 Ruff/Pyright/Compose import | candidate modification | Medium |

### 6.2 Probably Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/infrastructure/memory/redis_cache.py` | 现有 Redis 安全实现 | 可提取通用 client/envelope/key/health 规则，但不能把报告塞进 Memory 业务端口 | read-only reference / narrowly refactor if justified | High |
| `backend/infrastructure/memory/runtime.py` | Redis 连接生命周期 | 证明集中装配模式；当前全局对象是 Memory 专用 | read-only reference | High |
| `backend/application/memory/cache.py` | typed cache 合同 | 可复用状态/错误命名思路，不复用 fail-open 业务含义 | read-only reference | Medium |
| `backend/migrations/versions/` | Alembic 模式 | 若需要权威幂等表/约束，必须新增独立 revision | candidate modification | High |
| `backend/db/migration_runner.py`、`backend/migrations/env.py` | 迁移入口/安全降级 | 任何 Schema 方案必须兼容启动迁移与隔离 downgrade | read-only or candidate modification only if proven | High |
| `backend/middleware/auth.py` | 身份和资源隔离 | 不改认证协议，但所有幂等/快照入口必须复用它 | read-only | High |
| `frontend/src/views/ReportView.vue` | 页面按钮与刷新入口 | 需要展示重放/冲突/恢复状态时可能触达 | candidate modification | Medium |
| `frontend/src/components/report/ReportProgress.vue` | transport/恢复提示 | 可能新增恢复/降级标签 | candidate modification | Low |
| `docker/nginx/default.conf` | SSE 反代 | 若路径不变应保持；跨实例能力不能靠当前单 upstream 证明 | read-only / test | High |
| `tests/e2e/offline_app.py` | 确定性报告 workflow | 可计数唯一调度并提供双实例测试 app | candidate modification | Medium |
| `tests/e2e/test_live_report_progress.py` | D05 protected Live | 已有真实模型/Tushare审计，可扩展为 D06 创建重放验收 | candidate modification | High |

### 6.3 Supporting Context

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `tests/unit/report/*` | Tracker/Hub/service 基线 | 保护 D05 单调/发布顺序与隐私 | candidate test modification | Low |
| `tests/contract/test_report_progress_contract.py` | REST/SSE 安全合同 | 保护 auth、首帧、终态和错误脱敏 | candidate test modification | Medium |
| `tests/integration/test_memory_redis_cache.py` | 真实 Redis harness | 已证明 TTL、损坏、租约 fencing、12 并发 single-flight | read-only reference | Medium |
| `frontend/src/**/__tests__/*report*` | Parser/store/composable/UI tests | 已覆盖 D05 超时、fallback、cleanup、迟到创建响应 | candidate test modification | Low |
| `tests/e2e/test_report_progress_offline_contract.py` | Nginx→FastAPI→DB→SSE 旅程 | 可扩展幂等/恢复断言 | candidate test modification | Medium |
| `pyproject.toml`、`uv.lock` | 运行/测试依赖 | Redis 已存在，无需默认新增依赖 | read-only unless lock truly changes | High |
| `docker/docker-compose.yml` | 常规运行拓扑 | Redis 无持久化、单 backend、backend 不等待 Redis health | candidate configuration modification | High |
| `README.md`、D06 specs | 可运行口径与证据 | 最终必须只声明已验证能力 | candidate documentation modification | Low |
| `origin/feature/redis-integration-phase1` | 历史报告 Redis 实现 | 提供被拒绝 baseline 和局部概念证据 | read-only | High |

### 6.4 Out of Scope

| Path / Area | Reason |
| --- | --- |
| `Financial-MCP-Agent/src/agents/`、Prompt 和金融工具 | D06 不改变研究质量、模型决策或 Provider 业务逻辑。 |
| `Financial-MCP-Agent/src/conversation/`、chat router/UI | 对话 D03/D04 仅做回归，不迁移其控制卡状态。 |
| `Financial-MCP-Agent/src/skills/` | Skills 已单独交付，D06 不改发现/路由/执行。 |
| Memory 业务/Schema/Worker | 只读借鉴 Redis/幂等模式，不改变记忆语义或 key。 |
| Auth token/JWT 协议 | 继续复用 Bearer header 和现有所有权检查。 |
| 报告删除/取消/队列/重试 Worker | 除兼容回归外不扩大到任务取消或 crash 后续跑。 |
| `D:/FinanceProject/Finance` | 只能作为历史证据，不可 import、复制为运行时依赖或直接修改。 |
| `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` | 用户未跟踪文件，不属于 D06。 |

## 7. Existing Patterns to Reuse

| Pattern | Example file | Why reuse it |
| --- | --- | --- |
| PostgreSQL 是权威、Redis 是版本校验后的派生快照 | `backend/infrastructure/memory/redis_cache.py` | 已实现 schema/version/owner/resource 双重校验、损坏删除和回源。 |
| Redis 标识散列与业务 namespace | 同上 `_key()` / `_ref()` | 避免历史实现把原始 user ID 写入 key。 |
| SET NX EX + owner token + compare-delete | `RedisMemoryHotCache.acquire_fill_lease/release_fill_lease` | 可参考原子 claim/fencing；报告幂等不能直接套用短缓存 lease 语义。 |
| PostgreSQL unique constraint + 精确 IntegrityError 分类 | `backend/infrastructure/memory/repository.py::enqueue_outbox` | 可证明跨实例唯一性，且不吞掉其他完整性错误。 |
| 乐观版本/CAS | `SqlAlchemyMemoryRepository.apply_working_state` | 可参考快照单调推进和 stale reject。 |
| DB commit 后再发 best-effort 通知 | `run_report_task::_record_stage` | 保证缓存/通知不反转权威事务。 |
| 类型化且协议无关的 publisher port | `ReportProgressPublisher` | D06 infrastructure 可替换/组合发布器而不把 Redis 传进 Agent 节点。 |
| SSE 先订阅后首帧、立即 reconcile、周期 DB 收敛 | `backend/routers/report.py::_report_event_stream` | 已修复两类终态竞态，D06 应保留。 |
| 严格前端 allowlist parser + 单一 reducer | `reportProgress.ts`、`reportProgressStore.ts` | 防未知/敏感字段污染，保持终态单调。 |
| 显式 transport cleanup/epoch 隔离 | `useReport.ts` | 防迟到帧、旧任务和计时器污染恢复任务。 |
| 真实 Redis 隔离 namespace 与 finally cleanup | `tests/integration/test_memory_redis_cache.py` | D06 集成测试可复用可靠装配方式。 |
| Protected Live 只计数、不保存正文/Prompt | `tests/e2e/test_live_report_progress.py` | 已有真实模型 run、Tushare 白名单、hash 和秘密扫描。 |
| 历史命令规范化与轻量状态值 | `origin/feature/redis-integration-phase1` | 概念可参考；旧实现的短 hash、Redis-only/fail-open 和 untyped dict 不可直接迁移。 |

历史实现拒绝直接复用的确认事实：

- 以 `user_id + normalized command sha256[:16]` 作为隐式幂等身份，固定 TTL 600 秒。
- Redis unavailable 时 fail-open 创建新任务；占位命中但 3 秒读不到正式任务也创建新任务，不能保证唯一执行。
- Redis 是唯一幂等记录；服务重启/TTL 丢失后无数据库锚点。
- 原始 user ID 进入 Redis key；状态值是无严格 schema 的 dict。
- 状态 API 先信任 Redis 中的 `user_id` 并可不查数据库；不符合“DB 先授权、Redis 后加速”。
- SSE 使用 query token、进程内 untyped queue；当前 D05 已用 Bearer fetch-stream 和严格协议替代。
- 并发测试使用 FakeRedis/FakeSession，没有真实 PostgreSQL、真实 Redis、双实例或真实 workflow 调用计数。

## 8. Data Flow and State

### 8.1 Input Data

- Current HTTP body: `{command: str, user_id: str}`；`command` 只有 required，没有最小/最大长度和规范化合同。
- Current auth: Bearer token → `AuthContext.user_id`；auth disabled 时使用请求体 user ID。
- Current frontend: Axios POST，没有 `Idempotency-Key` 或 request fingerprint。
- Interview Claim evidence: 文档声称 `user_id + command hash`、`SET NX EX`、10 分钟内相同问题复用同一任务。

### 8.2 Intermediate State

- Router 临时生成 `task_id/report_id`，没有显式 command/request object 或 idempotency result。
- `BackgroundTasks` 保存 `command`、IDs、user ID 并在响应后调用 service。
- `ReportProgressTracker` 内存保存 running/completed nodes、stage statuses、current progress。
- `ReportProgressHub` 内存保存 task→subscribers/stages；队列容量 32，慢消费者丢旧保新。
- Browser 保存 `observationEpoch`、AbortController、reader、timers 和当前 Pinia task；均不跨刷新。

### 8.3 Persistent State

- `reports`: id、user/session、task ID(unique)、stock/company、Markdown content、status、progress、raw-safe error、created_at。
- Missing in Report: request/idempotency identity、command fingerprint、snapshot version、stage states、updated_at、dispatch/lease 状态、attempt/owner。
- Report 目前由 `Base.metadata.create_all` 管理，不在 `ALEMBIC_MANAGED_TABLE_NAMES` 中。
- Redis 当前只保存 Memory context/working/profile 派生值和短租约；不保存报告状态。
- Redis 容器无 RDB/AOF，任何 D06 值必须可从数据库重建。

### 8.4 Output Data

- Create: `{task_id, report_id, status}`，不能区分首次创建与重放。
- Status: task status/progress，completed 时返回 report ID，failed 时返回安全 code/message。
- SSE: `report-progress-v1` 的 `stream_ready`、`stage_update`、`task_terminal`；连接级 sequence。
- Final report: DB Markdown 正文，仅通过详情/下载返回，不进入 SSE。
- Frontend: 当前状态、进度、阶段、transport 状态和最终报告。

### 8.5 Potential Data Mismatch Points

1. Redis snapshot 若没有 DB 版本锚点，可能比 Report 终态陈旧。
2. 只存 Report `progress` 不能重建完整阶段 map；D05 首帧跨实例会丢 stages。
3. 每连接 sequence 重置，刷新后前端无法比较新旧连接事件。
4. DB commit 成功但 BackgroundTask 未执行/进程崩溃，会留下 pending；Redis 不能修复执行本身。
5. 后台 workflow 执行中 Report 被删除，后续 DB 更新静默跳过但模型/工具仍可能继续。
6. 前端创建响应丢失，没有 task ID 时仅加载历史；相同 POST 会新建任务。
7. Axios interceptor 只抛 `Error(message)`，会丢失 HTTP 409、稳定错误码和 idempotency result。
8. 历史文档的“相同用户+问题 Hash 10 分钟复用”与 Requirement 中“用户意图级外部 key、主动新建使用新 key”不是同一产品语义，必须在 Clarification 对齐。

## 9. External Dependencies

| Dependency | Where called | Input | Output | Error handling / fallback |
| --- | --- | --- | --- | --- |
| PostgreSQL/SQLite | report router/service/ORM | user/task/report 状态 | 权威任务和 Markdown | Router commit 异常向上抛；service 更新找不到行会静默跳过。 |
| Redis | 当前仅 Memory runtime/cache | 散列用户/资源、版本 envelope | 热缓存、短租约、health metrics | Memory 语义 fail-open；D06 correctness 语义未定义。 |
| LangGraph | `agent_service._get_workflow/run_report_task` | 完整 command/user context | 节点事件与最终 state | workflow 失败写安全 failed；events 无根输出时会整图 `ainvoke` fallback。 |
| OpenAI-compatible model | 历史报告 Agents | Prompt/context | 分析与汇总文本 | Provider 细节在报告 Agent；D05 Live 有 run 计数和 12 分钟总预算。 |
| Tushare/MCP | 报告 Agents/tools | 股票与财务查询 | 只读金融数据 | D05 Live 使用白名单审计；D06 不改工具逻辑。 |
| Nginx | `docker/nginx/default.conf` | `/api/report/events/*` | 无缓冲 SSE | connect 15s、send/read 300s；不提供多实例总线。 |
| Browser storage | auth token only | JWT | Authorization header | 报告任务/幂等状态当前不持久化。 |
| GitHub Actions | `.github/workflows` | repo/lock/config | 质量与 E2E结果 | 默认全离线；live workflow 当前只跑 controlled chat，不跑 report live。 |

## 10. Tests and Evaluation Assets

### 10.1 Existing Tests

- D05 backend unit: Tracker 并行完成单调性、Hub 慢消费者/cleanup、service DB-before-publish、失败脱敏。
- D05 contract: 三类严格帧、完成/运行/竞态 SSE、Bearer/404 隔离、status 兼容与安全失败。
- D05 frontend: parser、Pinia 单调 reducer、Bearer fetch SSE、首帧/响应头超时、畸形/提前结束 fallback、有界 polling、cleanup、迟到 create response。
- D05 Offline Compose: Nginx→FastAPI→真实 PostgreSQL→确定性 LangGraph→SSE→最终报告。
- D05 protected Live: 真实 LangGraph/模型/只读 Tushare、模型/tool 调用计数、报告 hash、secret scan；但预创建 Report 并直接调用 `run_report_task()`。
- Memory Redis integration: 真实 Redis TTL、隔离、损坏、不可达、租约 fencing、12 并发 single-flight。
- Memory migration/outbox tests: PostgreSQL unique idempotency、row locks、lease/retry/rollback 的成熟参考。

### 10.2 Coverage Gaps

- 没有当前主线 POST `/generate` 的 unit/contract 测试。
- 没有顺序/并发重复提交、同键异请求、跨用户同键、创建响应丢失测试。
- 没有真实 PostgreSQL + Redis 的报告幂等集成测试。
- 没有双 FastAPI 实例共享 DB/Redis 的创建与 SSE 恢复测试。
- 没有 Redis timeout/restart/expiry/corrupt/stale 对报告任务的故障注入。
- 没有证明 workflow/model/tool 只执行一次的 HTTP/Compose/Live 重放测试。
- 没有刷新后恢复活动报告任务的前端/浏览器测试。
- 没有报告 Redis key/value/log/artifact 的敏感字段扫描。
- 当前 Offline Compose 单 backend，不能声称跨实例。
- 当前 protected Live workflow 未纳入 report live；本地命令存在，但 GitHub 手动 workflow 只执行 chat live。

### 10.3 Candidate Test Locations

- `tests/unit/report/test_report_idempotency.py`: 规范化、指纹、结果/错误、状态机。
- `tests/contract/test_report_task_governance_contract.py`: Header/响应/409/ownership/compatibility。
- `tests/integration/test_report_task_governance.py`: real PostgreSQL + Redis 并发、TTL、故障、版本。
- `tests/unit/report/test_progress_hub.py` 或新 infrastructure test: shared snapshot/notification adapter。
- `frontend/src/api/__tests__/reportTaskContract.spec.ts`: 创建/冲突/恢复 parser。
- `frontend/src/composables/__tests__/useReport.governance.spec.ts`: key 生命周期、网络重试、刷新恢复、logout cleanup。
- `frontend/src/stores/__tests__/reportProgressStore.spec.ts`: 跨连接 snapshot version 与 stale reject。
- `tests/e2e/test_report_task_governance_offline.py`: 双实例/Redis/PostgreSQL/Nginx 完整旅程。
- `tests/e2e/test_live_report_progress.py`: 从创建用例提交两次并断言一次真实执行。

### 10.4 Visible Test Commands

- `uv lock --check`
- `uv run --locked ruff check <maintained scope> tests`
- `uv run --locked pyright <maintained scope> tests`
- `uv run --locked pytest backend -q`
- `uv run --locked pytest Financial-MCP-Agent -q -m "not live"`
- `uv run --locked pytest tests/evals -q -m "eval_smoke and not live"`
- `uv run --locked pytest -q`
- `npm run lint && npm run type-check && npm run build && npm run test -- --run`
- `docker compose -f docker/docker-compose.yml config --quiet`
- `docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e`
- Protected report live: `RUN_PROTECTED_LIVE_REPORT_E2E=true uv run --locked --with socksio python -m pytest tests/e2e/test_live_report_progress.py -q -m live`

## 11. Logging and Observability

### 11.1 Existing Logs

- D05 SSE 记录 open/close、task/report、transport、status、elapsed；DB reconcile 记录稳定错误码和异常类型。
- Report service 记录解析成功/降级、publish failure、workflow failure；D05 测试证明原始 command/provider error 不进入这些记录。
- Memory Redis 记录 stage/status/error_code/error_type，并提供 hits/misses/stale/malformed/errors/leases 指标。
- Live artifact 记录 provider/model 名、调用计数、阶段序列、耗时、终态和正文 hash，不保存正文/Prompt。

### 11.2 Missing Logs

- 没有报告 create/replay/conflict/in-progress/recovery 的稳定事件。
- 没有 request/idempotency digest、snapshot version、Redis source/degradation、unique dispatch 关联。
- Report 没有统一 trace ID 与 create→workflow→SSE 的持久关联。
- `/api/health` 没有 report task governance 组件状态/指标。
- 前端没有恢复来源、创建重放或冲突的可观察状态。

### 11.3 Observability Risks

- `run_report_task` 仍有 f-string 日志，包含 execution directory 和 report length；不是 D06 秘密，但格式与稳定字段不完整。
- 历史 Redis 分支打印 key prefix、使用原始 user ID key；不能迁移。
- 原始幂等键/command hash 若直接进入日志或 Redis key，会形成可关联用户行为数据。
- 若 Redis Pub/Sub 消息包含完整 command/Report content，会突破 D05 白名单边界。
- 当前 ExecutionLogger 是全局 runtime；并发真实报告可能共享/竞争 artifact 上下文，D05 已记录但 D06 不应顺带重构。

### 11.4 Output-channel Separation

| Channel | Current implementation | Stable fields / format | Redaction | Gaps |
| --- | --- | --- | --- | --- |
| User/API result | Pydantic Report REST + strict SSE frames | task/report/status/progress/stage/sequence | SSE 无正文/Prompt，failed 使用安全消息 | 无幂等结果、快照版本、结构化冲突。 |
| Terminal progress | `backend/main.py` 多处 `print` | 自由文本 | 部分异常类型化，仍有原异常 print | D06 不应新增 raw key/command；现有终端基线 Partial。 |
| Logs | module/logger + legacy setup_logger | D05 有 stage/task/status/error/elapsed | D05 report failure已脱敏 | create/replay/recovery/Redis fields 缺失，部分 f-string。 |
| Traces | Skill Trace/Memory Trace 为主 | trace/workflow/stage | 有 key-based redaction | Report create/progress 未形成统一 Trace 合同。 |
| Artifacts | ExecutionLogger + Live acceptance JSON | execution ID、report hash、counts | Live 有 secret scan | 并发全局 logger 风险；D06 artifact尚无格式。 |

## 12. Engineering Baseline Recon

| Area | Status | Evidence | Gap / implication |
| --- | --- | --- | --- |
| API/orchestration/domain/infrastructure boundaries | Partial | D05 `application/report_progress` 清晰；但 `report.py::generate_report` 直接 UUID/DB/调度，`agent_service.py` 混合 workflow 和 persistence | D06 不应把 Redis 命令继续堆进 Router；需建立唯一应用用例/端口。 |
| Agent/workflow/tool/prompt/model/memory/evaluation boundaries | Partial | D05 publisher 不依赖 HTTP；外部 Providers 在 Agent；Memory Redis 独立 | 报告 workflow 仍在 legacy service，且全局 logger/runtime 有并发风险。 |
| Docstrings, types, and key intent comments | Partial | D05 新模块中文 docstring/Enum/dataclass 完整 | Report create/status DTO、router return、DB model 与部分 legacy 函数类型/合同较弱。 |
| File-section navigation vs module separation | Partial | Router 有业务 section，D05 progress 已拆包 | Router 同时处理创建、查询、SSE、历史、下载、删除；新增治理应避免继续混责。 |
| Typed configuration and secret handling | Established for current Redis | `Settings` 校验 Redis URL/namespace/timeouts，`.env.example` 安全占位 | 设置命名是 Memory cache 语义；D06 参数和开关尚不存在。 |
| Error, retry, fallback, and state semantics | Partial | D05 有单调/终态/安全失败和有界前端 fallback；Memory cache 有 timeout/损坏降级 | 报告创建无幂等/并发/crash 状态；Redis 故障的正确性策略未冻结。 |

## 13. Risk Areas

| Area | Why risky | Likely touched? | Recommended handling |
| --- | --- | --- | --- |
| Auth/tenant isolation | 幂等命中或快照可能泄露他人任务存在性 | Yes | 每次先查 DB 权威所有权；相同外部 key 按用户隔离；401/404/409 contract test。 |
| Database schema/migration | Report 是 legacy create_all 表，当前 Alembic 只管理 Memory 新表 | Maybe | 优先独立非破坏性表/约束；真实 upgrade/downgrade/re-upgrade 与 legacy rows 验证。 |
| Concurrency/duplicate billing | 两个实例可同时创建并调用多个付费模型/工具 | Yes | PostgreSQL 原子唯一性为最终锚点，真实 barrier 并发和调用计数测试。 |
| Redis cache invalidation | 陈旧/过期/损坏可能回退终态或错误授权 | Yes | 版本 envelope、DB 校正、TTL/重启/损坏测试；Redis 不作 auth authority。 |
| BackgroundTasks crash window | API 返回后进程退出会留下 pending | Partially | 明确 D06 只治理观察/唯一调度还是也恢复执行；不隐含宣称队列级可靠性。 |
| External API cost/rate limit | 重复执行直接放大真实模型与 Tushare调用 | Yes | 默认 fake，protected Live 一个权威任务，两次提交只重放；失败即停。 |
| Privacy | command/hash/key 可反推用户研究意图 | Yes | HMAC/不可逆摘要、hash owner ref、白名单 snapshot、secret/privacy scan。 |
| Public API compatibility | 新 header/字段/409 影响旧客户端 | Yes | 可选输入、向后兼容字段、官方前端增量采用、OpenAPI contract。 |
| Multi-instance SSE | Pub/Sub 可丢，订阅/首帧竞态复杂 | Yes | subscribe-before-snapshot + DB/snapshot reconcile，Pub/Sub 只加速。 |
| Production configuration | Redis 当前不持久化且 backend 不依赖其 health | Yes | 不把 availability 假设写死；typed timeout/health 和显式 failure strategy。 |
| Report delete vs running task | 删除行后 workflow 仍可能花费资源且不落库 | No by default | 作为剩余风险记录；除非 Clarification 扩大范围，否则只做兼容回归。 |
| Global ExecutionLogger | 并发报告 artifact 可能竞争 | No by default | D06 测试观察但不顺带重构；发现实证故障则单独升级为 blocker/任务。 |
| Runtime Python mismatch | pyproject 3.12，生产 Docker 3.11 | Indirect | 新代码保持 3.11 可解析语法，Compose import 必测，不在 D06 升级镜像。 |

## 14. Unknowns and Assumptions

### 14.1 Unknowns From Missing Code Access

- None for the main D06 paths. 当前仓库、历史分支和历史 `Finance` 相关实现均可读。
- 外部生产部署拓扑、真实负载和 Redis HA 配置不在仓库中，不能从代码证明。

### 14.2 Unknowns From Incomplete Requirement

- 幂等身份究竟严格采用面试文档的“用户 + command hash、10 分钟”，还是采用客户端 `Idempotency-Key` + 服务端请求指纹。
- 用户主动在 10 分钟内生成相同问题的新报告是否应被允许。
- Redis 故障时，面试文档允许“重复任务风险上升”的 fail-open，D06 Requirement 则要求 correctness-first；两者需统一。
- “断线恢复”是恢复最新 snapshot 与后续事件，还是必须支持 `Last-Event-ID` 全量历史重放。
- 是否把创建后进程崩溃的 pending task 重新执行纳入 D06；这会接近持久任务队列。
- 是否允许新增 Alembic 管理的 report command/idempotency 表。

### 14.3 Unknowns From Ambiguous Architecture

- 报告 Redis 应使用独立 runtime/client，还是把当前 Memory 专用 runtime 抽成共享 connection 基础设施。
- 唯一 dispatch 的持久状态应附着 Report，还是独立 command/task receipt 表。
- 跨实例通知采用 Redis Pub/Sub、仅 Redis snapshot + DB polling，还是最小 Streams；当前代码没有既定模式。
- snapshot version 由数据库列、时间戳还是独立状态记录驱动；Report 当前无 updated_at/version/stages。
- 前端刷新恢复通过 route/report ID、sessionStorage/localStorage 还是同命令重放找回；当前路由 `/report` 无任务参数。

### 14.4 Assumptions

- Assumption: Redis 保持可丢、无 AOF/RDB，所有权威幂等事实与终态可由 PostgreSQL恢复。
- Assumption: D06 不承诺跨崩溃继续执行未完成 workflow，只保证不会重复执行且能恢复已提交状态；若用户要求队列级续跑，应另立任务。
- Assumption: 当前 D05 `report-progress-v1` 可以兼容增加可选 snapshot metadata，或以 v2 版本化；不能静默破坏严格 parser。
- Assumption: 历史实现只允许概念级复用，任何代码迁移都必须重新分层、类型化、脱敏并通过当前门禁。

## 15. Handoff to Next Step

Next step should use the Requirement Clarification Skill and produce `D06_REPORT_TASK_GOVERNANCE_CLARIFICATION_QUESTIONS.md`.

It should clarify:

- 以面试 Claim 为准的 `user_id + command hash + 600s` 是否是最终产品合同，或是否引入显式 `Idempotency-Key`；若选择更强工程方案，哪些面试文档必须同步改口径。
- Redis 故障是 fail-open、fail-closed，还是由 PostgreSQL 唯一约束继续正确服务。
- PostgreSQL 持久幂等锚点和非破坏性 Alembic 迁移授权。
- 恢复目标是 latest snapshot 还是完整 event replay；Pub/Sub/Streams 的范围。
- D06 是否只保证任务观察/去重，不保证 `BackgroundTasks` 崩溃续跑。
- 前端活动任务的安全持久化位置、登出清理和主动重复生成语义。
- TTL、进行中续期、已完成保留、冲突 HTTP 状态和旧客户端兼容。
- 多实例/并发/Redis restart/Live 的精确验收预算。

It should consider these files/modules in later solution design:

- `backend/routers/report.py`、`backend/schemas/report.py`
- `backend/application/report_progress/*`、潜在的独立 report task application/domain/infrastructure boundary
- `backend/services/agent_service.py`
- `backend/db/models.py`、`backend/migrations/versions/*`、迁移 runner
- `backend/config.py`、`backend/.env.example`、`backend/main.py`
- `backend/infrastructure/memory/redis_cache.py` 只作为模式参考
- `frontend/src/api/index.ts`、`useReport.ts`、`reportProgressStore.ts`、`ReportView.vue`
- report unit/contract/integration/frontend/E2E/live tests、Docker/CI/README

It should require explicit user approval before modifying these high-risk areas:

- 数据库 Schema/Alembic revision、Redis runtime/生产配置、公开创建 API/错误合同、认证/所有权代码、真实 API 调用与最终 GitHub merge。
- 当前用户已给出本轮总体授权，但 Clarification/PLAN 仍必须把上述改动范围和回滚路径写成可审查的冻结决定；不得把总体授权解释为允许破坏性迁移、生产写入或扩大到队列/取消/通用治理。
