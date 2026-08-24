# PLAN.md

## 1. Plan Metadata

- Plan name: Finance Agent 受控主链工程基础设施与直接模块重构治理计划
- Task type: 高风险跨模块工程治理、测试基础设施和 Agent Runtime 迁移前置建设
- Status: Completed (M0-M5)
- Target executor: Codex
- Related artifacts:
  - REQUIREMENT_SPEC.md
  - CODEBASE_RECON.md
  - CLARIFICATION_QUESTIONS.md
  - SOLUTION_TRADEOFF.md
- Repository root: D:/FinanceProject/Finance-agent-Skills
- Current branch: `docs/1-engineering-contract`（M0-M5 已在该专用分支完成；尚未执行 commit/push/PR/merge）
- Created date: 2026-08-20

## 2. User-facing Purpose

完成本计划后，用户应当能够按照一套明确、可学习、可执行的工程规范，从一个 GitHub Issue 开始，经过规格、分支、测试先行、实现、离线 CI、完整容器 E2E、真实服务验收、独立 Review、Squash Merge、发布观察和回滚，完成一个闭环；后续受控主链模块也必须复用同一闭环。

当前问题是：仓库虽已有 FastAPI、Vue、PostgreSQL、Docker Compose、离线 pytest/eval 和基础 CI，但工程规则仍是个人项目轻量版，Python 包、职责边界、质量工具、契约/集成/E2E 分层、结构化日志、Trace/Langfuse 语义、GitHub Issue/PR 模板尚未形成统一且可强制执行的工程合同。核心 Agent 调用链集中在超大文件中，Finance 历史目录的较完整主链资产又不能直接视为可迁移成品。

本计划的成功可通过以下现象观察：

- 仓库有唯一、无歧义的 AGENTS.md、CONTRIBUTING.md、目录/命名/测试/可观测规范和 Definition of Done。
- Feature、Bug 和 PR 模板强制填写目标、非目标、验收、风险、测试、观测和回滚。
- 本地与 CI 使用同一组可复现的格式、lint、类型、单元、契约、集成、离线 eval 和前端检查命令。
- Compose 能在不调用付费模型或生产服务的情况下运行离线完整链路验收；Live E2E 有显式、受保护、低成本、无生产写的执行方法。
- 日志和 Trace 具有稳定关联字段并完成敏感信息脱敏。
- 后续每个 Agent 模块遵循“先锁契约、再直接替换、同步改调用方、删除旧实现、单 PR 可 revert”的迁移规则，不建立兼容 Adapter。

## 3. Inputs Reviewed

- REQUIREMENT_SPEC.md: 已确认功能、工程、安全、测试、CI/CD、可观测性和验收需求。
- CODEBASE_RECON.md: 已确认真实入口、调用链、目录、配置、日志、测试、Docker 与 GitHub 现状。
- CLARIFICATION_QUESTIONS.md: 用户已确认所有 P0/P1 决策，尤其是直接模块重构、不做兼容 Adapter。
- SOLUTION_TRADEOFF.md: 选择 Structured Improvement，并把 Observation-first 作为每个模块重构前置门禁。
- Code files: AGENTS.md、pyproject.toml、.github/workflows/ci.yml、backend/main.py、backend/api/chat.py、backend/services/chat_service.py、Financial-MCP-Agent/src/agents/skill_router_node.py、Financial-MCP-Agent/src/agents/skill_executor_node.py、Financial-MCP-Agent/src/observability、frontend/src、frontend/package.json、docker/docker-compose.yml。
- Tests: backend 下 pytest、Financial-MCP-Agent/test_*.py、tests/evals、frontend type-check/build；当前已知根回归基线为 51 passed、4 skipped、4 deselected。
- External references: OpenAI Agents Python AGENTS.md/PLANS.md、GitHub Protected Branches 与模板文档、FastAPI Full Stack Template、Google SRE Release Engineering/Canary、DeerFlow AGENTS、Langfuse Observability、OpenTelemetry Logs、pytest、uv、Ruff、Pyright、GitHub Spec Kit。

## 4. Final Unified Direction

This iteration will 建设后续直接模块重构所必需的工程基础设施：工程宪法与协作模板、可复现 Python 工具链、分层测试与离线 Compose E2E、统一日志/Trace/Langfuse 契约，以及执行与回滚证据。每个里程碑独立实施、独立验收，不能一次执行多个里程碑。

This iteration will not 迁移实体解析、路由、改写、Planner、Executor、Verifier、Controller、Replanner 或 Synthesis 的业务逻辑；不会改公共 REST/WS 协议、数据库 Schema、鉴权、用户数据、生产配置，也不会建设 Redis、Kubernetes、微服务、OTel Collector 或虚构的生产 CD。

The plan follows “结构化分模块直接重构”：Finance 只提供历史证据；Finance-agent-Skills 是唯一实现；不保留旧 Runtime 兼容 Adapter。基础设施完成后，每个业务模块另开 Spec/Issue/分支/PR，先锁契约，再在唯一目标位置替换，并在同一 PR 修改所有调用方和删除旧实现。

## 5. Planning Assumptions

- Assumption: 当前 main 与 origin/main 同步；实施 Milestone 0 时必须重新验证，不能依赖本计划创建时状态。
- Assumption: 用户将对 GitHub Issue、分支、commit、push、PR、merge 和仓库设置等外部写操作逐次明确授权；本计划本身不构成这些写操作的授权。
- Assumption: Python 目标版本继续为 3.12，Node 继续为 20，除非现有依赖验证证明不兼容。
- Assumption: uv、Ruff、Pyright 和前端 ESLint 的引入方向已获产品决策确认，但实际依赖和版本必须在 Milestone 2 根据当前依赖解析后冻结。
- Assumption: 默认 CI 永远不读取真实模型、Tushare、MCP 或生产凭证；所有 live 测试必须有 live marker 和显式开关。
- Assumption: 本地 Live E2E 可以调用真实服务的只读能力；任何写入必须使用隔离测试库/租户，生产写永久禁止。
- Assumption: 现有公共 API 和前端事件协议在基础设施阶段保持字节级或 Schema 级兼容。
- Assumption: 真实生产部署平台尚未选择，因此 CD 在本计划中只到可复现构建、候选产物、手工验收和可回退版本，不伪造 deployment job。

## 6. Changed Surface

| Surface | Involved? | Why | Risk | Verification |
| --- | --- | --- | --- | --- |
| Frontend | 是，限测试/质量脚本 | 补 lint、保持 type-check/build、为后续浏览器 E2E 留统一入口 | 中 | npm ci、lint、type-check、build，后续离线 E2E |
| Backend API | 是，限测试夹具/可观测中间件 | 增加 API/WS 契约与关联 ID，不改变业务协议 | 中高 | REST/WS contract tests、现有回归、Compose smoke |
| Database | 是，限测试环境 | PostgreSQL 集成测试与隔离测试数据 | 中 | 独立测试库、事务清理、无 Schema 变更断言 |
| Cache | 否 | 当前没有 Redis 真实需求 | 低 | 确认未增加 Redis 依赖或配置 |
| Agent runtime | 是，限边界测试与观测钩子 | 为后续直接模块重构锁定现有契约 | 高 | characterization、contract、offline eval、E2E |
| Tool calling | 是，限 fake、契约和 Trace | 离线 E2E 需要可替换 Provider，工具调用需追踪 | 高 | tool schema/timeout/error contract tests |
| RAG / Memory | 否，行为不改 | 只记录未来边界，不迁移实现 | 中 | 现有相关测试不回归 |
| MCP | 是，限 fake/live 分流规范 | CI 不连真实 MCP，Live 可只读验证 | 中 | fake contract、live marker 与环境保护 |
| Skills | 是，限测试与目录所有权 | 现有 skill router/executor 是主链入口 | 高 | 现有 Agent tests、eval smoke |
| Tests | 是 | 补 unit/contract/integration/e2e 层级与 marker | 中 | pytest strict marker、分层命令、失败可归因 |
| Observability | 是 | 统一日志、Trace、Langfuse 和脱敏 | 高 | 字段断言、trace 关联、redaction tests |
| Security/Auth | 否，不能改变行为 | 仅保护测试凭证和日志脱敏 | 高 | secret scanning/fixture 检查、鉴权回归 |
| Build/Deployment | 是，限 CI 与候选构建 | 加强质量门禁和离线镜像验证 | 中 | CI YAML、Docker build/config/health；无生产部署 |

## 7. Repository Context

### 7.1 Relevant Entry Points

- 前端聊天入口：frontend 中聊天页面/composable 经 frontend API 客户端调用后端。
- 后端协议入口：backend/main.py 创建 FastAPI 应用；backend/api/chat.py 提供 /api/chat 相关 REST/流式入口。
- 后端用例入口：backend/services/chat_service.py 管会话、数据库和当前聊天编排。
- 当前 Agent 入口：Financial-MCP-Agent/src/agents/skill_router_node.py 与 skill_executor_node.py。
- Docker 入口：docker/docker-compose.yml。
- CI 入口：.github/workflows/ci.yml。
- 离线评测入口：tests/evals 及 python -m tests.evals.runner。

### 7.2 Relevant Call Chain

Vue/chat composable → frontend API client → /api/chat/stream 或 REST → FastAPI chat router → backend/services/chat_service.py → skill_router_node.py / skill_executor_node.py → LLM/工具/Skill/Memory Provider → PostgreSQL 与 trace → 流式事件返回前端。

目标依赖方向为：

Frontend → Backend Router → Backend Application Service → finance_agent public workflow/contracts → domain module → Provider Port → infrastructure implementation。

禁止 Provider、数据库或 Langfuse 反向导入 Router，也禁止 Router 直接拥有 Prompt、工具治理或 Agent 决策逻辑。

### 7.3 Existing Patterns to Reuse

- 复用 FastAPI Router、Pydantic 校验、application service 和 PostgreSQL 会话模式中已验证部分。
- 复用现有 pytest fixtures、tests/evals 固定数据集与 runner，不重建第二套评测框架。
- 复用 Docker Compose 的 PostgreSQL/backend/frontend 服务，增量补健康与离线 E2E。
- 复用 module logger 和当前 trace 存储思路，但集中配置日志与脱敏。
- 复用 frontend 的 TypeScript strict、type-check 和 build，补 lint 与 E2E 时沿用现有 Vite/Vue 栈。

### 7.4 Current Test Structure

- 根 pyproject.toml 指定 backend、Financial-MCP-Agent、tests/evals；默认 addopts 跳过 live。
- backend：当前 12 个已知测试通过。
- Financial-MCP-Agent：当前 33 个离线测试通过，4 个 live 默认跳过。
- tests/evals：smoke 当前 6 passed、4 skipped；Planner/Executor/Verifier 尚未迁移时由 find_spec 守卫跳过。
- 根回归：当前已知 51 passed、4 skipped、4 deselected。
- frontend：npm run type-check 与 npm run build 已通过；当前无 lint 和浏览器 E2E。
- CI：backend offline、eval smoke、frontend type-check/build 三个 job 已通过。

### 7.5 Current Observability Structure

- 当前本地 trace 默认开启，Langfuse 默认关闭。
- 已有 session_reporter/trace sink 等历史参考，但当前 key-based secret redaction 不完整。
- 日志和 Trace 尚未统一 stage、run_id/trace_id、status、elapsed_ms、error_code 等字段。
- chat_service.py、skill executor/router 仍有大量 print/getenv 与长内容输出风险，需要分里程碑收敛，禁止一次全仓替换。

## 8. Scope Control

### 8.1 In Scope

- 将根 AGENTS.md 升级为本项目唯一工程合同，并明确直接模块重构规则。
- 增加面向小白的 CONTRIBUTING.md、开发 SOP、架构与目录、命名、测试、可观测和 Definition of Done 文档。
- 增加 GitHub Feature/Bug Issue Form、PR Template。
- 建立 uv 锁定、Ruff、Pyright、pytest strict markers 和前端 ESLint 的渐进门禁。
- 建立 unit、contract、integration、eval、e2e、live 测试目录/marker/fixture 约定。
- 建立 PostgreSQL 集成、REST/WS 契约和离线 Docker Compose E2E 基础设施。
- 建立统一运行/Trace 上下文、结构化日志、Langfuse 导出边界和敏感信息脱敏契约。
- 对已有 CI 增加最小权限、超时、缓存、路径门禁、离线集成和失败产物规则。
- 形成后续模块直接重构的重复 SOP 与证据模板。

### 8.2 Out of Scope

- 任何受控主链业务模块的具体迁移或算法优化。
- Finance 目录文件的批量复制、导入或运行时依赖。
- 旧 Runtime 与新 Runtime 的兼容 Adapter、转发模块、双写或长期双轨。
- 公共 API/WS Schema、数据库 Schema、鉴权或用户数据变更。
- Redis、队列、微服务、Kubernetes、OTel Collector、正式生产 CD。
- 宣称未测量的准确率、延迟、并发、成本或可用性指标。

### 8.3 Allowed Files / Modules

Milestone 0 只读：整个仓库可读，不得编辑。

Milestone 1 允许：

- AGENTS.md
- CONTRIBUTING.md
- docs/architecture/README.md
- docs/engineering/development-sop.md
- docs/engineering/code-structure.md
- docs/engineering/testing-strategy.md
- docs/engineering/observability.md
- .github/ISSUE_TEMPLATE/feature.yml
- .github/ISSUE_TEMPLATE/bug.yml
- .github/ISSUE_TEMPLATE/config.yml
- .github/pull_request_template.md
- docs/specs/controlled-mainline-foundation/PLAN.md 的治理区块

Milestone 2 允许（实施时先确认精确包边界）：

- pyproject.toml
- uv.lock
- Financial-MCP-Agent/pyproject.toml（Needs confirmation：仅当验证为独立包/uv workspace member）
- frontend/package.json
- frontend/package-lock.json
- frontend/eslint.config.*（精确扩展名 Needs confirmation）
- scripts 下统一检查入口（精确文件名 Needs confirmation）
- .github/workflows/ci.yml
- .github/dependabot.yml（仅安全更新策略需要且无额外服务时）
- 对应规范文档和 PLAN.md 治理区块

Milestone 3 允许（测试基础设施）：

- tests/unit、tests/contract、tests/integration、tests/e2e、tests/fixtures
- backend/tests 或现有 backend 测试位置内的 app/REST/WS/DB 测试
- backend/conftest.py、根 conftest.py、Financial-MCP-Agent/conftest.py
- docker/docker-compose.yml
- docker 下专用测试 override（精确文件名 Needs confirmation）
- scripts 下 E2E 启停/探活/清理入口（精确文件名 Needs confirmation）
- .github/workflows/ci.yml
- pyproject.toml 中仅测试配置
- 对应规范文档和 PLAN.md 治理区块

Milestone 4 允许（可观测性最小切片）：

- backend 中应用级日志/请求上下文中间件（精确现有文件 Needs confirmation）
- Financial-MCP-Agent/src/observability
- Financial-MCP-Agent/src/config 中 typed Settings 相关文件（精确路径 Needs confirmation）
- chat_service.py、skill_router_node.py、skill_executor_node.py 仅允许接入统一上下文/日志/Trace，不允许改业务决策
- 对应 unit/contract/integration tests
- .env.example，仅添加无秘密的示例键
- 对应规范文档和 PLAN.md 治理区块

Milestone 5 只允许修复验证发现的同范围缺陷、更新上述文档与 PLAN.md 治理区块。任何新业务范围必须停止并另开计划。

### 8.4 Forbidden Changes

- Do not perform unrelated refactor.
- Do not reformat unrelated files.
- Do not modify generated files or build artifacts.
- Do not add dependencies unless explicitly approved by the frozen milestone and lockfile review.
- Do not change database schema unless explicitly approved in a separate high-risk plan.
- Do not change API response schema or WebSocket/SSE event schema unless explicitly approved.
- Do not modify authentication or authorization unless in scope.
- Do not modify secrets, real .env, credentials, or production deployment config.
- Do not delete user data.
- Do not weaken tests, markers, redaction, authorization or safety checks.
- Do not remove logging or safety checks without an equivalent verified replacement.
- Do not touch files outside allowed scope without stopping for approval.
- 不得把 Finance 加入 PYTHONPATH、运行时 import 或包依赖。
- 不得新增旧 Runtime → 新 Runtime 的兼容 Adapter、转发模块或永久双轨开关。
- 不得为了通过 Pyright/Ruff 添加全局 ignore 或一次格式化全部历史代码。
- 不得让默认 CI、PR 或普通 push 调用真实模型、Tushare、MCP、Langfuse 生产环境或任何付费服务。
- 不得在 Live E2E 中执行生产写入、下单、持仓修改、报告发布或外部业务副作用。
- 不得在日志、Trace、fixture、截图、测试报告或 CI artifact 中保存 Token、Authorization、Cookie、真实 .env、完整敏感 Prompt/响应或个人数据。
- 未经用户明确授权，不得 commit、push、创建/合并 PR、修改 GitHub 分支保护或部署。

## 9. Interfaces and Dependencies

| Interface / Dependency | Current Role | Planned Change | Compatibility Requirement | Validation |
| --- | --- | --- | --- | --- |
| /api/chat REST/stream | 前后端聊天协议 | 只补契约测试与关联 ID | 响应/事件 Schema 不变 | REST/WS/SSE contract + frontend smoke |
| backend chat application service | 会话、事务、Agent 编排 | 基础设施阶段仅接日志/Trace 上下文 | 业务分支和事务语义不变 | 当前回归 + integration + E2E |
| skill router/executor | 当前 Agent 路由与工具执行 | 只锁行为契约和接观测字段 | 路由/工具结果不变 | unit/contract/eval |
| Agent state | 节点间传递状态 | 记录未来 typed contract；本阶段不改业务字段 | 当前消费者继续可用 | characterization tests |
| Tool schema | 工具选择与参数边界 | 增加离线 fake/错误契约 | 名称、参数、返回语义不变 | contract tests |
| Model/Tushare/MCP Provider | 外部依赖 | 为测试定义替换边界；不得做旧新 Runtime Adapter | live 与 fake 遵循相同公开协议 | fake contract + protected live smoke |
| PostgreSQL | 会话/消息持久化 | 增加隔离集成测试配置 | Schema 不变，不污染开发/生产数据 | transaction cleanup + integration |
| Settings/env | 运行配置 | 逐步集中 typed Settings；新增安全 example | 现有安全默认值不被放宽 | settings tests + missing/invalid env tests |
| Prompt | Agent 行为契约 | 本计划只定义集中、版本化规则 | 不修改现有 Prompt 内容 | diff 审查 |
| Log/Trace schema | 调试与审计 | 统一 stage、trace_id、status、elapsed_ms、error_code 与 redaction | 允许增加字段，不输出秘密 | log assertions + redaction tests |
| Langfuse public SDK | 可选外部观测 | 作为 exporter，不让业务代码依赖私有 API | 关闭时主链正常 | exporter mock/off tests |
| pytest markers | 测试路由 | 严格注册 unit/contract/integration/eval/e2e/live/slow | 默认继续跳过 live | collect-only + marker CI |
| uv.lock | Python 可复现依赖 | 冻结实际安装解析 | 不静默升级生产依赖 | clean install + test |
| GitHub Actions | 自动质量门禁 | 最小权限、超时、缓存、分层 job | 默认完全离线 | workflow parse + PR run |

## 10. Engineering Implementation Contract

| Category | Files / modules | Required behavior or documentation | Verification | Status |
| --- | --- | --- | --- | --- |
| Architecture and dependency direction | AGENTS.md、docs/architecture、Backend/finance_agent 边界 | Router 薄、application service 管用例、Agent 模块管决策、Provider 管外部系统；Finance 不可运行依赖；不做兼容 Adapter | 文档一致性 Review、import/architecture test（建立后） | Required |
| Docstrings, types, field meaning, and section navigation | 所有新增/修改 Python 边界 | 中文 Google-style docstring；公开函数/类/节点/工具/状态显式类型；注释解释意图、失败与下游影响 | Ruff/Pyright、Review、API docs | Required |
| Configuration, env, secrets, constants, and prompts | typed Settings、.env.example、Prompt 规范 | 配置只加载一次并注入；秘密不入库；稳定业务常量留代码；Prompt 集中版本化 | settings tests、secret/redaction checks | Required |
| Terminal output, logs, traces, metrics, and artifacts | backend logging、Financial-MCP-Agent/src/observability | 终端简洁；logger 使用 logging.getLogger(__name__) 和参数化消息；稳定字段；长内容受控存放；无秘密 | log/trace contract、artifact inspection | Required |
| Validation, errors, retry/fallback, state, and compatibility | API 边界、Provider、Agent state | 外部输入边界校验；稳定错误码；不吞错；有限重试/总时限；副作用幂等；公共协议不变 | error-path tests、timeout/retry tests、contract tests | Required |
| Tests, Agent evaluation, and handoff evidence | tests、CI、Compose、PR 模板 | 默认离线；路径门禁；Compose E2E；Live 显式；每 PR 记录命令、结果、跳过、风险和回滚 | 本地与 CI 结果、E2E trace_id、Review 报告 | Required |

## 11. Test and Validation Strategy

### 11.1 Existing Tests to Run

- 在仓库根运行 python -m pytest backend -q：验证后端现有行为，预期无新增失败。
- 在仓库根运行 python -m pytest Financial-MCP-Agent -q -m "not live"：验证 Agent 离线行为，预期无外部调用且无新增失败。
- 在仓库根运行 python -m pytest tests/evals -q -m "eval_smoke and not live"：验证固定数据离线评测。
- 在仓库根运行 python -m pytest -q：验证根级回归并确认 live 默认跳过。
- 在 frontend 运行 npm ci、npm run type-check、npm run build；引入 ESLint 后增加 npm run lint。
- 在仓库根运行 docker compose -f docker/docker-compose.yml config：验证 Compose 静态配置。

### 11.2 New or Updated Tests Required

- tests/contract：REST、流式事件、Agent state、工具 Schema、日志/Trace 事件的契约测试；变更公共契约时必须先出现明确失败。
- tests/integration 或 backend 对应目录：FastAPI + PostgreSQL 真实测试库、事务清理、失败回滚、Provider fake 集成。
- tests/e2e：离线 Compose 主路径和一个失败路径；使用 fake model/Tushare/MCP，不读取生产 Secret。
- tests/unit：typed Settings、redaction、错误码、有限 retry/timeout 与 trace context。
- live：真实模型/Tushare/只读 MCP 的最小固定案例，必须带 live marker 和环境保护，默认 collection 后不执行。
- frontend：至少补 lint；浏览器 E2E 的具体框架和测试文件在 Milestone 3 以现有 Vue 栈和维护成本确认，未确认前不得擅自增加依赖。

### 11.3 Manual Smoke Tests

离线主路径：

1. 使用测试 Compose 启动 PostgreSQL、Backend、Frontend 和 fake Provider。
2. 检查 /api/health、数据库连接和前端页面。
3. 创建隔离测试会话，发送固定金融问题。
4. 验证前端收到开始、阶段、答案和结束事件，后端状态为成功。
5. 验证日志与 Trace 可通过同一 trace_id 关联且无秘密。

离线失败路径：

1. 让 fake Provider 返回超时或无效工具参数。
2. 验证系统产生稳定 error_code 或明确降级，不把空结果伪装为成功。
3. 验证容器仍健康，测试数据被清理。

Live 主路径：

1. 在本地受保护 .env 或 GitHub Environment 中显式启用 live。
2. 单并发发送固定、低成本、只读金融查询。
3. 验证真实模型/数据源调用、数据日期/来源、前后端渲染、trace_id 和耗时。
4. 不上传原始敏感内容；结束后清理隔离测试数据。

### 11.4 Agent/RAG/Tool Evaluation, if applicable

- 继续使用 tests/evals 的固定 smoke 数据和当前 metrics，不伪造基线。
- 后续每个模块迁移前新增对应 characterization cases；迁移后同一数据集做对比。
- 路由验证预期 route/skill/tool；实体解析验证标准化实体与歧义；Planner/Executor/Verifier 在模块存在后自动从 skip 转为执行。
- 工具失败、无证据、超时、无权限和参数无效必须有负例。
- 准确率、成功率、延迟和成本目标只有在基线实测后才能写入门禁。

### 11.5 Expected Terminal / Logs / Trace / Artifacts

- 终端：每个阶段一行摘要，包含 stage、status、elapsed_ms、trace_id 和必要的 error_code；不打印完整 Prompt/响应或大 JSON。
- 结构化日志：至少包含 timestamp、level、logger、stage、run_id/trace_id、status、elapsed_ms、error_code；按场景增加 route_result、selected_tool、params_valid、fallback_reason。
- Trace：一次聊天轮次一个 trace；会话用 session_id 聚合；route/rewrite/planner/executor/verifier/synthesis 使用稳定低基数 span 名；模型为 generation，工具为 tool observation。
- Artifacts：离线/Live E2E 只保留脱敏摘要、版本、trace_id、耗时、断言和失败诊断；短期保留策略在实施时写入规范。
- 所有输出先通过 key-based redaction；Authorization、Cookie、Token、password、secret、user profile 和原始敏感内容不可出现。

### 11.6 Acceptance Criteria

| Behavior / Risk | Test or Check | Command / Method | Expected Result |
| --- | --- | --- | --- |
| 工程规则无歧义 | 文档/模板 Review | 对照 AGENTS、CONTRIBUTING、Issue/PR Template | 直接重构、测试层级、回滚和权限口径一致 |
| 默认测试不花钱 | marker 与网络隔离检查 | pytest collect + offline CI | live 被跳过，无真实 Secret/外部请求 |
| Python 质量可执行 | Ruff/Pyright/pytest | 冻结后的统一命令 | 新范围全部通过；历史债有显式基线而非 ignore |
| 前端质量不回归 | lint/type/build | npm run lint/type-check/build | 全部通过 |
| API/流协议兼容 | contract tests | pytest tests/contract | Schema 与事件顺序满足冻结契约 |
| 数据库集成隔离 | PostgreSQL integration | pytest integration | 测试库独立、失败回滚、无残留 |
| 完整离线链路可跑 | Compose E2E | 专用脚本/compose override | 健康、主路径、失败路径、清理均通过 |
| Live E2E 安全 | 手工受保护运行 | 显式 live 命令/workflow_dispatch | 真实读成功、无生产写、预算受控 |
| 日志与 Trace 可关联 | log/trace assertions | unit + E2E inspection | 同一 trace_id 贯穿且 stage 名稳定 |
| 敏感信息不泄露 | redaction tests | pytest focused + artifact inspection | 秘密键值均被遮蔽 |
| 可回滚 | PR/版本检查 | squash commit + dry-run rollback 说明 | 单里程碑可 git revert/切回上个镜像 |
| 现有行为不回归 | 全仓回归 | python -m pytest -q + frontend checks | 不新增失败；所有 skip 有原因 |

## 12. Milestones

### Milestone 0: Safety and Baseline Check

**Goal:** 确认仓库、分支、用户改动、外部权限、现有命令和基线，保证后续不会覆盖用户工作或基于过期事实开发。

**Files / Modules:** 全仓只读；PLAN.md 的 Progress、Decision Log、Surprises & Discoveries 可更新。

**Implementation Intent:** 运行 git status --short、git branch --show-current、git fetch 后只读比较 origin/main；读取最近 AGENTS；确认精确测试命令、Docker 可用性和 CI 状态；为 Milestone 1 准备 Issue 内容与分支名，但未经授权不创建远程对象。

**Tests / Checks:** 运行现有 Python、frontend 和 docker compose config 基线；任何无法运行的命令记录原因和剩余风险。

**Expected Result:** 获得带日期、命令、结果、跳过项和工作区状态的基线；确认 Milestone 1 只改文档/模板。

**Stop Condition:** 目标文件存在未知用户改动；main 落后/分叉且无法安全同步；基线存在与本计划无关的阻断失败；需要未授权外部写操作。

**Rollback Note:** 无业务编辑；仅撤销本计划治理区块的记录即可。不得删除用户文件。

**Handoff Evidence:** git 状态、分支/提交、测试命令摘要、Docker/CI 可用性、阻断项、拟用 Issue/分支名。

### Milestone 1: Lock or Add Tests / Reproduction

**Goal:** 交付工程宪法与协作门禁，使后续每个功能都按唯一 SOP 描述、评审、验收和回滚。

**Files / Modules:** 仅限 8.3 中 Milestone 1 路径。

**Implementation Intent:** 重写 AGENTS.md；新增面向小白的 CONTRIBUTING、架构/代码结构/测试/可观测规范；新增 Feature、Bug、PR 模板。内容必须明确直接模块重构、不做兼容 Adapter、中文注释/类型要求、终端/日志/Trace 规则、离线/Live 测试分层、权限边界和 Definition of Done。

**Tests / Checks:** 检查 Markdown 链接、YAML 解析、模板字段、术语一致性和 git diff；运行现有最小回归证明纯文档变更未触碰 Runtime。

**Expected Result:** 小白可以从 CONTRIBUTING 完整走完 0 到 merge；Agent 可以从 AGENTS 得到明确允许/禁止和验证顺序；Issue/PR 不再缺关键证据。

**Stop Condition:** 规则之间存在冲突；需要改变业务 Runtime、依赖、API 或 GitHub 设置；用户对模板强制字段有新的 P0 决策。

**Rollback Note:** 整个 Milestone 1 独立分支/PR；合并前丢弃分支，合并后 git revert 对应 Squash 提交。

**Handoff Evidence:** 文件清单、文档/YAML 检查、现有回归结果、独立 Review 结论、PR 风险与回滚说明。

### Milestone 2: Implement Core Change

**Goal:** 建立可复现、可在本地和 CI 使用同一命令执行的静态质量与依赖基础设施。

**Files / Modules:** 仅限 8.3 中 Milestone 2 路径；不得触碰业务行为。

**Implementation Intent:** 验证并冻结 uv 项目/工作区边界；生成受审 lockfile；配置 Ruff、Pyright、pytest strict markers；前端增加 ESLint；CI 增加最小 permissions、timeout、cache 和稳定 job 名。新增代码严格，历史代码采用明确 include/baseline 渐进收紧，禁止全仓格式化。

**Tests / Checks:** clean environment install；Ruff format-check/lint；Pyright 目标范围；pytest collect 与现有离线回归；frontend lint/type-check/build；CI YAML 解析。

**Expected Result:** 开发者与 GitHub Actions 使用相同锁定依赖和质量命令；不依赖机器上的偶然包；未产生大面积无业务 diff。

**Stop Condition:** uv workspace 会改变 MCP 子项目发布语义；依赖解析需要升级生产包；Pyright 只能靠全局 ignore 通过；新增前端 lint 需要无关全仓重写。

**Rollback Note:** 独立 PR；回滚 pyproject/package 配置和 lockfile必须一起完成。不能只删 lockfile留下已升级依赖声明。

**Handoff Evidence:** 冷启动安装命令、锁文件 diff、各质量命令结果、CI 运行链接、历史债基线和未覆盖范围。

### Milestone 3: Add Validation, Error Handling, and Observability

**Goal:** 建立分层测试、离线完整链路和最小统一可观测契约，为业务模块直接重构提供安全网。

**Files / Modules:** 仅限 8.3 中 Milestone 3 和 Milestone 4 路径；如范围过大，必须拆成 3A 测试基础设施与 3B 可观测性两个独立 Issue/PR，仍按一次只执行一个子里程碑。

**Implementation Intent:** 增加 unit/contract/integration/e2e marker 与目录；创建 fake Model/Tushare/MCP；使用隔离 PostgreSQL；锁 REST/流式事件和当前 Agent 边界；建立 Compose 离线 E2E；统一 request/run/trace context、结构化日志、Langfuse exporter 公共接口与 key-based redaction。只接入观测，不改变路由、工具和回答业务决策。

**Tests / Checks:** focused unit/contract/integration；离线 eval；Compose 主路径和错误路径；Langfuse 关闭/失败不影响主链；redaction；全仓回归；frontend lint/type/build。

**Expected Result:** 任一后续模块可以在不花钱的情况下验证接口、数据库和前后端完整链路；失败能通过 trace_id 定位；敏感信息不进入输出。

**Stop Condition:** 需要更改 API/DB Schema/鉴权；需要真实生产服务才能让离线 E2E 通过；观测接入改变业务时序；单 PR 同时跨越测试与观测后不可评审；两次聚焦修复仍失败。

**Rollback Note:** 测试和观测分别独立 PR；关闭 Langfuse 时本地日志/Trace 仍可用；回滚不依赖恢复旧 Runtime。

**Handoff Evidence:** 测试矩阵、Compose 日志摘要、trace 示例的脱敏字段、redaction 断言、失败路径、资源清理结果、CI 链接。

### Milestone 4: Verification and Narrow Fixes

**Goal:** 以与真实用户相同的入口验收完整基础设施，只修复证据明确的同范围问题。

**Files / Modules:** 只允许修改 Milestone 2/3 已涉及且由失败直接指向的文件，以及测试/文档/PLAN 治理区块。

**Implementation Intent:** 按静态检查 → unit → contract → integration → eval → frontend → Compose offline E2E → protected Live E2E 的顺序运行；比较 CI 与本地；执行独立 Agent diff Review；修复仅限具体失败。

**Tests / Checks:** 执行 11.1 和 11.6 全部适用项；Live E2E 使用固定少量只读问题和隔离测试数据。

**Expected Result:** Required 与路径集成门禁通过；完整离线 E2E 通过；Live E2E 有真实读取证据或准确记录无法执行原因；无秘密、无生产写、无未解释 skip。

**Stop Condition:** 两次连续聚焦修复仍失败；修复需要跨出允许范围；真实服务凭证/预算/隔离环境不满足；发现数据污染或安全风险。

**Rollback Note:** 失败时保留诊断，停止扩大修改；回滚当前未合并分支或 revert 独立 Squash 提交；测试资源必须清理。

**Handoff Evidence:** 完整命令与结果、CI/Live 运行链接或本地摘要、trace_id、独立 Review 问题处理表、未验证项与风险。

### Milestone 5: Documentation and Handoff

**Goal:** 把实际可运行命令、结果和经验回填为唯一真相源，并为首个受控主链业务模块创建下一份规格输入。

**Files / Modules:** AGENTS.md、CONTRIBUTING.md、docs/architecture、docs/engineering、README 相关入口、当前 specs 目录和测试基线文档；不得改业务代码。

**Implementation Intent:** 删除失效或重复口径；文档只写已验证命令；更新 Progress、Decision Log、Surprises & Discoveries、Outcomes & Retrospective；列出下一模块候选及其真实入口、契约和风险，但不实施模块。

**Tests / Checks:** 文档链接/命令复核；全仓 diff；安全检查；确认所有 Review conversation 与 CI 完成。

**Expected Result:** 新会话无需聊天历史即可理解工程结构、运行测试、走完 PR 和安全回滚；首个业务模块可以进入独立 Requirement Definition。

**Stop Condition:** 文档声称的命令无法复现；仍有相互冲突的测试/回滚规则；存在未关闭 P0 安全问题。

**Rollback Note:** 文档 PR 可独立 revert；不得为了文档一致性修改 Runtime。

**Handoff Evidence:** 最终文档索引、已验证命令表、CI/Review 状态、遗留风险、推荐下一模块及其新 Spec 路径。

## 13. Execution Protocol

- Execute exactly one milestone at a time.
- Start each milestone by restating its goal and allowed files.
- Run git status --short before editing.
- Do not overwrite user changes.
- Do not modify files outside allowed scope.
- Do not move to the next milestone without reporting evidence and receiving the required authorization.
- If a required change is outside scope, stop and ask for approval.
- If tests fail, inspect the narrowest relevant logs and fix only the concrete issue.
- If two consecutive repair attempts fail, stop and produce MILESTONE_EXECUTION_BLOCKED.md or等价失败报告。
- Do not claim completion without verification evidence.
- Update Progress, Decision Log, Surprises & Discoveries, and Outcomes & Retrospective as work proceeds.
- Satisfy the applicable Engineering Implementation Contract and report Not applicable categories explicitly.
- 每个可交付里程碑采用一 Issue、一短分支、一 PR、一 Squash 提交；分支名使用 feat/<issue>-<slug>、fix/<issue>-<slug>、refactor/<issue>-<slug>、docs/<issue>-<slug> 或 chore/<issue>-<slug>。
- 开始编码前先写会失败的复现/characterization/contract test；不能写测试时必须说明可观察替代证据和原因。
- 每次编辑后先审 diff，再运行由窄到宽的检查；不得靠扩大 ignore、删断言或跳过测试解决失败。
- 任何 Agent 模块重构都必须在同一 PR 更新全部内部调用方并删除被替换实现、旧导入、重复 Prompt 和过期 Flag；不能创建兼容 Adapter。
- 真实服务只能在显式 Live E2E 使用；真实读、隔离写、生产写禁止；测试结束清理资源。
- 未经用户明确授权，不执行 commit、push、PR、merge、分支保护、release 或部署。

## 14. Rollback Plan

Before implementation, rollback is simply discarding the unexecuted plan. During implementation, each milestone should be isolated so it can be reverted independently.

- 分支：从已验证的最新 origin/main 建短分支，不在 main 直接开发。工作区若有用户改动，先停止，不 stash、不覆盖、不清理。
- 合并前：测试失败或方向错误时保留失败报告，丢弃未合并分支即可；不得删除用户文件或使用 git reset --hard。
- 合并后：每个里程碑 Squash Merge 为一个主分支提交；通过新 revert PR 执行 git revert，不改写 main 历史。
- 构建产物：候选镜像使用不可变提交 SHA/tag；异常时切回上一已通过 Compose/Live 验收的镜像，不依赖漂移的 latest。
- 配置：新增开关必须有默认安全值和删除期限；回滚配置使用上一已审版本。不得保留旧实现只为配置切换。
- 依赖：依赖声明与 lockfile 同步回滚；不得产生半升级状态。
- 数据库：本计划禁止 Schema 变更；集成/E2E 仅使用隔离测试库并自动清理。若未来必须迁移，另开包含 backup、upgrade、downgrade 与恢复演练的高风险计划。
- API：本计划禁止破坏性协议变更，因此代码 revert 应恢复兼容行为；若未来协议升级，必须先有版本策略。
- 停止条件：出现数据污染、秘密泄露、生产写、鉴权绕过、无法解释的契约变化或两次连续修复失败时立即停止，不继续“试到能过”。

## 15. Progress

- [x] Milestone 0: Safety and Baseline Check
  - Completed: 2026-08-20
  - Evidence: main 与 origin/main 均为 4570ee9；根回归 51 passed、4 skipped、4 deselected；前端 type-check/build 与 Compose config 通过；详见 milestones/m0/MILESTONE_EXECUTION_REPORT.md。
- [x] Milestone 1: Lock or Add Tests / Reproduction
  - Completed: 2026-08-20
  - Evidence: AGENTS/CONTRIBUTING/architecture/engineering docs and GitHub templates added; YAML/template/link checks and root pytest passed; see milestones/m1/MILESTONE_EXECUTION_REPORT.md.
- [x] Milestone 2: Implement Core Change
  - Completed: 2026-08-20
  - Evidence: uv.lock generated and `uv lock --check` passed; Ruff, Pyright, pytest, frontend lint/type-check/build and Compose config passed; see milestones/m2/MILESTONE_EXECUTION_REPORT.md.
- [x] Milestone 3: Add Validation, Error Handling, and Observability
  - Completed: 2026-08-20
  - Evidence: 分层测试、Fake Model/Tool/MCP、隔离 PostgreSQL、Trace 脱敏与 exporter 故障隔离已建立；Compose 启动 PostgreSQL、FastAPI、Vue/Nginx 并从前端代理入口完成离线聊天，11 passed；详见 milestones/m3/MILESTONE_EXECUTION_REPORT.md。
- [x] Milestone 4: Verification and Narrow Fixes
  - Completed: 2026-08-20
  - Evidence: 静态、分层/全仓离线、前端、Compose config 和 Compose 全栈 E2E 全部通过；Live marker 可收集但因显式凭证/开关为空未执行；详见 milestones/m4/MILESTONE_EXECUTION_REPORT.md。
- [x] Milestone 5: Documentation and Handoff
  - Completed: 2026-08-20
  - Evidence: `verification-baseline.md`、SOP/测试文档和 PLAN 交接入口已按实际命令更新；下一模块必须另开 Spec/Plan。

## 16. Decision Log

| Date | Decision | Reason | Source |
| --- | --- | --- | --- |
| 2026-08-20 | Finance-agent-Skills 为唯一主仓库 | 后续工程化开发和简历展示必须有唯一真相源 | 用户确认 |
| 2026-08-20 | 采用结构化分模块直接重构 | 不养双轨，同时保持小步评审和独立回滚 | 用户确认、SOLUTION_TRADEOFF.md |
| 2026-08-20 | Finance 仅作为证据来源 | 历史实现不完整且有冗杂，不能原样复制 | 用户说明、CODEBASE_RECON.md |
| 2026-08-20 | 首个实施 PR 只做工程规则与模板 | 先建立审查后续变更的统一合同 | CLARIFICATION_QUESTIONS.md |
| 2026-08-20 | CI 默认离线，Live E2E 显式执行 | 兼顾稳定低成本与真实完整链路验收 | 用户确认 |
| 2026-08-20 | Live 真实读、隔离写、生产写禁止 | 控制成本、副作用和数据安全风险 | 用户确认 |
| 2026-08-20 | Squash-only 与单里程碑回滚 | 让每个主分支提交对应一个可撤销交付物 | 用户确认、GitHub/Google SRE 实践 |
| 2026-08-20 | Redis、生产 CD、DB 迁移平台后置 | 当前没有真实运行目标，不建设空壳平台 | 用户确认 |
| 2026-08-20 | 本地 Python 命令固定使用仓库虚拟环境 | 系统 PATH 的 python 是 Windows Store 占位符，仓库 .venv 为 Python 3.12.13 且已有 pytest | Milestone 0 基线 |
| 2026-08-20 | M1 仅修改工程规则、文档和 GitHub 模板 | 先建立后续模块迁移可执行的共同合同，避免业务代码与规则同时变化 | PLAN.md M1 |
| 2026-08-20 | Python 依赖由根 pyproject.toml + uv.lock 统一解析 | 当前 backend/requirements.txt 无法为跨目录测试和 CI 提供单一锁定环境 | PLAN.md M2、uv lock --check |
| 2026-08-20 | 历史前端 lint 规则先做非阻断警告 | 直接修复 400+ 遗留模板风格问题会产生无关巨量 diff；新代码门禁先阻断真正错误 | PLAN.md M2、首次 npm run lint |
| 2026-08-20 | 离线 E2E 使用 tests/e2e 专用应用装配替换聊天服务 | 保留真实 FastAPI Router、Schema、Nginx 和前端构建，同时从结构上阻断模型和生产服务调用 | PLAN.md M3、Compose E2E |
| 2026-08-20 | Trace exporter 失败不得影响本地 Trace 和业务主链 | Langfuse 是可选出口，外部观测不可成为聊天可用性的硬依赖 | AGENTS.md、M3 unit test |
| 2026-08-20 | M4 不在无显式凭证和隔离环境时触发 Live E2E | 默认测试不得访问付费模型/生产服务；缺少安全边界时记录未执行而不是绕过门禁 | AGENTS.md、Live 环境检查 |
| 2026-08-20 | M5 以 verification-baseline.md 作为基础设施验收摘要 | 让新会话无需聊天历史即可执行真实命令、理解限制并进入首个模块 Spec | M5 文档复核 |

## 17. Surprises & Discoveries

| Finding | Impact | Action |
| --- | --- | --- |
| 当前核心 chat service、router、executor 文件规模很大 | 任何业务迁移都可能跨越隐式职责 | 每个模块先做调用方清单和 characterization tests |
| 当前 Compose 无 Redis，但部分描述超前 | 文档与真实代码存在口径风险 | 文档只描述已实现能力，Redis 明确后置 |
| 当前 trace 截断但缺少完整 key-based redaction | 日志/Trace 可能泄露敏感字段 | 在可观测里程碑先建立脱敏契约和测试 |
| 当前 eval 已为未迁移模块提供 find_spec 守卫 | 可渐进迁移而无需伪造实现 | 保留守卫，模块出现后自动启用相应评测 |
| 当前 Python 回归产生 56 个 datetime.utcnow 弃用警告 | 不阻断基础设施，但未来 Python 版本升级可能失败 | 作为独立技术债记录，不在 M0 越界修复 |
| 前端生产构建存在动态/静态混合导入和超大 chunk 警告 | 当前构建成功，但首屏体积和拆包策略需要后续实测 | 记录为前端性能债，不在基础设施基线中顺手重构 |
| M1 YAML 与文档检查需要额外脚本 | 模板本身不能依赖人工记忆验证 | 在后续 CI 里加入稳定的文档/配置检查入口 |
| uv sync 按锁文件重新解析了若干依赖版本 | 本地环境与 requirements.txt 的隐式安装状态存在漂移 | 后续 CI 统一 `uv sync --locked`；若运行时出现兼容差异，按具体包建立独立回归 |
| Pyright 发现 9 个未迁移历史 Agent import warning，但错误数为 0 | Planner/Executor/Verifier 评测尚未迁移，严格类型入口暂时只能给 warning | 保留 warning，模块迁移后通过 find_spec 守卫和边界类型逐步消除 |
| Alpine Nginx 容器内 `localhost` 健康检查连接失败 | 首次完整 Compose 被误判 unhealthy，应用本身正常 | 健康检查固定为 `127.0.0.1`，重跑后完整链路 11 passed |
| PostgreSQL 新库启动时增量迁移对已存在列报错后事务进入 aborted 状态，但应用仍记录初始化成功 | 当前 create_all 已生成目标列，E2E 未失败；生产迁移语义仍存在可靠性和误报风险 | 不在基础设施里程碑越界修改；作为首个独立数据库治理 Issue 处理 |
| Live marker 实际收集到 4 个历史测试，但仓库没有专用 live E2E 契约与安全环境校验 | 不能把“可收集”误报成“真实服务已验收” | M4 记录为未执行；首个真实 Provider 模块迁移时另建受保护 workflow_dispatch 验收 |

## 18. Outcomes & Retrospective

- What changed: M0 完成只读基线；M1 建立工程宪法和协作模板；M2 增加可复现工具链；M3 增加分层测试、Fake Provider、隔离 PostgreSQL、完整离线 Compose 服务链和 Trace 脱敏/故障隔离。
- What was verified: M3 本地分层测试通过；Compose 中 PostgreSQL、FastAPI、Vue/Nginx 健康，从前端代理入口完成健康与聊天请求，11 passed；exporter payload 也已验证脱敏，资源已清理。
- What remains risky: 当前已知为超大文件、隐式导入/环境变量、PostgreSQL 增量迁移事务语义、9 个未迁移类型 warning、历史前端 chunk 警告和未执行的真实 Live E2E；Trace exporter 的 key-based 脱敏已闭环，字符串模式脱敏作为后续增强。
- What should be improved next: 首个受控主链模块从 typed state/主链骨架开始，另开完整 Spec Coding 链；数据库迁移事务误报另开高风险治理计划。

## 19. Deferred Work

- 受控主链业务迁移顺序候选：typed state/主链骨架 → 实体解析与两阶段路由 → route-specific rewrite/Prompt → Tool Discovery/Planner/Validator → Executor/Evidence Envelope → Verifier/Controller/有限 Replanner → Synthesis/前端事件 → 全链清理。
- 上述每个模块必须根据统一面试问题口径与项目 SSOT 重新做需求定义、Gap 审核、方案权衡和独立 PLAN；本计划不预判其最终算法。
- 可安装 finance_agent 包的精确目录与首次直接迁移边界在基础设施完成后按真实 import 图冻结；不建立旧包转发。
- 浏览器 E2E 框架的最终选型在测试里程碑根据 Vue/Vite 现状和依赖成本确认。
- GitHub main 分支保护、Squash-only、自动删分支属于仓库外部设置，需用户明确授权后单独执行。
- Redis、生产部署平台、Canary 基础设施、OTel Collector、数据库迁移平台和长期记忆重构继续后置。

## 20. Handoff to Next Module

本基础设施计划 M0-M5 已完成。下一步不要继续修改本计划；请为首个受控主链模块创建独立 `docs/specs/<module>/REQUIREMENT_SPEC.md`，先完成真实入口和调用方勘察，再冻结该模块的契约、测试、观测、回滚和直接重构范围。
