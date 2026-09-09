# SOLUTION_TRADEOFF.md

## 1. Tradeoff Context

D09 要解决的不是“给当前 Resolver 再加一次模型调用”，而是消除三套相互矛盾的实体解析策略：公开对话只依赖小型静态目录，报告直接相信模型，历史 CLI/兼容函数继续复制规则。目标是在不改数据库、公共 API、记忆和 Skill 边界的前提下，建立唯一的受控实体解析内核，并用真实产品入口验证长尾自然语言实体能够被模型提出、被权威目录确认、被下游安全消费。

## 2. Inputs Reviewed

- REQUIREMENT_SPEC.md: 已冻结可观察行为、范围、失败语义、真实 API 验收和不保留长期双轨。
- CODEBASE_RECON.md: 已确认公开对话、报告、工具和历史入口的实际调用链、重复实现、测试与风险。
- CLARIFICATION_QUESTIONS.md: 12 个 P0/P1/P2 问题均已消解，无阻塞项。
- User decisions: 不修改面试文档；真实 API 测试允许且必须；迁移调用方后删除旧路径；D09 采用推荐方案。
- External sources: OpenAI Structured Outputs、Tushare `stock_basic`、spaCy EntityLinker/LLM entity linking、Rasa `EntitySynonymMapper` 官方资料与源码仓库。

## 3. User Decisions and Defaults

### 3.1 Confirmed Decisions

- 规则、目录、别名和确定性模糊匹配优先，模型只作受控兜底。
- 模型只能提出候选，不能成为证券标识的权威来源。
- 报告和对话迁移到共享内核；迁移完成删除旧 Resolver 逻辑，不保留长期双轨。
- 真实 OpenAI-compatible 与 Tushare 调用必须从受保护测试实际执行。
- 报告实体未确认时在多 Agent fan-out 前失败。

### 3.2 Conservative Defaults Used

- 生产动态目录首期完整支持 A 股股票；基金、指数、板块先复用现有确定性目录和统一扩展合同。
- 每轮模型兜底最多一次初始调用和一次语法修复；语义校验失败不重试。
- 本地目录命中不依赖外部 API；长尾候选在目录不可用时 fail closed。
- 保持报告现有输出代码格式，由薄 Adapter 转换共享 canonical symbol。

### 3.3 Blocking Decisions

无未解决 P0/P1 问题，方案不阻塞。

## 4. Core Decision Point

选择在现有 `conversation` 领域边界内演进一个异步共享 Resolver，并通过模型端口与权威目录端口受控扩展，还是继续在对话/报告各自修补，或引入一个独立重型证券主数据服务。

## 5. Reference Sources and Repository Evidence

### 5.1 Official Docs

#### Source: OpenAI Structured Outputs

**Link:** https://platform.openai.com/docs/guides/structured-outputs

**What was inspected:** strict JSON Schema 输出、schema adherence 以及模型拒绝/协议失败需要由调用方处理的边界。

**Relevant practice:** 模型输出必须进入明确 schema；结构化输出减少格式错误，但不能替代业务语义验证。

**Reusable part:** Partially reusable。

**Fit for this task:** 当前提供方是 OpenAI-compatible，不应假定所有模型都完整支持原生 strict schema；因此复用“严格 schema 合同”原则，并在本地用 Pydantic 验证和一次受控修复兜底，不绑定专属 SDK 功能。

#### Source: Tushare 股票基础信息 `stock_basic`

**Link:** https://tushare.pro/document/1?doc_id=25

**What was inspected:** `ts_code`、名称、交易所、上市状态等字段，单次覆盖全市场 A 股的能力、调用权限和频率约束，以及官方建议的本地保存方式。

**Relevant practice:** `stock_basic` 可作为股票名称—规范代码映射的外部主数据来源；目录数据适合缓存，不应在每个自然语言请求中盲目全量拉取。

**Reusable part:** Directly reusable。

**Fit for this task:** 复用仓库已有 Tushare Client；用短 TTL/进程缓存承载目录快照或点查结果，真实测试校验模型候选，不新增依赖。

#### Source: spaCy EntityLinker

**Link:** https://spacy.io/api/entitylinker

**What was inspected:** mention → candidate generation → knowledge-base ID linking、置信阈值与 NIL 结果。

**Relevant practice:** 模型或规则负责候选选择，最终结果必须落到 KnowledgeBase 的唯一标识；低于阈值应得到 NIL，而不是无条件采用预测。

**Reusable part:** Conceptual only。

**Fit for this task:** 直接引入 spaCy 与训练链过重，但“候选、KB grounding、阈值、NIL”四个概念与当前受控 Resolver 高度一致。

#### Source: spaCy LLM Entity Linking

**Link:** https://spacy.io/api/large-language-models

**What was inspected:** 先由 CandidateSelector 提供可行实体，再让 LLM 选择的模式，以及 top-N 候选边界。

**Relevant practice:** LLM 不应脱离候选/知识库独立创造实体；模型能力应受候选和知识库合同约束。

**Reusable part:** Partially reusable。

**Fit for this task:** 当前长尾场景允许模型先提出候选，但必须再由 Catalog 回查；不复制 spaCy runtime，只复用 grounding 思路。

### 5.2 Open-source Repositories

#### Source: explosion/spaCy

**Link:** https://github.com/explosion/spaCy/blob/master/spacy/pipeline/entity_linker.py

**What was inspected:** `EntityLinker` 对 KnowledgeBase、candidate generator、confidence threshold 与 NIL 的代码级边界。

**Relevant practice:** 把候选生成、候选选择、知识库和评分作为分离责任；未达到门禁不形成实体链接。

**Reusable part:** Conceptual only。

**Fit for this task:** 采用端口分离和 NIL/fail-closed 语义，不引入其 NLP/训练依赖。

#### Source: RasaHQ/rasa

**Link:** https://github.com/RasaHQ/rasa/blob/3.6.x/docs/docs/tuning-your-model.mdx

**What was inspected:** 规则/特征/分类器流水线以及 `EntitySynonymMapper` 对已识别实体进行已知同义词标准化的职责。

**Relevant practice:** 同义词归一化应是确定性的独立步骤，模型识别与 canonical normalization 不应混为一体。

**Reusable part:** Partially reusable。

**Fit for this task:** 保留当前 alias map 作为确定性优先级，不引入 Rasa pipeline；将模型定位为后置兜底而不是替换 alias normalization。

### 5.3 Local Project Patterns

| Local pattern | Evidence from CODEBASE_RECON.md | How to reuse |
| --- | --- | --- |
| 领域合同 + ports + infrastructure adapters | `conversation/contracts.py`、`ports.py`、`backend/infrastructure/chat/providers.py` | Resolver 编排与 canonical entity 留在领域；模型/Tushare 实现在基础设施层 |
| 严格 Pydantic 输出 | `backend/infrastructure/chat/skill_rerank.py`、memory candidate adapter | 复用 `extra=forbid`、typed errors、明确 timeout/max retry |
| 版本化 Prompt registry | `Financial-MCP-Agent/src/prompts/chat/registry.py` | 新增实体模型 Prompt 资产，不内联在 service |
| 集中 Settings | `backend/config.py`、`.env.example` | 模型名、超时、置信门禁和修复预算集中配置 |
| 结构化低敏 Trace | `WorkflowEvent`、`SkillTraceSink` | 记录 resolver path、calls、repair、failure code、elapsed，不记录正文 |
| 生产依赖集中装配 | `backend/application/chat/factory.py` | 由 factory 注入模型和目录 Adapter，测试可注入 fake |

## 6. Reusable Patterns

### 6.1 Directly Reusable Patterns

- 复用现有领域/端口/Adapter 分层，而不是让 `conversation` 直接导入 LangChain 或 Tushare。
- 复用 `Settings`、Prompt registry、Pydantic 严格合同、显式 timeout/max retry 和结构化 Trace。
- 复用 Tushare `stock_basic` 作为 A 股权威映射来源，并加受控缓存避免每轮全量查询。

### 6.2 Partially Reusable Patterns

- Rasa 的 synonym normalization 用于本地 alias 层；只复用职责划分。
- OpenAI strict structured output 用于合同设计；实际仍做 provider-independent 的本地 schema 校验。
- spaCy LLM entity linking 的 candidate/KB grounding 用于策略设计；本项目允许长尾模型先提出候选，再回查 Catalog。

### 6.3 Conceptual References Only

- spaCy 的训练式 EntityLinker、候选先验和向量模型可作为未来大规模实体库方向，但当前没有训练数据和依赖预算。
- 独立证券主数据服务、离线构建全量搜索索引和人工别名运营是长期能力，不在本轮实现。

### 6.4 Not Suitable for This Iteration

- 直接引入 spaCy/Rasa 或向量数据库。
- 让模型通过“常识”生成后直接采用代码。
- 在对话和报告分别维护 Prompt、规则或静态目录。
- 用 feature flag 长期保留旧/新 Resolver 双轨。

## 7. Solution Options

### 7.1 Option A: Minimal Fix

**What changes:** 只在公开对话的现有静态 Resolver 尾部接一个 LLM 调用，并增加少量解析测试。

**What does not change:** 报告 LLM-only Resolver、同步接口、旧兼容函数、CLI 复制规则、缺少权威回查。

**Benefits:** 改动最少，短期能演示某些长尾名称。

**Costs:** 继续维护多条策略，无法形成共享链路。

**Risks:** 模型幻觉仍可能进入主链；报告和对话输出不一致；直接违背“不保留双轨”。

**Testing burden:** Low-Medium，但无法通过跨场景一致性和旧路径删除验收。

**Rollback difficulty:** Low。

**Engineering impact:**

- Architecture/module ownership: 模型逻辑会污染领域模块。
- Documentation/types: 只能局部补字段。
- Configuration/secrets/prompts: 容易继续内联 Prompt/散落配置。
- Terminal/logging/tracing/artifacts: 路径可见性不完整。
- Errors/retry/state: 很难区分模型、目录和语义失败。

**When to choose it:** 只适合一次性原型；不适合本轮已确认要求。

### 7.2 Option B: Structured Improvement

**What changes:** 在现有 `conversation` 领域边界演进唯一异步 Resolver；明确模型端口、Catalog 端口、严格输出合同、一次语法修复和目录语义回查；对话、报告、生产工具与 CLI 使用薄 Adapter 迁移；完成后删除旧私有解析策略。

**What does not change:** 不改公共 API/数据库/记忆/Skill/报告正文；不引入新框架或生产依赖；不构建完整主数据服务。

**Benefits:** 与面试口径逐项对应，模型不可越过业务校验；测试可注入 fake，生产可走真实 API；统一 canonical entity 但保留场景输出兼容。

**Costs:** Resolver 需要异步迁移，涉及领域合同、factory、报告 Adapter、部分调用方和测试。

**Risks:** 调用方遗漏、外部目录额度/权限、报告失败语义变化、模型输出不稳定。

**Testing burden:** Medium-High；需单元、契约、eval、集成、真实产品入口 E2E 和全量回归。

**Rollback difficulty:** Low-Medium；按里程碑小提交可回滚，但不以运行时双轨回退。

**Engineering impact:**

- Architecture/module ownership: 领域负责决策，基础设施负责模型/Tushare，场景 Adapter 负责格式与失败映射。
- Documentation/types: 更新公开接口的中文 Google-style docstring、类型和实体结果字段。
- Configuration/secrets/prompts: Settings + `.env.example` + 版本化 Prompt；凭证仍来自既有 secret 边界。
- Terminal/logging/tracing/artifacts: 低敏结构化路径指标；真实响应不落测试 artifact。
- Errors/retry/state: 稳定错误码、模型总调用预算、目录不可用 fail closed、报告 fan-out 前终止。

**When to choose it:** 当前中等风险、已有分层基础、需要可信工程闭环和面试可解释性的项目。

### 7.3 Option C: Long-term Architecture Direction

**What changes:** 建独立证券主数据服务，全量定时同步股票/基金/指数/板块，建立别名运营、检索索引、版本与数据质量监控，所有 Agent 通过服务 API 做 linking。

**What does not change:** Agent 仍只消费 canonical entity，但当前仓库大量装配和部署方式会改变。

**Benefits:** 覆盖面、性能、治理、跨服务复用和在线运营能力最好。

**Costs:** 需要持久化 schema、同步任务、索引、管理流程、部署与监控，远超 D09。

**Risks:** 过度设计、引入新的单点和数据新鲜度问题、迁移周期长。

**Testing burden:** High；包括数据同步、版本、回填、漂移、服务 SLA 和多消费者兼容。

**Rollback difficulty:** High。

**Engineering impact:**

- Architecture/module ownership: 新增独立 bounded context/service。
- Documentation/types: 新公共 API、数据模型和运行手册。
- Configuration/secrets/prompts: 新数据任务与基础设施配置。
- Terminal/logging/tracing/artifacts: 数据质量和同步 artifact。
- Errors/retry/state: 新增跨服务一致性、重放和灾备语义。

**When to choose it:** 多产品共享、实体规模与别名运营已成为主要瓶颈时；本轮延后。

### 7.4 Option D: Observation-first Option

**What changes:** 只补路径 Trace、bad case 数据和现有行为评测，不改 Resolver。

**What does not change:** 当前功能 Gap 全部保留。

**Benefits:** 风险最低，可补充分布证据。

**Costs:** 不能完成用户已选 D09 开发。

**Risks:** 把已明确的架构缺口继续延期。

**Testing burden:** Low。

**Rollback difficulty:** Low。

**Engineering impact:** 仅增强可观测与评测，不满足功能合同。

**When to choose it:** 需求或根因不明时；当前证据已足，不选。

## 8. Decision Matrix

| Dimension | Option A Minimal Fix | Option B Structured Improvement | Option C Long-term Architecture | Option D Observation-first |
| --- | --- | --- | --- | --- |
| Scope | Small | Medium | Large | Small |
| Development Cost | Low | Medium | High | Low |
| Risk | Medium-High | Medium | High | Low |
| Reusability | Low | High | Very High | Medium |
| Fit to Current Requirement | Low | Very High | Medium | Low |
| Local Pattern Fit | Low | Very High | Low | High |
| External Pattern Fit | Partial | High | High | N/A |
| Test Burden | Low-Medium | Medium-High | High | Low |
| Rollback Difficulty | Low | Low-Medium | High | Low |
| Observability Improvement | Low | High | Very High | High |
| Long-term Maintainability | Low | High | Very High | Medium |
| Engineering-standard fit | Low | High | High but excessive | Partial |
| Recommendation | Reject | **Select** | Defer | Reject as final solution |

## 9. Recommended Solution

Selected option: **Option B — Structured Improvement**。

Why selected: 它是满足共享内核、权威回查、失败可解释、真实 API 验收和删除旧路径的最小可靠方案；能够复用当前 ports/factory/settings/prompt/trace/test 结构，不需要引入新框架或持久化系统。

Why not the other options: A 无法消除双轨且不能治理幻觉；C 远超当前规模和已授权边界；D 只能观测，不能完成 D09。

Local patterns reused: `conversation` 领域合同、infrastructure adapters、factory 注入、Pydantic 严格输出、集中 Settings、版本化 Prompt、结构化 Trace、pytest marker 和受保护 live harness。

External practices reused: OpenAI 的 schema-first 输出原则、Tushare 的证券主数据字段与缓存建议、spaCy 的 candidate/KB/NIL 边界、Rasa 的 synonym normalization 职责划分。

Remaining risks: async 迁移遗漏、Tushare 权限/字段差异、模型长尾稳定性、报告下游代码格式、旧历史入口导入方向。

What must be verified later: 所有生产调用方只指向共享内核；模型路径严格晚于确定性路径；幻觉候选被目录拒绝；语法修复不超预算；报告未确认不 fan-out；真实长尾查询从产品入口完成模型+目录调用；默认离线和全量回归通过。

## 10. Unified Technical Direction

- 在 `Financial-MCP-Agent/src/conversation` 保留实体领域合同与解析决策，演进为异步共享 Resolver；不在领域层导入模型 SDK、Tushare 或 backend service。
- 在 `backend/infrastructure` 提供 OpenAI-compatible 模型 Adapter 与 Tushare Catalog Adapter，由 `backend/application/chat/factory.py` 和报告装配边界注入。
- 解析顺序固定为显式代码/精确/别名/确定性模糊匹配，无法收敛后才调用模型；模型输出严格校验，最多一次 syntax repair，随后必须 Catalog grounding。
- 对话和报告只保留薄 Adapter；报告负责 stock-only 和代码格式映射。迁移生产调用方后删除旧 LLM-only/regex 私有策略，不用 feature flag 保留双轨。
- 新配置进入 Settings/`.env.example`，Prompt 进入版本化 registry；Trace 只记录路径、调用/修复计数、候选数、错误码和耗时。
- 验证必须覆盖单元、合同、eval、集成、真实受保护 E2E、默认全量套件和调用图静态复核；不伪造历史百分比。
- 延后完整多类型动态目录、独立主数据服务、别名运营和历史指标复现。

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| async 签名迁移漏掉调用方 | 先用 `rg` 建调用清单，迁移后静态复核旧符号与旧 Prompt 均为零 |
| 模型产生幻觉代码 | Pydantic schema 只保证结构；最终必须 Catalog 名称—代码—类型一致性回查 |
| Tushare 调用频率/权限不足 | 复用已有 client，目录短 TTL 缓存；默认测试 fake；失败用稳定错误码，不信任模型 |
| 语法修复放大费用 | 总预算最多 2 次，repair 只处理 syntax，语义失败不重试 |
| 报告行为变化 | 在 fan-out 前新增契约测试，验证未确认实体不会启动 Agent |
| 日志泄露查询或模型正文 | 结构化低敏字段，错误链不记录原始响应、prompt、token 或用户全文 |
| CLI 产生反向依赖 | 优先调用应用 Adapter；若无法保持分层，停止对应里程碑而非复制 Resolver |
| 历史指标不可复现 | 新 eval 数据、版本和分路径结果独立报告，不复写历史数值 |

## 12. Verification Direction

### 12.1 Engineering Contract for Plan Freezing

- Architecture/module ownership: 领域只负责编排和规则；模型/目录为 ports/adapters；场景格式与错误映射在 application/service adapter；router/UI 不承载策略。
- Interfaces/docstrings/types: 所有新增/变更公共 Python 接口补中文 Google-style docstring、明确类型、错误与副作用；canonical entity 与 resolver metadata 使用 typed contract。
- Configuration/secrets/constants/prompts: 部署参数集中 Settings，稳定阈值若需配置只保留一处真源；Prompt 版本化；不提交或打印凭证。
- Terminal/logging/tracing/artifacts: 终端简洁；Trace 有 `stage/status/elapsed_ms/resolver_path/model_calls/repair_count/failure_code`；live 不落敏感原文 artifact。
- Validation/errors/retry/state: 严格 schema；目录语义回查；syntax repair 最多一次；显式无效代码不问模型；歧义不写 STM；报告失败不 fan-out。
- Tests/evaluation/delivery evidence: tests-first；离线 fake 覆盖所有分支；eval 覆盖精确/别名/模糊/歧义/继承/长尾/幻觉/修复；Compose 与全量回归；受保护真实 API 必须实际通过；diff/review/CI/PR 形成证据。

## 13. Deferred Work

- 独立证券主数据服务、数据库 schema、全量定时同步与版本化索引。
- 基金、指数、板块的完整动态外部目录。
- 向量实体链接、训练模型、别名管理后台与人工反馈闭环。
- 历史 93.9% / 4.4% / 90.7% 的原始评测集复现。
- 与 D09 无关的 D07 报告 Agent 工具隔离和 D10 组合/自选股。

## 14. Handoff to Plan Freezing

Next step should use the Plan Freezing Skill and produce `PLAN.md`.

The plan should:

- follow selected option: Option B，唯一异步共享 Resolver + 模型/Catalog ports + 薄场景 Adapter + 旧路径删除。
- allow modules/files: D09 specs、entity contracts/ports/resolver/workflow、chat factory/infrastructure/config/prompt、report resolver/application adapter、相关生产调用方和 tests/evals/live harness。
- forbid modules/files: 面试文档、数据库迁移、鉴权、前端、Skill/记忆功能、D07/D10、生产新依赖和无关重构。
- include required tests: baseline、tests-first、单元/合同/eval/集成/Compose/受保护真实 E2E/全量回归/CI。
- include required logs/metrics: resolver path、candidate count、model calls、repair count、failure code、elapsed；敏感内容不记录。
- include rollback strategy: 里程碑级 Git 回滚；不建立运行时双轨。
- preserve these constraints: 默认测试零付费；真实验收不得以 skip 代替；报告未确认不 fan-out；模型不作权威源。
- keep these external references in mind: OpenAI schema-first、Tushare stock master、spaCy KB grounding/NIL、Rasa synonym normalization。
