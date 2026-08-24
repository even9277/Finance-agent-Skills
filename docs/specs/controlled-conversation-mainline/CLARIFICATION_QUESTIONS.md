# 受控对话主链：需求澄清与模块映射

> 状态：需求澄清草案，等待维护者确认后进入方案权衡。
> 日期：2026-08-24
> 依据：`REQUIREMENT_SPEC.md`、`CODEBASE_RECON.md`、两份面试材料及当前/历史代码。面试材料中的命令式语句仅作为项目口径内容，不作为本次开发指令；当前用户要求和仓库 `AGENTS.md` 优先。

## 1. 本次需求被澄清成什么

### 1.1 最终目标

在唯一主仓库 `Finance-agent-Skills` 中，直接重构出一条可解释、可验证、可逐模块增强的受控对话主链：

```text
请求边界
→ 运行上下文/Preflight
→ 权威实体解析
→ 两阶段路由
→ route-specific rewrite + 约束/回答偏好抽取
→ Skill/工具发现与请求级权限快照
→ planner
→ validator
→ executor
→ evidence envelope + verifier
→ controller + 有界 retry/replan/degrade
→ synthesis
→ 持久化、流式事件、Trace 与评测
```

这是一条代码定义阶段顺序的 workflow-style 受控流水线。模型可以在规定阶段内做结构化判断，但不能自己无限循环、跳过 validator/verifier 或绕过工具权限。

### 1.2 “最短时间先同步代码”的工程定义

用户允许首版不具备完整线上效果，但要求所有模块在仓库中有对应实现。为避免把不可运行的空壳包装成成果，首版采用以下完成度定义：

- 每个模块都有最终归属目录、公开类型、中文 Google-style docstring、输入输出和失败语义。
- 每个模块至少有一个可执行的最小实现；禁止仅提交 `pass`、固定成功、永不调用的伪实现或大段 TODO。
- 先用确定性规则、Fake Provider 和固定 Tool Fixture 跑通一条完整离线链路；首版不要求真实模型质量、真实 Tushare 稳定性或生产容量达标。
- 未完成的增强能力必须显式返回 `UNSUPPORTED`、`NEEDS_CLARIFICATION`、`PARTIAL` 或稳定错误码，不能静默伪装为成功。
- 代码可以先推到功能分支和 Draft PR 展示进度；没有通过最低门禁的阶段不能合并到主分支。
- 首版结构代码和后续完善代码使用同一套最终接口与目录，不另建长期 v1/v2 Runtime，不做 `Finance` → 新仓库 Adapter。

因此，首版交付物不是“生产完成版”，而是“**架构与合同完整、离线纵向切片可运行、真实效果待逐模块补强的工程基线**”。

## 2. 面试口径审核结论

### 2.1 正确且应保留的设计口径

- 对话模式应称为“受控执行链 / workflow-style 编排”，不是自由 Agent Loop。
- `active_entity` 必须在路由前固定；歧义时澄清，不能为了继续执行而偷偷选择最高分。
- 路由负责选择能力链，rewrite 负责把口语转成结构化执行契约，二者不能互相抢职责。
- `financial-sop` 与 `tushare-data` 共享 validator/executor/verifier/controller/synthesis 内核；Skill 主要在 planner 之前增加 SOP、工具和证据约束。
- planner 不能直接执行；计划必须经过工具存在性、参数、依赖、权限和证据覆盖校验。
- 工具成功不等于证据可用；Evidence/Verifier 必须检查实体、时间、维度、数据质量和证据角色。
- 重试和重规划必须有界；证据不足时降低结论强度或澄清，不能无约束进入总结。
- 一轮用户请求对应一条 Trace，阶段和工具调用对应子 span；会话用 `session_id` 聚合多轮。
- 默认离线测试不调用付费模型、真实 Tushare、生产数据库或外部 Langfuse。

### 2.2 当前口径与目标仓库的冲突

| 文档口径 | 当前目标仓库事实 | 澄清后的处理 |
| --- | --- | --- |
| 已有完整“实体→路由→改写→计划→验证→执行→证据→控制→总结”链路 | 当前真实入口主要是 `chat_service.py → skill_router_node → skill_executor_node`，多数中间阶段未成为独立主链 | 作为目标架构，不再写成目标仓库当前已全部实现 |
| route 前已有 authoritative entity resolver | 当前 Router 自己包含部分规则、上下文拼接和主体判断 | 首批抽出唯一实体解析合同；Router 只能消费解析结果 |
| 路由只读最小上下文 | 当前 `_build_skill_route_context` 会拼 running summary 和最近消息 | 后续以 Context Packet 白名单约束，具体尾窗大小由评测决定 |
| Prompt 已集中到 `src/prompts/` 并版本化 | 当前 Prompt 分散在 `chat_service.py`、Router、Executor 等文件 | 首版建立版本化 Prompt Registry；迁移模块时删除原重复 Prompt |
| 前端已有 `trace_summary/plan_preview/step_status/verification_summary/skill_confirm` | 当前主要消费 session/context/compaction/done/error，丰富控制帧未完整接入 | 定义 `StreamEventV1`，先保留现有事件，再增量加入可选事件并做契约测试 |
| PostgreSQL + Redis 已承担事实和运行态 | 目标仓库有 PostgreSQL/SQLite 路径，但未确认 Redis 主链能力 | 首版不依赖 Redis；幂等/熔断先用进程内可替换接口，Redis 实现放增强阶段 |
| Langfuse 已形成完整评测回流 | 当前已有 JSONL Trace、脱敏和可选 exporter，评测联动仍不完整 | 本地 JSONL 为首版事实源；Langfuse 是可选出口，失败不得阻断业务 |
| 冻结指标均有可信评测记录 | 当前目标仓库未发现足以重现全部数字的原始评测证据 | 数字保留为“面试材料历史口径/待复测”，迁移后用新基线重新生成证据 |
| 主模型统一为指定 Qwen 版本 | 当前配置默认值和实际 Provider 口径不完全一致 | 核心合同 Provider-agnostic；模型名只在 Settings/Adapter，首版不锁死供应商 |
| 启动自动迁移可作为数据库策略 | 自动 DDL 对企业级生产风险较高，且当前迁移历史未完全核实 | 首版不改 Schema；后续 Schema 变更必须单独 Alembic 迁移与回滚规格 |

### 2.3 缺失且必须补入需求的内容

- 唯一的跨阶段 Typed Run Context 和状态转换表。
- `SUCCEEDED / PARTIAL / NEEDS_CLARIFICATION / REJECTED / FAILED / CANCELLED / UNSUPPORTED` 终态及稳定错误码。
- REST 与 WebSocket 共用同一应用用例，避免两套编排漂移。
- 消息写入、失败回滚、重复请求和客户端断开的事务/幂等语义。
- 对结构化模型输出、工具参数、工具结果和流式事件的版本契约。
- 每个阶段的超时、重试、重规划、总步骤和总耗时预算。
- Prompt、Skill spec、Tool schema、数据集和 Trace schema 的版本关联。
- 哪些是“首版最小实现”，哪些是“真实效果增强”，哪些是“生产预研”，防止简历表述越界。

## 3. 统一状态与接口口径

### 3.1 核心状态

后续方案至少要覆盖下列稳定对象，名称可在方案阶段调整，但业务含义不能丢失：

| 合同 | 责任 |
| --- | --- |
| `ConversationRequest` | 用户、会话、消息、显式 Skill、请求/幂等标识 |
| `ConversationRunContext` | trace/run/session/turn、预算、时钟、版本、当前状态 |
| `ContextPacket` | 按阶段裁剪后的当前轮、尾窗、摘要、画像和已确认约束 |
| `EntityResolutionResult` | 主实体、候选实体、继承、置信度、澄清和失败原因 |
| `RouteDecision` | `financial-sop/tushare-data/fallback`、Skill、置信度、理由、确认要求 |
| `RewriteResult` | effective query、route-specific 槽位、当前约束、回答偏好、澄清 |
| `ToolPermissionSnapshot` | 本轮允许工具、发现来源、健康状态和版本/hash |
| `ToolPlan` / `ValidatedToolPlan` | DAG 步骤、参数、依赖、证据目标和校验结果 |
| `StepResult` / `EvidenceEnvelope` | 工具状态、错误、时间、来源、数据摘要和证据 ID |
| `VerificationResult` | accepted/rejected、缺失维度、claim level、是否可恢复 |
| `ControllerDecision` | retry/replan/clarify/degrade/stop 以及剩余预算 |
| `AnswerContextPack` / `ConversationResult` | 受控总结输入和唯一终态输出 |
| `StreamEventV1` | 统一、可版本化、前端可消费的流事件 |

核心状态禁止用一个无限扩张的 `dict[str, Any]` 承载。扩展性字段可以存在，但必须有命名空间、消费者和序列化规则。

### 3.2 状态转换

```text
RECEIVED → PREFLIGHTED → ENTITY_RESOLVED → ROUTED → REWRITTEN
→ PLANNED → VALIDATED → EXECUTING → VERIFIED → SYNTHESIZING
→ SUCCEEDED / PARTIAL / NEEDS_CLARIFICATION / REJECTED / FAILED / CANCELLED
```

- 任何阶段输入校验失败都不能进入下一阶段。
- `fallback` 可以跳过工具计划，但仍需经过受控上下文装配、总结和统一终态映射。
- `NEEDS_CLARIFICATION` 是正常业务终态，不是 500 错误。
- `PARTIAL` 必须携带缺失证据和允许结论范围。
- retry/replan 只从明确可恢复状态进入，不能形成无限环。

## 4. 逐模块设计口径与迁移映射

### 4.1 应用编排与运行上下文

- **设计口径**：API 层只做协议/鉴权/校验；一个 application orchestrator 拥有阶段顺序、预算、终态和事务协调；REST 与 WebSocket 只是同一运行结果的不同 presenter。
- **当前仓库**：编排集中在约 1,812 行 `backend/services/chat_service.py`，同步/流式大量重复。
- **历史参考**：`backend/services/chat/orchestrator.py`、`stream.py`、`preflight.py`、`agent_runtime/contracts.py`。
- **首版实现**：先定义 Typed Context、Stage Result、统一 orchestrator 和事件 sink；用 Fake Provider 跑全链，不改变数据库 Schema。
- **迁移路线**：先让新模块在功能分支完整串联，再一次性切换两个公开入口；切换时删除旧主链编排，不保留长期 Adapter。
- **最低验收**：同一输入经 REST/WS 得到同一终态；取消、异常和部分成功不重复写消息；全链有同一 `trace_id`。

### 4.2 Preflight、上下文与记忆读取

- **设计口径**：先做输入大小、安全和上下文预算；每阶段通过 Context Packet 只拿所需信息；当前轮显式要求高于 STM/LTM，LTM 不能覆盖本轮指令。
- **当前仓库**：已有 running summary、动态预算、异步压缩和画像读取，但上下文拼装分散在 Chat Service。
- **历史参考**：`preflight.py`、`working_state.py`、`memory_bridge.py`。
- **首版实现**：复用当前 Session/Message/summary；只抽出只读 Context Builder，不改 LTM 写回机制。
- **增强阶段**：上下文溢出恢复、约束合并、记忆 scope、离线多轮评测。
- **最低验收**：路由包不含完整 LTM/Skill 正文；当前轮约束不会被旧摘要覆盖；超预算返回稳定状态。

### 4.3 权威实体解析

- **设计口径**：当前轮优先、历史仅兜底；输出主实体/候选/继承/置信度/澄清；低置信度不猜。
- **当前仓库**：没有成为真实入口的统一 resolver；Router/Executor 各自存在主体识别逻辑。
- **历史参考**：`entity_resolver_v2.py`、`stock_resolver.py` 及历史 route bridge。
- **首版实现**：股票/基金代码与显式名称的确定性解析、代词继承、歧义返回；LLM resolver 作为可替换 Provider，默认测试不用。
- **增强阶段**：板块/指数、多实体比较、别名目录、置信度校准和 schema repair。
- **最低验收**：当前轮换主体覆盖上轮；“它”只在合法上下文继承；“平安”类歧义进入澄清；解析失败不调用工具。

### 4.4 两阶段意图路由

- **设计口径**：第一阶段发现/确认 SOP，第二阶段区分实时事实链与 fallback；显式 Skill 为高优先级但仍需权限和实体契约校验。
- **当前仓库**：`skill_router_node.py` 已支持规则、LLM、SOP 与 follow-up，但多种职责共存，合同仍偏动态。
- **历史参考**：`route_stage1.py`、`route_stage2.py`、`router.py`。
- **首版实现**：保留已验证规则作为 deterministic baseline，返回统一 `RouteDecision`；低置信度先返回 `NEEDS_CLARIFICATION`，首版不强制完成前端确认卡片。
- **增强阶段**：metadata shortlist、LLM rerank、显式选择与确认恢复、分路线评测。
- **最低验收**：概念问题不因金融关键词误进工具链；实时行情问题不走纯 fallback；路由不能修改实体。

### 4.5 Route-specific rewrite 与窄 Extractor

- **设计口径**：rewrite 只把原话转换为执行契约，不选最终工具、不验证证据、不重猜实体；约束和本轮回答偏好独立抽取并按“当前轮显式优先”合并。
- **当前仓库**：目标主链没有独立 rewrite/extractor；Prompt 和上下文处理在服务/Executor 中混合。
- **历史参考**：`query_rewriter.py`、`constraints_extractor.py`、`reply_preference_extractor.py`。
- **首版实现**：为三种 route 定义 discriminated union；先做确定性补全和严格 schema gate，未知槽位进入澄清。
- **增强阶段**：结构化模型输出、一次窄修复、multi-task 拆分和原意一致性检查。
- **最低验收**：fallback 不生成工具提示；SOP 不越过 Skill input contract；坏 rewrite 不能进入 planner。

### 4.6 Skill Registry、Retriever 与 Loader

- **设计口径**：`SKILL.md` 是人类说明，`skill_spec.yaml` 是机器合同，references 是稳定方法论，tests 是回归资产；发现、选择和加载分开，按阶段渐进披露。
- **当前仓库**：已有 5 个 Skill 目录和 Registry，部分 metadata/reference 发现已实现；Retriever/Loader 边界未完全独立。
- **历史参考**：历史 Skill Registry/route/loader 相关实现和 `skill_runner_v2.py`。
- **首版实现**：对现有 5 个 Skill 做启动时 schema gate，输出只读 registry snapshot；按 rewrite/planner/synthesis 提供最小视图。
- **增强阶段**：last-known-good snapshot、版本/hash、热更新、显式确认和单 Skill 指标。
- **最低验收**：声明不存在工具的 Skill 启动校验失败；reference 不能扩大 allowed tools；每个 Skill 有至少一正一反案例。

### 4.7 工具发现与动态白名单

- **设计口径**：`available_tools = 业务允许 ∩ 本轮发现 ∩ 可执行注册表 ∩ 健康状态`；权限快照先于 planner 固定并带版本。
- **当前仓库**：已有工具注册/Skill allowed tools/部分 policy violation 检查，但未形成统一请求级 snapshot。
- **历史参考**：`tool_discovery/capability_index.py`、`discovery_resolver.py`、`executable_registry.py`。
- **首版实现**：只读工具注册表 + 确定性 shortlist + `ToolPermissionSnapshot`；首版健康状态可使用进程内实现。
- **增强阶段**：共享熔断、capability index 版本、last-known-good 和工具权限审计。
- **最低验收**：planner 看不到白名单外工具；工具在计划后失效时 validator/executor 能返回稳定错误，而非调用失败后伪成功。

### 4.8 Planner

- **设计口径**：生成结构化 DAG，只描述目标、工具、参数、依赖、required/optional 和证据类型；不能执行工具。
- **当前仓库**：`skill_spec_planner.py`、`tushare_reference_planner.py` 与 Executor 内部计划逻辑并存。
- **历史参考**：`planner/sop_planner.py`、`tushare_planner.py`、`plan_preview.py`。
- **首版实现**：为一条股票快照和一个 SOP 用确定性 planner 产出真实计划；模型 planner 走 Provider 边界。
- **增强阶段**：更多数据需求、可选证据、并发 DAG、plan preview。
- **最低验收**：计划只能引用快照内工具；每步有稳定 step ID；依赖可拓扑排序；同输入 fixture 结果可复现。

### 4.9 Plan Validator

- **设计口径**：校验工具存在/权限、参数 schema、DAG 无环、依赖存在、重复调用、实体一致和 required evidence 覆盖。
- **当前仓库**：Executor 有局部 policy/schema/evidence 检查，但独立 validator 合同不足。
- **历史参考**：`planner/plan_validator.py`。
- **首版实现**：纯函数/纯领域服务，无网络；任何 issue 都返回结构化 `ValidationIssue`。
- **增强阶段**：业务语义规则、计划修复建议和版本兼容。
- **最低验收**：越权工具、非法参数、环、悬空依赖和缺 required evidence 全部被阻断。

### 4.10 Executor 与工具治理

- **设计口径**：只执行 validated plan；DAG 分层并发、action fingerprint 去重、单工具/总预算、只对瞬时错误有限重试、有副作用工具默认禁用。
- **当前仓库**：`skill_executor_node.py` 已有批量工具调用、deterministic/agentic/hybrid、证据和 Trace，但文件巨大、职责混合。
- **历史参考**：`execution_scheduler.py`、`budget.py`、`skill_runner_v2.py`。
- **首版实现**：提取统一 Scheduler/ToolInvoker 接口；Fake 工具支持成功、空结果、超时、非法结构；生产仅允许现有只读工具。
- **增强阶段**：API family 限流、三态熔断、Redis 共享状态、analysis clock 和缓存。
- **最低验收**：超时不会无限挂起；重复 action 只执行一次；required/optional 失败可区分；越权计划绝不执行。

### 4.11 Evidence Envelope 与 Verifier

- **设计口径**：工具返回先归一化，再按实体、时间、维度、角色和质量验收；输出 accepted/rejected/missing/claim level。
- **当前仓库**：`skill_evidence.py` 已有 `ToolEvidence` 和验证结果，但尚未成为所有链路唯一合同。
- **历史参考**：`executor/evidence_envelope.py`、`verifier/evidence_verifier.py`、`verifier/scoring.py`。
- **首版实现**：支持主体匹配、空结果、stale、required evidence 缺失和 descriptive/partial claim level。
- **增强阶段**：冲突证据、新闻弱证据、质量评分和 Skill-specific contract。
- **最低验收**：HTTP 200 的空 payload 不能成为 accepted evidence；错主体/旧时间证据不能支撑强结论。

### 4.12 Controller 与 Replanner

- **设计口径**：Verifier 只判断证据，Controller 决定动作；Replanner 只能补缺失维度或换批准的备用工具，不能推翻目标。
- **当前仓库**：Executor 有降级分支，但统一 Controller/Replanner 合同尚未接入真实入口。
- **历史参考**：`controller/runtime_controller.py`、`replanner/tushare_replanner.py`。
- **首版实现**：规则 Controller；最大一次 retry、一次 replan（具体数字在方案阶段冻结），预算耗尽后 PARTIAL/FAILED。
- **增强阶段**：按错误类别恢复、备用数据源和人工确认。
- **最低验收**：可证明无无限循环；不可恢复错误不重试；每次动作有 reason、budget before/after。

### 4.13 Synthesis

- **设计口径**：只读取 `AnswerContextPack`，不能直接读原始工具大包；accepted evidence、缺失维度和 claim level 是硬边界。
- **当前仓库**：Executor 内含 synthesis Prompt 和结果清理；fallback 另走 Chat Service Prompt。
- **历史参考**：`synthesis/answer_context_pack.py`、`synthesize_sop.py`、`synthesize_tushare.py`、`synthesize_fallback.py`。
- **首版实现**：确定性模板可对 Fake 证据生成完整/部分/澄清答案；真实 LLM 是可替换 Adapter。
- **增强阶段**：Prompt 版本、风格偏好、引用展示和越权断言。
- **最低验收**：rejected evidence 不进入上下文；PARTIAL 明示缺口；无实时证据不能声称“当前价格/确定原因”。

### 4.14 持久化、流式事件与前端

- **设计口径**：业务主链先产出阶段事件，REST Presenter 聚合最终结果，WebSocket Presenter 编码 `StreamEventV1`；控制帧和 token 不靠“能否 JSON parse”隐式区分。
- **当前仓库**：REST/WS 两套服务函数；WebSocket 使用纯文本 token + JSON 控制帧混合协议；前端已支持基础事件和压缩状态。
- **历史参考**：`chat/stream.py`、route summary/plan preview/HITL 代码。
- **首版实现**：保持现有公开协议兼容，新增事件必须带 `type/version/trace_id/sequence`；先完成后端合同和前端忽略未知事件能力。
- **增强阶段**：plan/step/verification/skill_confirm 卡片、断线恢复和消息幂等。
- **最低验收**：事件顺序可测试；错误帧不泄漏原始异常；客户端断开后任务和 DB session 正确清理。

### 4.15 可观测、评测与工程基础设施

- **设计口径**：一轮一 Trace、阶段一 Span、工具一子 Span；本地脱敏 JSONL 为事实源，Langfuse 为可选可视化出口；版本字段和 eval case 可关联。
- **当前仓库**：`skill_trace.py` 已有上下文、脱敏、JSONL、exporter 隔离；测试/Eval/Compose 基础设施已搭建，但真实主链 E2E 仍被 Fake Service 替换。
- **首版实现**：每个阶段至少记录 status/duration/error_code/contract version；Fake 通过真实 orchestrator 边界注入，不再替换整个 chat service。
- **增强阶段**：Prompt/Skill/Tool schema 链接、Langfuse score、bad-case 回灌和历史趋势。
- **最低验收**：离线完整链产生可断言 Trace；常见 Secret 被脱敏；exporter 故障不影响业务；指标不得在未重测前写成当前事实。

### 4.16 PostgreSQL、Redis、鉴权和高可用边界

- **设计口径**：PostgreSQL 是事实真源；Redis 只存可重建运行态；鉴权与 user/session 隔离必须贯穿主链。
- **首版范围**：复用当前鉴权、Session/Message 和隔离 PostgreSQL，不改 Schema；不把 Redis 设为跑通主链的前置条件。
- **增强范围**：请求幂等、分布式限流、共享熔断和热状态缓存；需要单独依赖和恢复方案。
- **非当前承诺**：生产 SLA、Kubernetes、跨区容灾、大规模压测和真实交易写入。
- **最低验收**：用户不能读取/续写他人会话；默认链路只读外部金融数据；生产写能力永久禁止。

## 5. 最短可行迁移路线

### Milestone 0：冻结合同与现有行为

- 建立上述核心类型、错误码、状态机和事件版本。
- 为现有 REST/WS、会话写入、Router/Executor 和 Trace 补 characterization tests。
- 不改变生产入口。

**结果**：大家先约定“每一棒交什么”，避免先搬代码后反复改字段。

### Milestone 1：仓库结构完整 + 离线纵向切片

- 在最终目录建立全部主链模块，不建临时 v2 目录。
- 每个模块提供可执行最小实现和 Fake Provider。
- 新 orchestrator 从请求走到最终回答和 Trace；至少覆盖成功、澄清、工具超时、证据不足四条离线路径。
- 暂不接管公开入口，可先推功能分支/Draft PR。

**结果**：最快实现“每个模块仓库里都有真实代码，并能离线跑通整条受控链”。

### Milestone 2：实体、路由、rewrite 接入真实入口

- 迁移并重构历史实体/两阶段路由/rewrite/extractor 逻辑。
- 使用当前 Skill Registry 和现有会话上下文。
- 先接只读 fallback + 一个代表性 Skill，建立模块评测。

**结果**：用户问题在调用工具前已有稳定主语、路径和执行契约。

### Milestone 3：Planner、Validator、Executor 收敛

- 迁移历史 planner/validator/scheduler 中经过测试证明有效的逻辑。
- 将当前巨型 Executor 的工具调用能力收敛到统一执行内核。
- 加入权限快照、预算、去重和失败分类。

**结果**：所有工具调用都来自可审查、可拒绝、可复现的 validated plan。

### Milestone 4：Evidence、Controller、Synthesis 收敛

- 接入统一 Evidence Envelope、Verifier、规则 Controller 和有界 Replanner。
- Synthesis 只消费 AnswerContextPack。
- 完成正常、部分成功、澄清和失败终态。

**结果**：证据不足不会强答，完整受控业务语义跑通。

### Milestone 5：REST/WS 单主链切换与旧实现删除

- REST/WS 同时切到新 orchestrator。
- 保持现有 API/事件兼容，加入版本化可选事件。
- 删除 `chat_service.py` 中被替换的编排/Prompt/重复状态逻辑和旧导入。
- 完成真实主链 offline Compose E2E。

**结果**：生产代码只剩一条受控主链，不再双轨。

### Milestone 6：真实效果与工程增强

- 逐模块接真实模型/只读数据源的 protected Live E2E。
- 补 Redis 熔断/限流/幂等、前端 plan/verification 卡片、Langfuse eval 回流。
- 重跑并形成新的指标基线，经过证据核验后再更新面试口径。

**结果**：从“完整可运行架构”进化到“效果、稳定性和面试证据一致”。

## 6. 每个里程碑的最低交付闭环

每个里程碑必须有：

1. 一个 GitHub Issue：问题、范围、非目标、模块映射和验收。
2. 独立功能分支；禁止直接改主分支。
3. 规格/合同或 ADR 更新。
4. 中文注释、Google-style docstring、类型和错误语义。
5. unit + contract + applicable integration/offline eval。
6. 经过真实 orchestrator 的离线 Compose E2E；Milestone 0 可用现有 characterization gate 例外。
7. Trace/artifact 证据、最终 diff review 和回滚说明。
8. Draft PR → CI → Code Review → 修复 → Ready PR → merge。
9. 单个 revert 可以恢复上一已验证里程碑。

未经用户明确授权，本澄清文档不执行 commit、push、创建 PR 或 merge。

## 7. 产业实践对照（外部参考，不是本项目当前实现）

- Anthropic 将 workflow 定义为由预设代码路径编排模型/工具，agent 则由模型动态控制步骤；并建议从能解决问题的最简单方案开始。该原则支持本项目使用固定主链、只在执行阶段保留有界反馈。[Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
- Anthropic 的可信 Agent 实践强调由用户控制工具权限，并按 always allow / approval / block 区分动作。本项目首版全为只读工具，未来任何写操作都必须单独审批，不能混入默认对话链。[Trustworthy agents in practice](https://www.anthropic.com/research/trustworthy-agents)
- LangGraph 把 durable execution、streaming、persistence 和 human-in-the-loop 作为图运行时能力；这说明首版自研线性编排可以保持简单，但如果以后需要跨请求暂停/恢复和复杂 HITL，应重新评估是否采用成熟运行时，而不是继续堆 if-else。[LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
- 严格结构化输出支持模型按 JSON Schema 生成，适合 Router/Rewrite/Planner 等合同；即便使用 strict 输出，业务语义验证仍必须保留。[OpenAI Structured Outputs API reference](https://platform.openai.com/docs/api-reference/responses-streaming/response/refusal?lang=python)
- Langfuse 建议聊天场景一轮一 Trace、会话用 Session 聚合，并用稳定的 observation 名称、版本和 metadata 支撑评测。该原则与本项目 `trace_id/session_id` 口径一致。[Langfuse tracing best practices](https://langfuse.com/docs/observability/best-practices)
- OpenTelemetry GenAI 语义约定提供 conversation、workflow、provider、tool execution 等标准属性；首版不必立即接 OTel Collector，但字段命名应避免与行业语义背离。[OpenTelemetry GenAI attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)

## 8. 已建议默认确认的决策

为满足“最快推进”，如果用户不提出异议，后续方案阶段按以下默认决策继续：

1. **第一优先级**：Milestone 0 + 1，即 Typed Contract、最终模块目录、最小真实实现和 Fake 全链 E2E。
2. **首个代表性业务切片**：只读单股基础快照；它比基金对比或市场异动的依赖少，最适合证明全链。
3. **编排方式**：自研线性 workflow + 有界 controller，不引入 LangGraph 作为对话主链运行时。
4. **入口策略**：开发分支可短期保留新旧代码，Milestone 5 切换时一次删除旧编排，不长期双轨。
5. **基础设施**：首版 PostgreSQL/Fake Provider 即可，Redis/Langfuse/真实模型不是离线跑通前置条件。
6. **GitHub 策略**：未完全跑通的代码只进入功能分支/Draft PR；主分支至少保持 import、静态检查、单元/合同和离线纵向 E2E 通过。
7. **指标策略**：面试文档中的既有数字不删除，但在新仓库 README/PR 中标注“待迁移后复测”，不能作为当前验收结果。

## 9. 仍需维护者确认的三项产品决策

这些选择不会阻止先做方案权衡，但必须在对应里程碑开始前冻结：

1. 首个单股快照案例是否使用“贵州茅台/600519.SH”，还是指定你更熟悉、面试更愿意讲的标的。
2. 首版低置信 Skill 是直接返回文字澄清，还是同步开发前端 `skill_confirm` 卡片；默认先文字澄清，卡片放增强阶段。
3. 何时允许把功能分支推送到 GitHub：Milestone 1 离线全链通过后，还是合同和模块目录创建完就先推 Draft PR；默认前者，仓库展示质量更好。

## 10. 下一步交接

用户确认本澄清后：

1. 使用 `solution-tradeoff` 对比“应用层 orchestrator + domain contracts”的具体目录和依赖组织方案，并核对优秀开源实现。
2. 使用 `plan-freezing` 生成只包含函数/文件/测试/回滚/禁止变更的 `PLAN.md`。
3. 依据 `small-step-implementation` 一次只执行一个里程碑；没有用户明确授权不 commit/push/PR/merge。
