# Skills 集成技术说明

> 状态：Milestone 9 最终实现事实（2026-08-30）
> 当前运行时：`Finance-agent-Skills`
> 历史 `Finance` 仓库：只读迁移参考，不是运行时依赖

## 1. 结论

当前项目已经把五类金融 Skills 迁入唯一受控对话主链。生产请求不再经过旧的
`backend/services/chat_service.py`、`skill_router_node.py` 或
`skill_executor_node.py`；这些历史结构也没有以 Adapter 形式保留为第二执行路径。

真实入口与主链是：

```text
Vue Chat UI
  → REST /api/chat/message 或 WebSocket /api/chat/stream
  → backend.routers.chat
  → ControlledChatUseCase
  → ControlledConversationWorkflow
  → Context → Entity → Route → Rewrite → Permission
  → Planner → Validator → 唯一 ControlledExecutor
  → EvidenceVerifier → Controller → 最多一次 Replan
  → accepted-evidence-only Synthesis
  → Repository 保存结果并提交/回滚事务
```

Skills 不是任意 Python 插件，也不能自行绕过工具治理。它们是四层版本化资产：

```text
SKILL.md                 人读的业务边界和操作说明
skill_spec.yaml          机器真相源：输入、工具、步骤、证据、输出、降级、并发
references/*.md          Rewrite / Planner / Synthesis 按阶段加载的参考资料
tests/ + 仓库 tests      资产、路由、规划、证据、交互和回归合同
```

## 2. 已落地的五个 Skills

| Skill | 适用场景 | 主要输入门控 | 主要证据 |
| --- | --- | --- | --- |
| `stock-first-pass` | 单股基本面首轮研判、是否继续跟踪 | 恰好一只股票 | 基础信息、行情、财务指标和三表 |
| `fund-compare` | 两只及以上基金/ETF 比较 | 至少两个兼容基金主体和比较意图 | 基金/ETF 基础信息、净值、场内行情、份额 |
| `etf-screen` | 按主题、风险或配置要求筛 ETF | 明确筛选意图/范围 | 基金基础信息及可用的净值、行情、份额 |
| `sector-hotspot-brief` | 板块强弱、热点和龙头简报 | 明确板块/行业/主题主体 | 板块快照、成分股、指数上下文 |
| `market-move-explain` | 股票、ETF、指数或板块涨跌解释 | 恰好一个异动主体 | 市场强证据；Web News 只作可选弱证据 |

资产目录为 `Financial-MCP-Agent/src/skills/<skill-name>/`。

## 3. 发现、注册与发布

### 3.1 Registry 扫描与 Schema Gate

`Financial-MCP-Agent/src/skills/skill_registry.py` 扫描 workspace Skills 和受控 vendor
目录。候选资产必须先经过 `schema_gate.py`，校验内容包括：

- `SKILL.md` frontmatter 和必需章节；
- `skill_spec.yaml` 名称、版本和合同字段；
- `depends_on_tools`、`allowed_tools` 与 tool plan 的闭合关系；
- 工具和 evidence type 是否属于治理目录；
- input/output/degrade/concurrency 合同；
- reference 路径包含关系和 section map。

未知工具、未知证据、路径逃逸、资产名称漂移或半成品快照都会被拒绝，不能进入
active Registry。

### 3.2 生命周期、Snapshot 与 LKG

`lifecycle.py` 和 `snapshot.py` 管理候选、active 与 last-known-good（LKG）状态。
刷新采用“先完整构造候选、再原子发布”的方式；失败时丢弃 pending，active/LKG
保持不变。`backend/application/chat/factory.py` 通过进程级 `get_skill_registry()`
复用 Registry，因此 LKG 可跨请求保留。

每次请求仍会固定一个不可变 `RegistrySnapshot`，并从同一快照构造 Catalog 与
Loader。即使进程随后刷新资产，本轮 route、rewrite、plan 和 synthesis 也不会混用
两个版本。

### 3.3 分阶段视图和 Reference Index

Registry 不把完整 Skill 正文一次性塞进模型或每个模块，而是投影为最小视图：

- routing view：名称、版本、适用/不适用边界、正反例、主体类型；
- rewrite view：input contract；
- planner view：允许工具、步骤、证据和并发合同；
- synthesis view：输出骨架、降级策略和有限 references。

`reference_index.py` 先做 Skill 和阶段硬过滤，再做确定性词法排序，并受 token/字符
预算和路径 containment 约束。当前没有宣称已实现 embedding/BM25 混合召回或脚本
沙箱。

## 4. 澄清与两阶段路由

### 4.1 Stage 1：Skills 优先

`SkillDiscovery` 只消费冻结 routing view。默认使用确定性规则和资产正反例打分，返回
top-K typed candidates；可选 OpenAI-compatible rerank 只能重排这些候选，默认关闭，
失败会回退确定性结果，不能新增候选或看到完整 Skill/会话历史。

集中阈值把结果分为：

- high confidence：自动选择具体 Skill；
- mid confidence：返回 `SkillConfirmation`，不执行工具；
- miss：进入 Stage 2。

缺主体也可以先命中 Skill。例如“这只股票基本面”“比较华安黄金 ETF”“最近什么板块
强”会分别进入对应 input contract，再给出股票、第二只基金或板块主体的专属澄清，
而不是统一报“缺实体”。

### 4.2 Stage 2：通用当前事实或 fallback

Stage 1 未命中后：

- 必须依赖当前金融事实的问题进入 `tushare-data`；
- 静态概念或普通聊天进入 `fallback`。

当前受控主链的 fallback 是兼容终态 `UNSUPPORTED`，不会因为缺少金融实体误报
`NEEDS_CLARIFICATION`，也不会执行金融工具。它不是另一条隐藏的普通聊天执行器。

### 4.3 显式选择与公开确认闭环

REST/WS 请求支持可选 `explicit_skill`。显式选择只跳过自动选择，不能跳过：

- Skill 是否存在于本轮快照；
- input contract；
- 工具权限交集；
- plan validation；
- evidence 和输出边界。

中置信结果通过 typed `skill_confirm` 控制帧和前端确认卡返回候选、版本与理由。确认后
在同一 session 重提 `explicit_skill`；取消不发送执行请求。旧客户端不提供该字段仍可
兼容工作。

## 5. Rewrite、规划与唯一执行器

`RouteAwareRewriter` 返回互斥的 `SopRewriteResult`、`TushareRewriteResult` 或
`FallbackRewriteResult`。它负责有效问题、主体、时间、约束、回答偏好和缺槽位检查，
不重新选择 route，也不直接选择工具。

同一消息包含两个独立 SOP 时，当前行为是要求拆分消息，不把两个任务交给一个 Skill
强吞；当前没有宣称已实现任意多任务自动拆解为 `task_items`。

Skills 执行路径如下：

1. Loader 从同一 RegistrySnapshot 读取 planner view；
2. `ControlledPermissionResolver` 计算 `skill allowed_tools ∩ ToolGovernanceCatalog`；
3. `ControlledPlanner` 将 spec steps 变成 typed `ToolPlan`；
4. `PlanValidator` 校验权限、Schema、依赖、重复动作、主体和预算；
5. 唯一 `ControlledExecutor` 只接收 `ValidatedToolPlan`；
6. Executor 按依赖分层、有界并发、fingerprint 去重和有限重试；
7. `EvidenceVerifier` 验收证据；
8. `RuleController` 决定 stop/replan/degrade，replan 最多一次且不扩权；
9. Synthesis 只接收 accepted evidence 和对应 Skill 的 synthesis view。

`tushare-data` 与 `financial-sop` 共用 Planner/Validator/Executor/Verifier/Controller/
Synthesis 组件，不存在 Skill 私有 Executor。

## 6. Evidence、降级与输出

工具返回成功不等于证据可用。`EvidenceVerifier` 会检查：

- tool/step/evidence contract 是否一致；
- 主体是否一致；
- 时间是否未来或过期；
- facts 和来源是否为空；
- 关键字段质量；
- 同主体、同日期、同字段是否冲突；
- must-have、any-of、per-symbol 和最少不同主体数。

结果分为 accepted/rejected/missing，并给出：

- `ANALYTICAL`：强证据完整且无硬门控失败；
- `DESCRIPTIVE`：存在可用证据但不足以支持完整分析；
- `REFUSE`：没有可用证据。

每个 Skill 的 `degrade_policy` 决定 primary、partial 和 graceful-decline 的收口顺序；
输出 section order 与 style variant 来自 spec，不由工具结果临时扩张。

## 7. Web News 弱证据

`search_web_news` 已进入统一只读工具治理、Validator、唯一 Executor 和 Verifier，当前仅
`market-move-explain` 资产声明可使用。生产 Provider 使用 Tavily-compatible HTTP，
默认 `ENABLE_WEB_NEWS=false`；缺 key、超时、限额、HTTP 错误或注入样本都会安全失败。

安全边界包括：

- query 只保留公开主体、事件词和时间窗口；
- timeout、单次结果数、freshness、分钟限流和日配额有界；
- include/exclude domains 经过 typed Settings 校验；
- 标题、URL、摘要和发布时间规范化并去重；
- 网页内容是不可信输入，不能回流 Planner 或触发新工具；
- Web News 单独存在时不能提升为分析结论；
- 行情等强证据完整时，新闻只能形成保守“可能驱动”，不能写成确定因果。

## 8. 记忆、事务和公开入口

`ControlledChatUseCase` 在工作流前读取会话尾窗、running summary、working state 和经
治理的 memory context；当前轮显式消息始终优先。工作流返回结构化 working-state
更新，Repository 在同一请求事务中保存用户/助手消息并 commit，异常 rollback。

Skills 不拥有独立记忆库，也不会直接写数据库。记忆检索、缓存、命令和后台 worker
仍由 Application/Memory 边界管理。

## 9. Trace 与可复现评测

本地 Trace 以 root + ordered stage spans 记录实际分支。关键低基数字段包括：

- `trace_id/run_id/session_id/stage/status/duration_ms/error_code`；
- route family/source/confidence band、候选名；
- selected Skill/version/spec hash/Registry snapshot hash；
- permission hash、plan/step/replan/degrade/terminal status；
- planner/synthesis Reference 的独立 path/hash；
- Web trigger、query SHA-256、source/accepted/rejected counts；
- accepted/rejected/missing 数量、claim level 和 evidence score。

Trace 不保存原始 Web query、reference 正文、网页正文、secret 或默认模型完整回答。
Langfuse 是可选 exporter；当前没有声称已完成真实线上 score→dataset 回流。

`tests/evals/skills_sop` 用真实 Workflow/Registry/Loader 和确定性 Fake Ports 执行 15
条 smoke case，每条重复 3 次。2026-08-30 M9 基线：

| 指标 | 实测 |
| --- | ---: |
| Skill activation accuracy | 0.933333 |
| Activation precision | 0.909091 |
| Activation recall | 1.0 |
| Plan compliance | 1.0 |
| Evidence coverage | 1.0 |
| Clarification accuracy | 1.0 |
| Claim-level accuracy | 1.0 |
| Overclaim rate | 0.0 |
| Deterministic stability | 1.0 |

唯一 activation mismatch 是多任务请求：Router 先给出 provisional `fund-compare`，
Rewrite 随后正确识别两个独立 SOP 并在 0 tool call 时要求拆分；评测仍按 gold
`skill_id=null` 记为 activation mismatch，没有为追求 100% 改指标口径。

历史文档中的 75×3、81.8%→93.8% 等数字因缺少原始数据集和 artifact，状态仍是
`not_reproduced`，不能与当前 15×3 基线混写。

## 10. 配置边界

配置通过 `backend/config.py` 的 typed Settings 集中加载。Skills 相关关键环境变量：

- `SKILL_RERANK_PROVIDER=disabled|openai`、`SKILL_RERANK_MODEL`、
  `SKILL_RERANK_TOP_K`、`SKILL_RERANK_TIMEOUT_SEC`；
- `ENABLE_WEB_NEWS`、`TAVILY_API_KEY`、`WEB_NEWS_TIMEOUT_SEC`、
  `WEB_NEWS_MAX_RESULTS`、`WEB_NEWS_FRESHNESS_DAYS`、域名和配额设置；
- `ENABLE_TRACE`、`CHAT_TRACE_JSONL_PATH`、`ENABLE_LANGFUSE` 及 Langfuse 设置。

真实密钥只允许放环境变量或 secret manager；日志、Trace、测试 fixture 和报告不得保存
可用凭证。

## 11. 排查顺序

1. Registry 日志：看 `skill_registry.refresh` 的 status、snapshot hash、active/rejected；
2. `controlled_chat.entity_resolution`：看候选数、置信度和 error code；
3. `controlled_chat.route`：看 family、source、band、shortlist、selected Skill/version；
4. `controlled_chat.rewrite`：看是否因槽位、主体基数或多任务澄清；
5. `controlled_chat.permission/plan/validate`：看 spec/permission hash 和问题数；
6. `controlled_chat.execute`：看 tool/batch/failure/dedup/replan 数量；
7. `controlled_chat.verify/controller`：看 missing、claim、degrade 和终止原因；
8. `controlled_chat.synthesis/termination`：确认只使用 accepted evidence 并形成唯一终态。

## 12. 验证命令与结果

最终 M9 已执行：

- CI exact Ruff：通过；
- CI exact Pyright：0 errors / 0 warnings；
- backend：11 passed；Agent：33 passed、4 deselected；
- offline eval：29 passed；memory eval：13 passed；
- root regression：348 passed、6 skipped、6 deselected、3 xfailed；
- frontend lint/type/build/Vitest：5 files、9 tests passed；
- 生产 backend image 构建与镜像内迁移/记忆依赖导入：通过；
- Compose config、Redis rollback override：通过；
- 隔离 PostgreSQL + Redis + backend + frontend Compose E2E：242 passed、1 skipped、
  40 deselected、3 xfailed；真实 HTTP 健康检查和聊天/记忆接口通过。

默认测试未调用付费模型、真实 Tavily、真实行情或生产服务。

## 13. 当前限制与正确面试口径

已实现并验证：五 Skill 四层资产、Schema Gate、进程级 Registry/LKG、请求快照、
Reference 分阶段 Loader、确定性发现、可选 rerank、显式选择、中置信确认卡、专属槽位
澄清、spec-driven plan、唯一 Executor、Evidence/Controller/Degrade/Synthesis、Web News
弱证据、版本 Trace 和可复现评测。

仍属后续增强：完整证券主数据服务、默认 LLM rerank、任意多任务自动拆解、
embedding/BM25 reference 混排、Skill scripts 沙箱、shadow/canary 发布平台、Redis 共享
熔断/限流/幂等、Provider 逐 token streaming、plan/step/verification 前端卡、真实
Langfuse score 回流、历史黄金集复测和生产部署。

一句话表述：

> 我把五类投研 Skills 迁成了版本化四层资产，通过 Schema Gate 和进程级 LKG Registry
> 发布；请求在唯一受控主链里完成发现、确认、按阶段加载、spec 驱动规划、权限校验、
> 有界执行、证据验收、降级和 accepted-only 总结，并用 15×3 可复现评测与完整
> Compose E2E 验证。历史效果数字没有原始 artifact，所以只保留为待复测口径。
