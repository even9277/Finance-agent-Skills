# SOLUTION_TRADEOFF.md

## 1. Tradeoff Context

当前仓库已经完成受控对话与记忆主线，但 Skills 仍是薄注册表和若干硬编码规则；历史仓库有更完整的 `skills_v2` 和 Web Search，却依赖旧的 dict/Pydantic 合同、旧工具注册表和第二套执行器。核心权衡是：在不破坏现有唯一生产主链的前提下，如何把 5 个投研 SOP Skill 升级为真正由文件资产驱动、可确认、可校验、可追踪和可评测的能力。

## 2. Inputs Reviewed

- REQUIREMENT_SPEC.md: 已审阅 `docs/specs/skills-sop-migration/REQUIREMENT_SPEC.md`。
- CODEBASE_RECON.md: 已审阅当前生产入口、记忆边界、Skills 缺口、历史实现和测试基线。
- CLARIFICATION_QUESTIONS.md: 已收敛核心能力、确认协议、rerank、生命周期、Web News、评测和授权边界。
- User decisions: 完整迁移、功能与两份面试口径对应、复用可复用旧实现、保留当前需求和完整开发流程。
- External sources: OpenAI Skills、Anthropic Agent Skills、OpenClaw、Hermes Agent、OpenAI Structured Outputs、Tavily Search 官方资料。

## 3. User Decisions and Defaults

### 3.1 Confirmed Decisions

- 在唯一主仓库和唯一受控对话主链内实现，不接回历史运行时。
- 5 个 Skill 均形成四层资产和端到端机器合同。
- 复用同一 Validator/Executor/Verifier/Controller/Synthesis，不建立 Skill 私有执行器。
- 纳入显式选择、中置信确认、分阶段 Loader、可插拔 rerank、统一 Web News 弱证据和可复现评测。
- 文件系统是持久真相源，Registry 是运行时派生快照；请求固定版本，刷新失败保留 LKG。
- 不声称复现缺少原始数据的历史指标。

### 3.2 Conservative Defaults Used

- rerank 离线默认确定性，在线模型为可选增强且失败安全回退。
- Web Search 默认关闭，使用已有依赖/标准库的 Tavily HTTP 适配，缺 key 安全降级；不新增生产依赖。
- Lifecycle 只做进程内状态、快照和回滚语义，不增加数据库迁移或管理平台。
- 多任务首版以结构化澄清/拆分提示处理，不在一次请求中并行编排多个 Skill。
- 只新增 Skill 确认卡，不顺带实现 plan/step/verification 前端卡片。

### 3.3 Blocking Decisions

无阻塞 Plan Freezing 的 P0 问题。远端 Issue/分支规范、commit/push/PR 和 live 凭证验收仍是交付授权门，不阻塞本地实现。

## 4. Core Decision Point

选择是在现有生产合同上做最小硬编码补丁、把历史 Skills v2 原样迁回，还是把历史能力按当前类型化主链重写为结构化的 Skills 子系统，并只通过阶段化合同接入现有 Workflow。

## 5. Reference Sources and Repository Evidence

### 5.1 Official Docs

#### Source: OpenAI Skills Catalog / Skill Creator

**Link:** https://github.com/openai/skills/blob/main/skills/.system/skill-creator/SKILL.md
**What was inspected:** Skill 目录结构、frontmatter、`scripts/references/assets` 边界、渐进加载和 validation 流程。
**Relevant practice:** name/description 用于发现，正文命中后加载，references 按需读取；脚本用于需要确定性的重复逻辑且必须测试。
**Reusable part:** Directly reusable。
**Fit for this task:** 支持“路由只看紧凑 metadata、命中后再加载正文/refs”和四层资产，但本项目额外需要金融执行 spec，不能只用通用 `SKILL.md`。

#### Source: Anthropic Agent Skills Overview and Best Practices

**Link:** https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
**What was inspected:** metadata、instructions、resources 的三级 progressive disclosure 以及 description 触发机制。
**Relevant practice:** 只让当前阶段需要的内容进入上下文，避免所有 Skill 正文常驻。
**Reusable part:** Directly reusable。
**Fit for this task:** 直接支持 Retriever/Loader 分离；本项目进一步按 rewrite/planner/synthesis 细分业务阶段。

#### Source: OpenAI Function Calling / Structured Outputs

**Link:** https://help.openai.com/en/articles/8555517-function-calling-updates
**What was inspected:** strict schema 输出与 JSON mode 的边界。
**Relevant practice:** 模型 rerank 输出必须用结构化 schema 校验；仅“可解析 JSON”不足以保证字段合同。
**Reusable part:** Partially reusable。
**Fit for this task:** 在线 rerank 可要求严格结构化返回并继续做本地验证；当前兼容模型未必完整支持 strict，因此必须保留验证和确定性 fallback。

#### Source: Tavily Search API

**Link:** https://docs.tavily.com/documentation/api-reference/endpoint/search
**What was inspected:** Bearer auth、`topic=finance/news`、时间窗、domain include/exclude、结果字段和 400/401/429/限额/5xx 失败。
**Relevant practice:** 显式限制搜索深度、结果数、时间范围和域名；不请求 provider 生成的 answer/raw content；对限流、配额、超时和认证错误分类。
**Reusable part:** Directly reusable at provider boundary。
**Fit for this task:** 标准库 HTTP 足够完成可选 provider，不必引入 SDK；返回仍需本地规范化、去重、注入扫描和弱证据标注。

### 5.2 Open-source Repositories

#### Source: OpenClaw Skills

**Link:** https://github.com/openclaw/openclaw/blob/main/docs/tools/skills.md
**What was inspected:** Skill 与 Tool/Plugin 分离、来源优先级、allowlist、realpath containment、第三方 Skill 不可信和 secret 注入边界。
**Relevant practice:** Skill 可见性与工具权限是两套控制；resolved path 必须留在可信根；Secret 不进入 Prompt/日志。
**Reusable part:** Partially reusable。
**Fit for this task:** 直接支持 reference 路径 containment 和 spec/tool governance join；完整 marketplace/install/sandbox 体系过重，不迁移。

#### Source: Hermes Agent

**Link:** https://github.com/NousResearch/hermes-agent/blob/main/AGENTS.md
**What was inspected:** bundled/optional skills、frontmatter 元数据、配置注入、Skill 引用工具必须真实存在的审查标准。
**Relevant practice:** 重能力默认不启用；metadata 可表达平台/配置要求；SKILL.md 中引用的工具必须由运行时提供。
**Reusable part:** Partially reusable。
**Fit for this task:** 支持 Web News 默认关闭、schema gate 校验“文档声称工具”和治理目录一致；其大规模 catalog/安装流程不适合当前 5 Skill 项目。

#### Source: Historical Finance Skills v2

**Link:** local read-only `D:/FinanceProject/Finance/Financial-MCP-Agent/src/skills_v2/`
**What was inspected:** schema gate、stable version、snapshot/LKG、lifecycle、stage loader、reference index、SOP planner、Web Search 和测试。
**Relevant practice:** 资产字段、原子快照、阶段加载、reference metadata、Web News envelope 可作为迁移基线。
**Reusable part:** Partially reusable。
**Fit for this task:** 行为高度匹配，但类型、依赖和执行路径与当前主线不兼容；必须重写适配，不能复制旧 runner/executor。

### 5.3 Local Project Patterns

| Local pattern | Evidence from CODEBASE_RECON.md | How to reuse |
| --- | --- | --- |
| 类型化跨阶段合同 | `conversation/contracts.py` | 新 spec/snapshot/load/confirm/rerank/evidence 均用冻结 dataclass/enum |
| 请求级不可变快照 | `SkillCatalogSnapshot` | 扩展内容 hash 和视图，保持单轮一致性 |
| 唯一有界执行器 | `conversation/execution.py` | Tushare、Web News 和未来 script 都走同一治理/执行路径 |
| 权限取交集 | `permissions.py` + `tool_governance.py` | spec 只缩权，Registry join 先拒绝未知/越权工具 |
| 明确终态和错误码 | Workflow contracts | 区分确认、输入澄清、注册失败、搜索降级和证据缺失 |
| 记忆权威/派生分离 | memory migration | 文件资产为权威，Registry/LKG 为派生，不让派生反向扩权 |
| 离线 Provider 和 live marker | memory tests/providers | rerank/search 默认 fake/deterministic，真实调用显式门禁 |
| 结构化 Trace | WorkflowEvent | 追加版本/hash/置信带/reference/degrade，不记录正文 |

## 6. Reusable Patterns

### 6.1 Directly Reusable Patterns

- 当前 `ConversationState`、Workflow 阶段、权限快照、Plan Validator、Executor、Evidence Verifier、Controller 和 Synthesizer 框架。
- Skill 文件目录、5 个 canonical name、现有 Tushare 工具治理目录。
- OpenAI/Anthropic 的 metadata-first、body-on-trigger、resources-on-demand 渐进披露。
- 历史 5 Skill 的场景边界、spec 字段、references 和 cases，经过当前工具能力审计后迁移。

### 6.2 Partially Reusable Patterns

- 历史 `skills_v2` 的 schema/snapshot/loader/reference/lifecycle 行为：按当前 dataclass、错误码、logger、Settings 和测试体系重写。
- 历史 Web Search：保留 provider/postprocess/query/source-policy 分层，移除散落 `os.getenv`、缺失 DDGS 依赖和把异常原文拼进用户态结果的做法。
- OpenClaw 的来源优先级、路径 containment 和 allowlist：只采用安全语义，不引入 marketplace/安装器。
- Hermes 的 optional capability：用 feature flag 和 required config 表达，而非复制其 catalog。
- 在线 rerank：复用现有模型 Provider，但只在 topK 上运行并做严格本地验证/回退。

### 6.3 Conceptual References Only

- BM25 + embedding 大规模 Skills 检索。
- 专用路由小模型、自动 bad-case 自学习、生产 A/B。
- 完整 Skill 发布平台、按用户灰度、自动流量回滚。
- Script sandbox 和动态安装第三方 Skill。

### 6.4 Not Suitable for This Iteration

- 原样复制历史 `skill_runner_v2.py`、`skill_executor_node.py` 或旧 backend chat pipeline。
- 让 Skill Loader 直接执行脚本或外部请求。
- 让 reference、LLM rerank 或网页内容改变工具权限。
- 为 5 个小型 reference 集引入向量数据库或新检索依赖。
- 为生命周期增加数据库表和管理后台。

## 7. Solution Options

### 7.1 Option A: Minimal Fix

**What changes:** 补齐 5 个 spec 字段，在现有 Registry 增加几条校验，并继续扩展硬编码 router/rewrite/planner。

**What does not change:** Registry 单文件、无阶段 Loader、无 LKG、无完整确认恢复；历史 Web Search/生命周期不迁移。

**Benefits:** 改动小、短期容易通过现有 smoke tests。

**Costs:** 资产仍不是真相源；相同规则继续散落；难以兑现面试口径。

**Risks:** spec/代码漂移、错误 Skill 扩权、版本不可追溯、未来每加 Skill 都改核心代码。

**Testing burden:** 中等；虽然代码少，但要覆盖大量硬编码组合。

**Rollback difficulty:** 低。

**Engineering impact:**

- Architecture/module ownership: 继续混合职责。
- Documentation/types: 少量扩展，难形成完整合同。
- Configuration/secrets/prompts: 缺系统化治理。
- Terminal/logging/tracing/artifacts: 只能补字段，不能完整关联版本。
- Errors/retry/state: 无明确刷新/LKG/确认状态。

**When to choose it:** 只要求修一个 Skill 误触发或展示 Demo 时；不满足本次完整迁移。

### 7.2 Option B: Structured Improvement

**What changes:** 在现有 `src/skills` 内建立类型化 schema gate、version、reference index、loader、snapshot/lifecycle 管理；升级 5 个资产；让 discovery/rewrite/planner/verifier/synthesis 分阶段消费同一 spec；增量加入确认协议、可插拔 rerank、统一 Web News 和评测/trace。

**What does not change:** 不更换 API 框架、数据库、记忆系统、模型抽象、现有 Validator/Executor/Controller 主干；不引入第二运行时或新生产依赖。

**Benefits:** 满足完整口径；复用当前可靠主链；资产、权限、证据、输出和 trace 闭合；后续加 Skill 主要增资产而非改核心映射。

**Costs:** 中高量级的跨模块合同和测试工作；必须谨慎做兼容迁移。

**Risks:** 跨阶段字段扩展、Registry 首启/刷新语义、确认协议和 Web News 会增加边界数量。

**Testing burden:** 高，但可按模块和里程碑分层验证，默认离线。

**Rollback difficulty:** 中低；保持旧主链结构，可按 feature flag/模块回滚，文件资产和 Registry 可恢复 LKG。

**Engineering impact:**

- Architecture/module ownership: Skills 子系统负责资产治理；Conversation 负责阶段编排；Infrastructure 负责模型/搜索 provider；Frontend 只负责协议展示。
- Documentation/types: 新公共类/合同必须类型化并写中文 Google-style docstring；同步更新技术说明和实现矩阵。
- Configuration/secrets/prompts: Settings 集中管理 rerank/search/loader 预算和 key；Prompt 版本化。
- Terminal/logging/tracing/artifacts: 新增低基数 Skill/版本/hash/置信/加载/降级字段和 eval artifact。
- Errors/retry/state: schema fail closed、刷新 LKG、rerank fallback、search bounded retry/degrade、确认可恢复。

**When to choose it:** 当前个人/面试工程项目需要真实、可解释、可测试的完整 Skills 体系；推荐。

### 7.3 Option C: Long-term Architecture Direction

**What changes:** 独立 Skills 服务或插件平台，持久化生命周期，文件 watcher，BM25+embedding，多租户灰度，管理 UI，脚本 sandbox，专用路由模型，完整在线实验。

**What does not change:** 理论上仍可保留对话执行内核，但接口和部署边界需重做。

**Benefits:** 适合几十/上百 Skill 和多团队发布治理。

**Costs:** 极高，新增服务、存储、部署、依赖和运维面。

**Risks:** 远超当前 5 Skill 规模；分布式一致性和回滚复杂；容易包装过度。

**Testing burden:** 极高，需集成、性能、灰度、灾备和安全测试。

**Rollback difficulty:** 高。

**Engineering impact:**

- Architecture/module ownership: 新服务/平台边界。
- Documentation/types: 新公共 API 和数据模型。
- Configuration/secrets/prompts: 多环境配置和 secret manager。
- Terminal/logging/tracing/artifacts: 跨服务追踪、发布和流量指标。
- Errors/retry/state: 分布式状态、幂等、回滚和灾备。

**When to choose it:** Skills 数量和团队规模真实增长后；本次 Deferred。

### 7.4 Option D: Observation-first Option

**What changes:** 只补 trace、schema smoke、评测数据和实现矩阵，不改变运行行为。

**What does not change:** 所有核心缺口仍在。

**Benefits:** 风险最低，先建立真实基线。

**Costs:** 不能交付用户要求的迁移功能。

**Risks:** 文档与代码继续脱节。

**Testing burden:** 低到中。

**Rollback difficulty:** 低。

**Engineering impact:** 主要是测试、trace 和文档，不解决架构缺口。

**When to choose it:** 需求/生产故障证据不足时；本次已完成足够勘察，不作为主方案，但把其评测纪律合并进 Option B。

## 8. Decision Matrix

| Dimension | Option A Minimal Fix | Option B Structured Improvement | Option C Long-term Architecture | Option D Observation-first |
| --- | --- | --- | --- | --- |
| Scope | 小 | 中高 | 极大 | 小 |
| Development Cost | 低 | 中高 | 极高 | 低 |
| Risk | 中：漂移延续 | 中：可分层控制 | 高 | 低 |
| Reusability | 低 | 高 | 很高但过度 | 中 |
| Fit to Current Requirement | 低 | 最高 | 中：超范围 | 低 |
| Local Pattern Fit | 中 | 最高 | 低 | 高 |
| Test Burden | 中 | 高 | 极高 | 低中 |
| Rollback Difficulty | 低 | 中低 | 高 | 低 |
| Long-term Maintainability | 低 | 高 | 高但成本失衡 | 中 |
| Engineering-standard fit | 低中 | 高 | 中 | 中 |
| Recommendation | 不选 | **选择** | Deferred | 作为 B 的评测策略 |

## 9. Recommended Solution

Selected option: **Option B：在现有受控主链内做结构化 Skills 改进**。

Why selected:

- 唯一能同时满足用户完整口径、当前主链兼容、可测试性和个人项目规模。
- 当前 Workflow/Executor/Verifier 已足够成熟，问题集中在 Skill 资产到各阶段的合同传递，不需要重建 Agent 框架。
- 历史实现提供了行为证据，可以降低设计不确定性，但通过适配而不是整套复制来控制技术债。

Why not the other options:

- Option A 无法让 spec 成为真相源，也无法兑现 Loader/LKG/确认/Web News/Trace 口径。
- Option C 把 5 Skill 项目扩大成发布平台，超出实际证据和需求。
- Option D 不能交付功能，但它的基线、数据和 trace 方法应成为 Option B 的首尾门禁。

Local patterns reused: 类型化合同、请求级不可变快照、唯一执行器、权限交集、明确终态、记忆权威边界、离线 provider、结构化 Trace。

External practices reused: OpenAI/Anthropic 渐进披露，OpenClaw path containment/Skill-tool 分权，Hermes optional capability 和工具存在性校验，OpenAI 结构化模型输出，Tavily 受限 Search API。

Remaining risks:

- 对话合同扩展影响面大；必须逐里程碑保持现有测试绿。
- 历史资产含当前不存在的工具/字段；必须先 schema join 后激活。
- Web News 是弱证据和外部调用；默认关闭、严格预算、内容不可信。
- 当前没有历史 75×3 原始证据；不能把新小数据集结果等同历史指标。

What must be verified later:

- 5 Skill 的 schema/permission/evidence/output 闭合。
- 中置信确认和显式选择从前端到 Workflow 的可恢复性。
- spec 驱动计划与原 tushare-data 计划使用同一 Executor。
- Registry 原子快照/LKG、路径 containment 和并发读取。
- rerank/search 无配置或失败时不会破坏离线启动和主链。
- 全量 Python/前端/Compose 回归与真实 eval artifact。

## 10. Unified Technical Direction

- 在 `Financial-MCP-Agent/src/skills/` 内按当前编码标准建立类型化 `schema/version/reference/loader/snapshot/lifecycle/registry` 边界，文件资产为唯一持久真相源，Registry 只发布通过 schema gate 和工具/evidence join 的不可变快照。
- 扩展而不替换 `conversation/contracts.py`；让 `skill_discovery/routing/rewriting/planning/verification/synthesis/workflow` 分阶段消费同一冻结 Skill 上下文，并始终复用现有 permission、validator、executor、controller。
- 在 API/WS/frontend 只增量加入 `explicit_skill` 和 `skill_confirm` 闭环；旧请求/事件兼容，其他控制卡延期。
- 在线 rerank 和 Web News 均由可替换 adapter 提供，默认离线确定性/disabled；配置和 secret 进入 typed Settings，Prompt 版本化，失败安全回退。
- 迁移并修订历史 5 Skill assets/references/cases；`market-move-explain` 的 Web News 只能作为补充弱证据，不能替代市场数据或回流 Planner。
- 新测试覆盖 schema、LKG、Loader 分层、路由正反例、确认、input contract、plan/evidence/degrade、trace、Web Search 安全和 5 Skill E2E；新指标只由仓库 runner/artifact 生成。
- 禁止历史仓库 runtime import、第二执行器、数据库化生命周期、新生产依赖、完整灰度平台和伪造历史指标。

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| 合同扩展造成广泛回归 | 增量可选字段、集中构造器、contract tests、每里程碑全量相关回归 |
| Registry 错误导致服务不可用 | 首启 fail closed；刷新失败保留 LKG；状态和原因可观测 |
| Skill spec 扩权 | schema gate 与工具治理目录/evidence enum 强制 join；unknown 即拒绝 |
| Reference 路径逃逸或内容污染 | realpath containment、stage hard filter、metadata/hash、无私有/实时内容 |
| LLM rerank 不稳定 | topK 有限输入、typed output、本地阈值、确定性 fallback、三次评测 |
| 确认恢复版本漂移 | confirmation token 绑定 user/session/skill/version/snapshot hash/TTL，恢复时重验 |
| Web Search 成本、限流、注入和强因果 | 默认关闭、配额/超时、最小 query、去重/扫描、弱证据、claim-level 降级 |
| 历史指标不可复现 | 保留历史标签；新基线记录 dataset/runner/snapshot/model/run count |
| 破坏记忆边界 | 记忆只进 context/synthesis，权限和证据只由当前请求+Skill+治理目录决定 |

## 12. Verification Direction

### 12.1 Engineering Contract for Plan Freezing

- Architecture/module ownership: Skills 管资产治理和阶段加载；Conversation 管业务编排；Infrastructure 管外部 provider；API/UI 管协议适配；Memory 不变。
- Interfaces/docstrings/types: 公共和跨模块接口使用明确 dataclass/enum/Protocol；新增/修改 Python 同步中文 Google-style docstring、类型和意图注释。
- Configuration/secrets/constants/prompts: Settings 单点校验；`.env.example` 仅安全占位；阈值/枚举/业务常量在代码集中；模型 Prompt 版本化；不得记录 key。
- Terminal/logging/tracing/artifacts: 终端简洁；logger 参数化；Trace 记录稳定版本/hash/状态；长内容只进默认关闭的受控 artifact；eval 产物记录路径和版本。
- Validation/errors/retry/state: schema fail closed、刷新 LKG、请求快照固定、rerank/search 有界重试/超时、confirmation 防重放、Web 内容不可信、所有降级有终态/错误码。
- Tests/evaluation/delivery evidence: unit→contract→integration→e2e→eval→full regression→frontend→Compose；默认无付费/生产调用；最终 diff review 和文档矩阵更新。

## 13. Deferred Work

- BM25/embedding reference retrieval、专用路由小模型。
- 多 Skill 并行执行和复杂子任务 DAG。
- Script sandbox 与动态第三方 Skill 安装。
- 数据库化生命周期、管理 API、shadow 流量、自动回滚和发布看板。
- 企业级 Web Search 平台、完整域名治理、生产 A/B。
- `plan_preview/step_status/verification_summary` 前端卡片。
- 在缺少原始数据时复刻 75×3 历史数字。

## 14. Handoff to Plan Freezing

Next step should use the Plan Freezing Skill and produce `PLAN.md`。

The plan should:

- follow selected option: Option B，按依赖顺序拆成可独立验收的小里程碑。
- allow modules/files: 本专题 docs、`src/skills`、指定 `src/conversation`、chat infrastructure/factory/config、chat schema/router、最小 frontend chat 组件和相关 tests/evals/docs。
- forbid modules/files: 历史 `Finance` 写入、旧 executor/runtime 复活、记忆持久化、鉴权、报告/持仓、数据库 migration、无关 UI。
- include required tests: schema/snapshot/loader、route/confirm/rewrite、planner/permission/evidence/degrade、web search、trace、API/WS/frontend、5 Skill E2E/eval、全量回归/Compose。
- include required logs/metrics: Skill/version/hash/route source/confidence band/loaded refs/degrade/search decision，以及 dataset/runner/snapshot/model/run-count artifact。
- include rollback strategy: 每个里程碑可反向移除；旧主链结构保留；Registry LKG；新增在线能力默认关闭。
- preserve these constraints: 单执行器、spec 只缩权、网页不回流 Planner、记忆不扩权、无凭证离线可用、无 commit/push。
- keep these external references in mind: OpenAI/Anthropic progressive disclosure、OpenClaw containment/allowlist、Hermes optional capability、OpenAI structured output、Tavily Search API。
