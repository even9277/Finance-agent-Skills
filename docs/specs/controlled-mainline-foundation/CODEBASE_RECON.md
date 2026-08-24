# CODEBASE_RECON.md

## 1. Reconnaissance Target

Requirement source:

- `docs/specs/controlled-mainline-foundation/REQUIREMENT_SPEC.md`
- 用户关于“先完善基础设施、统一 AGENTS.md、测试/集成、目录与命名，再小步迁移受控主链”的要求。
- `Finance/金融Agent项目描述文档/` 中的统一项目口径与模块说明。

Focus areas:

- 确认当前真正可运行的前端、后端与对话 Agent 入口。
- 对照主仓库、历史 `Finance` 实现和项目描述，识别工程基线及受控主链缺口。
- 盘点目录所有权、配置、外部依赖、测试、CI、Docker、日志、Trace、Langfuse 和 GitHub 门禁。
- 为下一步澄清“目录方案、质量工具、CD 边界、Live E2E 与 Code Review”提供事实。

Out-of-scope reminders:

- 本阶段只读勘察，不迁移业务模块，不修改公共 API、数据库结构、生产配置或 GitHub 设置。
- `Finance` 只作历史证据源，不作为可直接合并的目标代码。
- 不读取或输出本地 `.env` 中的真实凭证。

## 2. Project Overview

Project type:

- Confirmed：一个前后端分离的金融 Agent 全栈单体仓库，同时包含对话模式、报告模式、记忆、金融 Skills、MCP 子项目与评测资产。

Languages:

- Python、TypeScript/Vue、SQL、YAML、Dockerfile、Markdown。

Frameworks:

- 后端：FastAPI、Pydantic v2、SQLAlchemy Async、LangChain/LangGraph。
- 前端：Vue 3、Pinia、Vue Router、Axios、Vite、TypeScript。
- Agent/外部能力：OpenAI-compatible API、Google GenAI、Tushare、MCP、Mem0/pgvector 相关代码、Langfuse。

Runtime / package manager:

- Python 3.12（CI），后端依赖由 `backend/requirements.txt` 管理。
- Node 20（CI），前端使用 npm 与 `package-lock.json`。
- MCP 子项目单独使用 `uv` 与 `uv.lock`。
- Confirmed gap：主 Python 应用没有统一 lockfile；根 `pyproject.toml` 目前只配置 pytest。

Main service type:

- FastAPI 单体后端；Vue/Nginx 前端；PostgreSQL/pgvector 容器；报告模式运行 LangGraph；对话模式运行自研服务编排和 Skill 链。

Frontend/backend split:

- Confirmed：`frontend/` 与 `backend/` 分离，通过 `/api` REST 和 `/api/chat/stream` WebSocket 通信。

Test framework:

- Python：pytest 能发现 unittest 测试；Agent live 测试通过 pytest marker 隔离。
- 前端：当前只有 `vue-tsc` 类型检查和 Vite build，未发现 Vitest/Playwright 测试。

Deployment clues:

- `docker/docker-compose.yml` 可启动 PostgreSQL、Backend、Frontend 和 pgAdmin。
- Dockerfile 使用 Python 3.12 与 Node 20 多阶段构建。
- 当前未发现正式 staging/production 发布工作流、镜像仓库推送或云平台部署定义。

Confirmed facts:

- Git 主仓库是 `even9277/Finance-agent-Skills`，默认分支为 `main`，公开仓库。
- GitHub 当前允许 merge commit、rebase 和 squash 三种方式，合并后不自动删分支。
- `main` 当前没有 branch protection 或 repository ruleset。
- 现有 CI 最近一次在 `main@4570ee9` 成功。
- 当前工作树在勘察开始前与 `origin/main` 同步；本规格文档为本次新增未提交文件。

Assumptions:

- Inferred：短期目标继续保持模块化单体，而不是拆微服务，因为代码、Compose 和用户目标都没有给出拆服务需求。
- Inferred：受控主链首先服务对话模式，报告模式仅要求共享稳定底座，不在首批迁移范围。

## 3. Directory Structure Summary

| Path | Apparent role | Relevance | Notes |
| --- | --- | --- | --- |
| `backend/main.py` | FastAPI 应用装配与生命周期 | 高 | 初始化 DB、Trace、账号、STM/LTM worker；当前包含较多直接 `print` 和宽泛降级 |
| `backend/routers/` | HTTP/WebSocket 协议入口 | 高 | 聊天、报告、鉴权、记忆、用户、持仓路由 |
| `backend/schemas/` | Pydantic API DTO | 高 | 已有分层，但核心响应仍含 `Optional[dict]`，未形成统一错误 Envelope |
| `backend/services/` | 用例编排与大量业务逻辑 | 高 | `chat_service.py` 达 2058 行，混合会话、Prompt、Memory、Skill、Trace、持久化和流式协议 |
| `backend/db/` | SQLAlchemy 引擎与 ORM | 中/高 | SQLite/PostgreSQL 兼容；启动时含手写增量字段迁移 |
| `Financial-MCP-Agent/src/agents/` | 报告 Agent 与当前对话 Skill 链 | 高 | 当前 Router/Executor 分别约 660/1891 行，职责继续膨胀 |
| `Financial-MCP-Agent/src/skills/` | Workspace Skills 与 Registry | 高 | 已有 `SKILL.md + skill_spec.yaml + references/tests` 的部分资产模式 |
| `Financial-MCP-Agent/src/tools/` | MCP/Tushare/Trace/模型辅助 | 高 | 工具、Provider 配置与可观测性混在同一宽目录 |
| `Financial-MCP-Agent/src/memory/` | Mem0/LTM 适配与 Worker | 中/高 | 与 DB 任务表、环境变量和后台任务耦合 |
| `frontend/src/api/index.ts` | 前端 API 与 WS 契约 | 高 | 单文件 416 行，所有资源契约集中；未由 OpenAPI 生成 |
| `frontend/src/composables/` | 前端业务副作用编排 | 高 | `useChat.ts` 负责 WS 生命周期和控制帧 |
| `frontend/src/stores/` | Pinia 客户端状态 | 中 | 会话、画像、报告、鉴权、持仓状态 |
| `tests/evals/` | 离线评测与固定 smoke 数据 | 高 | 已迁移框架；Planner/Executor/Verifier 在目标模块不存在时跳过 |
| `.github/workflows/ci.yml` | 普通离线 CI | 高 | 后端/Agent pytest、Eval smoke、前端 type-check/build |
| `docker/` | 本地容器链路 | 高 | 尚无 E2E 驱动脚本、测试 profile 或 CI 容器验收 job |
| `vendor/tushare-skills/` | 官方 Tushare Skill 能力源 | 支撑 | 第三方/上游资产，不应随业务重构大范围修改 |
| `a-share-mcp-is-just-i-need/` | 独立 MCP 服务子项目 | 支撑 | 独立 `pyproject.toml`/`uv.lock`，由后端运行时调用 |
| `migrations/` | 少量 SQL 修复脚本 | 高风险支撑 | 未形成 Alembic 等完整迁移链 |
| `docs/` | 公开架构、安装、部署、评测文档 | 高 | 存在文档描述领先实际实现的问题 |

## 4. Entry Points

### 4.1 Startup Entry

Confirmed backend startup:

```text
docker compose / uvicorn
-> backend.main:app
-> lifespan()
-> init_db()
-> initialize_trace_runtime()
-> 可选 Mem0 + LTM worker
-> 可选 STM compaction worker
-> 注册 /api/* routers
```

Confirmed frontend startup:

```text
frontend/src/main.ts
-> Vue App + Pinia + Router
-> views/composables
-> frontend/src/api/index.ts
```

Confirmed report runtime:

```text
POST /api/report/generate
-> backend/routers/report.py
-> FastAPI BackgroundTasks
-> backend/services/agent_service.py::run_report_task
-> Financial-MCP-Agent/src/main.py LangGraph
```

### 4.2 Request / Task Entry

当前对话存在两个产品入口：

- REST：`POST /api/chat/message` → `backend.routers.chat.send_message()`。
- WebSocket：`/api/chat/stream` → `backend.routers.chat.chat_stream()`；前端常用路径由 `useChat.ts::sendMessageStream()` 建立连接。

两者最终分别调用 `chat_service.chat_single_turn()` 和 `chat_service.stream_chat_single_turn()`，并共享 `_run_skill_chat_if_enabled()`。

## 5. Relevant Call Chain

当前真实可运行对话主链：

```text
用户输入
-> Vue ChatView / useChat
-> WebSocket /api/chat/stream（或 REST /api/chat/message）
-> AuthMiddleware / authenticate_websocket + ensure_user_access
-> backend/services/chat_service.py
-> 创建/读取 Session，保存用户 Message
-> 可选 Memory/STM 上下文
-> ENABLE_CHAT_SKILLS=false：直接走通用 LLM fallback
   或
   ENABLE_CHAT_SKILLS=true：route_chat_skill()
      -> 规则/LLM Router
      -> execute_skill()
      -> 可选确定性计划、Tushare/MCP 工具、现有 Evidence 校验、LLM 总结
-> 保存 assistant Message、更新上下文/压缩任务
-> 可选异步 LTM 写入
-> 发送 token/控制帧
-> skill_trace JSONL + 可选 Langfuse exporter
```

Confirmed segments:

- 前端 `frontend/src/composables/useChat.ts` 通过 `frontend/src/api/index.ts::buildWsUrl('/chat/stream')` 建连。
- FastAPI 路由执行 JWT/用户隔离后调用 chat service。
- `chat_service` 直接导入现有 `skill_router_node` 与 `skill_executor_node`。
- Feature Flag 默认值中 `enable_chat_skills`、`enable_tushare_skills`、`enable_stm`、`enable_memory`、`enable_langfuse` 均为 `False`；`enable_trace` 默认为 `True`。
- Skill 未启用或 Router 选择 fallback 时，直接调用 `_get_llm()`，没有进入历史 v2 受控链。

Inferred segments:

- 从产品体验看，WebSocket 是主要对话入口，REST 是同步兼容入口；仓库没有显式流量统计证明二者占比。
- 当前 `execute_skill()` 中有 Planner/Evidence 名称和一些确定性取数能力，但不等同于项目描述中的独立 v2 Planner → Validator → DAG Executor → Verifier → Controller → Replanner 闭环。

Unknown segments:

- 尚无运行期流量或 trace 样本证明哪些 Feature Flag 在用户日常环境实际开启。
- 尚无自动化 E2E 证明 REST 与 WebSocket 两条路径行为完全一致。

历史 `Finance` v2 候选主链：

```text
backend/services/chat/orchestrator.py
-> preflight / memory / session split modules
-> skill_pipeline.py
-> entity_resolver_v2
-> route_stage1 + route_stage2
-> route-specific query_rewriter + narrow extractors
-> tool discovery / planner / plan validator
-> execution scheduler + evidence envelope
-> verifier + controller + replanner
-> synthesis
-> artifacts / trace DB sink / session reporter
```

Confirmed：历史实现存在上述模块和 Feature Flag，但关键 v2 Flag 默认关闭，且仍有 `skill_executor_node.py` 2030 行、`skill_pipeline.py` 716 行等集中式复杂模块。因此它是“能力与测试证据源”，不是可整体复制的成品。

## 6. Related Files

### 6.1 Definitely Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `AGENTS.md` | 当前仓库总规约 | 与用户新的严格工程目标直接冲突 | candidate modification | High |
| `pyproject.toml` | 根 Python 工具入口 | 目前只有 pytest marker，未来质量命令需统一 | candidate modification | Medium |
| `.github/workflows/ci.yml` | CI 门禁 | 当前只覆盖 pytest/Eval/build | candidate modification | High |
| `docker/docker-compose.yml` | 完整链路启动 | Live E2E 与本地集成的运行底座 | candidate modification | High |
| `backend/main.py` | 应用装配 | 配置、生命周期、日志与追踪入口 | candidate modification after plan | High |
| `backend/services/chat_service.py` | 当前对话总编排 | 未来受控主链的接入点，也是最大耦合点 | candidate modification after plan | High |
| `backend/routers/chat.py` | REST/WS 协议入口 | API、鉴权、错误与控制帧契约 | candidate modification after contract | High |
| `backend/schemas/chat.py` | Chat API DTO | 未来 plan/step/verification/error 契约 | candidate modification after contract | High |
| `Financial-MCP-Agent/src/agents/skill_router_node.py` | 当前 Router | 现有行为基线与路由迁移适配 | read-only first / candidate later | High |
| `Financial-MCP-Agent/src/agents/skill_executor_node.py` | 当前执行聚合 | 现有工具/证据行为基线，拆分风险高 | read-only first / candidate later | High |
| `Financial-MCP-Agent/src/tools/skill_trace.py` | 本地 trace 契约 | 未来全链观测与脱敏基座 | candidate modification | High |
| `tests/evals/` | 离线回归 Harness | 迁移前后对比和模块解锁机制 | candidate modification | Medium |

### 6.2 Probably Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `frontend/src/api/index.ts` | TS API/WS 类型 | 与未来控制帧和错误码同步 | candidate modification after API contract | High |
| `frontend/src/composables/useChat.ts` | WS 生命周期 | 需要消费 plan/step/verification 与错误事件 | candidate modification after API contract | High |
| `backend/config.py` | 类型化 Settings | 新开关、预算、观测策略应由此统一 | candidate modification | High |
| `backend/db/database.py` | 引擎与启动迁移 | 集成测试与迁移治理会受影响 | read-only unless approved | High |
| `backend/db/models.py` | 持久状态 | trace/eval 落库若采用会触及数据契约 | read-only unless approved | High |
| `Financial-MCP-Agent/src/skills/skill_registry.py` | Skill 注册与契约 | Tool Governance 与版本化重要输入 | candidate modification later | High |
| `Financial-MCP-Agent/src/tools/trace_exporters/langfuse_exporter.py` | Langfuse 桥接 | 当前依赖 Langfuse 旧版/内部接口，需版本权衡 | candidate modification | High |
| `docker/Dockerfile.backend` | 后端镜像 | 依赖可复现性、安全和 E2E | candidate modification | Medium |
| `docker/nginx/default.conf` | API/WS 反向代理 | 完整链路与流式行为 | candidate modification if tests expose gap | Medium |

### 6.3 Supporting Context

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/.env.example` | 运行配置说明 | 配置契约与安全默认值 | candidate modification | Medium |
| `Financial-MCP-Agent/.env.example` | 模型/MCP 配置说明 | 当前存在两套 env 来源 | candidate modification | Medium |
| `backend/requirements.txt` | 主 Python 依赖 | 版本范围较宽且无锁定 | candidate modification after tool choice | High |
| `frontend/package.json` | 前端质量命令 | 当前无 lint/unit/e2e script | candidate modification | Medium |
| `docs/eval-baseline.md` | M1 评测证据 | 作为后续指标版本基线 | append/update only after verified runs | Low |
| `docs/项目代码架构说明.md` | 当前公开架构说明 | 需要与真实目录同步 | candidate modification | Medium |
| `README.md` | 对外项目入口 | 当前存在描述领先实现与部分路径历史口径 | candidate modification after implementation | Medium |

### 6.4 Out of Scope

| Path / Area | Reason |
| --- | --- |
| `vendor/tushare-skills/**` | 上游 vendored 能力源，本阶段不改 |
| `a-share-mcp-is-just-i-need/**` | 独立子项目；除非未来契约测试发现阻塞，不在首个治理里程碑修改 |
| `migrations/**` 与生产数据 | 本阶段禁止数据库契约与数据迁移 |
| 鉴权算法、账号模型与用户数据 | 高风险安全/隐私边界，需独立 Issue 和显式批准 |
| 报告模式 LangGraph 业务节点 | 当前重点是对话受控主链基础设施 |
| 生产云环境、域名、TLS、Kubernetes | 未给出目标平台，不伪造 CD 完成度 |

## 7. Existing Patterns to Reuse

| Pattern | Example file | Why reuse it |
| --- | --- | --- |
| FastAPI Router → Service → Schema 基础分层 | `backend/routers/chat.py`、`backend/services/chat_service.py`、`backend/schemas/chat.py` | 协议入口已经存在，未来应保留外部入口稳定并缩小 service 职责 |
| Feature Flag 渐进启用 | `backend/config.py` | 适合受控主链双轨接入与快速回退 |
| 本地 trace 为主、Langfuse 为可选 exporter | `skill_trace.py`、`langfuse_exporter.py` | 外部观测故障不应阻断业务；这个原则与项目口径一致 |
| Pydantic 结构化 Agent 结果 | `skill_router_node.py::SkillRouteDecision`、`skill_evidence.py` | 可作为未来 typed state/contract 的起点 |
| Skill 四层资产的雏形 | `src/skills/fund-compare/` | `SKILL.md + skill_spec.yaml + references + tests` 便于版本与验收 |
| 固定数据离线评测 | `tests/evals/**/data/smoke.jsonl` | CI 稳定、无付费调用，适合作为迁移保护网 |
| Live marker 隔离真实依赖 | 根 `pyproject.toml` | 满足普通 CI 低成本与发布前真实验收分离 |
| 前端 composable/store 分工 | `useChat.ts`、`chatStore.ts` | 可在不把 Agent 规则放进组件的前提下接入新状态事件 |

需要谨慎复用而不能照搬：

- `sys.path` 注入是当前可运行兼容方式，不应成为目标架构规范。
- `chat_service.py` 和 `skill_executor_node.py` 的现有行为需要契约测试保护，但大文件组织方式不应继续扩展。
- 宽泛 `except Exception` 后继续运行只适合明确的可选能力降级，不能成为统一错误策略。

## 8. Data Flow and State

### 8.1 Input Data

- REST：`ChatMessageRequest(user_id, message, session_id?)`。
- WebSocket：手写 JSON，字段同上；鉴权 token 放 URL query 或 Header。
- 配置：`Settings` 读取 Agent 与 Backend 两份 `.env`；部分底层模块仍直接读 `os.getenv()`。

### 8.2 Intermediate State

- 当前请求级状态主要分散在局部变量和非类型化 `dict`：`skill_trace`、`route_trace`、`executor.trace`、memory profile。
- `skill_trace_context` 使用 `contextvars` 保存 trace/span 上下文。
- 当前没有统一的受控主链 `WorkingState` 作为所有节点的类型化契约。

### 8.3 Persistent State

- SQLAlchemy 表保存用户、账号、会话、消息、报告、持仓、观察列表、画像、LTM 任务、摘要与 STM 压缩任务。
- SQLite 是默认本地路径，Compose 使用 PostgreSQL/pgvector。
- Trace 默认追加到本地 JSONL；日志和报告写本地挂载目录。
- 主仓库未发现 Redis 实现或 Compose 服务；项目描述中的 Redis 属于历史增强口径，尚未迁入主仓库。

### 8.4 Output Data

- REST：`reply/session_id/memory_profile/context_window`。
- WebSocket：普通文本 token 与 JSON 控制帧混合传输；当前类型包括 session、context、compaction、done、error。
- 当前主仓库前端类型中未发现项目描述所称 `route_summary/plan_preview/step_status/verification_summary/skill_confirm` 控制帧。

### 8.5 Potential Data Mismatch Points

1. 后端 Pydantic DTO 与前端手写 TypeScript 类型没有自动契约校验或生成。
2. WS 用“字符串是否以 `{` 开头”识别控制帧；模型正文若恰好为 JSON，存在误判可能。
3. REST 与 WS 各有大量近似编排逻辑，行为可能漂移。
4. `memory_profile: Optional[dict]`、`route_trace: dict` 等核心状态缺少稳定 Schema。
5. `Settings` 与直接 `os.getenv()` 并存，测试覆盖和配置来源可能不一致。
6. README/项目描述已宣称部分 v2 能力，但主仓库实际没有对应模块或前端事件。

## 9. External Dependencies

| Dependency | Where called | Input | Output | Error handling / fallback |
| --- | --- | --- | --- | --- |
| OpenAI-compatible LLM | `chat_service._get_llm()`、Router/Executor 等 | Prompt/messages/model config | 模型消息/结构化路由 | 当前通用 fallback 未见统一总超时；多个调用点各自处理 |
| Google GenAI/OpenRouter | `src/utils/llm_clients.py` 等 | messages/config | completion | 有 backoff，但包含同步 `time.sleep` 与多层重试逻辑，预算不统一 |
| Tushare | `src/tools/tushare_client.py`、chat tools | API 名称/股票与时间参数 | 金融数据 dict/list | 有 asyncio timeout、tenacity 重试和节流；异常分类仍较粗 |
| MCP stdio server | `src/tools/mcp_client.py` | tool call | MCP tool result | 当前未形成统一请求级预算和错误码契约 |
| PostgreSQL/SQLite | `backend/db/` | ORM/SQL | 持久业务事实 | 应用启动即 init/create/补字段；正式迁移回滚能力不足 |
| Mem0/pgvector | `src/memory/` | 对话、画像、embedding | 语义记忆 | Feature Flag 可关闭，worker 有有限重试；涉及隐私和外部调用 |
| Langfuse | `langfuse_exporter.py` | 本地 trace record | trace/span/event | 初始化或导出失败降级 no-op；当前实现调用 Langfuse 内部资源接口，升级兼容风险高 |
| Nginx | `docker/nginx/default.conf` | HTTP/WS | 反向代理 | 容器依赖 Backend 健康；未见自动浏览器 E2E 验证 |

## 10. Tests and Evaluation Assets

### 10.1 Existing Tests

- Backend：鉴权服务、报告下载响应头、Agent 事件提取、Skill 回复 action 处理；多数是单元级 unittest。
- `backend/test_stock_resolver.py` 是可执行手工脚本，不是标准 pytest 测试函数。
- Agent：Router、Executor helper、Evidence、Skill Registry、Trace、Langfuse exporter、Tushare client/tools、response normalizer 等。
- Live：当前至少 4 个真实模型/Skill 用例有 `@pytest.mark.live`，默认跳过。
- Eval：entity、route、rewrite、planner、executor、verifier、synthesis、skill activation、web search 的 smoke 数据与 runner。
- CI：Backend/Agent offline tests、Eval smoke、前端 type-check/build 已存在且最近成功。

### 10.2 Coverage Gaps

- 未发现 `tests/unit/contract/integration/e2e` 分层目录。
- 未发现 FastAPI `TestClient`/httpx API 契约测试，REST/错误码/OpenAPI 未被自动验证。
- 未发现 WebSocket 端到端协议测试。
- 未发现 Docker Compose 启动、健康检查、登录、聊天请求与清理的自动化脚本。
- 未发现前端组件单测或 Playwright 浏览器 E2E。
- 未发现覆盖率采集和核心模块阈值。
- Planner/Executor/Verifier Eval 当前因主仓库目标模块缺失而 skip；数据集加载通过不等于模块行为通过。
- 未发现 Prompt/Skill/Tool Schema 的兼容快照门禁和 bad case → eval 回流流程自动化。
- 未发现负载、并发、断连恢复、故障注入、数据库迁移回滚测试。

### 10.3 Candidate Test Locations

- `tests/unit/`：纯领域/策略/Schema/状态机。
- `tests/contract/`：REST、WS frame、OpenAPI、Tool/Prompt/Skill contract。
- `tests/integration/`：FastAPI + 临时 DB + fake provider/MCP/Tushare adapter。
- `tests/e2e/`：Docker Compose 黑盒请求；offline profile 与 live profile 分开。
- `tests/evals/`：保留 Agent 模块离线评测和版本基线。
- `frontend/src/**/__tests__/` 与 `frontend/e2e/`：前端状态/控制帧及少量关键浏览器路径。

这些是候选归属，不是已冻结的目录方案。

### 10.4 Visible Test Commands

```bash
python -m pytest backend -q
python -m pytest Financial-MCP-Agent -q -m "not live"
python -m pytest tests/evals -q -m "eval_smoke and not live"
cd frontend && npm run type-check && npm run build
docker compose -f docker/docker-compose.yml config
```

Confirmed：根 pytest 默认排除 `live`；普通 CI 不配置真实凭证。

## 11. Logging and Observability

### 11.1 Existing Logs

- `setup_logger()` 创建控制台和文件 handler，默认 root DEBUG、控制台 INFO、文件 DEBUG。
- `skill_trace.py` 定义 trace/span/event 记录，具有 trace/session/user/workflow/schema/policy/stage/status/duration/data/metrics/refs。
- trace 默认写 `Financial-MCP-Agent/logs/chat_traces.jsonl`，可选写 Prompt、reply、tool payload、claims artifact。
- Langfuse exporter 可选启用，初始化和导出失败不阻断主业务。

### 11.2 Missing Logs

- 没有统一 HTTP request_id/trace_id 中间件把 API 响应、普通日志与 Agent trace 自动关联。
- 没有稳定的全局错误码枚举；大多数用户错误直接返回字符串。
- Provider/model/tool 的 timeout、retry、token、cost 字段没有统一跨模块契约。
- 没有正式 metrics exporter/dashboard/alert 配置。
- 报告 `execution_logger` 与对话 `skill_trace` 尚未形成共享 SDK/Schema。

### 11.3 Observability Risks

- `_sanitize_value()` 主要做长度截断，不按 key 对 Token、Cookie、Authorization、画像或 Prompt 做真正脱敏。
- JSONL 写入的是原始 record，而不是 `_log_record_payload()` 的截断版本；如果调用方放入敏感字段，会原样落盘。
- `chat_service` 会记录/打印 user/session 摘要，部分日志使用 f-string，字段结构不稳定。
- 维护源码中检测到约 231 个 `print()` 和约 99 个直接环境变量读取点，终端、日志和配置边界未收敛。
- Trace 文件只有线程锁；多进程容器并发追加、一致性、轮转、保留周期与磁盘上限未定义。
- Langfuse exporter 使用 SDK 内部资源 API，依赖升级后可能静默失效。

### 11.4 Output-channel Separation

| Channel | Current implementation | Stable fields / format | Redaction | Gaps |
| --- | --- | --- | --- | --- |
| User/API result | Pydantic REST + 手写 WS JSON/text | REST 部分稳定；WS 有 `type` | 用户可见错误未分类 | WS 文本/控制帧混合，缺统一 error code |
| Terminal progress | 大量 `print()` + logger console | 多为自然语言和图标 | 无统一策略 | 与日志重复，自动化解析困难 |
| Logs | `setup_logger` 文本文件 | 时间/name/level/message | 仅个别字段截断 | 非 JSON、字段和上下文不统一 |
| Traces | `skill_trace` JSONL + exporter | trace/span/event envelope 较完整 | 只有值截断 | key-based 脱敏、采样、保留、多进程写入缺失 |
| Artifacts | trace/date/id 子目录 | kind/path/relative_path | 默认关闭 | 开启后原始内容可能含敏感数据，无 manifest/retention |

## 12. Engineering Baseline Recon

| Area | Status | Evidence | Gap / implication |
| --- | --- | --- | --- |
| API/orchestration/domain/infrastructure boundaries | Partial | 已有 routers/schemas/services/db | chat service、Agent executor 仍混合编排、Prompt、Provider、持久化和观测；无 `backend/integrations` |
| Agent/workflow/tool/prompt/model/memory/evaluation boundaries | Partial | agents/tools/skills/memory/tests/evals 已分目录 | 无独立 prompts 目录；当前 Agent 节点过大；工具和 Provider/Trace 混在 `tools` |
| Docstrings, types, and key intent comments | Partial | 部分 public 函数有中文说明和类型 | 风格不一致；大量核心 dict 未类型化；docstring 未系统描述 Raises/失败语义 |
| File-section navigation vs module separation | Partial | 大文件有 Phase/section 注释 | `chat_service.py` 2058 行、`skill_executor_node.py` 1891 行，section 已在掩盖多职责 |
| Typed configuration and secret handling | Partial | `backend/config.py::Settings`、`.env.example`、`.gitignore` | 两份 env + 99 个直接 getenv；Compose 有固定开发密码；JWT 有不安全默认值且启动未强制拒绝 |
| Error, retry, fallback, and state semantics | Partial | Tushare timeout/retry、Memory 降级、Feature Flag 存在 | 没有统一错误 taxonomy/预算；宽泛异常多；部分 LLM 无总超时；核心状态 dict 化 |

## 13. Risk Areas

| Area | Why risky | Likely touched? | Recommended handling |
| --- | --- | --- | --- |
| JWT/用户隔离 | 小改可能导致跨用户会话/画像泄漏 | 基础设施只定义门禁，不改算法 | 独立安全 Issue、契约测试、显式批准 |
| 金融工具与结论 | 错标的、旧数据或证据不足会产生误导 | 后续受控链必触及 | typed evidence、时间/主语校验、只读 Live E2E、明确免责声明 |
| 数据库初始化/迁移 | 当前启动时补字段，回滚困难 | 首个里程碑不触及 | 只读；后续单独设计迁移框架与备份/回滚 |
| LTM/画像/聊天日志 | 含个人偏好与对话内容 | 观测规范会触及边界 | 默认最小采集、字段白名单、外部平台显式 opt-in |
| 付费模型/Tushare/MCP | 费用、限流、外部波动 | Live E2E 会触及 | 显式 marker/profile、预算、超时、单并发、只读数据 |
| Prompt/Tool 执行 | 模型可生成错误或越权动作 | 后续受控链必触及 | dynamic allowlist、Schema gate、幂等、预算和 controller |
| Docker/生产配置 | 固定凭据、`latest` pgAdmin、无环境隔离 | 基础设施会设计，首步可安全修文档/校验 | 区分 dev/test，生产 Secret 与镜像固定另立里程碑 |
| Langfuse/Trace | 敏感信息泄露或 exporter 静默失败 | 基础设施会触及 | 本地审计为主、key-based redaction、契约测试、SDK 公共 API |
| 大文件拆分 | 易产生行为回归和循环导入 | 后续迁移会触及 | 先 Characterization tests，再通过 Facade/Adapter 小步抽离 |
| GitHub main 无保护 | 可绕过 PR/CI 直接 push | 需要用户授权后配置 | 先稳定 checks，再启用 ruleset/branch protection |

## 14. Unknowns and Assumptions

### 14.1 Unknowns From Missing Code Access

- 无。两个本地仓库均可读取；但没有读取本地 `.env`、真实运行数据、私有 Langfuse 项目和生产服务，这是有意的安全边界。

### 14.2 Unknowns From Incomplete Requirement

- 正式部署目标（云主机、容器平台、Vercel/Cloudflare 等）未确定。
- Live E2E 可用的测试账号、模型预算和 Tushare 数据权限未定义。
- 用户希望 Code Review 最终是否要求人工批准，还是接受独立 Agent Review + 自审证据。
- 是否需要在此阶段就引入 Redis；主仓库当前没有该依赖，但项目描述包含 Redis 能力。
- 对外 API 是否必须保持完全兼容，还是允许版本化 `/api/v2`。

### 14.3 Unknowns From Ambiguous Architecture

- Python 目标包是渐进改造 `Financial-MCP-Agent/src`，还是新建可安装的规范包后适配旧入口。
- Backend application service 与 Agent runtime orchestrator 的最终编排所有权边界尚未冻结。
- REST 与 WebSocket 是否继续双入口等价，还是一个成为主入口、另一个只做兼容。
- 本地 JSONL 是否继续作为长期审计账本，还是后续迁移到数据库/OTel collector。

### 14.4 Assumptions

- 采用渐进式模块化单体和 Feature Flag 双轨迁移，优先保留用户可见 API。
- 首批工作只建立工程规则、质量门禁和可测试骨架，不迁移完整业务链。
- 真实 E2E 是发布/里程碑验收门禁，但不进入普通 push/PR CI。
- 所有简历表述只引用已合并代码、测试/评测报告和 trace 证据。

## 15. Handoff to Next Step

Next step should produce `CLARIFICATION_QUESTIONS.md`，再进入方案权衡。

It should clarify:

- 目标包布局：原地渐进拆分，还是新包 + Anti-Corruption Adapter。
- 第一批基础设施是否只做治理文档/模板，还是同时引入 Ruff、类型检查和测试目录。
- CI 必选检查与耗时上限；容器集成是在 PR 运行还是 nightly/manual。
- Live E2E 的真实依赖、预算、数据权限、凭证环境和产物保留。
- Langfuse 的数据采集边界，以及是否同时引入 OpenTelemetry 标准语义。
- GitHub main 保护规则与个人项目 Review 证明方式。
- Redis、生产 CD 和数据库迁移是否继续后置。

It should consider these files/modules in later solution design:

- `AGENTS.md`
- `pyproject.toml`
- `.github/workflows/ci.yml`
- 后续新增的 Issue/PR 模板与贡献文档
- `docker/docker-compose.yml` 及候选测试 profile
- `backend/config.py`、`backend/main.py`
- `backend/services/chat_service.py` 与未来 Facade/Adapter 边界
- `Financial-MCP-Agent/src/tools/skill_trace.py`
- `tests/evals/` 与候选 `tests/contract|integration|e2e/`

It should require explicit user approval before modifying these high-risk areas:

- GitHub branch protection/ruleset、合并策略和仓库设置。
- JWT/鉴权、多用户隔离和测试账号策略。
- 数据库 Schema、迁移与任何真实数据操作。
- 真实模型/Tushare/MCP/Langfuse 的凭证、费用或生产写操作。
- 公共 REST/WS 契约及不兼容变更。
- 生产部署、域名、TLS、Secret 与云资源。
