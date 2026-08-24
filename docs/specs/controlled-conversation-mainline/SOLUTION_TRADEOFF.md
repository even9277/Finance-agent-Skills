# SOLUTION_TRADEOFF.md

## 1. Tradeoff Context

本次需要决定：如何在 `Finance-agent-Skills` 中，用最短时间形成“模块齐全、合同清晰、离线完整链可运行”的受控对话主链，同时避免把 `Finance` 历史代码整包复制、长期保留双 Runtime，或为了企业级外观引入不必要的微服务和工作流框架。

目标不是本轮直接完成所有业务实现，而是为后续 `PLAN.md` 冻结一个可小步交付、可单独回滚、能支持面试口径逐模块落地的唯一技术方向。

## 2. Inputs Reviewed

- `REQUIREMENT_SPEC.md`：确认唯一主仓库、受控主链、默认离线测试、分层验收、无长期 Adapter/双轨和无未授权 GitHub 写操作。
- `CODEBASE_RECON.md`：确认 REST/WS 真实入口、约 1,812 行 `chat_service.py`、现有 Router/Executor/Skill Registry/Trace、动态状态和当前 E2E 绕过真实 Agent 主链的问题。
- `CLARIFICATION_QUESTIONS.md`：确认 16 个模块的目标口径、最小实现定义、贵州茅台纵向案例、文字澄清和 Milestone 1 后再准备 Draft PR。
- 用户决策：先追求仓库架构与模块实现完整，允许真实效果后续完善；首版必须有最小可执行实现和离线全链，不能只是空壳。
- 本地工程标准：`AGENTS.md` 与 `PYTHON_AGENT_ENGINEERING_STANDARD.md`。
- 外部来源：Anthropic、LangGraph、Langfuse、OpenTelemetry、OpenAI Structured Outputs，以及 DeerFlow、Hermes Agent、OpenClaw、LangGraph 开源仓库。

## 3. User Decisions and Defaults

### 3.1 Confirmed Decisions

- 首个纵向业务案例：贵州茅台 `600519.SH` 只读基础快照。
- 低置信路由首版返回文字澄清，不同步开发 `skill_confirm` 前端卡片。
- Milestone 1 离线完整主链通过后，才进入功能分支/Draft PR 同步环节。
- `Finance-agent-Skills` 是唯一运行时真相源；`Finance` 永久只读参考。
- 对话模式采用 workflow-style 受控流水线，不使用自由 Agent Loop。
- 首版不要求真实模型/生产服务完整跑通，但要求全部模块有最小真实实现并能通过 Fake 全链。

### 3.2 Conservative Defaults Used

- 首版不修改数据库 Schema，不引入 Redis、消息队列、OTel Collector 或新生产依赖。
- REST 与 WebSocket 最终共用一个应用用例；在正式切换前只允许功能分支上的短期共存。
- 首版 Controller 默认规则驱动，只允许有界 retry/replan；具体数字由 `PLAN.md` 冻结并通过终止测试证明。
- Prompt、模型和工具通过现有 Settings/Registry 注入；核心合同不硬编码模型供应商。
- 本地 JSONL Trace 为必要事实源，Langfuse 为可选出口。

### 3.3 Blocking Decisions

没有未解决的 P0 决策。可继续进入 Plan Freezing。

## 4. Core Decision Point

选择“在现有模块化单体上建立 Typed Domain Contracts + 单一 Application Orchestrator + 可替换外部端口，并以离线纵向切片逐步替换巨型 Chat Service”，而不是只做表面拆文件、整包移植历史 Runtime，或把对话链整体迁入 LangGraph。

## 5. Reference Sources and Repository Evidence

### 5.1 Official Docs

#### Source: Anthropic — Building Effective Agents

**Link:** https://www.anthropic.com/engineering/building-effective-agents
**What was inspected:** workflow/agent 区分、routing、prompt chaining、parallelization 和“从最简单方案开始”的建议。
**Relevant practice:** 明确任务使用预定义路径和阶段 gate；Routing 适合类别清晰的输入；只在不可预知子任务中提高自主性。
**Reusable part:** Directly reusable。
**Fit for this task:** 金融对话阶段和验收条件清晰，适合受控 workflow；仅在 Executor 后保留有界反馈。

#### Source: LangGraph Overview / StateGraph

**Link:** https://docs.langchain.com/oss/python/langgraph/overview
**Repository evidence:** https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/graph/state.py
**What was inspected:** durable execution、streaming、HITL、persistence，以及 `StateGraph` 的 state schema、context schema 和 node `State -> Partial<State>` 模型。
**Relevant practice:** 运行状态与不可变运行上下文应分开建模；复杂长任务可使用 checkpoint/interrupt。
**Reusable part:** Partially reusable。
**Fit for this task:** 复用“typed state + run-scoped context + 显式阶段”思想；首版不复用图运行时，因为当前主链线性、无需跨请求 checkpoint。

#### Source: Langfuse — Tracing Best Practices

**Link:** https://langfuse.com/docs/observability/best-practices
**What was inspected:** 一轮聊天一 Trace、会话聚合、稳定低基数 observation 名称、generation/tool 嵌套和版本/metadata。
**Relevant practice:** Trace 名称视作稳定接口；动态 ID 放 metadata；工具调用嵌套在所属阶段；测试/生产环境分开。
**Reusable part:** Directly reusable。
**Fit for this task:** 与现有 `skill_trace.py` 高度一致，可通过扩展而非替换实现。

#### Source: OpenAI — Structured Outputs

**Link:** https://platform.openai.com/docs/api-reference/responses-streaming/response/refusal?lang=python
**What was inspected:** `json_schema` 与 `strict` schema adherence。
**Relevant practice:** Router/Rewrite/Planner 的模型输出应生成即满足结构 Schema，但仍需业务语义校验。
**Reusable part:** Conceptual only / provider adapter 内部分复用。
**Fit for this task:** 当前模型供应商不固定，不能把 OpenAI 专有参数写进领域合同；端口可以暴露结构化输出能力。

#### Source: OpenTelemetry GenAI Semantic Conventions

**Link:** https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/
**What was inspected:** conversation、workflow、provider、execute_tool、usage 等属性语义。
**Relevant practice:** 观测字段应与通用语义兼容，Span 名保持低基数。
**Reusable part:** Conceptual only。
**Fit for this task:** 首版不建设 OTel 链路，但 Trace 字段避免自创冲突语义。

### 5.2 Open-source Repositories

#### Source: ByteDance DeerFlow

**Link:** https://github.com/bytedance/deer-flow
**What was inspected:** Skill 渐进加载、Skill 目录作为包边界、工具过滤、执行前二次授权，以及 LangGraph/LangChain 长任务 Harness 定位。
**Relevant practice:** 只把必要 Skill 内容加入当前上下文；被禁用或未授权工具不应暴露给模型，并在真正执行前再次检查。
**Reusable part:** Partially reusable。
**Fit for this task:** 可复用 progressive disclosure 和“发现时过滤 + 执行时再校验”；完整 sandbox/subagent/harness 过重，不复制。

#### Source: NousResearch Hermes Agent

**Link:** https://github.com/NousResearch/hermes-agent
**What was inspected:** Tools/Toolsets、Skills、Memory、MCP、Security、Configuration 分离，以及仓库贡献测试入口。
**Relevant practice:** Skill、工具、记忆、Provider 和安全边界应独立；外部能力按 toolset/配置组合，而不是散落在 Agent Loop 中。
**Reusable part:** Conceptual only / 部分目录职责可借鉴。
**Fit for this task:** 支持明确端口和模块边界，但 Hermes 的跨平台 Gateway、自改进记忆和长循环不适合当前金融对话纵向切片。

#### Source: OpenClaw Skills

**Link:** https://github.com/openclaw/openclaw/blob/main/docs/tools/skills.md
**What was inspected:** workspace/global Skill、allowlist、snapshot/verification、Proposal/Review 后再修改 Skill。
**Relevant practice:** Skill 发现应受作用域和 allowlist 限制，Skill 版本/来源需要可验证，Skill 改动先评测再生效。
**Reusable part:** Partially reusable。
**Fit for this task:** 复用 snapshot/hash/schema gate；不引入 marketplace、安装系统或动态自修改 Skill。

#### Source: LangGraph StateGraph implementation

**Link:** https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/graph/state.py
**What was inspected:** 状态 Schema、运行上下文 Schema、Reducer 和编译后执行模型。
**Relevant practice:** 区分可变状态和运行时依赖；阶段只返回受控状态增量。
**Reusable part:** Conceptual only。
**Fit for this task:** 用于设计 Typed Contracts，不引入 StateGraph 本身。

### 5.3 Local Project Patterns

| Local pattern | Evidence from CODEBASE_RECON.md | How to reuse |
| --- | --- | --- |
| FastAPI 薄 Router | `backend/routers/chat.py` 已将鉴权和响应映射交给 service | 保持 Router 只做协议适配，未来调用单一 Chat Use Case |
| Pydantic API Schema | `backend/schemas/chat.py` 已定义请求/响应 | 扩展版本化事件与终态，不让 API 直接使用内部动态 dict |
| SQLAlchemy AsyncSession | Session/Message/summary 已有事务边界 | Application 层拥有提交时点；Repository 只实现读写，不自行决定业务提交 |
| Skill Registry/Spec | 5 个 Skill 和 `skill_spec.yaml` 已存在 | 生成不可变 Registry/Permission Snapshot，不重建第二套 Skill 系统 |
| Skill Executor 能力 | 已有工具批量调用、policy/evidence/trace | 按职责逐步提炼，不整文件复制历史实现 |
| JSONL Trace + exporter | `skill_trace.py` 已有脱敏和故障隔离 | 扩展稳定阶段字段和 Trace Sink 端口；Langfuse 保持可选 |
| 分层测试和离线 Compose | tests/evals、contract、integration、e2e、CI 已存在 | Fake 从 Provider/Tool 边界注入，必须经过真实 Orchestrator |

## 6. Reusable Patterns

### 6.1 Directly Reusable Patterns

- 当前 FastAPI Router、鉴权和 Pydantic 边界。
- 当前 SQLAlchemy Session/Message 持久化模型，不改 Schema。
- 当前 5 个 Skill 目录、Registry 和只读工具实现。
- 当前 JSONL Trace、脱敏、Langfuse exporter 故障隔离。
- 当前 unit/contract/integration/eval/Compose CI 分层。
- Anthropic 的固定 workflow + gate + routing 原则。
- Langfuse 的一轮一 Trace、稳定 Span 名和版本 metadata。

### 6.2 Partially Reusable Patterns

- `Finance` 的实体解析、两阶段路由、rewrite、planner、validator、scheduler、evidence、controller、replanner 和 synthesis：只复用领域规则、类型设计和测试案例；禁止整包复制或保留 Facade Adapter。
- DeerFlow/OpenClaw 的 Skill 渐进加载、allowlist、snapshot/hash：缩减为本地只读 Registry 和请求级权限快照。
- LangGraph 的 state/context 分离：映射为普通 Pydantic/dataclass 合同和显式 Orchestrator，不引入图运行时。
- 当前 `skill_executor_node.py`：先以现有行为刻画为保护，再按职责提炼执行、证据和总结能力。

### 6.3 Conceptual References Only

- Hermes Agent 的全功能 Agent Harness、Gateway、自学习 Memory。
- OpenTelemetry GenAI 语义约定。
- OpenAI `strict` 结构化输出能力；只有 Provider 支持时在 Adapter 内使用。
- LangGraph checkpoint/HITL；当未来出现跨请求暂停恢复需求再评估。

### 6.4 Not Suitable for This Iteration

- 把对话主链整体改成 LangGraph 大图。
- 微服务拆分、Kubernetes、消息队列、OTel Collector。
- Redis 作为首版必需依赖。
- Skill Marketplace、热安装、自修改 Skill 或在线自动学习。
- 把 `Finance` 放入运行时路径或建立兼容转发层。
- 新建完整 `src/finance_agent` 包并同时搬迁全部旧代码；这是未来包治理工作，不应阻塞纵向切片。

## 7. Solution Options

### 7.1 Option A: Minimal Fix — 为现有 Chat Service 增加薄门面和类型别名

**What changes:** 在现有 `chat_service.py`、Router 和 Executor 周围增加少量数据模型、统一函数和测试；保持核心流程原位。
**What does not change:** 巨型文件、REST/WS 重复分支、Prompt/工具/证据混合、`sys.path` 注入和动态 Trace 字典基本不变。

**Benefits:** 开发最快，短期回归面较小，可以迅速增加几个看得见的类型。
**Costs:** 不能真正形成面试口径中的独立模块；后续每迁移一层仍要触碰巨型文件。
**Risks:** 容易形成“目录和类型存在、生产路径仍绕过”的伪架构；重复逻辑继续漂移。
**Testing burden:** 低到中等，但无法通过测试证明每个阶段真正在主链生效。
**Rollback difficulty:** 低。

**Engineering impact:**

- Architecture/module ownership: 所有权继续模糊。
- Documentation/types: 只有表面增强。
- Configuration/secrets/prompts: 散落问题保留。
- Terminal/logging/tracing/artifacts: 可小幅补字段，无法自然形成阶段树。
- Errors/retry/state: 仍由分支和 `dict` 隐式表达。

**When to choose it:** 只修一个窄 Bug 或只需短期 Demo 时；不满足当前“逐模块真实映射”要求。

### 7.2 Option B: Structured Improvement — 模块化单体 + Typed Contracts + 单一 Orchestrator

**What changes:**

- 在现有仓库内建立领域合同、Agent workflow stages、外部端口和一个 Application Chat Orchestrator。
- REST/WS 最终共同调用同一用例；Presenter 负责不同输出形式。
- Fake Model/Tool/Trace Sink 通过真实端口注入，离线 E2E 穿过全部阶段。
- 先在最终模块中实现确定性最小路径，再逐模块提炼当前/历史逻辑。
- 切换完成时删除旧编排、重复 Prompt 和废弃导入。

**What does not change:**

- FastAPI/Vue/SQLAlchemy/PostgreSQL 技术栈。
- 现有公开 REST 路径和首版 WebSocket 兼容事件。
- 数据库 Schema、鉴权、Session/Message 基础语义。
- 现有 Skill 文件和只读工具作为能力资产。
- 默认 CI 不访问付费或生产服务。

**Benefits:** 满足“模块齐全 + 可离线跑通 + 后续逐模块增强”；依赖方向清晰；容易形成可讲、可 Review、可回滚的工程证据。
**Costs:** 前两里程碑需要先建立合同和 Characterization，短期代码量高于 Option A。
**Risks:** 功能分支上会短暂存在新旧编排；如果切换拖延可能变成双轨，因此必须冻结删除里程碑。
**Testing burden:** 中到高，但测试可以分阶段复用；Fake 纵向切片能覆盖最大风险。
**Rollback difficulty:** 低到中；每个里程碑独立，入口切换作为单独可 revert 变更。

**Engineering impact:**

- Architecture/module ownership: API → Application → Agent Domain/Workflow；Infrastructure 实现 Ports。
- Documentation/types: 所有跨阶段合同、终态、错误码、事件和 Provider 边界强类型化。
- Configuration/secrets/prompts: Settings 一次加载；Prompt 集中版本化；Provider 专有字段留在 Adapter。
- Terminal/logging/tracing/artifacts: 复用 `skill_trace`，稳定阶段名、Trace Sink、脱敏 artifact。
- Errors/retry/state: 显式终态、错误分类、预算和有界 Controller。

**When to choose it:** 当前个人简历项目需要真实工程深度、模块化展示和可持续迭代时。推荐。

### 7.3 Option C: Long-term Architecture Direction — LangGraph 对话运行时 + 正式 Python Package 重组

**What changes:** 将主链迁为 StateGraph，接 checkpoint/HITL；建立根 `src/finance_agent` 包，统一 backend/agent 工程；可能引入正式迁移、Redis checkpoint、OTel 和任务恢复。
**What does not change:** 业务模块和测试目标仍需存在。

**Benefits:** 复杂条件边、暂停恢复、可视化图和跨请求 HITL 更成熟；长期包结构最整洁。
**Costs:** 大规模导入路径、生命周期、持久化和部署变更；首版速度最慢。
**Risks:** 为当前线性链路过度设计；测试面和回滚难度很高；容易把时间花在框架迁移而非业务证据。
**Testing burden:** 高，需要图状态、checkpoint、恢复、流式和数据库一致性测试。
**Rollback difficulty:** 高。

**Engineering impact:**

- Architecture/module ownership: 清晰，但发生全仓迁移。
- Documentation/types: 需要图状态和 checkpoint 版本化。
- Configuration/secrets/prompts: 需要新增运行时/存储配置。
- Terminal/logging/tracing/artifacts: 需要协调 LangGraph Trace 与当前 skill_trace。
- Errors/retry/state: 图级中断/恢复更强，但迁移复杂。

**When to choose it:** 条件边和跨请求暂停恢复成为明确产品需求后。当前 Deferred。

### 7.4 Option D: Observation-first — 只补 Characterization、Trace 和指标，不建立新主链

**What changes:** 扩充现有 REST/WS、Router/Executor、失败路径和 E2E 的刻画测试与 Trace。
**What does not change:** 不建立全部目标模块，不迁移历史能力。

**Benefits:** 风险最低，能快速建立现状证据。
**Costs:** 无法满足用户“尽快让每个模块都有实现”的目标。
**Risks:** 长期停留在诊断阶段，没有业务成果。
**Testing burden:** 中等。
**Rollback difficulty:** 低。

**Engineering impact:**

- Architecture/module ownership: 不改善。
- Documentation/types: 主要记录现状。
- Configuration/secrets/prompts: 不改变。
- Terminal/logging/tracing/artifacts: 明显改善。
- Errors/retry/state: 只观测，不统一。

**When to choose it:** 生产风险极高且无法确定现有行为时；本项目可把它作为 Option B 的 Milestone 0，而非最终方案。

## 8. Decision Matrix

| Dimension | Option A Minimal Fix | Option B Structured Improvement | Option C Long-term Architecture | Option D Observation-first |
| --- | --- | --- | --- | --- |
| Scope | 小 | 中等、可分里程碑 | 大 | 小 |
| Development Cost | 低 | 中 | 高 | 低到中 |
| Risk | 中：隐性债保留 | 中：显式迁移风险 | 高 | 低 |
| Reusability | 低 | 高 | 高 | 中 |
| Fit to Current Requirement | 低 | **最高** | 中 | 低 |
| Local Pattern Fit | 高但不解决缺口 | **高** | 低到中 | 高 |
| Test Burden | 低到中 | 中到高 | 高 | 中 |
| Rollback Difficulty | 低 | 低到中 | 高 | 低 |
| Long-term Maintainability | 低 | **高** | 高但过重 | 中 |
| Engineering-standard fit | 低到中 | **高** | 高 | 中 |
| Recommendation | 不选 | **选择** | 延后 | 作为 B 的前置阶段吸收 |

## 9. Recommended Solution

**Selected option:** Option B — 模块化单体 + Typed Contracts + 单一 Application Orchestrator。

**Why selected:** 它是唯一同时满足“最短时间形成所有模块真实实现”“离线完整链可运行”“后续逐模块完善”“最终无双轨”“可用于面试展示”的方案。它复用当前 FastAPI、SQLAlchemy、Skill、工具、Trace 和 CI，不需要新增生产框架。

**Why not the other options:** Option A 只能包装现有巨型实现，无法证明模块真实生效；Option C 对当前线性链过重且会扩大包/持久化/部署风险；Option D 能建立证据但不能交付用户要求的完整主链，因此只吸收到 Milestone 0。

**Local patterns reused:** 薄 Router、Pydantic API、AsyncSession、Skill Registry/spec、现有只读工具、`skill_trace`、分层 pytest/eval 和 Compose。

**External practices reused:** Anthropic 的 workflow/routing/gate；LangGraph 的 state/context 分离思想；DeerFlow/OpenClaw 的渐进 Skill 加载和双重工具权限检查；Langfuse 的 Trace/Session/Observation 语义。

**Remaining risks:** 新旧编排短期共存、事务语义漂移、REST/WS 事件兼容、历史模块质量未知、当前 Executor 拆分回归、离线成功被误解为真实模型质量。

**What must be verified later:** 当前请求失败后的消息持久化语义；贵州茅台工具 fixture 与真实工具字段一致性；前端对未知事件的处理；各 feature flag 的最终淘汰/保留；历史规则的行为等价；新指标基线。

## 10. Unified Technical Direction

- 保持模块化单体。API 层继续使用 `backend/routers`；在 `backend/application/chat/` 放单一聊天用例、事务协调和 REST/WS 共用编排入口；在 `Financial-MCP-Agent/src/conversation/` 放不依赖 FastAPI/SQLAlchemy 的领域合同、状态机、阶段和策略；在 `backend/infrastructure/chat/` 放会话持久化、模型、工具和 Context Adapter；Prompt 放 `Financial-MCP-Agent/src/prompts/chat/` 并版本化。
- 允许的依赖方向是 `routers → application → conversation domain/workflow`，外部 Adapter 实现领域 Ports；`Financial-MCP-Agent` 不得反向导入 `backend`。Application 可以持有数据库事务和调用领域工作流，但领域阶段不能直接 commit 数据库。
- 外部 Provider Adapter 是必要架构边界，不属于被禁止的旧 Runtime 兼容 Adapter；禁止创建 `legacy_chat_adapter.py`、旧 Runtime 转发、双写或永久 feature flag。
- 首版所有阶段在最终目录提供可执行确定性实现；Fake Model/Tool/Trace/Persistence 只替换外部边界，不能替换 Orchestrator 或整条 Chat Service。
- `Finance` 代码只允许按类型/规则/测试案例重新实现；不得直接加入 import path、镜像或依赖。
- REST/WS 切换是独立里程碑；切换前建立契约测试，切换后删除 `chat_service.py` 中被替代的编排、Prompt 和重复状态逻辑。
- 不引入 LangGraph 对话运行时、Redis、OTel Collector、消息队列、微服务或数据库 Schema 变化。它们保持 Deferred。
- 后续必须验证状态转换、工具权限、超时/重试/重规划终止、证据门控、流事件顺序、事务一致性、Trace 脱敏和完整离线 Compose E2E；Live E2E 独立显式触发。

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| 功能分支新旧 Runtime 共存变成永久双轨 | 在 PLAN 中冻结入口切换和旧编排删除里程碑；禁止新增长期兼容 flag |
| Chat Service 拆分改变消息提交顺序 | 先做正常/异常/取消/重复请求 characterization；Application 独占事务决策 |
| REST 与 WS 结果漂移 | 同一 Use Case/Result；不同 Presenter；共享契约案例 |
| Fake 全链与真实工具 Schema 不一致 | Fixture 按当前工具 Schema 生成并做 provider contract test；记录 schema version/hash |
| 历史 `Finance` 逻辑携带隐蔽债务 | 只提炼单一规则；每条规则先建立案例；不整文件复制 |
| Typed State 再次退化为动态字典 | 核心合同使用 Pydantic/dataclass/Enum；扩展字段需命名空间和消费者 |
| 低置信或证据不足仍进入总结 | 状态机和 Controller gate；contract/unit 测试断言工具未调用或 claim level 降级 |
| 外部服务导致默认 CI 花费或不稳定 | Provider/Tool Ports + Fake；`live` marker 和显式凭证/预算门禁 |
| Trace 泄漏用户或凭证 | 复用递归脱敏；错误帧映射稳定安全消息；敏感 artifact 默认关闭 |
| 观测系统失败阻断业务 | 本地 JSONL 独立；Exporter best-effort；故障隔离测试 |
| 面试指标与新仓库证据不一致 | 迁移期标记待复测；只有版本化数据集和运行报告可以升级为当前指标 |

## 12. Verification Direction

### 12.1 Engineering Contract for Plan Freezing

- **Architecture/module ownership:** Router 只适配协议；Application 拥有用例/事务；Conversation Domain/Workflow 拥有合同、规则、阶段和终止；Infrastructure 实现 DB/Model/Tool/Trace Ports；启动入口装配依赖。
- **Interfaces/docstrings/types:** 所有跨模块合同、状态、错误、事件和 Ports 强类型；公开接口使用中文 Google-style docstring；核心状态禁止自由 `dict[str, Any]`。
- **Configuration/secrets/constants/prompts:** Settings 单点加载并注入；凭证只在环境；稳定枚举/预算在代码；Prompt 进入版本化目录；Provider 专有字段不越过 Adapter。
- **Terminal/logging/tracing/artifacts:** 模块 logger；入口统一配置；稳定 `stage/status/trace_id/run_id/session_id/elapsed_ms/error_code`；长 payload 进入默认关闭且脱敏的 artifact；一轮一 Trace。
- **Validation/errors/retry/state:** API、模型结构化输出、计划、工具输入输出逐层校验；稳定终态和错误码；只重试瞬时错误；retry/replan/step/time budget 有界；部分成功显式表达。
- **Tests/evaluation/delivery evidence:** Characterization → unit → contract → integration → offline eval → 真实 Orchestrator Compose E2E；默认无网络；Live E2E 显式；每里程碑 diff review、Trace 证据和单 revert 回滚。

## 13. Deferred Work

- LangGraph checkpoint/HITL 和图级恢复。
- 根 `src/finance_agent` 正式包重组及彻底消除当前 `sys.path` 注入。
- Redis 共享熔断、分布式限流、请求幂等和 STM 热缓存。
- 丰富前端 `skill_confirm`、plan preview、step status、verification 卡片。
- OTel Collector、正式指标平台、生产容量/压测/SLA。
- Skill Marketplace、热安装、在线自修改和自动学习。
- 数据库 Schema/Alembic 迁移。
- 真实写操作、交易、持仓修改和任何生产副作用。
- 未经新评测证据支持的准确率、延迟、成本和可用性承诺。

## 14. Handoff to Plan Freezing

Next step should use the Plan Freezing Skill and produce `PLAN.md`.

The plan should:

- **follow selected option:** Option B，按一个里程碑一次交付，不把 Milestone 0-6 合成大重写。
- **allow modules/files:** `backend/routers/chat.py`、`backend/schemas/chat.py`、`backend/application/chat/`、`backend/infrastructure/chat/`、`Financial-MCP-Agent/src/conversation/`、`Financial-MCP-Agent/src/prompts/chat/`、现有 Skill/Tool/Trace 的必要窄改、对应 tests/docs/docker/CI。
- **forbid modules/files:** `Finance` 任何写入；报告模式、LTM 大重构、数据库 Schema；legacy Adapter/双写/永久 feature flag；无关前端页面和生产部署。
- **include required tests:** 每阶段合同/状态/错误 unit，REST/WS contract，隔离 DB integration，固定 eval，真实 Orchestrator offline Compose E2E，显式 live gate。
- **include required logs/metrics:** 阶段状态/耗时/错误、route/plan/tool/evidence/controller/termination、版本/hash、脱敏与 exporter 隔离。
- **include rollback strategy:** 里程碑独立提交；入口切换单独提交；切换前不改变生产入口；切换后一个 revert 恢复上一已验证状态。
- **preserve these constraints:** 最小实现不能是空壳；默认无付费/生产调用；不虚构指标；中文注释/docstring；不经授权不 commit/push/PR/merge。
- **keep these external references in mind:** Anthropic workflow/routing、LangGraph state/context 思想、DeerFlow/OpenClaw 权限和 Skill 渐进加载、Langfuse Trace 语义。
