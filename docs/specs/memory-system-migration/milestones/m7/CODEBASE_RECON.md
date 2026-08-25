# CODEBASE_RECON.md

## 1. Reconnaissance Target

Requirement source: `docs/specs/memory-system-migration/milestones/m7/REQUIREMENT_SPEC.md`

Focus areas: 自然语言记忆命令的 REST/WebSocket 入口、受控聊天应用链、权威记忆写入与删除、pending confirmation 持久化、Redis/pgvector/Mem0 派生刷新、前端 API/store/composable/sidebar、测试与 CI。

Out-of-scope reminders: 不替换受控金融工作流；不进入 M8/M9；不启用真实付费模型、真实 Tushare 或 Mem0 网络；不把 Redis/pgvector/Mem0 变成权威源；不修改生产凭据和真实用户数据。

## 2. Project Overview

Project type: 全栈金融 Agent，包含 FastAPI 后端、Vue 3 前端、受控对话工作流、PostgreSQL/Redis/pgvector 记忆基础设施和 Docker Compose 验收。

Languages: Python 3.12、TypeScript、Vue SFC、SQL/Alembic、YAML。

Frameworks: FastAPI、Pydantic v2、SQLAlchemy async、Alembic、Vue 3、Pinia、Axios、Vite、Nginx。

Runtime / package manager: Python 由 uv/`uv.lock` 管理；前端由 npm/`package-lock.json` 管理；容器由 Docker Compose 管理。

Main service type: 同步 REST + 基础 WebSocket 对话服务，后台运行 STM/LTM/semantic-index Workers。

Frontend/backend split: `backend/` 提供 API、应用和基础设施；`Financial-MCP-Agent/src/` 提供受控工作流、领域合同、工具和 Trace；`frontend/` 提供 Vue UI。

Test framework: Pytest 分 unit/contract/integration/evals/e2e；前端目前只有 ESLint、vue-tsc 和 Vite build，未配置 Vitest/Playwright。

Deployment clues: `docker/docker-compose.yml` 为常规拓扑，`docker/docker-compose.offline.yml` 为隔离 PostgreSQL/pgvector、Redis、FastAPI、Nginx、Vue 的 deterministic E2E；GitHub Actions 有 Python、Frontend、Compose packaging 和 Offline Compose E2E 四项门禁。

Confirmed facts:

- `backend/main.py` 是 FastAPI 入口，并按 feature flags 启动 LTM、STM 和 semantic-index Worker。
- `backend/routers/chat.py` 的 REST 和 WebSocket 都调用 `build_chat_use_case(db).execute(ChatCommand(...))`。
- `ControlledChatUseCase.execute` 当前先 `prepare_turn`，再执行 M6 retrieval，随后运行完整受控金融 workflow，并提交消息、Working State 和结果。
- `SqlAlchemyAuthoritativeMemoryRepository` 已支持显式 profile/text 写入、文本更新、单条软删除、候选确认、审计和 INDEX Outbox。
- `MemoryRecordRow`、`MemoryAuditEventRow`、`MemoryOutboxTaskRow`、`MemoryProviderReferenceRow` 和 `MemorySemanticIndexRow` 均已存在；没有 pending memory command 表。
- 前端已有 `memoryApi`、`memoryStore`、`useMemory` 和 `MemorySidebar`，但它们使用旧式 profile/item CRUD 和 `confirm=true` 清空接口。

Assumptions:

- Assumption: M7 应继续使用当前 `POST /api/chat/message` 和 `/api/chat/stream` 作为自然语言入口，而不是增加第二聊天入口。
- Assumption: M7 的 UI 控制优先复用 `MemorySidebar`，是否新增模态框/组件由方案阶段决定。

## 3. Directory Structure Summary

| Path | Apparent role | Relevance | Notes |
| --- | --- | --- | --- |
| `backend/routers` | REST/WS 协议适配 | High | chat 与 memory 路由是公开边界 |
| `backend/application/chat` | 单轮聊天编排与共同结果合同 | High | 当前唯一前台主链入口 |
| `backend/application/memory` | 记忆 authority/context/retrieval/candidate contracts | High | M7 新用例应位于此边界 |
| `backend/infrastructure/memory` | SQL/Redis/Mem0/pgvector 实现 | High | 所有权、事务和派生刷新依赖这里 |
| `backend/db` / `backend/migrations` | ORM 与 Alembic | High | pending command 若持久化将需要 expand-first migration |
| `backend/services/memory_service.py` | 历史/兼容记忆服务 | High | 仍被 memory router 调用，但与新 authority 边界并存 |
| `Financial-MCP-Agent/src/memory` | provider-independent contracts/policy | High | M2-M6 稳定记忆合同所在 |
| `Financial-MCP-Agent/src/conversation` | 受控金融 workflow | High | 普通请求必须保持原顺序，命令分支不得污染 planner/evidence |
| `frontend/src/api` | Axios 与公开 TS 类型 | High | 需要映射统一命令结果合同 |
| `frontend/src/stores` / `composables` | 记忆和聊天客户端状态 | High | 当前存在乐观更新但失败不回滚 |
| `frontend/src/components/memory` | 画像和记忆面板 | High | M7 UI 的主要候选入口 |
| `tests` | 单元、合同、集成、评测和 E2E | High | 已有 M0-M6 回归，缺 M7 命令状态机和前端测试 |

## 4. Entry Points

### 4.1 Startup Entry

- 后端：`backend/main.py` 创建 FastAPI、注入 AuthMiddleware、挂载 `/api/chat` 和 `/api/memory`，lifespan 初始化数据库、Redis、Trace 和 Workers。
- 数据库：`backend/db/database.py:init_db` 对历史表使用 `create_all`，对 memory-v1 表使用 Alembic；M7 新表不能落入历史启动 DDL。
- 前端：`frontend/src/main.ts` 启动 Vue；`ChatView.vue` 和 `ReportView.vue` 都挂载 `MemorySidebar`。
- 容器：`docker/docker-compose.offline.yml` 提供完整隔离 E2E。

### 4.2 Request / Task Entry

- 自然语言 REST：`POST /api/chat/message` -> `backend/routers/chat.py:send_message`。
- 自然语言 WebSocket：`/api/chat/stream` -> `backend/routers/chat.py:chat_stream`。
- 显式记忆 UI/API：`/api/memory/profile/*`、`/api/memory/items/*`、`DELETE /api/memory/all`。
- 前端聊天：`frontend/src/composables/useChat.ts` -> `chatApi.sendMessage`。
- 前端记忆：`MemorySidebar.vue` -> `useMemory.ts` -> `memoryApi`。

## 5. Relevant Call Chain

```text
Chat input / REST / WebSocket
-> auth context + ensure_user_access
-> ChatCommand
-> build_chat_use_case
-> ControlledChatUseCase.execute
-> SqlAlchemyConversationRepository.prepare_turn
-> M6 governed retrieval
-> ControlledConversationWorkflow.run
-> Working State + message/result persistence
-> commit
-> ChatOutcome
-> REST ChatMessageResponse / WebSocket frames
-> Vue chat store/view
```

M7 期望但当前缺失的分支：

```text
Authenticated ChatCommand
-> typed memory-command preflight
-> ordinary finance? continue existing chain
-> explicit memory command?
   -> validate owner/target/scope/version
   -> inspect or authoritative mutation
   -> broad/destructive? persist pending confirmation
   -> commit audit/outbox/pending transition atomically
   -> return shared MemoryCommandResult and terminate before finance workflow
```

Confirmed segments:

- REST/WS 共享 `ChatCommand` 与 `ChatOutcome`。
- M6 retrieval 已在 workflow 前执行，但没有命令预检。
- 权威 repository 的单条写/删不会自行 commit，支持调用方事务。
- 文本写/删会 enqueue INDEX Outbox，当前权威过滤可立即排除删除记录。

Inferred segments:

- M7 可将命令预检装配到 `ControlledChatUseCase`，但最终位置需方案权衡，因为 `prepare_turn` 同时负责建立会话和写入当前 user message。
- 旧 `memory_service` 可继续承担兼容读取，但写入路径是否统一切到 authority repository 需澄清。

Unknown segments:

- WebSocket 客户端对新增结构化 memory-command frame 的具体消费方式未实现。
- pending command 的数据库约束、并发锁和状态转换尚不存在。
- 高影响 profile 命令如何与现有 candidate confirmation UI 合并尚未定义。

## 6. Related Files

### 6.1 Definitely Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/application/chat/use_case.py` | 唯一前台编排 | 命令必须在 finance workflow 前终止 | candidate modification | High |
| `backend/application/chat/contracts.py` | REST/WS 共同合同 | 需要兼容承载命令结果 | candidate modification | High |
| `backend/application/chat/factory.py` | 生产依赖装配 | 需要注入命令用例/仓储 | candidate modification | Medium |
| `backend/routers/chat.py` | REST/WS presenter | 映射统一结构化结果 | candidate modification | High |
| `backend/schemas/chat.py` | 公开 API schema | 兼容扩展命令字段 | candidate modification | High |
| `backend/application/memory/authority.py` | 权威写端口 | 可复用显式写/删语义 | candidate modification | High |
| `backend/infrastructure/memory/authority_repository.py` | SQL 权威实现 | 事务、所有权、审计、Outbox | candidate modification | High |
| `backend/db/models.py` | ORM 状态 | pending command 无现有模型 | candidate modification | High |
| `backend/migrations/versions` | 版本化 schema | pending persistence 需要迁移 | candidate modification | High |
| `backend/routers/memory.py` | 显式记忆 API | 当前 API 可能绕过统一命令结果 | candidate modification | High |
| `backend/schemas/memory.py` | 记忆 DTO | 当前类型宽松且默认可变容器 | candidate modification | Medium |
| `frontend/src/api/index.ts` | TS API 合同 | REST/WS 命令状态需要映射 | candidate modification | Medium |
| `frontend/src/composables/useMemory.ts` | 客户端编排 | 当前乐观写失败不回滚 | candidate modification | Medium |
| `frontend/src/stores/memoryStore.ts` | 记忆状态 | 需承载 pending/partial/error | candidate modification | Medium |
| `frontend/src/components/memory/MemorySidebar.vue` | 记忆 UI | inspect/delete/confirm/cancel 入口 | candidate modification | Medium |

### 6.2 Probably Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/services/memory_service.py` | 旧兼容服务 | 现有路由使用，需决定保留或收口 | candidate modification/read-only | High |
| `backend/infrastructure/memory/redis_cache.py` | Redis 派生缓存 | 权威修改后需失效 | candidate modification | High |
| `backend/infrastructure/memory/index_tasks.py` | INDEX Outbox | 文本变化已复用 | read-only / narrow reuse | High |
| `backend/infrastructure/chat/repository.py` | 会话事务 | 命令与 session/message 的原子边界 | candidate modification | High |
| `Financial-MCP-Agent/src/memory/contracts.py` | 稳定领域枚举/类型 | 命令合同可能归属此处 | candidate modification | High |
| `Financial-MCP-Agent/src/tools/skill_trace.py` | Trace schema | 需要安全阶段事件 | candidate modification | Medium |
| `frontend/src/composables/useChat.ts` | 聊天交互 | 收到命令结果后刷新 memory UI | candidate modification | Medium |

### 6.3 Supporting Context

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/config.py` | typed Settings | TTL、范围上限和开关候选位置 | candidate modification | High |
| `backend/.env.example` | 安全配置文档 | 如新增可部署配置需同步 | candidate modification | Medium |
| `.github/workflows/ci.yml` | CI 门禁 | 前端测试脚本需接入 | candidate modification | Medium |
| `docker/docker-compose.offline.yml` | 完整离线环境 | M7 E2E 设置和真实 PostgreSQL 验收 | candidate modification | High |
| `tests/e2e/offline_app.py` | deterministic 应用装配 | 命令链需可离线运行 | candidate modification | Medium |
| `tests/e2e/test_offline_compose_stack.py` | 全栈 E2E | 真实 HTTP/DB/派生验证位置 | candidate modification | High |
| `tests/contract/test_controlled_chat_contract.py` | 受控入口合同 | 证明普通金融链不回归 | candidate modification | High |
| `tests/integration/test_memory_*` | M2-M6 数据合同 | 可复用数据库/用户隔离夹具 | candidate modification | High |
| `tests/evals/memory/data/characterization_v1.jsonl` | 版本化评测集 | M7 命令案例候选 | candidate modification | Medium |

### 6.4 Out of Scope

| Path / Area | Reason |
| --- | --- |
| `Financial-MCP-Agent/src/tools/chat_tushare_tools.py` | M7 不改变金融工具或真实数据调用 |
| Planner/Verifier/Executor 实现 | 命令分支应在其之前终止，普通路径只做回归 |
| `Financial-MCP-Agent/src/memory/mem0_client.py` 历史直接调用 | M6 已建立受控 Provider 边界，不能重新引入双轨写入 |
| 报告生成主链 | 报告模式记忆注入已明确延后 |
| 生产 `.env` / 真实数据库 | 不读出、不提交、不执行破坏操作 |

## 7. Existing Patterns to Reuse

| Pattern | Example file | Why reuse it |
| --- | --- | --- |
| REST/WS 共用 Application command/outcome | `backend/application/chat/contracts.py` | 防止两套行为和错误语义 |
| 调用方拥有事务，repository 不自行 commit | `authority_repository.py`、`conversation/repository.py` | 支持命令、审计、Outbox、pending 状态原子提交 |
| PostgreSQL authority + derived consistency | `AuthorityMutationResult` | 明确区分权威成功与派生待同步 |
| user_id 复合所有权过滤 | memory authority/provider repositories | 防止跨租户读写 |
| Versioned Alembic | `20260825_03_semantic_index.py` | M7 schema 可审查、可回滚、可 parity 测试 |
| Lease/idempotency/fail-closed | semantic/LTM workers | pending confirm 需要同等级安全语义 |
| Typed Settings + safe example | `backend/config.py`, `.env.example` | 配置集中、默认离线安全 |
| Stable trace stages without content | controlled trace and M6 retrieval | 可观测但不泄露正文/查询/用户 ID |
| Deterministic offline Compose | `docker-compose.offline.yml` | 默认 CI 不调用付费或生产服务 |

## 8. Data Flow and State

### 8.1 Input Data

- Chat REST: `user_id`, `message`, optional `session_id`。
- Chat WS: bearer/token auth + JSON `user_id/message/session_id`。
- Memory API: query user + typed-ish profile/item payload；当前 delete-all 使用 `confirm=true` 布尔查询参数。
- Frontend: Pinia user identity、chat session、memory form values 和 item IDs。

### 8.2 Intermediate State

- `ChatCommand` 是协议无关输入。
- `PreparedChatTurn` 包含 session、recent messages、summary、profile、Working State。
- M6 `RetrievalResult`/`MemoryContextItem` 只进入 Context/Rewrite/Synthesis。
- M7 尚无 `MemoryCommandIntent`、`MemoryCommandResult`、pending snapshot 或 confirmation state。

### 8.3 Persistent State

- 权威：`memory_records`、`user_invest_profiles`、`memory_candidates`、`memory_audit_events`、`memory_outbox_tasks`。
- 会话：`sessions`、`messages`、`memory_working_states` 和 summary metadata。
- 派生：Redis cache、`memory_semantic_index`、`memory_provider_references`。
- 缺失：绑定 user/session/fingerprint/version/expiry 的 pending command 权威表。

### 8.4 Output Data

- REST 当前只返回 `reply/session_id/memory_profile/context_window`。
- WS 当前返回 session_id、文本 reply、context_update/compaction/done/error frames。
- Memory CRUD 返回多种 ad hoc dict，未统一 `status/error_code/consistency_status/command_id`。
- 前端 memory store 保存 profile、items、stats，但没有 pending/confirmation/consistency 状态。

### 8.5 Potential Data Mismatch Points

- `backend/routers/memory.py` 文档仍称 item 来自 Mem0，但 M6 已把 PostgreSQL 设为唯一 authority。
- `MemoryItem`/TS `MemoryItem` 仍以旧 `id/content/source` 结构描述，M6 authority result 使用 `record_id/status/version/consistency_status`。
- 旧 profile endpoints 返回简单“已更新”，没有高影响字段确认状态。
- `DELETE /memory/all?confirm=true` 只靠一个布尔值，无法证明预览范围、版本、会话绑定、单次消费或重放安全。
- `useMemory` 先乐观更新 Pinia，API 失败时不回滚，可能向用户显示未实际持久化的状态。
- `MemoryProfileResponse.user_id` 向前端返回原始用户 ID；是否必要需隐私评审。

## 9. External Dependencies

| Dependency | Where called | Input | Output | Error handling / fallback |
| --- | --- | --- | --- | --- |
| PostgreSQL/SQLAlchemy | memory/chat repositories | owner-scoped commands and records | authority rows/audit/outbox | 事务 rollback、约束映射；M7 pending 未实现 |
| Redis | memory runtime/cache | versioned snapshots | rebuildable cache | 失败降级，不影响 authority |
| pgvector | semantic provider | deterministic query/content embedding | derived hits | authority post-filter；失败部分降级 |
| Mem0 | semantic provider adapter | explicit promoted text, infer=false | provider IDs/hits | 默认 disabled，user metadata fail-closed |
| LLM compatible provider | controlled workflow / candidate extraction | chat/prompt | route/synthesis/candidates | 默认 M7 不应依赖 live parsing；已有超时/启动校验 |
| Tushare | controlled tools | validated finance params | read-only market data | M7 命令分支必须保证不调用 |
| Langfuse/trace exporter | trace adapter | safe metadata | spans | 可选，失败不能影响主功能 |

## 10. Tests and Evaluation Assets

### 10.1 Existing Tests

- M2 authority/outbox/ownership/concurrency：`tests/integration/test_memory_transactional_outbox.py`。
- M3 summary/Working State：`test_memory_summary_worker.py`、unit memory tests。
- M4 Redis cache/失效/故障：`test_memory_redis_cache.py`、`test_profile_cache_invalidation.py`。
- M5 candidate governance/确认：`test_memory_candidate_governance.py`、`test_memory_ltm_worker.py`。
- M6 semantic retrieval/worker/pgvector：`test_m6_semantic_retrieval.py`、offline Compose stack。
- 受控普通对话合同/阶段/证据：`test_controlled_chat_contract.py`、conversation unit/e2e/evals。

### 10.2 Coverage Gaps

- 无 M7 命令 parser/preflight/状态机测试。
- 无 pending confirmation 数据表、迁移、并发、过期、重放、跨用户/会话/版本负例。
- 无 REST/WS 对同一命令结果的合同测试。
- 无 delete-all 安全预览和 one-shot confirmation。
- 无前端 Vitest/Vue Test Utils/Playwright 配置或测试命令。
- 无聊天框发自然语言命令后验证 PostgreSQL/派生状态并回归普通金融查询的全栈旅程。

### 10.3 Candidate Test Locations

- `tests/unit/memory/test_m7_memory_commands.py`
- `tests/contract/test_memory_command_contract.py`
- `tests/integration/test_memory_command_lifecycle.py`
- `tests/evals/memory/data/commands_v1.jsonl`
- `tests/e2e/test_offline_compose_stack.py`
- `frontend/src/**/__tests__` 或仓库最终选定的 Vitest 目录
- `frontend/e2e` 或仓库最终选定的 Playwright 目录

### 10.4 Visible Test Commands

- `uv run --locked ruff check [maintained scope] tests`
- `uv run --locked pyright [maintained scope] tests`
- `uv run --locked pytest backend -q`
- `uv run --locked pytest Financial-MCP-Agent -q -m "not live"`
- `uv run --locked pytest tests/evals -q -m "eval_smoke and not live"`
- `uv run --locked pytest -q`
- `npm run lint && npm run type-check && npm run build`
- `docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e`

## 11. Logging and Observability

### 11.1 Existing Logs

- Chat REST/WS 记录稳定内部错误码和 error type。
- Controlled workflow trace 记录阶段、sequence、status、duration、error code 和安全计数。
- M6 context trace 记录 memory hit/token/status，不记录正文。
- Memory router 记录 profile/item 操作类别和状态，不记录内容或用户 ID。

### 11.2 Missing Logs

- 无 memory command detected/validated/pending/confirmed/cancelled/expired/rejected 阶段。
- 无 pending command 的安全 command reference、影响计数、版本冲突和重放拒绝指标。
- 前端目前 `console.warn`，没有统一用户可见错误/恢复状态或 trace reference。

### 11.3 Observability Risks

- 命令原文和记忆正文属于私人内容，不能因为调试 parser 进入日志/Trace。
- pending preview 若包含正文会扩大泄露面；应默认记录数量、类型和哈希/安全引用。
- 旧 `setup_logger` 与标准 `logging.getLogger` 并存，后续实现需复用现有入口配置而非在库模块重复装 handler。

### 11.4 Output-channel Separation

| Channel | Current implementation | Stable fields / format | Redaction | Gaps |
| --- | --- | --- | --- | --- |
| User/API result | Chat schema + ad hoc memory dicts | reply/session/profile/context | 部分安全 | memory command 状态合同缺失 |
| Terminal progress | backend lifespan `print` | 启动/停止中文进度 | 不含正文 | 与 M7 无直接阶段 |
| Logs | Python logger/setup_logger | stage/status/error_code/type | M6 已避免正文/user id | M7 命令阶段缺失 |
| Traces | skill_trace | trace/session/group/span/sequence/duration | 受控属性白名单 | M7 branch/span 缺失 |
| Artifacts | optional trace artifacts | configurable | 默认 capture 关闭 | parser/pending 不应新增正文 artifact |

## 12. Engineering Baseline Recon

| Area | Status | Evidence | Gap / implication |
| --- | --- | --- | --- |
| API/orchestration/domain/infrastructure boundaries | Partial | 新 chat/memory application + infrastructure 已分层 | 旧 memory router/service 仍混合兼容写路径 |
| Agent/workflow/tool/prompt/model/memory/evaluation boundaries | Established | conversation、memory、tools、prompts、evals 分离 | M7 command boundary 尚不存在 |
| Docstrings, types, and key intent comments | Partial | M2-M6 新模块强类型、中文 docstrings | 旧 routes/schemas 有宽松 dict/default mutable 和重复“Phase”注释 |
| File-section navigation vs module separation | Partial | router/sidebar 使用稳定 section | memory router/service 较长，不能继续承载状态机 |
| Typed configuration and secret handling | Established/Partial | Pydantic Settings + `.env.example` | startup 仍为历史 SDK 注入 env；M7 不应扩散 getenv |
| Error, retry, fallback, and state semantics | Partial | authority/worker/retrieval 有稳定状态和降级 | memory CRUD/pending confirmation 没有统一错误和状态机 |

## 13. Risk Areas

| Area | Why risky | Likely touched? | Recommended handling |
| --- | --- | --- | --- |
| Authentication/tenant isolation | 记忆为私人用户数据 | Yes | 所有 SQL/确认绑定 auth user，跨用户负例 |
| Destructive deletion | forget/delete-all 不可逆且范围大 | Yes | 软删、预览、one-shot confirm、版本锁、隔离 E2E |
| Database migration | pending state/constraint 影响持久化 | Yes | expand-first Alembic、upgrade/downgrade/reupgrade/parity |
| Concurrency/idempotency | 重试/双击可能重复删除 | Yes | fingerprint/unique constraint/row lock/fencing tests |
| Cache/provider invalidation | 用户可能看到旧记忆 | Yes | authority first、derived status、post-filter、retry |
| Controlled finance workflow | 错误分支可能触发 Tushare/证据链 | Yes | 明确终止合同和 tool_call_count=0 负例 |
| Public API/WS compatibility | 前端和已有调用方依赖字段 | Yes | additive schema、REST/WS contract snapshots |
| Privacy/logging | 命令原文/记忆正文敏感 | Yes | 安全计数/hash/reference，secret/content scan |
| Frontend optimistic updates | API 失败时 UI 与 authority 漂移 | Yes | pending/success/failure state，不提前持久显示 |
| Production/live providers | 费用与外部数据风险 | No | M7 默认 read-only/offline，保持显式 gate |

## 14. Unknowns and Assumptions

### 14.1 Unknowns From Missing Code Access

- 无缺失代码访问；工作区相关源文件均可读。
- 未启动浏览器或运行测试，这是 reconnaissance 阶段约束，不代表运行状态已验证。

### 14.2 Unknowns From Incomplete Requirement

- “忘掉我的文本记忆”的默认范围和最大条数尚未由用户额外决定。
- 前端是否展示完整正文或受限片段尚未最终决定。
- 中英文命令覆盖范围尚未最终决定。

### 14.3 Unknowns From Ambiguous Architecture

- 旧 `memory_service` 的兼容读取保留范围与写入收口边界需要方案选择。
- 命令 preflight 在 `prepare_turn` 前还是后执行，会影响 session 创建、用户消息审计和 pending session binding。
- 统一命令合同放在 `src.memory.contracts` 还是 `backend.application.memory` 需要按跨模块消费者决定。
- 前端 Vitest/Playwright 的最小依赖和 CI 布局需要方案权衡。

### 14.4 Assumptions

- Assumption: 宽范围 delete/forget 默认先软删除 authority，再异步清理派生；不物理删除审计。
- Assumption: 用户的明确 profile/text 命令属于 `MemorySource.USER_COMMAND`，高影响字段仍需 confirmation。
- Assumption: inspect 可以读取当前用户 authority 的有效记录，不依赖 Mem0 availability。

## 15. Handoff to Next Step

Next step should use Requirement Clarification and produce `CLARIFICATION_QUESTIONS.md`.

It should clarify:

- 命令 parser 的覆盖范围、确定性/模型边界和 fail-closed 规则。
- pending command 的数据保留、默认 TTL、影响范围上限和 supersede 行为。
- 旧 memory API 写路径是否在 M7 统一收口到新 authority use case。
- frontend 的正文展示、确认 UX 和测试工具依赖。
- user message/session 应在命令处理前还是处理后持久化以满足审计和确认绑定。

It should consider these files/modules in later solution design:

- `backend/application/chat/*`
- `backend/application/memory/*`
- `backend/infrastructure/memory/*`
- `backend/routers/chat.py`, `backend/routers/memory.py`
- `backend/schemas/chat.py`, `backend/schemas/memory.py`
- `backend/db/models.py`, `backend/migrations/versions/*`
- `Financial-MCP-Agent/src/memory/contracts.py`
- `frontend/src/api`, `stores`, `composables`, `components/memory`
- `tests/unit|contract|integration|evals|e2e` and `.github/workflows/ci.yml`

It should require explicit user approval before modifying these high-risk areas:

- destructive delete/forget semantics and persisted pending-command schema
- authentication/tenant isolation and public REST/WS contracts
- M5 high-impact profile confirmation rules
- frontend test dependencies and lockfile
