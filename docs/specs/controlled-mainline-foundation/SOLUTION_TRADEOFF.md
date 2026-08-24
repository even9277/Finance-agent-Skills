# SOLUTION_TRADEOFF.md

## 1. Tradeoff Context

本次决策不是选择“要不要重构”，而是确定如何在 Finance-agent-Skills 中直接建立唯一的受控 Agent 主链，同时避免把 Finance 历史目录中的技术债、隐式依赖和大文件结构原样复制进主仓库。用户已经明确否决长期兼容 Adapter 和新旧双轨实现，并要求工程过程稳定、可验证、可回滚、可用于简历讲解。

当前主调用链已经能提供聊天能力，但编排、模型调用、工具执行、数据库事务和事件输出集中在少数超大文件中；历史 Finance 目录拥有较完整的实体解析、两阶段路由、改写、Planner、Executor、Verifier、Controller、Replanner 和 Synthesis 资产，但这些资产并非可以直接视为生产级成品。因此必须同时解决两个问题：建立工程质量底座，以及按照模块边界直接重构唯一正式实现。

## 2. Inputs Reviewed

- REQUIREMENT_SPEC.md：已读取，确认工程治理、测试、CI、可观测性和受控主链分阶段迁移范围。
- CODEBASE_RECON.md：已读取，确认当前入口、调用链、大文件、配置、测试、Docker、日志和 GitHub 状态。
- CLARIFICATION_QUESTIONS.md：已读取，P0/P1 决策均已由用户确认。
- User decisions：Finance-agent-Skills 是唯一主仓库；直接重构，不做旧入口兼容 Adapter；其余推荐决策全部接受。
- External sources：OpenAI Agents Python、FastAPI Full Stack Template、GitHub 官方文档、Google SRE、Langfuse、OpenTelemetry、pytest、uv、Ruff、Pyright、DeerFlow、OpenClaw、Hermes Agent 和 GitHub Spec Kit。

## 3. User Decisions and Defaults

### 3.1 Confirmed Decisions

- 在 Finance-agent-Skills 中直接分模块重构，每个业务模块只保留一个正式实现。
- Finance 仅作为行为、失败案例、Prompt、评测和测试证据来源，不作为可运行依赖。
- 不建立旧 Runtime 到新 Runtime 的兼容 Adapter，不长期维护双轨实现。
- 不做整条链路的一次性大爆炸重写；模块输入输出先锁定，再原位替换。
- 首个实施 PR 只完善工程宪法、协作模板和结构规范，不迁移业务 Runtime。
- PR 默认运行离线门禁；容器集成按路径触发；真实模型与真实服务 E2E 必须显式触发。
- Live E2E 可以真实读取，但写操作只能落在隔离测试环境，永远禁止生产写。
- 个人仓库采用自审、独立 Agent Review、CI 证据和用户确认组成的 Review 闭环。
- 使用 Squash Merge；一个 Issue、分支、PR、可回滚主分支提交对应一个里程碑。
- Python 质量工具方向为 Ruff、Pyright、pytest、uv，采用新增代码严格、历史代码逐步消债。
- 定义厂商无关的 Trace 语义，Langfuse 作为导出实现；暂不建设 OTel Collector。
- Redis、正式生产 CD 和数据库迁移平台在出现真实需求前后置。

### 3.2 Conservative Defaults Used

- 公共 REST/流式接口和前端事件协议默认保持兼容；任何破坏性变更必须另开 Issue 并重新确认。
- 数据库 Schema、鉴权、用户数据和生产部署默认禁止变更。
- 新目标 Python 包可采用 src/finance_agent 布局，但每次迁移都必须在同一 PR 更新全部内部调用方并删除被替换实现。
- Port/Provider 只用于隔离模型、Tushare、MCP、数据库、记忆和 Langfuse 等外部依赖，不得演变成旧新实现转发层。
- 功能开关只用于独立能力启停或短期切流；稳定后删除开关和死代码。

### 3.3 Blocking Decisions

无。当前不存在阻止 Plan Freezing 的 P0 决策。

## 4. Core Decision Point

在不保留兼容 Adapter 的前提下，选择“历史实现原样合并”“结构化分模块直接替换”还是“整链一次性重写”，并冻结一种既能形成清晰目标架构、又能通过小 PR 和契约测试回滚的实施方向。

## 5. Reference Sources and Repository Evidence

### 5.1 Official Docs

#### Source: GitHub Protected Branches

**Link:** https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
**What was inspected:** PR、required checks、conversation resolution、linear history、force push 与规则绕过控制。
**Relevant practice:** 主分支变更通过 PR 和状态检查进入，限制破坏历史的操作。
**Reusable part:** Directly reusable
**Fit for this task:** 直接支撑“一里程碑一 PR、Squash 后可 revert”的交付与回滚模型。

#### Source: GitHub Issue and Pull Request Templates

**Link:** https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-request-templates/about-issue-and-pull-request-templates
**What was inspected:** 结构化 Issue Form 与 PR Template 的仓库配置方式。
**Relevant practice:** 在编码前固定问题、验收、风险、测试和回滚信息。
**Reusable part:** Directly reusable
**Fit for this task:** 可直接转化为本仓库 Feature、Bug 和 PR 模板。

#### Source: Google SRE Release Engineering and Canarying

**Link:** https://sre.google/sre-book/release-engineering/ ; https://sre.google/workbook/canarying-releases/
**What was inspected:** 可重复构建、自动化发布、小而自包含的变更、逐步暴露和回滚原则。
**Relevant practice:** 交付物可复现；变更单元小；回滚路径在发布前定义。
**Reusable part:** Directly reusable
**Fit for this task:** 当前没有生产平台，先落实可复现镜像、离线容器验收和 Git 回滚，比虚构 production deploy 更可靠。

#### Source: Langfuse Observability Best Practices

**Link:** https://langfuse.com/docs/observability/best-practices
**What was inspected:** trace、session、generation、tool observation 和稳定命名语义。
**Relevant practice:** 一次聊天轮次对应 trace，会话用于聚合；模型和工具调用使用正确 observation 类型；名称保持低基数。
**Reusable part:** Directly reusable
**Fit for this task:** 可映射 route、rewrite、planner、executor、verifier、synthesis 阶段，并避免动态 ID 污染名称。

#### Source: OpenTelemetry Logs Data Model

**Link:** https://opentelemetry.io/docs/specs/otel/logs/
**What was inspected:** 日志与 Trace 通过 TraceId、SpanId 和资源属性关联的标准语义。
**Relevant practice:** 结构化日志携带统一关联字段，不让每个模块自行发明一套字段。
**Reusable part:** Partially reusable
**Fit for this task:** 先复用字段语义和关联方式，不在本轮部署 Collector 或完整遥测平台。

#### Source: pytest Markers, uv, Ruff and Pyright

**Link:** https://docs.pytest.org/en/stable/how-to/mark.html ; https://docs.astral.sh/uv/guides/projects/ ; https://docs.astral.sh/ruff/formatter/ ; https://github.com/microsoft/pyright/blob/main/docs/configuration.md
**What was inspected:** strict marker、锁定项目环境、统一格式与 lint、分范围类型检查配置。
**Relevant practice:** 测试层级显式分类；依赖可复现；新代码严格检查；历史代码渐进收紧。
**Reusable part:** Directly reusable
**Fit for this task:** 与现有 pytest 和 TypeScript strict 思路一致，能避免一次性格式化全部历史文件。

### 5.2 Open-source Repositories

#### Source: OpenAI Agents Python

**Link:** https://github.com/openai/openai-agents-python/blob/main/AGENTS.md ; https://github.com/openai/openai-agents-python/blob/main/PLANS.md
**What was inspected:** 仓库入口说明、模块所有权、格式/lint/类型/测试命令、PR 约束，以及可独立验证的执行计划写法。
**Relevant practice:** Runtime 入口只做编排；内部职责分离；每个里程碑有可观察结果、验证命令、决策记录和恢复方式。
**Reusable part:** Directly reusable
**Fit for this task:** 适合用于本仓库 AGENTS.md、PLAN.md 和模块 PR 的验收规范。

#### Source: FastAPI Full Stack Template

**Link:** https://github.com/fastapi/full-stack-fastapi-template
**What was inspected:** 后端 pytest、真实数据库集成、Docker Compose 健康检查、前端 Playwright、分离 CI 工作流。
**Relevant practice:** API、数据库、镜像和浏览器路径都有可执行验证，而不是只在 README 声明。
**Reusable part:** Partially reusable
**Fit for this task:** 可缩放到当前 Vue + FastAPI + PostgreSQL 栈；不会照搬其业务模型和部署平台。

#### Source: DeerFlow

**Link:** https://github.com/bytedance/deer-flow/blob/main/AGENTS.md ; https://github.com/bytedance/deer-flow/blob/main/backend/AGENTS.md
**What was inspected:** 根级与子目录级工程规则、测试要求、离线测试与显式 live 测试分层。
**Relevant practice:** 根规则描述全局边界，局部规则描述模块命令；默认测试不依赖外部付费服务，live 通过环境显式开启。
**Reusable part:** Directly reusable
**Fit for this task:** 支撑本项目分层 AGENTS.md 和离线/Live E2E 的双层验收。

#### Source: OpenClaw Runtime Architecture

**Link:** https://github.com/openclaw/openclaw/blob/main/docs/agent-runtime-architecture.md ; https://github.com/openclaw/openclaw/blob/main/AGENTS.md
**What was inspected:** Runtime、Provider、工具/插件边界和仓库级协作规则。
**Relevant practice:** 外部能力通过清晰契约进入 Runtime，编排逻辑不散落 Provider 私有字段。
**Reusable part:** Conceptual only
**Fit for this task:** 借鉴边界与契约，不引入其完整多平台 Runtime 和插件生态。

#### Source: Hermes Agent

**Link:** https://github.com/NousResearch/hermes-agent/blob/main/AGENTS.md
**What was inspected:** Provider 抽象、管理器、Skill 资产和离线测试组织。
**Relevant practice:** 外部模型能力通过稳定接口管理，Skill 的实现和测试放在明确边界内。
**Reusable part:** Partially reusable
**Fit for this task:** 可用于 Provider/Skill 分层，但不采用自演进或完整平台机制。

#### Source: GitHub Spec Kit

**Link:** https://github.com/github/spec-kit/blob/main/docs/concepts/spec-of-specs.md
**What was inspected:** Spec、Plan、Tasks 和 Implement 的分阶段产物，以及按独立切片组织变更。
**Relevant practice:** 每个功能切片拥有自己的需求、计划和任务证据，避免只有聊天记录没有工程依据。
**Reusable part:** Directly reusable
**Fit for this task:** 当前 docs/specs 下的产物链可以直接承接后续模块 Issue 和 PR。

### 5.3 Local Project Patterns

| Local pattern | Evidence from CODEBASE_RECON.md | How to reuse |
| --- | --- | --- |
| FastAPI Router + application service | chat router 将请求交给 backend/services/chat_service.py | Router 继续只做协议适配；会话、事务和用例编排留在 application service |
| 节点化 Agent 能力 | 当前已有 skill_router_node.py 和 skill_executor_node.py | 新主链按实体、路由、改写、规划、执行、校验、总结拆边界，不让节点直接承担数据库事务 |
| pytest 与离线 eval | 当前根测试 51 passed、4 skipped、4 deselected；tests/evals 已存在 | 保留现有离线基线，增加契约、集成和 E2E，不重写已有效评测 |
| Docker Compose 全栈基础 | 当前已有 PostgreSQL、backend、frontend、pgAdmin | 扩展健康检查和离线 E2E；暂不为描述一致性虚构 Redis |
| 本地 trace 与可选 Langfuse | 当前 trace 默认开启、Langfuse 默认关闭 | 统一事件与脱敏后保留本地审计，Langfuse 作为可插拔导出 |
| 配置开关 | 当前多个能力默认关闭 | 只保留真正独立能力或短期切流开关，迁移稳定后删除过期开关 |

## 6. Reusable Patterns

### 6.1 Directly Reusable Patterns

- 一 Issue、一分支、一 PR、一主分支 Squash 提交，CI 通过后合并。
- Spec → Recon → Clarification → Tradeoff → Plan → 单里程碑实施的产物链。
- 默认离线测试、显式 Live E2E；真实服务凭证只从受保护环境注入。
- Router 薄、application service 管用例、Agent Runtime 管推理与工具编排、Provider 管外部系统。
- 稳定 trace/span 名称、trace_id 贯穿、结构化错误码和 key-based 脱敏。

### 6.2 Partially Reusable Patterns

- FastAPI 模板的数据库、Compose 与浏览器测试拆分可复用，但需要适配 Vue 和当前会话协议。
- src/finance_agent 可安装包结构可复用，但必须渐进迁移，不能一次移动全仓。
- Provider/Port 可用于依赖反转，但不能承担旧接口到新接口的长期兼容。
- Ruff/Pyright strict 先覆盖新包和跨模块边界，历史大文件在被迁移时消债。

### 6.3 Conceptual References Only

- OpenClaw 的完整 Runtime/插件/权限体系只作为边界设计参考。
- DeerFlow 的长任务、多 Agent 和沙箱能力只作为未来扩展参考。
- OTel Collector、指标后端和分布式 Trace 基础设施在出现部署目标后再选型。

### 6.4 Not Suitable for This Iteration

- 原样复制 Finance 整个目录或全部 Prompt。
- 为了“企业级”引入 Kubernetes、Redis、消息队列、微服务或虚假的 production deploy。
- 永久保留旧新两套实现、转发文件或双写链路。
- 一次 PR 同时迁移实体、路由、Planner、Executor、Verifier 和 Synthesis。
- 用全局 ignore、跳过测试或宽泛异常吞掉来获得表面绿灯。

## 7. Solution Options

### 7.1 Option A: Minimal Fix

**What changes:** 在当前 chat_service.py、skill_router_node.py 和 skill_executor_node.py 周围继续抽少量函数，并把 Finance 中缺失逻辑直接拼入现有模块。

**What does not change:** 现有目录、sys.path 注入、大文件职责和分散配置基本不变。

**Benefits:** 首次代码改动小，短期看到功能的速度快。

**Costs:** 技术债继续累积，模块边界和可独立测试性仍然不足。

**Risks:** 历史逻辑与当前逻辑交叉后更难解释、评审和回滚。

**Testing burden:** 中等；需要保护大文件中的多个隐式分支。

**Rollback difficulty:** 单次小改动较低，但长期越来越高。

**Engineering impact:**

- Architecture/module ownership: 继续混合职责。
- Documentation/types: 只能局部补充，核心状态仍可能是松散字典。
- Configuration/secrets/prompts: 散落问题难根治。
- Terminal/logging/tracing/artifacts: 只能补丁式统一。
- Errors/retry/state: 失败语义继续跨层耦合。

**When to choose it:** 仅适用于边界明确的单一缺陷，不适合当前跨模块治理与主链建设。

### 7.2 Option B: Structured Improvement

**What changes:** 先建立工程规则、测试和可观测底座；随后按实体解析、路由、改写、规划、执行、校验、总结等模块逐个直接迁入唯一目标结构。每个模块先做行为刻画和契约测试，再更新全部内部调用方并删除旧实现。

**What does not change:** 未被当前里程碑选中的模块不动；公共 API、数据库 Schema、鉴权和生产部署不变。

**Benefits:** 不养双轨；每次变更可评审、可验证、可 revert；最终目录与职责逐步收敛。

**Costs:** 开始功能迁移前要补工程宪法、测试夹具和可观测契约；每个模块必须认真定义输入输出。

**Risks:** 如果模块切片过大，仍会产生隐式跨层影响；如果只移动文件不重写边界，会形成“新目录里的旧代码”。

**Testing burden:** 中高，但可按模块分摊；契约、集成、离线 eval、Compose E2E 和受保护 Live E2E 分层执行。

**Rollback difficulty:** 低到中；每个 Squash PR 可单独 revert，镜像可回到上一已验证版本。

**Engineering impact:**

- Architecture/module ownership: 建立唯一 finance_agent 包与明确依赖方向，Backend 不拥有 Agent 领域逻辑。
- Documentation/types: 跨模块状态、公开函数、节点和工具必须类型化，并配中文 Google-style docstring。
- Configuration/secrets/prompts: 统一 typed Settings、版本化 Prompt 和安全环境变量入口。
- Terminal/logging/tracing/artifacts: 统一结构化字段、稳定阶段名、脱敏和有限产物。
- Errors/retry/state: 明确错误码、超时、有限重试、降级、终止条件和持久化边界。

**When to choose it:** 当前项目的推荐方案，兼顾简历可解释性、工程完整性和个人可维护成本。

### 7.3 Option C: Long-term Architecture Direction

**What changes:** 一次性把 Backend、Agent、Tools、Memory、Prompt、Observability 全部重写到新包，可能同时更换配置、依赖和部署结构。

**What does not change:** 理论上只保留公共协议和数据，但实际很难保证。

**Benefits:** 目标目录最快在表面上统一。

**Costs:** 变更巨大，代码评审和缺陷定位困难，测试建设跟不上改写速度。

**Risks:** 行为遗漏、隐藏依赖、生产凭证误用、数据兼容和无法安全回滚风险最高。

**Testing burden:** 极高，需要同时验证所有模块组合和前后端协议。

**Rollback difficulty:** 高；一个大 PR 的 revert 会连同已正确功能一起撤回。

**Engineering impact:**

- Architecture/module ownership: 目标可能清晰，但过程不受控。
- Documentation/types: 很容易为了赶进度只做结构搬迁。
- Configuration/secrets/prompts: 同时迁移会扩大泄密与配置漂移风险。
- Terminal/logging/tracing/artifacts: 新旧语义难比较。
- Errors/retry/state: 整链失败时难定位归因。

**When to choose it:** 仅当现有系统不可运行、无用户数据且有完整回归与专门团队时考虑。本项目明确 Deferred。

### 7.4 Option D: Observation-first Option

**What changes:** 只补契约测试、离线评测、Trace 和 E2E，不开始模块重构。

**What does not change:** Runtime 行为与目录保持原状。

**Benefits:** 风险低，能建立真实基线并发现隐式依赖。

**Costs:** 用户看不到主链能力迁移，结构债务不下降。

**Risks:** 如果长期停留在观测阶段，会变成“只搭测试不交付功能”。

**Testing burden:** 中等，主要是建设 Harness。

**Rollback difficulty:** 低。

**Engineering impact:**

- Architecture/module ownership: 不改善。
- Documentation/types: 只冻结现状契约。
- Configuration/secrets/prompts: 可先补安全测试。
- Terminal/logging/tracing/artifacts: 明显改善。
- Errors/retry/state: 只能观察，不能解决核心设计问题。

**When to choose it:** 不作为最终路线，但作为 Option B 每个业务模块开始前的强制门禁。

## 8. Decision Matrix

| Dimension | Option A Minimal Fix | Option B Structured Improvement | Option C Long-term Architecture | Option D Observation-first |
| --- | --- | --- | --- | --- |
| Scope | 小，但持续堆叠 | 中，按模块切片 | 极大 | 小到中 |
| Development Cost | 短期低、长期高 | 中，可分期 | 高 | 中 |
| Risk | 中，债务扩散 | 中，可控 | 高 | 低 |
| Reusability | 低 | 高 | 高 | 中 |
| Fit to Current Requirement | 低 | 很高 | 低 | 部分符合 |
| Local Pattern Fit | 中 | 高 | 低 | 高 |
| Test Burden | 中 | 中高、可分摊 | 极高 | 中 |
| Rollback Difficulty | 低到中 | 低到中 | 高 | 低 |
| Long-term Maintainability | 低 | 高 | 理论高、交付风险高 | 中 |
| Engineering-standard fit | 低 | 高 | 过程不符合小步交付 | 高但不交付功能 |
| Recommendation | 不选 | 选定；D 作为模块前置门禁 | 后置 | 嵌入 B，不单独停留 |

## 9. Recommended Solution

Selected option: Option B Structured Improvement，并把 Option D 的行为刻画、测试和可观测作为每个模块重构前的强制步骤。

Why selected: 它是唯一同时满足“直接重构、不做适配”“不一次性大爆炸”“每步稳定可回滚”和“形成可展示工程链路”的方案。

Why not the other options: A 会继续放大现有大文件和隐式依赖；C 的评审、验证和回滚半径不可接受；D 单独使用无法交付受控主链。

Local patterns reused: 现有 FastAPI Router/application service、pytest、离线 eval、Docker Compose、本地 trace 和可选 Langfuse；有效资产继续使用，缺口增量补齐。

External practices reused: OpenAI Agents Python 的模块与计划规则、GitHub 的 PR 保护、FastAPI 模板的分层测试、DeerFlow 的 offline/live 分流、Langfuse/OTel 的关联语义、Google SRE 的小变更与回滚。

Remaining risks: 当前核心文件过大；隐藏 sys.path 和环境变量依赖较多；历史 Finance 实现质量不一致；公共流式协议和数据库事务可能与 Agent 节点耦合。

What must be verified later: 每个模块的真实调用方、输入输出契约、失败与降级语义、Prompt 版本、工具副作用、REST/WS 兼容、离线基线、Compose E2E、Live E2E 和 trace 脱敏。

## 10. Unified Technical Direction

- 先完成工程宪法、GitHub 模板、目录/命名/注释/日志/测试规范，再建设可复现工具链和分层测试。
- 在 Financial-MCP-Agent 下逐步建立唯一可安装的 finance_agent 包；建议边界包括 contracts、workflows、entity_resolution、routing、rewriting、planning、execution、verification、synthesis、tools、prompts、providers 和 observability。
- Backend Router 只做协议适配；Backend application service 管会话、事务和用例；finance_agent 管受控推理主链；Provider/Port 隔离模型、Tushare、MCP、数据库、记忆和 Langfuse。
- 每个模块先从当前主仓库和 Finance 提取可观察行为与失败样本，形成 characterization/contract tests；随后直接在唯一目标模块实现、同 PR 修改内部调用方、删除旧实现/旧导入/重复 Prompt，不增加兼容转发文件。
- 公共 REST/WS、数据库 Schema、鉴权、用户数据和生产部署默认保持不变；需要改变时必须另开高风险 Issue 走完整决策链。
- Required CI 只使用离线 Fake/Fixture；Compose E2E 验证前后端与 PostgreSQL；Live E2E 显式使用受保护凭证、真实读取和隔离写入，永不生产写。
- 日志与 Trace 至少携带 stage、run_id/trace_id、status、elapsed_ms、error_code；模型、工具、handoff、retry、termination 和 fallback 可关联；所有日志、Trace 和产物先做 key-based 脱敏。
- 每个模块对应一个 Issue、分支、PR 和 Squash 提交；合并后通过 git revert 或上一已验证镜像回退，不长期保留旧实现作为回滚手段。
- Redis、微服务、Kubernetes、OTel Collector、正式生产 CD 和数据库迁移平台后置，直到有真实运行约束。

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| 直接改内部导入导致隐藏调用方断裂 | 迁移前用搜索和契约测试列全调用方；调用方与实现同 PR 更新；运行根级回归和 Compose E2E |
| 历史 Finance 逻辑被误当成正确答案 | 只提取行为意图、失败案例和测试证据；所有实现按新契约重写并独立 Review |
| 单个模块边界过大 | 一个里程碑只允许一个稳定职责；发现跨模块必要变更即停下重新规划 |
| 公共 API/WS 事件被无意改变 | 建立 REST/WS contract tests；公共协议变更默认禁止 |
| 新目录只是搬运旧大文件 | 为每个目标模块冻结 Owner、依赖方向、类型和最大职责；Review 检查跨层调用 |
| 真服务测试产生费用或副作用 | workflow_dispatch、测试环境 Secret、固定小样本、单并发、预算上限、真实读/隔离写、生产写禁止 |
| 日志或 Trace 泄露凭证和用户内容 | 集中 redaction，敏感 key 和 header 覆盖测试，原始 Prompt/响应默认不上传 |
| 数据库事务与 Agent 重试造成重复副作用 | application service 持有事务边界；工具标注副作用；只对瞬时错误有限重试并加入幂等保护 |
| 回滚时数据库或协议不兼容 | 普通模块 PR 禁止 Schema/破坏性协议变更；此类工作必须独立迁移和回滚方案 |
| 质量工具一次性制造巨量 diff | 新包严格、历史触达收紧；禁止全仓无业务价值格式化 |

## 12. Verification Direction

### 12.1 Engineering Contract for Plan Freezing

- Architecture/module ownership: 模块化单体；依赖只从 Backend protocol/application 指向 finance_agent public contracts，再指向 Provider ports；基础设施不得反向依赖 Router。
- Interfaces/docstrings/types: 公共 API、Agent state、节点、工具 Schema、错误和 Provider 接口必须显式类型；新增/修改 Python 使用完整中文 Google-style docstring 与意图注释。
- Configuration/secrets/constants/prompts: 单一 typed Settings；提交安全 .env.example；Prompt 版本化集中存放；禁止业务代码散落 getenv 和 Provider 私有字段。
- Terminal/logging/tracing/artifacts: 终端只输出阶段摘要；日志结构化；trace_id 贯穿；长 Prompt/响应只在安全且必要时存入受控产物；统一脱敏。
- Validation/errors/retry/state: 边界输入校验；稳定 error_code；不吞异常为“空成功”；只重试瞬时错误；有限次数/时间预算；副作用幂等；明确终止和降级。
- Tests/evaluation/delivery evidence: Ruff、Pyright、unit、contract、integration、offline eval、frontend type/lint/build、Compose offline E2E、受保护 Live E2E；每个 PR 给出命令、结果、跳过项、风险和回滚证据。

## 13. Deferred Work

- 具体实体解析、路由、改写、Planner、Executor、Verifier、Controller、Replanner 和 Synthesis 的实现优化，需要后续逐模块对齐统一面试口径与 SSOT。
- Redis、分布式锁、队列、微服务和 Kubernetes。
- 正式生产部署平台、自动生产 CD、Canary 基础设施和 OTel Collector。
- 数据库 Schema 迁移框架与数据回填。
- 公共 REST/WS 协议破坏性升级。
- 长期记忆架构重写和自动 Skill 自演进。

## 14. Handoff to Plan Freezing

Next step should use the Plan Freezing Skill and produce PLAN.md.

The plan should:

- follow selected option: 结构化分模块直接重构，Observation-first 作为每个模块的前置门禁。
- allow modules/files: 当前规格目录；首个实施里程碑只允许 AGENTS.md、CONTRIBUTING.md、docs/工程规范和 .github 模板；后续模块由各自计划重新冻结。
- forbid modules/files: 首个实施里程碑禁止业务 Runtime、API、数据库、前端功能、依赖和部署变更；任何跨里程碑修改先停下。
- include required tests: 文档/模板一致性检查、现有回归基线，以及后续的 unit/contract/integration/eval/Compose/live 分层门禁。
- include required logs/metrics: stage、run_id/trace_id、status、elapsed_ms、error_code、模块结果和降级原因；不承诺未测量的性能数字。
- include rollback strategy: 专用分支、一里程碑一 Squash PR、git revert、上一已验证镜像、禁止通过永久双轨实现回滚。
- preserve these constraints: 公共协议、数据库 Schema、鉴权和生产配置默认不变；真实读/隔离写；生产写禁止；中文注释与严格跨模块类型。
- keep these external references in mind: OpenAI Agents Python、GitHub 官方协作规则、FastAPI Full Stack Template、Google SRE、DeerFlow、Langfuse、OpenTelemetry 和 GitHub Spec Kit。
