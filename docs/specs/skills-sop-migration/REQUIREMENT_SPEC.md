# REQUIREMENT_SPEC.md

## 1. Task Type

Primary type: New Feature

Secondary types: Refactor, Test / Evaluation Improvement, Engineering Governance, Project Packaging / Interview Demo Improvement

Classification rationale: 本任务需要把旧仓库已有的金融 Skills 能力迁移并补全到当前对话 Agent，同时让实现、测试、trace 与两份面试口径文档可逐项核对；它既是能力新增，也是跨版本迁移、治理和评测闭环建设。

## 2. Requirement Restatement

在不破坏当前记忆模块、通用 `tushare-data` 链路和既有对话能力的前提下，将金融投研 SOP Skills 集成迁移并完善到当前仓库。系统最终应支持 5 个范围固定的 Skill：`stock-first-pass`、`fund-compare`、`etf-screen`、`sector-hotspot-brief`、`market-move-explain`。

每个 Skill 必须是可发现、可注册、可澄清、可路由、可按阶段加载、可生成受约束计划、可通过统一执行内核执行、可按证据契约验收与降级、可追踪、可离线评测的能力资产，而不是一段孤立 Prompt 或一套私有执行循环。实现结果必须和以下业务口径一致：

- Skill 资产由模型可读的业务手册、机器可执行契约、稳定方法论参考和回归样例共同组成；运行时冲突以机器契约为准。
- 文件系统是持久化真源，Registry 生成并发布运行时快照。
- `financial-sop` 与 `tushare-data` 的差异主要位于 planner 之前；二者复用同一套 validator、executor、verifier/controller 和 synthesis 运行内核。
- 用户显式选择优先但不能绕过实体、必填槽位、权限和证据校验；自动触发遵循候选召回、受控选择、必要确认和安全回退。
- route、rewrite、planner、synthesis 仅加载各自职责所需的最小 Skill 上下文。
- 证据强度决定回答强度；实时金融事实不得由模型记忆或静态 reference 代替，网页新闻只能作为受治理的弱线索。
- 当前项目定位是个人全栈可运行 Demo、离线评测与工程文档，不包装为生产 SLA、线上大盘、持牌投顾或投资收益承诺。

## 3. Problem Source

来源：产品需求与面试/项目包装一致性要求。

用户提供了两份现有业务口径文档，明确描述了目标功能、模块边界、离线评测口径和不应夸大的范围。当前代码是否已经部分实现、旧仓库哪些模块可直接复用、当前记忆/路由/执行内核的真实接口与差距，尚待只读代码勘察确认。

## 4. Current Behavior

已知事实：

- 实际 Git 仓库位于 `D:\FinanceProject\Finance-agent-Skills`，需求定义开始前工作区干净，原分支为 `main`。
- 已从 `main` 新建并切换到 `feature/skills-sop-migration`；`main` 保留为历史和回滚基线，没有删除。
- 两份文档声明当前/目标系统已有对话产品底座、权威实体解析、三类路由、route-specific rewrite、统一 Plan-and-Execute 工具内核、记忆与可观测体系，并描述了待对齐的 Skills 体系。
- 旧版 Finance 或其他本地仓库中可能已有可复用的 Skill 代码，但具体位置、完整度、测试状态和兼容性尚未核验。

Not provided / 待勘察：

- 当前仓库实际入口、包结构、配置、数据库与前后端调用链。
- 当前记忆模块、实体解析、路由、rewrite、planner、validator、executor、verifier/controller、synthesis、trace 的实现完成度与接口。
- 当前是否已有 Skill Registry、Retriever、Loader、spec schema、5 个 Skill 资产、前端 `skill_confirm` 卡片和评测数据。
- 旧实现的准确路径、可复用范围、依赖和测试结果。
- 文档中冻结指标能否由仓库内现有数据集和评测脚本复现。

## 5. Expected Behavior

1. 系统启动或显式刷新 Skills 时，从受控根目录发现 Skill 资产，解析并校验元数据与机器契约，形成带版本/hash 的一致性 Registry 快照；不合法 Skill 不进入自动候选池，刷新失败保留上一份可用快照。
2. Registry 至少能表达 Skill ID、描述、版本、别名、支持实体类型、执行模式、状态、工具白名单、reference 索引、spec/reference hash 和 registry version，并被路由、加载、计划、trace 及需要的 UI 共同消费。
3. 用户显式选择 Skill 时优先采用该选择，但实体类型、主体数量、必填槽位或执行权限不满足时必须澄清或安全回退，不能强行执行。
4. 未显式选择时，系统使用规则与 compact metadata 形成小候选集，再进行结构化选择；高置信自动进入，中等置信返回确认状态，低置信回退 `tushare-data` 或 `fallback`。具体阈值应由现状、测试与后续方案阶段确定，不在本阶段写死。
5. 相邻意图必须有清晰边界：概念解释“黄金 ETF 是什么”不能误触发 `etf-screen`；“贵州茅台为什么跌”应优先考虑异动解释而非普通首轮研判；真实多任务应拆分而非由单一 Skill 吞并。
6. `financial-sop` rewrite 仅对齐已选 Skill 的输入契约、实体、约束和缺失槽位。阻塞型缺失返回结构化澄清；仅有安全默认值时可继续并记录默认口径；明显 route/entity 冲突返回结构化失败并由编排层有界处理。
7. Loader 对 rewrite、planner、synthesis 分阶段返回结构化上下文。reference 检索先按 `skill_id` 与阶段硬过滤，再做小规模、可解释的词面匹配；reference 不得增加工具权限、放宽证据要求或保存实时行情、新闻正文和用户私有信息。
8. Skill-guided planner 基于已解析实体、rewrite 契约和 Skill spec 生成结构化计划；计划必须在执行前校验工具存在性、输入 schema、白名单、依赖 DAG、重复步骤和 required evidence 覆盖。
9. Skills 不建立私有 executor。实际可用工具是 Skill 白名单、当前发现候选、可执行注册表和健康状态的交集；工具执行复用当前统一的超时、有限重试、并发/限流、去重、预算、失败与 trace 语义。
10. 统一 verifier 将工具输出归一到稳定 evidence type，按主体、时间、字段质量和 required evidence 验收。controller 按缺失维度与 degrade policy 决定澄清、有限 retry/replan、降级或停止；synthesis 不得绕过裁决。
11. `search_web_news` 如在现有范围内可用，必须作为统一工具受控执行；搜索 query 只包含最小化的公开实体、事件词和时间窗口，网页内容作为不可信弱证据，不得回流控制 planner 或触发新工具。若当前仓库不存在该能力，其本次纳入范围由勘察和方案权衡确认。
12. synthesis 只接收经过整理和验收的上下文包，按 Skill 输出骨架覆盖必要维度，同时遵守 `allowed_claim_level`、缺失证据和金融安全边界；不得给确定性买卖建议或把弱新闻写成确定因果。
13. 每轮 Skills 请求可通过稳定 trace 关联候选、选择/确认、Skill/Registry/spec/reference 版本、阶段化加载、rewrite、计划、工具调用、证据裁决、缺失维度、降级、结论等级、耗时和错误码；外部观测失败不阻塞主链路。
14. 测试覆盖 5 个 Skill 的资产校验、发现/注册、触发边界、显式选择、澄清、阶段化加载、计划约束、工具越权拦截、证据不足降级、输出越界和回滚/last-known-good 语义。默认测试不得调用付费模型或生产服务。
15. 如仓库内确有已冻结的 150 条路由集、75 条 Skills 专项集和固定三次运行机制，应能生成可追溯评测报告并核对文档指标；若不存在，不得伪造数据，应建立可运行的小规模真实基线并明确与文档历史口径的差异。

## 6. Scope

### 6.1 In Scope

- 阅读并记录当前仓库的记忆模块、上下文装配、实体解析、路由、rewrite、工具发现与注册、planner、validator、executor、verifier/controller、synthesis、配置、trace、测试和评测现状。
- 定位并审计旧版 Finance/本地仓库的 Skill 资产与实现，逐项判断直接复用、适配复用、重写或不迁移。
- 对照两份口径文档建立“面试声明 → 代码模块 → 测试/trace 证据”的映射。
- 迁移或补全 5 个固定金融 SOP Skills 及其必要资产。
- 完成 Skill 发现、注册、生命周期/快照、检索、显式选择、确认/回退、澄清、阶段化加载与 reference 检索。
- 接入现有统一 planner/validator/executor/verifier/controller/synthesis，而不是复制执行内核。
- 补齐机器契约、类型、输入/输出校验、失败语义、配置、日志/trace、敏感信息处理和必要文档。
- 添加与风险相称的单元、集成、端到端替身测试、离线评测/fixture 和手工验收用例。
- 审查最终 diff、执行仓库规定的格式化、lint、类型检查、聚焦测试和更广回归，并记录无法运行的检查和残余风险。

### 6.2 Out of Scope

- 不删除 `main` 或其他历史分支，不覆盖用户未提交工作，不擅自提交、推送、合并或发布。
- 不把 Skills 做成独立 Agent 或第二套 executor，不重写无关的报告模式、记忆系统、鉴权、数据库或前端。
- 不在没有必要时引入新生产依赖、数据库迁移、外部付费模型调用或真实生产服务调用。
- 不在本期实现几十个 Skill、专用路由小模型、完整 BM25 + embedding reference RAG、企业级域名治理、脚本沙箱、生产 A/B、完整灰度发布平台或自动化生产回滚。
- 一期不把 Skill scripts 做重；若现状确有必要脚本，只允许作为受控、确定性后处理并继续走统一 executor，具体需在方案阶段确认。
- 不把历史离线指标包装为当前代码实测、线上大盘、SLA 或投资效果。
- 不承诺投资收益，不输出“必买/必卖”等确定性投资建议。

### 6.3 Unknown Scope

- `search_web_news` 是否已存在且具备本次可安全复用的完整治理链路。
- 前端 `skill_confirm` 卡片是否需要本次修改，或现有协议已经足够。
- Registry 热刷新、shadow 状态和 Skill 级回滚需要做到真实运行能力，还是仅实现可验证的本地 Demo 语义。
- 旧仓库已有代码与当前仓库接口差异是否会触发公共 API、配置或持久化结构变更。
- 文档指标数据集与 runner 是否存在、是否可信、是否可离线复现。

## 7. Constraints

### 7.1 Hard Constraints

- 实现必须与两份用户指定文档的统一口径对应；若代码现状与文档冲突，必须显式记录差距并由证据决定迁移方案，不能只修改话术掩盖缺口。
- 5 个 Skill 的名称、职责边界和安全边界保持不变，除非后续代码证据证明存在不可兼容问题并获得明确确认。
- Skill 只提供业务 SOP 和机器契约；工具执行、重试、并发、证据归一与生成收口复用统一运行内核。
- 机器执行冲突时以结构化 spec 为准；Registry 必须在请求前暴露 schema、工具、evidence 与路径问题。
- 当前用户明确要求与系统金融安全规则优先；本轮 working state 和实时证据次之；长期记忆仅作默认背景，不得扩大工具权限或结论强度。
- 实时行情、财务与新闻不得写入静态 references；网页内容视为不可信输入；日志、trace、测试 fixture 和异常不得泄露凭据、持仓、金额、私有对话、完整内部 plan 或敏感 payload。
- 默认测试不得调用付费模型或生产服务；live 测试必须显式隔离和开关控制。
- 不进行 destructive Git 或数据操作，不删除旧分支，不提交或推送，除非用户后续明确授权。
- Python 公共与跨模块接口必须有类型；新增或修改公共类、函数、路由、服务、Agent/workflow 节点与工具时，按仓库语言使用 Google-style docstring，并同步更新有业务意义的注释。

### 7.2 Soft Constraints

- 优先复用当前仓库已验证的边界和旧仓库可兼容实现，避免无关重构与重复抽象。
- 先用小规模、可解释的规则/metadata/词面检索闭环；只有证据表明规模或同义表达需要时才升级复杂检索。
- 变更应按冻结里程碑小步落地，每个里程碑保持窄 diff、可独立测试和可回滚。
- 使用稳定枚举/错误码表达状态与失败，终端输出简洁，长诊断进入脱敏 artifact。

## 8. Stakeholders and Impact

- 最终用户：获得可解释、可澄清、证据边界明确的 5 类投研分析能力，降低误触发与强结论风险。
- 开发者/维护者：获得统一资产结构、注册校验、版本快照、可追踪失败语义和回归测试，减少跨 Skill 漂移。
- 面试评审者：可以从代码、测试和 trace 验证每项工程声明，而非只看到文档或 Prompt。
- Agent runtime：新增 Skill 选择与上下文约束，但继续复用既有执行和证据治理能力。
- 记忆/上下文系统：仅向合适阶段提供最小切片，避免长期偏好污染路由、工具权限或证据强度。
- 工具执行与数据源：需要向 Registry/spec 暴露稳定的工具 ID、输入 schema、evidence type 与健康/可执行状态，但不应被 Skill 绕过。
- 前端：可能需要消费统一 Registry metadata 和确认状态；是否修改由勘察确定。
- 可观测与评测系统：需要关联 Skills 新增中间状态、版本和指标，并保持外部 exporter 非阻塞。

## 9. Engineering Quality Requirements

### 9.1 Interface Documentation and Types

- 为 Skill metadata/spec、Registry snapshot、retrieval/selection、loaded stage context、rewrite 结果、clarification/confirmation、evidence contract、degrade decision 和 trace 字段提供显式类型。
- 公共接口文档说明业务责任、输入约束、输出结构、副作用、失败语义、兼容性与下游消费者，不重复签名本身。
- 机器消费状态使用稳定 Enum/Literal 或错误码，避免核心链路依赖无结构 `dict[str, Any]`。

### 9.2 Architecture and Module Ownership

- 明确区分 Skill 资产与注册、发现/选择、阶段化加载、业务计划约束、统一执行、证据治理、synthesis、评测与可观测职责。
- 路由/UI/API 只做协议适配和边界校验；业务编排进入对应 service/workflow；文件系统、模型、工具和外部观测由适配层承担。
- 不在 Skill Loader、Prompt 或路由器中隐式执行工具；不让 planner 重新路由；不让 synthesis 自行改变证据裁决。

### 9.3 Configuration, Secrets, Constants, and Prompts

- 部署可变设置通过当前仓库集中、类型化配置加载；稳定阈值与业务规则是否属于代码或配置由方案阶段根据现状决定，禁止散落 `os.getenv()`。
- 新增开关必须有安全默认值和 `.env.example` 文档，不提交真实 `.env` 或凭据。
- Prompt/Skill spec/工具 schema/评测集等兼容性敏感资产应可版本化或计算稳定 hash。

### 9.4 Terminal Output, Logging, Tracing, and Artifacts

- 关键阶段记录 `stage`、`trace_id/run_id`、`status`、`elapsed_ms`、版本/hash、稳定 `error_code` 和必要指标；状态至少能区分 `STARTED/SUCCEEDED/FAILED/SKIPPED/PARTIAL` 或仓库等价语义。
- Skills trace 能把候选、选择/确认、加载、计划、工具、证据、降级和生成串成同一事实链；外部观测不可用不阻塞回答。
- 默认只记录脱敏摘要、hash、ID 与 artifact 引用，不记录凭据、完整私密对话或未经批准的原始模型/工具 payload。

### 9.5 Validation, Errors, Retry, State, and Compatibility

- 所有文件、YAML/frontmatter、路径、工具、输入 schema、evidence type、状态迁移和用户外部输入在边界校验。
- 非法 Skill、无效计划和阻塞型缺槽位必须在执行前失败或澄清，不得静默转为空结果或成功。
- 仅对瞬时故障做有界、可追踪重试；有副作用时需幂等保护。Skills 不增加无限循环或无界 replan。
- 当前 API、会话、记忆和工具执行兼容性默认保持；如勘察发现必须变化，应进入澄清和方案权衡，不能直接修改。

## 10. Success Criteria

### 10.1 Functional Criteria

- 5 个 Skill 均可从规范资产注册为可用能力，并能被统一列举与按阶段加载。
- 非法资产在 Registry 阶段被禁用并给出可诊断原因；有效快照不会因一次失败刷新而丢失。
- 显式选择、高置信自动选择、中置信确认、低置信回退、阻塞槽位澄清和多任务拆分均有可执行测试案例。
- 5 个 Skill 的正例、相邻反例、缺槽位、缺证据和输出越界行为符合本文与两份业务文档。
- 计划只使用可用白名单工具并覆盖最低证据要求；实际执行复用统一 runtime。
- 证据不足时 controller/synthesis 按 Skill 降级，禁止确定性买卖建议与弱新闻强因果。

### 10.2 Compatibility Criteria

- 现有非 Skills 的 `tushare-data`、`fallback`、记忆、会话、鉴权及报告模式测试保持通过。
- 未经确认不改变现有公共 API、数据库 schema、持久化语义、工具 ID/schema 和前端协议。
- 旧版可复用资产迁移后必须通过当前接口校验，不通过时不得以兼容层掩盖根因。

### 10.3 Reliability Criteria

- 文件解析失败、工具不可用、模型选择异常、缺槽位、工具超时/空数据、证据冲突和外部 trace exporter 失败均产生明确、受控结果。
- 每轮使用进入链路时固定的 Registry/Skill 版本，避免同一请求读到混合快照。
- 运行时权限不得超过 spec、可执行注册表与健康状态交集。

### 10.4 Observability Criteria

- 可以仅凭一条 trace 区分召回、选择、rewrite、计划、工具、数据源、证据裁决、记忆污染和 synthesis 越界问题。
- trace 记录必要版本、hash、候选分数/规则命中、确认/回退原因、加载 reference、计划、证据裁决、缺失维度、降级与 claim level。
- 所有观测与评测输出可追溯到测试/数据集版本，且敏感字段已脱敏。

### 10.5 Testing Criteria

- 新增/修改模块有聚焦单元测试；关键用户路径有使用 fake/stub 工具和模型的集成测试。
- 资产 P1 校验覆盖 frontmatter、目录名/alias、spec schema、工具 join、计划白名单、evidence mapping、reference 路径与文档/spec 对齐。
- 每个 Skill 至少覆盖正常命中、相邻误触发、缺槽位、证据不足和输出越界五类行为。
- 可运行的离线评测报告分别展示 family routing、具体 Skill 选择、证据覆盖、降级/越界及单 Skill 分项，不用一个总平均掩盖差异。
- 按仓库实际命令完成 format → lint → typecheck → focused tests → broader regression → final diff review；无法执行项需记录命令、原因和残余风险。

## 11. Risks and Mitigations

- 风险：两份文档描述的是理想/历史口径，当前代码可能没有对应实现。缓解：先建立“声明—代码—测试”差距表，指标和能力只以可运行证据确认。
- 风险：旧仓库代码直接复制会破坏当前架构、类型或配置。缓解：逐模块审计依赖和接口，优先迁移领域资产，适配必须走当前边界并有测试。
- 风险：Skills 与记忆、路由、rewrite、工具治理交叉，容易扩大变更面。缓解：以 planner 前约束为主要边界，冻结禁止修改项并按里程碑落地。
- 风险：相邻 Skill 误触发或模型路由不稳定。缓解：正反例、显式选择、候选分差、确认/回退及多次离线评测共同约束。
- 风险：spec、SKILL.md、工具 schema、evidence type、references 与 tests 漂移。缓解：Registry/P1 前置 join 与一致性校验，版本/hash 和回归覆盖。
- 风险：新增校验过严导致可用请求被拒绝。缓解：区分阻塞缺失、安全默认和可继承省略，并覆盖正反边界样例。
- 风险：网页或工具结果污染 Prompt、泄露隐私或形成强因果。缓解：最小化外发、untrusted envelope、来源/时间/注入检查和 claim-level 降级。
- 风险：离线指标不可复现或被误表述为本次实测。缓解：先核验数据集、runner、版本和计算公式；缺失时建立新基线并显式区分历史声明。
- 风险：切分支或后续 Git 操作误伤用户历史。缓解：已保留 `main`，仅新建开发分支；未经授权不提交、推送、合并或删除分支。

## 12. Open Questions

1. Question: 旧版 Skills 实现的权威来源究竟是当前工作区中的哪个仓库/目录？
   Why it matters: 决定复用审计范围，避免把文档草稿或过时实现当成迁移真源。
   Suggested default: 在代码勘察阶段扫描 `D:\FinanceProject` 下相邻 Git 仓库和明确的 Skills 目录，以最近提交、测试与当前接口兼容性共同判断，不仅凭目录名。

2. Question: 本次是否必须修改前端 `skill_confirm` 交互？
   Why it matters: 可能扩大到前后端协议与 UI 测试。
   Suggested default: 先核验现有卡片和协议；若已能表达候选、原因、确认/取消与恢复，则不改 UI，只补后端集成与测试。

3. Question: 文档中的冻结指标是否有对应数据集、runner 和历史 artifact？
   Why it matters: 决定本次能否复现实测值，还是只能验证计算链路并建立新基线。
   Suggested default: 没有完整证据时不声称复现历史数字；交付真实可运行评测与差异说明。

4. Question: Registry 热更新、shadow 和按 Skill 回滚要做到什么深度？
   Why it matters: 会显著影响状态管理、配置和测试范围。
   Suggested default: 当前 Demo 实现进程内原子快照、last-known-good、固定请求版本和可测试的状态迁移；不实现生产流量灰度平台。

5. Question: 是否允许为 Skills 增加新的第三方依赖？
   Why it matters: YAML/schema、文件监听或检索实现可能诱导新增依赖。
   Suggested default: 优先使用仓库已有依赖与标准库；任何新生产依赖必须在方案权衡阶段证明必要性。

## 13. Handoff to Next Step

下一步使用 Codebase Reconnaissance Skill，只读检查当前代码库以及本地旧版 Skills 来源。重点确认：项目类型与入口；仓库/目录边界；记忆和上下文现状；实体解析与三类路由；route-specific rewrite；工具 capability/executable registry；planner/validator/executor/verifier/controller/synthesis 调用链；Skill 资产、Registry、Retriever、Loader 与 reference 检索现状；前端确认协议；配置、Prompt、日志、trace、artifact；测试、离线数据集、runner 和指标计算；公共接口、持久化与安全风险。该阶段不得修改代码或决定最终方案。

## Decisions Needed Before Codebase Reconnaissance

- [x] 保留 `main`，在新分支 `feature/skills-sop-migration` 工作。
- [x] 以两份指定文档的统一口径作为需求来源，但以可运行代码和测试验证“当前已实现”声明。
- [x] 默认审计当前工作区内可发现的旧版 Skills 实现，优先复用兼容代码。
- [ ] 通过只读勘察确定旧版权威来源、前端是否需要修改、历史评测是否可复现。
- [ ] 在勘察后只提出会实质影响架构、公共协议、持久化或依赖的必要澄清问题。
