# CODEBASE_RECON.md

## 1. Reconnaissance Target

Requirement source:

- `docs/specs/skills-sop-migration/REQUIREMENT_SPEC.md`。
- `D:/FinanceProject/Finance/金融Agent项目描述文档/成果点二-投研分析Skills集成-完整阐述.md`。
- `D:/FinanceProject/Finance/金融Agent项目描述文档/对话模式与可观测与skills.md`。
- 当前主仓库 `D:/FinanceProject/Finance-agent-Skills`。
- 只读历史证据仓库 `D:/FinanceProject/Finance`。

Focus areas:

- 现有记忆模块和受控对话主链的架构边界、状态合同与生产入口。
- 5 个投研 SOP Skill 的发现、注册、校验、快照、选择、澄清、分阶段加载、规划、执行、证据校验、降级、合成、追踪和评测现状。
- 历史仓库中可迁移但不能直接成为运行时依赖的 `skills_v2`、资产、测试和 UI 交互设计。

Out-of-scope reminders:

- 本步骤不修改生产代码、不选择最终方案、不运行测试。
- 历史 `Finance` 仓库只作为行为和证据来源，不允许成为新主线的 import、文件或服务依赖。
- 不复活旧 `skill_executor_node.py` 或 `skill_runner_v2.py` 形成第二套执行器。
- 不把文档中的历史离线指标当作当前仓库已复现结果。
- `search_web_news`、完整前端卡片、在线 LLM rerank 是否纳入本次里程碑仍需在澄清和方案权衡阶段冻结。

## 2. Project Overview

Project type: Confirmed，金融 Agent 模块化单体，包含 FastAPI 后端、独立 Agent/领域包、Vue 前端、数据库迁移、离线评测与 Compose E2E。

Languages: Confirmed，Python 3.12、TypeScript/Vue、YAML、Markdown、SQL/Alembic。

Frameworks: Confirmed，FastAPI、SQLAlchemy、Alembic、Pydantic、LangChain/LangGraph、Vue 3、Pinia、Vite、Vitest。

Runtime / package manager: Confirmed，Python 由 `uv.lock`/uv 管理，前端由 npm lockfile 管理；CI 使用 Python 3.12、Node 20。

Main service type: Confirmed，FastAPI REST + WebSocket 聊天服务，PostgreSQL 为生产权威持久化，Redis 仅作可降级缓存。

Frontend/backend split: Confirmed，`backend/` 提供 API 和应用装配，`Financial-MCP-Agent/src/` 持有受控对话、Skill、工具与模型领域逻辑，`frontend/` 为 Vue 客户端。

Test framework: Confirmed，pytest（unit/contract/integration/e2e/eval/live markers）与 Vitest；ruff/pyright/vue-tsc/ESLint 为质量门禁。

Deployment clues: Confirmed，`docker/docker-compose.yml`、`docker/docker-compose.offline.yml` 和后端/前端/E2E Dockerfile；GitHub Actions 构建生产后端镜像并运行离线 Compose E2E。

Confirmed facts:

- 当前提交为 `e46f042`，新工作分支为 `feature/skills-sop-migration`，`main` 保留且未删除。
- 当前生产聊天装配入口是 `backend/application/chat/factory.py`，每个请求构建 `ControlledConversationWorkflow`，并注入 `SkillRegistry().conversation_snapshot()`。
- 受控对话链已经具备类型化状态、路由、改写、权限、计划、校验、唯一执行器、证据校验、控制器、合成和 Trace。
- 记忆模块已迁移到同一聊天用例：记忆检索只进入上下文/改写/合成，不参与工具授权或证据判定；PostgreSQL 为权威源，Redis/Mem0 是可降级派生层。
- 5 个目标 Skill 目录均存在，但除 `fund-compare` 外，其余目录目前只有 `SKILL.md + skill_spec.yaml`。
- 当前 Registry 是薄实现：可扫描、处理 workspace/vendor 覆盖、生成不可变对话快照和做简单引用检索，但没有完整 schema gate、生命周期、原子刷新/LKG 或分阶段 Loader。
- 当前路由、改写和规划包含硬编码 Skill 规则，`skill_spec.yaml` 尚未成为端到端机器合同真相源。
- 当前公开 REST/WS 请求和前端请求没有 `explicit_skill`；领域合同虽然保留该字段，但公开入口无法传入。
- 当前没有 `skill_confirm` 控制帧/前端卡片，没有 `search_web_news` 生产工具，也没有 75×3 Skills 集的可复现评测数据。

Assumptions:

- 本次迁移优先在现有受控对话主链内增强 Skill 合同消费，不替换已经完成的记忆和执行器主线。
- 5 个 Skill 的文件资产、规则和离线 cases 可以从历史仓库选择性复制并按当前合同重写。
- 用户所说“需求与之前保持不变”意味着保留当前主线已冻结的安全边界、失败语义、离线默认和历史口径标注规则。

## 3. Directory Structure Summary

| Path | Apparent role | Relevance | Notes |
| --- | --- | --- | --- |
| `backend/application/chat/` | 聊天用例与依赖装配 | 高 | 公开入口唯一应用层；应保持薄且不承载 Skill 规则 |
| `backend/infrastructure/chat/` | 模型、Tushare、仓储、Trace 适配器 | 高 | Provider 和 Trace 扩展边界 |
| `backend/application/memory/` | 记忆命令、检索与观测用例 | 中 | 已完成的边界必须保持，不应让 Skill 扩权 |
| `backend/infrastructure/memory/` | PostgreSQL/Redis/Mem0 适配 | 中 | 仅确认交互边界，本次不应重构 |
| `backend/routers/chat.py` | REST/WS 协议适配 | 高 | 显式 Skill/澄清恢复若进入公开协议将触及此处 |
| `backend/schemas/chat.py` | 公开请求响应 Schema | 高 | 当前没有 `explicit_skill` 或确认载荷 |
| `backend/config.py` | 单一 Settings | 高 | 当前有旧 Skill flags，但没有 Registry/Loader/rerank 新配置 |
| `Financial-MCP-Agent/src/conversation/` | 受控对话领域主链 | 最高 | 本次主要集成归属；已有唯一执行器和合同 |
| `Financial-MCP-Agent/src/skills/skill_registry.py` | 当前 Skill 注册、快照、引用读取 | 最高 | 需评估拆分为 schema/snapshot/loader/reference 边界 |
| `Financial-MCP-Agent/src/skills/*/` | 5 个 SOP 资产 | 最高 | 当前资产不完整且规范字段不足 |
| `Financial-MCP-Agent/src/agents/` | 历史路由/规划/执行实现 | 参考 | 不在当前生产主链；只可提炼行为和测试 |
| `Financial-MCP-Agent/src/tools/` | 工具和 Trace 基础设施 | 高 | 当前生产治理目录仅含 Tushare 只读工具 |
| `tests/` | 跨层测试和离线评测 | 最高 | 已有烟测骨架，但 Skills 覆盖量和断言不足 |
| `frontend/src/composables/useChat.ts` | 前端 WS 消费 | 中/待定 | 只处理现有事件；若做确认卡则需扩展 |
| `docs/specs/controlled-conversation-mainline/` | 已冻结主链事实与延期项 | 高 | 是兼容边界和口径基线 |
| `docs/specs/memory-system-migration/` | 已完成记忆迁移证据 | 高 | 防止 Skills 迁移破坏记忆行为 |
| `D:/FinanceProject/Finance/.../skills_v2/` | 历史完整 Skills 子系统 | 只读参考 | 有 schema gate、snapshot、loader、reference index、lifecycle |
| `D:/FinanceProject/Finance/.../skills/*/` | 历史完整 Skill 资产 | 只读参考 | 含更丰富 spec、references、cases，但部分依赖旧工具 |

## 4. Entry Points

### 4.1 Startup Entry

- Confirmed：`backend/main.py` 创建 FastAPI，装载配置、数据库、可选记忆 worker、Trace runtime 和路由。
- Confirmed：`backend/config.py` 是后端 typed Settings 入口；底层旧 Trace 仍有部分 `os.getenv` 兼容读取。
- Confirmed：当前启动阶段不会构建全局、带状态的 Skill 生命周期管理器；Registry 在聊天用例工厂中按请求实例化。

### 4.2 Request / Task Entry

- REST：`POST /api/chat/message` → `backend/routers/chat.py` → `build_chat_use_case()` → `ControlledChatUseCase.execute()`。
- WS：`/api/chat/stream` → 同一聊天用例 → 现有 session/context/compaction/text/done/error 帧。
- Internal/eval：测试直接构建 `ControlledConversationWorkflow` 或 `TwoStageRouter`，注入 `SkillRegistry().conversation_snapshot()`。
- Confirmed：公开 Schema 不接受 `explicit_skill`，因此内部显式选择能力当前不可由正式客户端触发。

## 5. Relevant Call Chain

```text
REST / WebSocket input
-> ChatMessageRequest / WS JSON validation
-> ControlledChatUseCase
-> conversation repository + optional governed memory retrieval
-> ControlledConversationWorkflow
-> context preflight
-> authoritative entity resolution
-> TwoStageRouter -> SkillDiscovery (metadata-only, deterministic today)
-> RouteAwareRewriter (hard-coded SOP requirements today)
-> ControlledPermissionResolver (snapshot allowlist + tool governance catalog)
-> ControlledPlanner (hard-coded requirement-to-tool mapping today)
-> PlanValidator
-> ControlledToolExecutor (single bounded DAG executor)
-> EvidenceVerifier
-> ControlledController / bounded replan
-> ControlledSynthesizer
-> repository persistence + working-state update
-> REST response / WS frames
-> SkillTraceSink -> JSONL + optional exporter
```

Confirmed segments:

- 从 API 到 `ControlledChatUseCase`、Workflow、存储与 Trace 的生产装配已直接读取。
- Workflow 使用同一个不可变 `SkillCatalogSnapshot` 贯穿路由和权限，工具执行只走现有 `ControlledToolExecutor`。
- 记忆检索结果只进入受控 `ContextPacket`，不会修改 Skill/工具权限。
- Planner 目前从 `data_requirements` 和 `permissions.py` 的静态映射生成计划，并未读取 Skill spec 的步骤合同。
- Verifier 目前检查计划要求，不直接消费 Skill spec 的 `required_evidence`；Synthesizer 也没有加载 Skill 输出/降级章节。

Inferred segments:

- 要让文件资产成为持久真相源，需要在 Workflow 请求级快照之外提供经校验的选中 Skill 分阶段上下文，但应保持它不可变并与快照 hash 关联。
- Registry 若改为进程级管理器，可减少每请求扫描成本；其热刷新、LKG 与生命周期语义属于方案选择，尚未冻结。

Unknown segments:

- 本次是否必须实现在线 LLM rerank，还是先以可插拔接口 + 确定性离线实现交付。
- 本次是否包含公开 `skill_confirm` 卡片协议与前端恢复，或继续以文字澄清完成闭环。
- 本次是否包含 `search_web_news` 及其真实 Provider、来源可信度分级和外网失败语义。

## 6. Related Files

### 6.1 Definitely Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `Financial-MCP-Agent/src/skills/skill_registry.py` | 当前注册表 | 发现、快照、引用读取均集中在单文件 | 候选拆分/重构 | 高：启动可用性与快照兼容 |
| `Financial-MCP-Agent/src/skills/{5 skills}/` | Skill 文件资产 | 面试口径要求的四层资产载体 | 候选补齐/升级 | 中：合同与工具能力必须一致 |
| `Financial-MCP-Agent/src/conversation/contracts.py` | 跨阶段合同 | 快照、路由、改写、计划、证据和 Trace 类型 | 候选增量扩展 | 高：跨模块兼容 |
| `Financial-MCP-Agent/src/conversation/skill_discovery.py` | Stage1 检索 | 当前仅硬编码规则 | 候选改为 spec metadata 驱动 | 中 |
| `Financial-MCP-Agent/src/conversation/routing.py` | 两阶段路由 | 决定 Skill 选择和澄清 | 候选扩展置信分层 | 高：行为兼容 |
| `Financial-MCP-Agent/src/conversation/rewriting.py` | 路由专属改写 | 当前数据要求硬编码 | 候选消费 input contract | 高：实体/澄清合同 |
| `Financial-MCP-Agent/src/conversation/planning.py` | 唯一 Planner | 当前未消费 spec steps | 候选变为 Skill-guided | 高：执行计划正确性 |
| `Financial-MCP-Agent/src/conversation/permissions.py` | 权限快照 | Skill allowlist 与治理目录交集 | 保留并加强 join gate | 高：权限安全 |
| `Financial-MCP-Agent/src/conversation/workflow.py` | 唯一编排 | 分阶段 Loader 的接入点 | 候选增量接线 | 最高 |
| `Financial-MCP-Agent/src/conversation/verification.py` | 证据门禁 | 需对齐 required evidence/degrade | 候选增量扩展 | 高 |
| `Financial-MCP-Agent/src/conversation/synthesis.py` | 最终回答 | 需消费输出合同和降级策略 | 候选增量扩展 | 中 |
| `Financial-MCP-Agent/src/conversation/tool_governance.py` | 可执行工具目录 | schema gate 与 permission join 的权威 | 复用/可能扩展 | 高 |
| `backend/application/chat/factory.py` | 生产装配 | 当前每请求创建 Registry 快照 | 候选调整装配生命周期 | 中 |
| `tests/evals/skill_activation/` | Skill 路由 eval | 当前仅 5 条正例 | 候选扩展三类样本与门禁 | 中 |

### 6.2 Probably Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/schemas/chat.py` | 公开合同 | 显式选择/确认若入 scope 必改 | 待澄清 | 高 |
| `backend/routers/chat.py` | REST/WS 适配 | 确认恢复和控制帧接入点 | 待澄清 | 高 |
| `frontend/src/composables/useChat.ts` | WS 客户端 | 当前无 Skill 事件 | 待澄清 | 中 |
| `backend/config.py` | typed Settings | Loader/rerank/预算可配置边界 | 候选增量配置 | 中 |
| `Financial-MCP-Agent/src/tools/skill_trace.py` | Trace runtime | 需要 Skill/version/spec/ref/route/degrade 字段 | 候选扩展低基数属性 | 中 |
| `Financial-MCP-Agent/src/prompts/chat/` | 版本化 Prompt | 若引入 LLM rerank/Skill synthesis 会涉及 | 待方案 | 中 |
| `tests/contract/test_skill_catalog_contract.py` | 快照合同 | 现有不可变/hash 基线 | 扩展回归 | 高 |
| `tests/unit/conversation/` | 主链单测 | 路由、规划、证据已有夹具 | 扩展回归 | 高 |
| `tests/e2e/test_controlled_chat_chain.py` | 端到端主链 | 验证单执行器和终态 | 扩展 Skills cases | 高 |

### 6.3 Supporting Context

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `docs/specs/controlled-conversation-mainline/*` | 已交付主线 SSOT | 列出了现状和延期能力 | 保持一致，必要时更新矩阵 | 低 |
| `docs/specs/memory-system-migration/*` | 记忆迁移证据 | 需要作为回归边界 | 只读/回归引用 | 低 |
| `docs/skill功能集成技术说明.md` | 旧技术说明 | 仍指向已退出的旧主链 | 后续候选修订 | 中：误导维护者 |
| `Financial-MCP-Agent/src/agents/skill_spec_planner.py` | 旧 spec 规划器 | 可提炼 spec→plan 规则 | 只读参考，不接回生产 | 高 |
| `Financial-MCP-Agent/src/agents/skill_executor_node.py` | 旧大执行器 | 有输出/降级/证据处理经验 | 只读参考 | 最高：禁止双运行时 |
| `D:/FinanceProject/Finance/Financial-MCP-Agent/src/skills_v2/*` | 历史子系统 | 有所需 schema/snapshot/loader/ref 模型 | 适配设计参考 | 高：不能原样复制 |
| `D:/FinanceProject/Finance/Financial-MCP-Agent/src/skills/*` | 历史资产 | 有完整 sections、refs、cases | 筛选迁移 | 中 |

### 6.4 Out of Scope

| Path / Area | Reason |
| --- | --- |
| 记忆持久化模型、Outbox、Redis/Mem0 实现 | 已完成的独立主线；Skills 只能消费受控上下文 |
| 报告、持仓、用户、鉴权业务 | 与本次 Skill SOP 集成无直接关系 |
| 旧 `agents/skill_executor_node.py` 生产复活 | 会破坏唯一执行器和架构边界 |
| 生产数据库 Skill 生命周期表 | 当前未发现需求证据；文件系统+内存快照足以作为默认候选 |
| 真实外部服务调用 | 默认测试必须离线，live 需显式门禁和凭证 |

## 7. Existing Patterns to Reuse

| Pattern | Example file | Why reuse it |
| --- | --- | --- |
| 不可变请求级快照 + hash | `conversation/contracts.py::SkillCatalogSnapshot` | 已进入生产主链且能保证单轮一致性 |
| 类型化跨阶段状态 | `conversation/contracts.py` | 避免历史实现中的 `dict[str, Any]` 漂移 |
| 单一有界 DAG Executor | `conversation/execution.py` | 已实现超时、重试、并发和终止预算 |
| 工具目录与权限快照交集 | `conversation/tool_governance.py`、`permissions.py` | 防止 Skill 文件扩大权限 |
| 显式错误码和终态 | `conversation/errors.py`、`contracts.py` | 可稳定测试澄清、拒绝、部分回答与失败 |
| 结构化 WorkflowEvent | `conversation/workflow.py`、`backend/infrastructure/chat/trace.py` | 可追加 Skill 版本、hash、路由和降级属性 |
| PostgreSQL 权威、派生层可降级 | `backend/infrastructure/memory/` | Registry LKG/刷新可借鉴“权威与派生分离”原则 |
| 离线确定性 Provider + 显式 live gate | 记忆 provider/tests 与 pytest markers | 适合 rerank、引用检索、合成测试 |
| 历史 schema gate/loader 分层概念 | 历史 `skills_v2/` | 与面试文档的发现/注册/加载口径一致，但需按当前类型重写 |

## 8. Data Flow and State

### 8.1 Input Data

- 当前公开输入：已认证 `user_id`、`message`、可选 `session_id`。
- 当前内部合同额外支持 `request_id` 和 `explicit_skill`，但 API 未映射后者。
- 上下文输入：最近消息、rolling summary、工作实体/候选、确认约束、表达偏好和受预算限制的记忆命中。
- Skill 输入源：目录内 `SKILL.md`、`skill_spec.yaml`、`references/*.md` 和测试资产。

### 8.2 Intermediate State

- `ConversationState` 维护阶段转换、请求级预算、实体、RouteDecision、RewriteResult、权限快照、计划、步骤结果、证据、控制器决定和终态。
- `SkillCatalogSnapshot` 目前只包含 description/version/mode/allowed tools/reference paths/hash。
- 当前缺少独立的、类型化 `ValidatedSkillSpec` 与按 rewrite/planner/synthesis 分层的 `LoadedSkillContext`。
- 当前 Registry 在每次用例装配时扫描文件，Workflow 内使用一次冻结快照；没有 active/pending/LKG 的进程级状态。

### 8.3 Persistent State

- 对话、消息、working state、记忆记录和治理状态进入数据库；Skill Registry 状态未持久化。
- Skill 文件系统是当前事实来源，但 schema 不合法时多数情况只记录 warning/skip，无法形成可查询生命周期。
- JSONL Trace 和可选 artifacts/Langfuse 是观测输出，不是业务权威状态。

### 8.4 Output Data

- 用户结果：同步 JSON 或 WS 文本/控制帧；终态包含成功、部分、澄清、拒绝、失败、取消、不支持。
- 计划/证据：内部强类型合同；目前未公开成前端卡片。
- Trace：阶段、状态、耗时、error_code 和少量 attributes。
- Eval：pytest 断言和固定 JSONL 数据；当前没有完整 Skills 指标报告链。

### 8.5 Potential Data Mismatch Points

- `SKILL.md` frontmatter、`skill_spec.yaml`、工具治理目录和 Planner 硬编码映射可能互相漂移。
- 当前 `version` 与 snapshot hash 不包含 spec/markdown/reference 正文 hash，修改资产后追踪可能无法精确复现。
- `required_evidence` 与当前 Planner/Verifier 使用的数据要求可能不一致。
- `route_metadata`/anti-examples/input contract 在当前 spec 中不存在，路由和澄清只能依赖代码硬编码。
- 历史 market-move spec 需要 `search_web_news`，当前治理目录和 Provider 不支持；原样迁移会导致 schema/执行断裂。
- API 没有 `explicit_skill`，面试口径里的“用户显式选择优先”目前只有内部能力。

## 9. External Dependencies

| Dependency | Where called | Input | Output | Error handling / fallback |
| --- | --- | --- | --- | --- |
| OpenAI-compatible model | `backend/infrastructure/chat/providers.py` | 版本化 Prompt/上下文/证据 | 合成文本等 | 配置校验、超时/异常映射；默认测试替身 |
| Tushare | 同上及工具适配 | 规范化实体、时间、工具参数 | 市场/财务事实 | 统一工具结果与受控错误；无 token 时不能做真实验收 |
| PostgreSQL/SQLite | conversation/memory repositories | 会话、消息、状态、记忆 | 权威持久数据 | 事务与稳定错误；离线可用隔离 DB |
| Redis | memory cache | 会话/摘要/记忆缓存 key | 可丢弃缓存 | 失败回源权威数据库 |
| Mem0/pgvector | memory semantic provider | 受治理记忆派生数据 | 语义候选 | 默认 disabled/deterministic；失败不改变权威状态 |
| Langfuse | trace exporter | 脱敏事件 | 远端 trace/score | 可选、失败隔离 |
| 文件系统 | SkillRegistry | Skill 四层资产 | Registry/refs | 当前多为 warning/skip；需要更明确门禁/LKG 语义 |
| Web news | Not found in current production catalog/provider | N/A | N/A | 历史设计存在，当前未实现 |

## 10. Tests and Evaluation Assets

### 10.1 Existing Tests

- `tests/contract/test_skill_catalog_contract.py`：快照不可变、排序/hash、路由/执行/引用视图基本合同。
- `tests/unit/conversation/test_understanding_stages.py`：实体、两阶段路由、改写基础行为。
- `tests/unit/conversation/test_tool_governance.py`：权限和工具治理。
- `tests/e2e/test_controlled_chat_chain.py`：主链终态、执行/证据/控制器路径。
- `tests/evals/skill_activation/`：目前仅 5 条正例，每个目标 Skill 一条。
- `tests/evals/route|rewrite|planner|executor|synthesis/`：各阶段小型固定数据烟测。
- `Financial-MCP-Agent/src/skills/fund-compare/tests/`：旧路径下 fund compare 资产/规划/证据测试。
- 历史仓库有 schema gate、version、snapshot、lifecycle、loader、SOP planner/runner/verifier 和 5 Skill P1 测试，可转写为当前主线回归。

### 10.2 Coverage Gaps

- 缺少 malformed YAML/frontmatter、重名/别名冲突、路径逃逸、未知工具、步骤越权、evidence mapping 不闭合的完整 schema gate 测试。
- 缺少 Registry 原子刷新、失败保持 LKG、并发读取和 snapshot 可复现测试。
- 缺少 Loader 对三阶段 section 白名单、reference stage hard filter、token budget 和权限隔离测试。
- 缺少正例/反例/相邻 Skill 混淆/多任务/显式选择/中低置信确认的路由数据集。
- 缺少 5 Skill 的 input cardinality、澄清、plan steps、required evidence、degrade/output contract 端到端测试。
- 缺少 spec/markdown/reference hash 进入 trace 的合同断言。
- 缺少当前可复现的 75×3 数据和历史指标复算；任何新数字都必须由 runner 生成。
- 缺少公开 API `explicit_skill` 和 Skill 确认恢复测试（若纳入 scope）。
- 缺少 web news 工具与来源分层测试（若纳入 scope）。

### 10.3 Candidate Test Locations

- `tests/unit/skills/`：schema、version、reference index、loader、snapshot manager。
- `tests/contract/`：Skill catalog/spec/trace/API 合同。
- `tests/unit/conversation/`：discovery、route、rewrite、planner、verifier、synthesis。
- `tests/e2e/`：5 Skill 正常/澄清/部分证据/越权拒绝全链。
- `tests/evals/skill_activation/` 和新 `tests/evals/skills_sop/`：可复现的数据集和指标 runner。
- 各 `src/skills/<name>/tests`：资产自身静态合同；是否保留分散测试需在方案阶段统一。

### 10.4 Visible Test Commands

- `uv run --locked ruff check ...`（CI 列表需覆盖新增 skills 模块）。
- `uv run --locked pyright ...`（同上）。
- `uv run --locked pytest backend -q`。
- `uv run --locked pytest Financial-MCP-Agent -q -m "not live"`。
- `uv run --locked pytest tests/evals -q -m "eval_smoke and not live"`。
- `uv run --locked pytest -q`。
- `cd frontend && npm run lint && npm run type-check && npm run build && npm run test -- --run`。
- `docker compose -f docker/docker-compose.yml config --quiet`。
- `docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e`。

## 11. Logging and Observability

### 11.1 Existing Logs

- 主链通过 `WorkflowEvent` 输出稳定 `stage/status/elapsed_ms/error_code/trace_id/run_id/session_id`。
- `SkillTraceSink` 桥接本地 JSONL 和可选 exporter；artifact capture 和 Langfuse 均有 feature flag。
- Registry 使用项目 logger 记录扫描、覆盖和文件读取失败。

### 11.2 Missing Logs

- 当前主链未稳定记录 `selected_skill`、Skill version、registry/spec/reference hash、route source、top candidates/margin、loaded sections/reference ids、degrade reason。
- Registry 无 active/pending/LKG/refresh result 等可审计状态事件。
- 当前没有 eval dataset/version/runner/version 与指标 artifact 的统一记录。

### 11.3 Observability Risks

- 若把完整 Skill 文本、Prompt、引用或工具 payload 直接写入日志，会泄露私有规则/数据并造成高基数。
- 若只记录 Skill 名不记录 hash/version，无法解释一次回答使用了哪一版资产。
- 当前底层 Trace 仍有 `os.getenv`，新增配置应通过 typed Settings 注入，避免继续扩散双配置源。

### 11.4 Output-channel Separation

| Channel | Current implementation | Stable fields / format | Redaction | Gaps |
| --- | --- | --- | --- | --- |
| User/API result | REST JSON、WS 文本和少量控制帧 | session/reply/done/error | API 层不返回内部异常 | 无 Skill 确认/计划/证据卡片 |
| Terminal progress | startup `print` + CI 输出 | 非完全结构化 | 不应输出 secret | 仍有历史式打印和 f-string 日志 |
| Logs | module logger | 部分 stage/status/error_code | 记忆模块已有脱敏实践 | Registry/Skills 字段不足 |
| Traces | WorkflowEvent→JSONL/Langfuse | trace/run/session/stage/status/elapsed | artifact 开关默认关闭 | 缺 Skill 内容版本链 |
| Artifacts | 可选 prompt/reply/diagnostics | 文件路径 | 默认关闭 | 未统一 Skills eval/validation 报告 |

## 12. Engineering Baseline Recon

| Area | Status | Evidence | Gap / implication |
| --- | --- | --- | --- |
| API/orchestration/domain/infrastructure boundaries | Established | chat factory/use case、conversation domain、infrastructure adapters 分离 | SkillRegistry 仍同时承担发现、解析、引用检索 |
| Agent/workflow/tool/prompt/model/memory/evaluation boundaries | Established | 受控主链和记忆迁移已显式分层 | Skill 文件合同尚未贯穿 rewrite/planner/verifier/synthesis |
| Docstrings, types, and key intent comments | Partial | 新 conversation/memory 模块类型和中文 Google-style 文档较好 | `skill_registry.py` 仍大量 `Any`、薄 docstring；历史代码不可直接复制 |
| File-section navigation vs module separation | Partial | 新主链按模块拆分 | Registry 单文件混合 frontmatter/YAML/discovery/index/load/snapshot |
| Typed configuration and secret handling | Partial | `backend/config.py` 集中 Settings，`.env.example` 安全占位 | 旧 Trace 有环境直读；Skills 新预算/模式未建 typed config |
| Error, retry, fallback, and state semantics | Partial | Executor/Workflow 有稳定终态、错误码、预算、重试 | Registry 多数解析失败 warning/skip；无 LKG/明确拒绝策略 |

## 13. Risk Areas

| Area | Why risky | Likely touched? | Recommended handling |
| --- | --- | --- | --- |
| 唯一生产聊天主链 | 破坏会影响 REST/WS、记忆和全部 Skill | 是 | 增量接入、保持现有 Executor，端到端回归 |
| 跨阶段 contracts | 新字段影响大量构造器和测试 | 是 | 冻结兼容策略，一次只扩展所需类型 |
| Skill schema gate | 过严会导致启动不可用，过松会越权/漂移 | 是 | 区分首次启动与刷新；定义 reject/LKG 语义 |
| 工具权限 | spec 可被编辑，不能成为扩权来源 | 是 | 永远与治理目录取交集，未知工具门禁失败 |
| 历史代码迁移 | 基于旧 Pydantic/dict/第二执行器 | 是 | 迁移行为和资产，不复制运行时依赖/大执行器 |
| `search_web_news` | 新外部能力、来源可信度和失败语义复杂 | 待定 | 独立里程碑或明确延期，不做假实现 |
| 前端确认协议 | 涉及公开 API、WS、恢复和幂等 | 待定 | 若纳入需单独合同和 E2E；否则文字澄清 |
| 指标口径 | 文档有历史数字但当前数据不全 | 是 | 只报告 runner 实测；历史值显式标注不可复现 |
| Branch/Issue 治理 | 当前分支名不符合 `feat/<issue>-slug` | 是 | 在实施前创建/确认 Issue 后改名；不自行 push/PR |
| 需求文件位置 | 已在勘察交接时迁入专题目录 | 否 | 后续 artifact 继续使用同一目录 |

## 14. Unknowns and Assumptions

### 14.1 Unknowns From Missing Code Access

- Not found：当前主仓库中不存在生产 `search_web_news` 工具/provider。
- Not found：当前主仓库中不存在 Skill 生命周期数据库表或 Registry 管理 API。
- Not found：当前主仓库中不存在前端 `SkillConfirmCard`。
- 仓库代码均可读取；没有因权限导致的关键未知项。

### 14.2 Unknowns From Incomplete Requirement

- “完整迁移”是否要求本次同时交付在线 LLM rerank、Web news、前端确认卡和管理生命周期，还是先完成后端核心闭环。
- 低置信是否继续文字澄清；中置信是否必须产生结构化确认载荷。
- 是否需要热更新/动态启停，还是应用启动和请求构建时校验即可。
- 是否有可使用的 Issue 编号和目标分支名。
- 是否要求本次重建 75×3 数据集，还是先建立可扩展 runner 与代表性门禁集。

### 14.3 Unknowns From Ambiguous Architecture

- Registry 是进程级单例还是请求级构建；两者在刷新、一致性和测试隔离上取舍不同。
- Loader 上下文应进入现有 Rewrite/Plan/Answer pack 的新字段，还是由专用服务在阶段边界传递。
- Spec 的 `tool_plan_steps` 是确定性计划模板还是 Planner 约束；文档倾向“约束模板”，历史实现更接近直接生成。
- 生命周期状态是否只存在内存/配置，还是需要持久管理面。

### 14.4 Assumptions

- 默认以后端核心闭环为首要目标；前端卡片、web news 和在线 rerank 不在缺乏明确授权时偷偷扩入。
- 默认应用可在无外部模型、无 Tushare token、无 Redis/Mem0 时运行全部离线测试。
- 默认 Skill references 只包含稳定方法论，不包含实时行情、私有数据或工具凭证。
- 默认不会删除 `main`；“关闭原分支”按离开原分支并保留可恢复历史处理。

## 15. Handoff to Next Step

Next step should produce `CLARIFICATION_QUESTIONS.md`（当前可用技能清单没有独立 Requirement Clarification Skill，因此应按 Spec Coding 规则人工完成同等澄清门禁）。

It should clarify:

- 本轮必交付边界：核心后端 Skills 闭环 vs 在线 rerank、web news、前端确认卡、热更新/管理面。
- 显式选择与中/低置信澄清的公开协议和恢复语义。
- 5 Skill spec 的权威字段、版本/hash 规则、required/optional evidence 和降级级别。
- Registry 首启失败、刷新失败、LKG、workspace/vendor 冲突和生命周期语义。
- Planner 如何消费 `tool_plan_steps`，以及与现有工具治理/Validator 的职责边界。
- 指标验收以何种数据规模为本轮门禁，如何标注历史数据。
- Issue/分支治理和 artifact 目录修正。

It should consider these files/modules in later solution design:

- `Financial-MCP-Agent/src/skills/skill_registry.py` 与候选的新 `skills/` 子模块。
- `Financial-MCP-Agent/src/conversation/{contracts,skill_discovery,routing,rewriting,planning,permissions,workflow,verification,synthesis}.py`。
- `Financial-MCP-Agent/src/conversation/tool_governance.py` 和 `backend/infrastructure/chat/providers.py`。
- `backend/application/chat/factory.py`、`backend/config.py`；若公开确认能力入 scope，再考虑 router/schema/frontend。
- 5 个 Skill 资产及 `tests/unit|contract|e2e|evals`。

It should require explicit user approval before modifying these high-risk areas:

- 新增真实外网搜索或任何新的生产外部依赖。
- 修改公开 REST/WS 合同或前端恢复协议。
- 新增数据库持久化/迁移来管理 Skill 生命周期。
- 删除旧代码、删除分支、commit、push 或创建 PR。
- 改变当前记忆系统权威边界、鉴权、安全或部署配置。
