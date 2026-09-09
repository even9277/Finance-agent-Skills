# REQUIREMENT_SPEC.md

## 1. Task Type

Primary type: New Feature

Secondary types: Refactor, Test / Evaluation Improvement, Project Packaging / Interview Demo Improvement

Classification rationale: D09 需要在现有确定性实体解析之后补齐受控模型兜底、局部修复、语义校验和真实链路验收，同时消除报告/对话各自猜实体造成的口径偏差。

## 2. Requirement Restatement

在不修改面试文档的前提下，让金融 Agent 的实体解析实现与既有口径一致：股票、基金、ETF、指数和板块首先通过显式代码、标准目录、别名与可解释的模糊规则解析；只有确定性链路不能可靠收敛时，才允许调用配置中的真实 OpenAI-compatible 模型做结构化候选裁决或补全。模型结果必须经过严格 Schema 和权威目录语义校验；结构损坏最多做一次局部修复，候选竞争、低置信或显式代码无效时必须澄清或受限失败，不能猜测后继续调用金融工具。

报告模式与对话模式应消费同一权威解析底座，由各自适配层输出所需结构，不保留长期双轨解析实现。现有 Chat API、WebSocket 协议、数据库 Schema、Skills、Memory、工具执行与报告工作流拓扑不得因本任务改变。

## 3. Problem Source

- 用户确认的 Gap D09：当前实现主要依赖静态目录、规则和别名，而面试口径描述了“确定性解析 + 受控 LLM fallback + 修复链路”。
- 面试材料中的已冻结 Claim：统一实体解析底座、route 前固定 `active_entity`、歧义不偷选、严格结构生成、一次语法修复、语义校验后才允许下游消费。
- 当前阶段尚未读取实现代码；具体缺口由下一步只读 Codebase Reconnaissance 核实。

## 4. Current Behavior

已知现状来自前序审计：

- 主要通过静态证券目录、规则、别名和现有会话继承处理实体。
- 尚无足够代码证据证明真实模型兜底、损坏结构局部修复、权威目录二次校验构成完整运行链路。
- 报告与对话是否真正共享同一解析底座尚需代码勘察确认。
- 当前 API、前端事件、Trace 和离线评测对 D09 失败路径的覆盖程度尚需确认。

## 5. Expected Behavior

1. 用户输入有效标准代码、标准名称或已登记别名时，确定性解析直接返回，不调用模型。
2. 用户输入口语简称、未登记俗称或上下文相关称呼，且确定性解析无法可靠收敛时，解析器只向模型提供最小化问题上下文和受控候选信息，要求返回版本化结构。
3. 模型不得成为证券主数据真源。模型给出的实体必须回查权威目录并规范化为 canonical ID；不存在、类型不兼容或越出允许候选范围时不得进入 route/rewrite/planner。
4. 模型输出 JSON/Schema 损坏时，仅在实体解析局部允许一次结构修复；第二次仍损坏则返回稳定失败码并澄清或受限降级，不重跑整条 Agent 链路。
5. “平安”等缺乏充分消歧上下文的竞争候选必须保留候选并触发澄清，不能因模型给出 top1 就静默执行。
6. 显式证券代码校验失败时不得使用模型猜另一个标的。
7. 当前轮明确实体优先；只有无新实体、存在承接表达、历史实体高置信且类型兼容时才允许继承。模型兜底不得绕过这些继承门禁。
8. 报告单股票入口与对话权威入口使用同一 canonical 解析结果；适配层分别输出 `(company_name, stock_code)` 与结构化 `active_entity/candidates/clarification`。
9. 真实 API 验收必须从实际产品入口模拟用户使用，证明至少一条确定性命中不会调用模型、一条模型兜底成功、一条歧义澄清不会调用工具。

## 6. Scope

### 6.1 In Scope

- 统一实体解析领域合同、候选与解析路径语义。
- 确定性解析优先级和显式代码权威边界。
- 受控 OpenAI-compatible 模型兜底 Port/Adapter、版本化 Prompt 和严格结构输出。
- 最多一次局部 syntax repair，以及 repair 后的 semantic validation。
- 对话模式与报告模式的场景适配和单轨调用方迁移；迁移完成后删除被替代的旧解析路径。
- 稳定失败码、低敏日志/Trace、模型调用次数与解析路径指标。
- Unit、contract、offline eval、集成/E2E、protected live 和 CI 验收。

### 6.2 Out of Scope

- 不修改 `D:/FinanceProject/Finance/金融Agent项目描述文档/` 下任何文件。
- 不开发 D07 报告 Agent 工具隔离或 D10 Portfolio/自选股。
- 不调整路由、Skills、Memory、工具治理、证据校验和最终回答的业务策略。
- 不改变数据库 Schema、公共 REST/WebSocket/SSE 协议或前端交互。
- 不引入新的模型 SDK、向量库、搜索服务或付费依赖。
- 不把历史 `Finance` 仓库加入生产运行依赖。
- 不把模型输出直接当作股票/基金/板块/指数权威主数据。

### 6.3 Unknown Scope

- 报告模式当前解析入口与对话解析器的实际代码关系，需勘察后确认迁移面。
- 当前目录对基金、ETF、指数、板块的覆盖完整度，需勘察现有 catalog 和 tests。
- 现有模型 Provider 是否支持严格 JSON/结构化输出；若不支持，后续方案需在不加依赖下比较适配方式。

## 7. Constraints

### 7.1 Hard Constraints

- 用户已授权且要求 protected live 使用真实 API；只能进行只读金融查询，不得触发真实写操作。
- 默认测试不能调用付费模型；Live 必须由显式 marker 和环境开关保护。
- 不保留长期双轨；调用方迁移完成后删除被替代入口、重复 Prompt 和过期开关。
- 显式代码失败、模型低置信、目录校验失败或竞争候选不能静默转成成功。
- 模型调用必须有超时、最大调用次数和稳定失败语义；不得整轮自动重试。
- Prompt、模型原始响应、API Key、Token、用户私密上下文不得进入普通日志、Trace、提交或测试夹具。
- 用户未跟踪的 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` 不得修改、暂存或提交。

### 7.2 Soft Constraints

- 优先复用当前受控对话领域合同、OpenAI-compatible Provider、Prompt 版本管理、Trace 和评测设施。
- 模型只处理确定性规则无法稳定覆盖的长尾语言，不重复处理已确定的标准代码和目录命中。
- 以可解释、可回放的 resolver path 和 failure code 优先于增加复杂召回框架。

## 8. Stakeholders and Impact

- 最终用户：降低查错证券、错误继承和歧义硬猜的风险；必要时多一轮澄清。
- Agent runtime：route/rewrite/planner 获得统一且已验证的实体合同，模型兜底会带来有界额外延迟和费用。
- 报告工作流：继续获得单股票二元组，但来源收敛到同一 canonical 解析底座。
- 开发维护者：可按 resolver path、候选、置信区间、repair 次数和稳定错误码定位 bad case。
- 面试评审：文档中的实体解析链路可以由真实代码、测试和 Trace 证据支撑，而非停留在口径层。

## 9. Engineering Quality Requirements

### 9.1 Interface Documentation and Types

- 公共解析合同、Port、Provider、适配入口和 Prompt 请求/响应使用显式 dataclass/Pydantic/Enum/Protocol 类型。
- 新增或修改的公共 Python 接口使用中文 Google-style docstring，说明输入、返回、失败、调用预算和敏感边界。
- 不使用自由 `dict[str, Any]` 作为核心解析状态。

### 9.2 Architecture and Module Ownership

- canonical 规则、候选合并、置信与失败决策属于领域/工作流层；具体模型 SDK 调用属于基础设施 Adapter；启动装配属于 backend factory/lifespan。
- Router 和报告 Agent 不得直接拼实体解析 Prompt 或消费 Provider 私有对象。
- 报告/对话只保留场景适配差异，不复制底层解析规则。

### 9.3 Configuration, Secrets, Constants, and Prompts

- 复用 typed Settings 和现有 OpenAI-compatible 凭证，不新增真实密钥文件。
- 部署可变的模型、超时、置信阈值或开关只能由统一 Settings 注入；稳定的枚举、路径优先级和协议版本保留在代码。
- Prompt 存放在版本化、聚焦的实体解析资产中，不散落在 Router/Service。

### 9.4 Terminal Output, Logging, Tracing, and Artifacts

- 日志/Trace 至少可关联 `trace_id/run_id`，并记录低基数字段：`stage/status/resolver_path/model_called/repair_count/candidate_count/confidence_band/failure_code/elapsed_ms/prompt_version`。
- 不记录完整用户问题、模型 Prompt、原始模型输出、完整候选别名、Token 或 Authorization。
- Live artifact 只保存测试 ID、模型标识、调用次数、路径、状态、时延、结果哈希和脱敏候选引用。

### 9.5 Validation, Errors, Retry, State, and Compatibility

- 区分确定性未命中、显式代码无效、候选歧义、模型超时、模型结构损坏、模型结果目录校验失败等稳定状态。
- syntax repair 最多一次且只修结构；semantic validation 失败不得再次要求模型“换个答案”。
- 模型兜底和 repair 均计入同一实体解析总预算；取消和超时必须向上层稳定投影。
- 下游继续只消费已验证领域对象，公共产品协议保持兼容。

## 10. Success Criteria

### 10.1 Functional Criteria

- 显式标准代码、标准名称、别名和高置信模糊匹配在离线测试中均走确定性路径，模型调用数为 0。
- 至少一类真实口语长尾输入在确定性未命中后，经真实模型返回结构化候选并通过目录校验，得到正确 canonical 实体。
- 竞争候选、无效显式代码、模型幻觉实体、类型冲突和低置信结果均停止在实体解析/澄清边界，工具调用数为 0。
- 一次损坏结构可被局部 repair；连续损坏不超过两次模型调用并返回稳定失败。
- 报告与对话适配器对同一股票输入得到同一 canonical ID。

### 10.2 Compatibility Criteria

- 现有 REST/WebSocket/SSE 响应 Schema、数据库 Schema、认证、路由枚举、Skills 和工具合同不变。
- 现有实体解析、STM 继承、route、rewrite、report 和默认非 Live 测试不回归。
- 迁移完成后不存在旧调用方或重复解析实现的活跃引用。

### 10.3 Reliability Criteria

- 模型超时、限流、网络错误和无效结构在固定预算内结束，不导致整轮崩溃或无限重试。
- 模型不可用时保留确定性解析能力；需要模型才能判断的长尾输入明确澄清/降级。
- 并发请求之间不共享候选、repair 计数或解析结果等可变请求状态。

### 10.4 Observability Criteria

- 可从单轮 Trace 判断是 deterministic、inheritance、model_fallback、syntax_repair、clarification 或 failed 路径。
- 可观测模型调用次数、repair 次数、候选数量、置信区间、最终 failure code 和耗时。
- Secret/Prompt/原始响应扫描无泄露。

### 10.5 Testing Criteria

- 测试先行，覆盖确定性优先、模型成功、模型超时/限流、一次 repair、二次损坏、幻觉 canonical ID、歧义澄清、显式代码无效、继承门禁和报告/对话一致性。
- 建立或扩充固定版本实体解析 golden set；工程 schema/路径指标与模型质量指标分开。
- 运行相关 unit、contract、offline eval、integration、对话/报告 offline E2E、仓库默认非 Live 全量回归。
- protected live 必须从真实产品入口至少验证模型 fallback 成功与歧义安全停止，记录低敏证据；不允许整轮盲目重试。
- PR 的 Python、前端、Docker 与 Compose CI 全部通过后才可合并。

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| 模型给出流畅但不存在的证券代码 | 目录是唯一真源；semantic validation 不通过即失败/澄清 |
| 模型兜底增加延迟和费用 | 确定性优先、最小 Prompt、单次 fallback + 最多一次 syntax repair、记录调用次数 |
| LLM 把真实歧义误收敛为 top1 | 竞争候选和置信分差使用硬门禁，模型不能覆盖澄清规则 |
| 报告/对话迁移影响面过大 | 先 characterization，再共享底座与薄适配；逐里程碑验证 |
| Prompt/响应进入日志 | 只记录版本、哈希、计数和低敏状态；提交前 secret/content audit |
| 真实 API 结果非确定 | 离线合同测试负责工程正确性；Live 只证明真实接线和安全边界，不把单次模型质量当稳定指标 |
| 面试材料指标缺少当前可复现实验 | 不在代码任务中改口径；只报告本轮真实 golden set 和 Live 数据，不伪造历史指标 |

## 12. Open Questions

### Q1（P1）模型兜底能否从目录外自由生成 canonical ID？

- Question: 模型是否允许直接生成目录未召回的证券代码？
- Why it matters: 自由生成召回更广，但会把模型变成证券主数据源并放大查错标的风险。
- Suggested default: 模型可以提出标准名称/代码，但必须在权威目录回查唯一命中；未命中即失败，绝不直接执行。

### Q2（P1）语义校验失败是否允许第二次模型修复？

- Question: 模型返回合法 JSON 但实体不存在或类型冲突时，是否再让模型换答案？
- Why it matters: 再调用可能提高表面成功率，但会把 semantic guessing 伪装成 repair。
- Suggested default: 不允许；只有 JSON/字段结构损坏可做一次 syntax repair，语义失败直接澄清/降级。

### Q3（P1）报告模式迁移边界

- Question: 如果报告入口仍有独立解析实现，本轮是否同步迁移并删除旧路径？
- Why it matters: 不迁移就无法证明“共享底座 + 场景适配”，迁移则扩大回归范围。
- Suggested default: 按用户已确认的“不保留长期双轨”执行；若无公共 API/数据库破坏则本轮迁移，并增加跨适配一致性测试。

### Q4（P2）是否复现材料中的历史百分比

- Question: 是否要求本轮重新跑出 `active_entity 93.9%`、`误继承 4.4%`、`歧义澄清召回 90.7%`？
- Why it matters: 这些数字需要原始标注集、固定模型与重复运行协议，单次开发测试不能证明。
- Suggested default: 本轮先冻结可复现 golden set 与指标定义，报告当前实测值；不把历史口径数字当硬验收门槛。

## 13. Handoff to Next Step

下一步使用 Codebase Reconnaissance Skill，只读核查当前实体解析入口、领域合同、目录/别名来源、报告/对话调用方、模型 Provider、Prompt/Trace、STM 继承、测试与评测资产。不得修改代码或运行实现任务。

## Decisions Needed Before Codebase Reconnaissance

- [x] 真实 API 允许且必须执行；仅做只读产品链路验收。
- [x] 不保留长期双轨；迁移调用方后删除旧路径。
- [x] 不修改面试文档；D07/D10 不在本轮范围。
- [x] Q1-Q3 使用保守推荐默认值，来自用户“D09 按你的要求编写”的授权。
- [ ] Q4 作为 P2 延后，不阻塞代码勘察与实现。
