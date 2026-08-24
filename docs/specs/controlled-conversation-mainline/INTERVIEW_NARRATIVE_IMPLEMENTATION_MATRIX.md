# 受控对话主链：面试口径与当前实现映射

> 状态：M8 最终事实核对
> 日期：2026-08-24
> 当前实现真相源：`Finance-agent-Skills`
> 历史证据源：`Finance/金融Agent项目描述文档/成果点-对话模式与工具治理-完整阐述.md`、`Finance/金融Agent项目描述文档/对话模式与可观测与skills.md`

## 1. 这份文档解决什么问题

两份面试材料同时包含设计目标、历史代码、未来增强和历史评测数字。它们适合解释“为什么这样设计”，但不能直接证明当前主仓库已经完成每一项能力。本文件以当前代码、自动化测试、Compose 和 Live 报告为证据，回答三个问题：

1. 面试材料里的每个模块，在当前主仓库中映射到哪里。
2. 哪些能力已经由真实主链验证，哪些只有受限实现，哪些仍未实现。
3. 面试时怎样表述才不会把历史口径或未来方案冒充为当前事实。

`Finance` 只读参考，不是运行时依赖；当前实现没有通过 Adapter 转发到历史 Runtime，也没有保留第二条对话主链。

## 2. 状态定义与证据优先级

| 状态 | 含义 | 面试表述规则 |
| --- | --- | --- |
| `VERIFIED_IMPLEMENTED` | 当前唯一公开主链已调用，且有自动测试或 Live/Compose 证据 | 可以说“当前已实现并验证”，同时说明验证边界 |
| `IMPLEMENTED_WITH_LIMITATIONS` | 核心合同或最小实现已存在，但效果、产品交互或分布式能力未完成 | 必须主动说出限制，不能使用完整生产化措辞 |
| `DEFERRED_NOT_IMPLEMENTED` | 仅存在历史代码、文档目标或 Deferred 记录，当前主链未实现 | 只能说“设计过/下一阶段计划”，不能说“已经做了” |
| `HISTORICAL_CLAIM_REQUIRES_RETEST` | 面试材料给出了数字，但当前仓库没有可复现同口径数据集和报告 | 只能称为历史联调口径；简历当前事实必须改用新证据 |

证据优先级固定为：当前生产调用链与合同测试 > 当前 Compose/Live 报告 > 当前单元/离线评测 > 历史 `Finance` 代码 > 面试材料叙述。代码和文档冲突时，以当前代码为准。

## 3. 当前唯一真实调用链

```text
Vue Chat UI
→ POST /api/chat/message 或 WebSocket /api/chat/stream
→ backend.routers.chat
→ ControlledChatUseCase
→ SqlAlchemyConversationRepository.prepare_turn
→ ControlledConversationWorkflow
   1. Context
   2. Entity Resolution
   3. Two-stage Route
   4. Route-aware Rewrite + Constraints + Reply Preference
   5. Tool Permission Snapshot
   6. Planner
   7. Validator
   8. Bounded Executor
   9. Evidence Verifier
  10. Rule Controller
  11. At most one bounded evidence Replan
  12. Accepted-evidence-only Synthesis
→ Repository.save_result + commit/rollback
→ REST response 或兼容 WebSocket 帧
→ redacted root Trace + ordered stage spans
```

生产装配位于 `backend/application/chat/factory.py`。REST 和 WebSocket 都调用 `ControlledChatUseCase.execute()`；旧 `backend/services/chat_service.py` 已删除，因此不存在长期双轨。

## 4. 逐模块映射

### 4.1 产品入口、应用编排与事务

- **面试口径**：前端和 FastAPI 形成产品闭环；REST/WS 共用 session/message/context；一轮任务有统一编排、持久化和错误处理。
- **当前状态**：`VERIFIED_IMPLEMENTED`。
- **当前设计**：Router 只做鉴权、请求映射和安全错误响应；`ControlledChatUseCase` 独占一轮事务，工作流或持久化异常会 rollback；REST/WS 共用同一用例和 `ChatOutcome`。
- **证据**：`backend/routers/chat.py`、`backend/application/chat/use_case.py`、`backend/infrastructure/chat/repository.py`、`tests/contract/test_controlled_chat_contract.py`、`tests/integration/test_controlled_chat_cutover_persistence.py`。
- **限制**：HTTP 响应仍保持旧公开字段，没有直接暴露内部 route、verification 和 terminal status；这是兼容选择，不代表这些内部合同不存在。
- **安全口径**：可以说“已完成唯一公开入口切换和事务闭环”；不要再说公开入口仍经过巨型 `chat_service`。

### 4.2 Preflight、上下文、STM 与 LTM

- **面试口径**：当前轮优先；route/rewrite/synthesis 使用不同最小上下文切片；STM/LTM 不能覆盖当前显式指令；Context Harness 可回放注入与裁剪。
- **当前状态**：`IMPLEMENTED_WITH_LIMITATIONS`。
- **当前设计**：Repository 读取最近消息、`running_summary` 和结构化画像；`ContextBuilder` 只把当前消息、最多 6 条最近消息和摘要交给工作流；Constraint/Preference 只从当前轮抽取。仓库保留 STM/LTM 基础设施和画像 UI；当前受控主链只消费既有最近消息/`running_summary`，并在结果中返回既有画像。
- **证据**：`Financial-MCP-Agent/src/conversation/context.py`、`backend/infrastructure/chat/repository.py`、`backend/services/stm_context_service.py`、`backend/services/stm_compaction_worker.py`、`tests/unit/conversation/test_controlled_state.py`。
- **缺口**：自动压缩入队、LTM 检索/写回、scope filter、conflict resolution、`state_before/state_after` 字段级 Harness 和分阶段画像注入尚未重新接入受控主链；`running_summary` 当前作为文本使用，本轮结束后也没有更新画像。
- **安全口径**：可以说“已实现最小上下文、会话尾窗、摘要和画像读取边界”；完整 Context Harness 和 LTM 分阶段注入仍是增强项。

### 4.3 权威实体解析

- **面试口径**：route 前固定 `active_entity`；当前轮优先；历史只做门控继承；多实体和歧义必须澄清。
- **当前状态**：`IMPLEMENTED_WITH_LIMITATIONS`。
- **当前设计**：`AuthoritativeEntityResolver` 支持股票/基金/板块/指数的冻结目录、显式代码、两个基金比较、代词继承、多历史实体歧义和“平安”歧义；输出 Typed `EntityResolutionResult`，Router 只读消费。
- **证据**：`Financial-MCP-Agent/src/conversation/entity.py`、`tests/unit/conversation/test_understanding_stages.py`、`tests/evals/entity/`。
- **缺口**：目录是代码内小型确定性 catalog，不是统一证券主数据服务；没有 LLM structured resolver、syntax repair、语义 repair、全市场别名库或置信度校准。
- **安全口径**：可以说“主链已经有权威实体阶段和可验证澄清”；不能说“已覆盖全市场实体或完成 LLM 三段式修复”。

### 4.4 两阶段路由与 Skill 激活

- **面试口径**：Stage1 做 SOP shortlist + rerank + confidence gate；Stage2 按是否必须依赖当前事实区分 `tushare-data/fallback`；显式 Skill 是高优先级真源。
- **当前状态**：`IMPLEMENTED_WITH_LIMITATIONS`。
- **当前设计**：`TwoStageRouter` 已固定两阶段职责；`SkillDiscovery` 对 5 个 Skill 做确定性规则匹配，高置信自动进入、低置信返回文字澄清；Stage2 区分静态概念和当前金融事实。Application 合同支持 `explicit_skill`。
- **证据**：`Financial-MCP-Agent/src/conversation/routing.py`、`skill_discovery.py`、`tests/evals/route/`、`tests/evals/skill_activation/`。
- **缺口**：当前没有 LLM rerank、top1/top2 margin 校准或真实 150×3 数据集；公开 REST/WS Schema 没有 `explicit_skill` 字段，前端也没有 `skill_confirm` 确认卡，所以显式选择目前仅是内部合同能力。
- **安全口径**：应表述为“确定性规则基线 + Typed 两阶段路由 + 文字澄清”；LLM rerank 和确认卡是待增强能力。

### 4.5 Route-specific Rewrite、约束与回答偏好

- **面试口径**：三条 route 使用不同结构化 rewrite；约束和回答偏好由窄 extractor 提取；缺槽位时澄清；rewrite 不重路由、不选工具。
- **当前状态**：`VERIFIED_IMPLEMENTED`（确定性基线），模型增强为 `DEFERRED_NOT_IMPLEMENTED`。
- **当前设计**：`RouteAwareRewriter` 返回 `SopRewriteResult/TushareRewriteResult/FallbackRewriteResult` 判别联合；约束和偏好是独立 Typed 对象；基金比较、单股 SOP 等输入不完整会进入澄清；工具选择留给 Permission/Planner。
- **证据**：`Financial-MCP-Agent/src/conversation/rewriting.py`、`constraints.py`、`preferences.py`、`tests/evals/rewrite/`。
- **限制**：当前为规则抽取，不是三个并发 LLM 调用；没有 arbitrary multi-task decomposition、一次模型 schema repair 或 90×3 历史数据集复测。
- **安全口径**：可以说“已把 rewrite 和两个窄 extractor 拆成独立合同并接入主链”；不要说“已用并发模型把 p50 从 1.9s 降到 1.4s”。

### 4.6 Prompt 管理

- **面试口径**：Prompt 集中管理、版本化，并与 Trace/Eval 关联。
- **当前状态**：`IMPLEMENTED_WITH_LIMITATIONS`。
- **当前设计**：受控主链 Synthesis 从 `Financial-MCP-Agent/src/prompts/chat/registry.py` 读取 `chat-synthesis-v2`；`ModelSynthesisRequest` 显式携带 `prompt_version`，测试会断言版本。
- **证据**：`Financial-MCP-Agent/src/prompts/chat/registry.py`、`Financial-MCP-Agent/src/conversation/synthesis.py`、`tests/evals/synthesis/test_synthesis_eval.py`。
- **缺口**：Entity/Route/Rewrite/Planner 当前是确定性模块，因此不存在相应运行中模型 Prompt；没有环境级 Prompt Registry、A/B、canary 或自动回滚。
- **安全口径**：可以说“当前真实模型调用的 Synthesis Prompt 已集中版本化”；不要把历史 `src/prompts/` 中所有设想都说成生产主链正在调用。

### 4.7 Skill Registry、Loader 与五个金融 SOP

- **面试口径**：5 个 SOP 用 `SKILL.md + skill_spec.yaml + references + tests` 表达；Registry 启动校验；路由、规划和总结按阶段渐进加载。
- **当前状态**：`IMPLEMENTED_WITH_LIMITATIONS`。
- **当前设计**：`SkillRegistry().conversation_snapshot()` 为每轮 Workflow 提供冻结 `SkillCatalogSnapshot`；合同把 routing view、execution view 和 reference view 分开；五个 Skill 可被发现并约束权限/数据需求。
- **证据**：`Financial-MCP-Agent/src/skills/skill_registry.py`、`Financial-MCP-Agent/src/skills/financial-sop/`、`Financial-MCP-Agent/src/conversation/contracts.py`、`tests/contract/test_skill_catalog_contract.py`。
- **缺口**：没有完整 lifecycle 状态机、shadow/canary、last-known-good 热切换、reference BM25/embedding 或 ScriptToolSpec；不能把这些设计说成已上线。
- **安全口径**：可以说“已有冻结快照和分阶段视图，5 个 SOP 已进入同一主链”；生命周期和热更新是后续治理设计。

### 4.8 工具发现、动态白名单与权限快照

- **面试口径**：Capability Index、Executable Registry、当前轮 shortlist、Skill `allowed_tools` 和健康状态求交，形成版本化权限快照。
- **当前状态**：`IMPLEMENTED_WITH_LIMITATIONS`。
- **当前设计**：`ToolGovernanceCatalog` 维护 15 个只读工具 Typed Schema；`ControlledPermissionResolver` 根据 rewrite 需求和 Skill 执行视图求交，并生成带 hash 的请求级 `ToolPermissionSnapshot`；Planner 和 Validator 共用该快照。
- **证据**：`Financial-MCP-Agent/src/conversation/tool_governance.py`、`permissions.py`、`tests/unit/conversation/test_tool_governance.py`。
- **缺口**：没有扫描 vendor 文档生成完整 capability index；没有按实时健康、权限等级、freshness 动态过滤；`search_web_news` 不在当前治理目录和生产 Provider 中。
- **安全口径**：可以说“已实现静态治理目录 + 请求级冻结白名单”；不能说“全量 Tushare capability 自动索引和健康感知 discovery 已上线”。

### 4.9 Planner 与 Plan Validator

- **面试口径**：Planner 只生成结构化 DAG；Validator 检查工具、权限、Schema、依赖、重复动作、实体和证据覆盖。
- **当前状态**：`VERIFIED_IMPLEMENTED`（确定性 Planner）。
- **当前设计**：`ControlledPlanner` 把已验证 rewrite 映射为 `ToolPlan`，每步有稳定 ID、Typed 参数、证据维度、required 标记和 action fingerprint；`PlanValidator` 返回结构化问题并生成 `ValidatedToolPlan`，未验证计划不能进入 Executor。
- **证据**：`Financial-MCP-Agent/src/conversation/planning.py`、`validation.py`、`tests/evals/planner/`、`tests/unit/conversation/test_tool_governance.py`。
- **限制**：Planner 是确定性 requirement-to-tool 映射，不是模型基于全量能力自由生成；计划当前多数步骤无复杂依赖，不能以此证明历史通用 Planner 的 88.4% 合规率。
- **安全口径**：可以说“受控主链用确定性 Planner 先确保权限和可复现性”；模型 Planner 是未来可替换 Provider，不是当前事实。

### 4.10 Executor、并发、重试与去重

- **面试口径**：只执行 validated plan；按 DAG 分层并发；去重；单工具和总预算；只对瞬时错误有限重试。
- **当前状态**：`VERIFIED_IMPLEMENTED`，分布式韧性为 `DEFERRED_NOT_IMPLEMENTED`。
- **当前设计**：`ControlledExecutor` 接收 `ValidatedToolPlan`，按层执行，使用 Semaphore 限制 `RunBudget.max_concurrency`（默认 4），action fingerprint 去重，并区分 timeout/transient/permanent/budget failure；重试和总 attempt 有界。
- **证据**：`Financial-MCP-Agent/src/conversation/execution.py`、`contracts.py`、`tests/unit/conversation/test_tool_governance.py`、`tests/evals/executor/`。
- **缺口**：没有“固定 6 路并发”的当前生产承诺、API family 限流、Redis 共享熔断、分布式幂等或 `analysis_clock` 时间桶对齐。
- **安全口径**：应说“默认最大并发 4、可由冻结预算配置，已验证有界并发”；历史“6 路并发及其 p50/p95”待复测。

### 4.11 Evidence Envelope 与 Verifier

- **面试口径**：工具成功不等于证据可用；按主体、时间、维度、角色、质量和冲突验收；输出 accepted/rejected/missing/claim level。
- **当前状态**：`VERIFIED_IMPLEMENTED`。
- **当前设计**：Provider 先把结果转换为 `ToolObservation`；`EvidenceVerifier` 再归一化为 `EvidenceEnvelope`，执行主体、时效、证据维度、角色、质量和冲突检查，并输出 `ANALYTICAL/DESCRIPTIVE/REFUSE` 结论级别。HTTP 200 的空 payload、错主体和陈旧证据不能被静默接受。
- **证据**：`Financial-MCP-Agent/src/conversation/verification.py`、`contracts.py`、`tests/unit/conversation/test_evidence_control_synthesis.py`、`tests/evals/verifier/`。
- **限制**：当前生产目录没有网页新闻证据，因此“弱新闻与行情强证据冲突治理”只属于设计口径；Skill-specific degrade policy 目前主要收敛为统一 claim level。
- **安全口径**：可以完整讲 Evidence/Verifier 主链，但要把网页新闻分层说明为未接入能力。

### 4.12 Controller 与有界 Replanner

- **面试口径**：Verifier 判断证据，Controller 决定 retry/replan/degrade/stop；Replanner 只补明确缺口且不能无限循环。
- **当前状态**：`VERIFIED_IMPLEMENTED`。
- **当前设计**：`RuleController` 依据 `VerificationResult` 和预算返回唯一动作；`BoundedEvidenceReplanner` 只在原权限快照内，为 missing requirement 选择未尝试的备用只读动作；默认最多一次 replan，重复 fingerprint 不会再执行。
- **证据**：`Financial-MCP-Agent/src/conversation/control.py`、`replanning.py`、`workflow.py`、`tests/unit/conversation/test_evidence_control_synthesis.py`。
- **限制**：当前没有模型 Replanner，也没有丰富备用数据源；Controller 没有单独实现跨请求恢复或人工确认恢复。
- **安全口径**：可以说“已证明有限终止和证据补齐”；不要说“所有外部故障都能自动恢复”。

### 4.13 Synthesis 与受控回答

- **面试口径**：Synthesis 只看 accepted evidence、缺失维度、执行摘要和 claim level；rejected evidence 不得进入事实上下文。
- **当前状态**：`VERIFIED_IMPLEMENTED`。
- **当前设计**：`AnswerContextPack.create()` 只复制 accepted facts；被拒绝证据只保留不含事实值的摘要；`ControlledSynthesizer` 使用版本化系统 Prompt 调用 OpenAI-compatible Provider，空返回会失败；确定性 Fake 用于默认测试，真实模型已在 protected Live 场景验证一次。
- **证据**：`Financial-MCP-Agent/src/conversation/contracts.py`、`synthesis.py`、`backend/infrastructure/chat/providers.py`、`tests/evals/synthesis/`、`LIVE_VALIDATION_REPORT.md` 第 8 节。
- **限制**：当前没有自动 citation UI、模型 Judge 或对所有 Skill 的真实生成质量评测。
- **安全口径**：可以说“回答生成已被 accepted-only 上下文硬约束”；不能把一次 Live 成功扩展成全场景正确率。

### 4.14 前端、REST 与 WebSocket 事件

- **面试口径**：前端展示流式 token、route summary、plan preview、step status、verification 和 skill confirm 卡片。
- **当前状态**：REST/WS 单主链为 `VERIFIED_IMPLEMENTED`；丰富控制事件为 `DEFERRED_NOT_IMPLEMENTED`。
- **当前设计**：前端已支持会话、消息、摘要、上下文窗口、画像和 WebSocket；WS 发送 `session_id → 一段最终回答文本 → context_update → done`，异常返回稳定码和安全文案。
- **证据**：`backend/routers/chat.py`、`frontend/src/composables/useChat.ts`、`frontend/src/stores/chatStore.ts`、`tests/contract/test_controlled_chat_contract.py`。
- **缺口**：不是 Provider 逐 token streaming；没有 `plan_preview/step_status/verification_summary/skill_confirm` 产品卡片；内部 `WorkflowEvent` 目前送往 Trace，不作为公开 WS 事件协议。
- **安全口径**：应说“REST/WS 已共用业务用例，WS 是兼容终态文本帧”；不要演示不存在的控制卡片。

### 4.15 持久化、鉴权、Redis 与高可用

- **面试口径**：PostgreSQL 是事实真源，JWT 和用户隔离贯穿主链；Redis 承担幂等、熔断、限流和可重建运行态。
- **当前状态**：数据库/事务/鉴权隔离为 `VERIFIED_IMPLEMENTED`；Redis 治理为 `DEFERRED_NOT_IMPLEMENTED`。
- **当前设计**：SQLAlchemy Repository 管理 Session/Message/summary/profile 读取与一轮消息原子写入；REST/WS 都鉴权并按 user ownership 查询；Compose 用 PostgreSQL 验证，Live 用临时 SQLite 隔离。
- **证据**：`backend/middleware/auth.py`、`backend/infrastructure/chat/repository.py`、`tests/integration/test_postgres_isolation.py`、`tests/integration/test_controlled_chat_cutover_persistence.py`。
- **缺口**：当前受控链没有 Redis 请求幂等、共享熔断、分布式限流、断线恢复或生产 SLA；数据库 Schema 仍有历史初始化噪声，未迁移到完整 Alembic 治理。
- **安全口径**：可以说“当前用户/会话隔离和事务已验证”；Redis 三态熔断只能作为下一阶段方案。

### 4.16 Trace、Langfuse 与可观测

- **面试口径**：一轮一 Trace、阶段一 Span、工具一子 Span；JSONL 是本地账本，Langfuse 做跨请求聚合和 score；bad case 回流评测。
- **当前状态**：本地 Trace 为 `VERIFIED_IMPLEMENTED`；真实 Langfuse 与完整评测回流为 `IMPLEMENTED_WITH_LIMITATIONS`。
- **当前设计**：`WorkflowEvent` 按实际执行分支被 `SkillTraceSink` 映射为一个 root 和有序阶段 Span；固定成功案例为 12 个阶段，澄清路径提前终止，重规划路径会增加重复阶段。稳定字段包括 trace/run/session/sequence/stage/status/elapsed/error；JSONL 和可选 exporter 共用递归脱敏；exporter 故障不阻断主链。
- **证据**：`backend/infrastructure/chat/trace.py`、`Financial-MCP-Agent/src/tools/skill_trace.py`、`tests/unit/conversation/test_controlled_trace_adapter.py`、`tests/unit/test_trace_redaction.py`、M7 `TRACE_ARTIFACT_INDEX.json`。
- **缺口**：M7 没向真实 Langfuse 项目发送数据；当前受控 root 下没有完整 generation/tool-call 语义 span、token/cost/score/dataset 回写；没有会话 Markdown 复盘或 PostgreSQL trace sink 的当前主链验收。
- **安全口径**：可以说“本地可回放和脱敏 exporter 边界已验证”；Langfuse 应说“可选出口，尚未完成真实在线闭环”。

### 4.17 离线评测、Compose、Live 与历史指标

- **面试口径**：按 Entity/Route/Rewrite/Planner/Executor/Verifier/Synthesis/Skill/Web Search 分模块评测，并给出 93.8%、88.4%、95%+ 等结果。
- **当前状态**：测试基础设施为 `VERIFIED_IMPLEMENTED`；历史数字为 `HISTORICAL_CLAIM_REQUIRES_RETEST`。
- **当前证据**：默认全量最近结果为 `126 passed, 2 skipped, 5 deselected`；Compose 为 `73 passed, 1 skipped`；真实 LLM + 只读 Tushare + HTTP + 临时 SQLite Live 为 `1 passed`；固定 mainline eval 的终态准确率和阶段覆盖率均为 `1.0`。
- **覆盖范围**：默认测试不访问付费模型或生产服务；Compose 只 Fake 外部 Model/Tool Ports，真实经过 Nginx、FastAPI、Application、Workflow、Repository、PostgreSQL 和生产 Trace Adapter；Live 必须显式开启且无生产写。单元测试会按被测边界使用 Repository/Trace Fake。
- **缺口**：当前 `tests/evals/*/data/smoke.jsonl` 是小型 smoke，不是面试材料中的 150×3、90×3、75×3 黄金集；没有证明 70.2%→88.4%、81.8%→93.8%、工具成功率 >98% 或单轮 <10s。
- **安全口径**：面试时优先给出当前可复现测试矩阵；历史指标只能说明“过去的联调口径，正在按新主链重建黄金集”。

### 4.18 工程流程与 GitHub 闭环

- **面试口径**：AGENTS、Spec Coding、Issue、短分支、测试先行、CI、Review、Squash Merge 和单提交回滚形成闭环。
- **当前状态**：`VERIFIED_IMPLEMENTED`。
- **当前证据**：M0-M7 均有独立 Issue/PR/里程碑报告并已 Squash Merge；CI 包含 Python 静态检查、分层测试、前端 lint/type/build、Compose config 和真实离线 Compose E2E；Live workflow 仅手工触发并绑定受保护 Environment。
- **证据**：`AGENTS.md`、`CONTRIBUTING.md`、`.github/workflows/ci.yml`、`.github/workflows/live-e2e.yml`、`docs/specs/controlled-conversation-mainline/milestones/`。
- **限制**：仓库管理员仍需在 GitHub 配置 Live Environment secrets/审批和可选分支保护；当前没有 CD/生产部署流水线，因为用户没有要求部署，项目也没有生产写授权。
- **安全口径**：可以说“研发与 CI 闭环已跑通”；不要把 CI 说成已部署生产的 CD。

## 5. 两份面试材料中的主要冲突

| 面试材料说法 | 当前主仓库事实 | 处理结论 |
| --- | --- | --- |
| Router 使用 metadata shortlist + LLM rerank | 当前是冻结 metadata + 确定性规则 | 保留两阶段设计，明确 rerank 未实现 |
| 中置信返回前端 `skill_confirm` 卡片 | 当前返回文字澄清，公开协议无显式 Skill 字段 | 卡片与确认恢复延期 |
| Rewrite 与两个模型 Extractor 并发 | 当前三个职责已拆开，但均为确定性规则 | 可以讲分层，不能讲模型并发延迟收益 |
| Planner 根据能力索引自由生成计划 | 当前是 deterministic requirement-to-tool | 当前方案优先可复现和安全，模型 Planner 延期 |
| 自动扫描 vendor 构建 Capability Index | 当前为代码内 Tool Governance Catalog | 不得把静态目录称为完整自动发现 |
| `search_web_news` 进入统一 Executor | 当前生产工具目录无该工具 | 网页检索整段属于设计/历史能力 |
| 默认 6 路并发 | 当前默认 `max_concurrency=4` | 使用当前配置事实，历史性能数字待复测 |
| Redis 三态共享熔断、限流、幂等 | 当前主链未实现 | 作为高可用增强，不包装成当前成果 |
| 前端展示 plan/step/verification/confirm | 当前只支持基础 WS 和上下文更新 | 明确未实现 |
| WebSocket 逐 token 流式 | 当前只发送一段最终回答文本 | 称为兼容流式通道，不称 Provider token streaming |
| Langfuse 已完成 trace-score-dataset 回流 | 当前只验证可选 exporter 边界，未真实发送 | 真实在线回流延期 |
| 历史准确率/合规率/延迟均已冻结 | 当前没有同口径数据集 | 全部标记待复测 |

## 6. 面试时推荐的统一表述

可以用下面这段作为当前版本的主口径：

> 我把对话模式从历史的巨型服务重构成了一条 workflow-style 受控主链。REST 和 WebSocket 共用同一个 Application Use Case；请求依次经过最小上下文、权威实体、两阶段路由、route-specific rewrite、请求级工具权限快照、确定性 Planner、Plan Validator、有界 Executor、Evidence Verifier、规则 Controller、最多一次补证和 accepted-evidence-only Synthesis，最后在同一事务里保存消息。当前默认测试完全离线，Compose 会真实经过 Nginx、FastAPI、工作流和 PostgreSQL；另外有显式保护的真实模型和只读 Tushare Live E2E。为了保证口径真实，我把 LLM rerank、前端确认/计划卡、网页新闻、Redis 共享熔断、逐 token streaming、在线 Langfuse 评测回流和历史指标复测明确留在后续阶段，不把设计方案说成已经上线。

## 7. 后续迁移与增强顺序

受控主链本体已经迁移完成，后续不再重新复制历史 Runtime。建议按可验证价值推进：

1. **重建黄金集并复测指标**：先把 150/90/75 等历史样例整理成版本化数据集，避免继续使用不可复现数字。
2. **丰富公开事件协议和前端状态卡**：先定义版本化事件，再实现确认恢复、plan/step/verification 展示。
3. **模型化理解阶段**：在现有 Typed 合同之后接入可替换 structured-output Provider，逐模块对比确定性基线，不绕过 schema gate。
4. **网页新闻弱证据**：作为统一只读 Tool 接入治理目录、Executor、Verifier 和引用协议，不做 Skill 私有联网脚本。
5. **分布式韧性**：另开规格引入 Redis 幂等、限流和共享熔断；必须带故障注入、恢复和多实例测试。
6. **在线观测与发布治理**：配置真实 Langfuse、score/dataset 回流、分支保护和受保护 Live Environment；CD/生产部署需另行授权。

这些增强都应继续使用当前 `ConversationRunContext`、权限快照、Evidence 和终态合同，不创建第二套 v2 Runtime。
