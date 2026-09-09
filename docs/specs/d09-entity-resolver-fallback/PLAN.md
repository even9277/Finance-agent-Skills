# PLAN.md

## 1. Plan Metadata

- Plan name: D09 受控实体解析模型兜底与共享链路收敛
- Task type: Agent runtime / backend cross-module behavior migration and evaluation
- Status: Frozen for implementation review
- Target executor: Codex
- Related artifacts:
  - `docs/specs/d09-entity-resolver-fallback/REQUIREMENT_SPEC.md`
  - `docs/specs/d09-entity-resolver-fallback/CODEBASE_RECON.md`
  - `docs/specs/d09-entity-resolver-fallback/CLARIFICATION_QUESTIONS.md`
  - `docs/specs/d09-entity-resolver-fallback/SOLUTION_TRADEOFF.md`
- Repository root: `D:/FinanceProject/Finance-agent-Skills`
- Current branch: `feat/56-entity-resolver-fallback`
- GitHub Issue: `#56`
- Created date: 2026-09-08

## 2. User-facing Purpose

After this change, the user should be able to用真实自然语言输入一个不在小型静态目录中的 A 股公司名称，由统一实体解析链先执行代码/名称/别名/模糊匹配，再在必要时调用真实 OpenAI-compatible 模型提出候选，并由 Tushare 权威目录确认唯一代码；对话与报告消费同一个 canonical entity，歧义或无法确认时不会让下游 Agent 猜测。

The current problem is公开对话仅有 10 条左右静态目录，报告却直接信任 LLM 生成代码，另有兼容函数和 CLI 复制规则；模型输出没有统一 schema、权威回查、修复预算、失败码和跨场景 Trace，因而与既定面试口径不一致。

The success of this plan can be observed by：

- 确定性命中不调用模型；长尾查询走 `model_fallback` 且目录确认 canonical symbol。
- 幻觉/冲突代码被拒绝；歧义进入澄清；显式无效代码不被模型“修正”。
- 模型语法错误最多修复一次，语义错误不重试。
- 对话、报告与生产工具入口不再维护私有 Resolver；旧路径静态扫描为零。
- 报告未获得唯一已确认 stock 时不启动四个分析 Agent。
- 默认离线套件、Compose、全量回归、受保护真实模型+Tushare E2E、PR CI 全部通过。

## 3. Inputs Reviewed

- REQUIREMENT_SPEC.md: 可观察行为、范围、非目标、真实 API 门禁、旧路径删除、验收标准。
- CODEBASE_RECON.md: 对话/报告/工具/CLI 调用链、同步/异步边界、现有测试、配置、Trace 和风险。
- CLARIFICATION_QUESTIONS.md: 12 个问题的原因、候选方案与已采用决策；无 P0/P1 阻塞。
- SOLUTION_TRADEOFF.md: 选择 Option B“共享异步 Resolver + 模型/Catalog ports + 薄 Adapter”。
- Code files: `conversation/entity.py`、`contracts.py`、`ports.py`、`workflow.py`；chat factory/providers/trace；`backend/services/stock_resolver.py`、`agent_service.py`；Tushare client；Prompt registry；历史 CLI/工具调用方。
- Tests: `tests/unit/conversation`、`tests/contract`、`tests/evals/entity`、`tests/e2e/test_live_controlled_chat_chain.py`、报告服务测试、`Financial-MCP-Agent` 兼容测试。
- External references: OpenAI Structured Outputs、Tushare `stock_basic`、spaCy EntityLinker/LLM entity linking、Rasa EntitySynonymMapper；只复用模式，不新增框架。
- Repository rules: 根 `AGENTS.md`、`PYTHON_AGENT_ENGINEERING_STANDARD.md`、`pyproject.toml`、GitHub CI/live workflows。

## 4. Final Unified Direction

This iteration will在 `conversation` 领域边界形成唯一异步实体解析内核；用明确 ports 隔离模型和权威目录；用严格 schema、一次 syntax repair、Catalog grounding、稳定错误码和低敏 Trace 约束模型；将对话、报告、生产工具与 CLI 迁移到共享内核或薄 Adapter；迁移后删除旧 LLM-only/regex 策略；新增可复现 eval 与受保护真实 API E2E。

This iteration will not修改面试文档、数据库 schema、鉴权、前端公共协议、Skill/记忆所有权、报告正文结构、D07/D10，也不会引入 spaCy/Rasa/向量库或新的生产依赖。

The plan follows现有 domain/ports/adapters/factory/settings/prompt/trace/test 结构和 Option B；外部实践只用于严格 schema、KB grounding、NIL/fail-closed、alias normalization 与证券主数据校验。

## 5. Planning Assumptions

- Assumption: `backend.services.stock_resolver.resolve_stock()` 的既有异步返回形状可作为报告薄 Adapter 保留；旧内部 Prompt/解析代码必须删除。
- Assumption: `TushareClient.stock_basic()` 在授权环境可返回 `ts_code/name/list_status`；生产实现需要兼容 DataFrame/list-like fake，但不新增数据依赖。
- Assumption: 已有 OpenAI-compatible 配置和 `ChatOpenAI` 足以完成结构化候选调用；provider 不保证原生 strict JSON Schema，因此本地 Pydantic 校验仍为真门禁。
- Assumption: 用户已授权本任务持续执行至验收，并已授权真实受保护 API、提交、推送、PR、审核、修复与合并；仍不得扩展到未授权高风险范围。
- Assumption: `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` 是用户未跟踪文件，必须保持原样且永不暂存。

## 6. Changed Surface

| Surface | Involved? | Why | Risk | Verification |
| --- | --- | --- | --- | --- |
| Frontend | No | 公共请求/响应不变 | Low | 前端只跑既有回归/CI，不修改代码 |
| Backend API | Indirect | 对话/报告内部失败路径改变，schema 不变 | Medium | REST/WS/报告合同测试 |
| Database | No | 不改持久化模型 | Low | migration diff 为零；集成回归 |
| Cache | Yes, process local | Tushare 目录结果避免每轮全量调用 | Medium | TTL/fake catalog 单测；无 Redis schema 改动 |
| Agent runtime | Yes | Resolver 位于 route 与 report fan-out 前 | High | workflow/report fan-out 契约测试与 E2E |
| Tool calling | Indirect | 生产工具的 symbol fallback 改用统一 Adapter | Medium | 工具单测和旧路径扫描 |
| RAG / Memory | No behavior change | STM 只消费确认实体 | Medium | 继承/歧义/STM 既有测试 |
| MCP | No contract change | 下游工具 schema 不变 | Low | 受控链与工具回归 |
| Skills | No behavior change | Resolver 只在 Skill route 前提供 canonical entity | Medium | Skills 路由/eval 回归 |
| Tests | Yes | tests-first、eval、live E2E | High | 新旧测试全部执行 |
| Observability | Yes | 新 resolver path/calls/repair/failure/elapsed | Medium | Trace 单测与手工检查 |
| Security/Auth | No contract change | live 仍使用受保护 secrets | Medium | 无明文凭证、默认测试无外呼 |
| Build/Deployment | Config only | 安全 `.env.example` 与 live workflow 门禁可能补字段 | Medium | Compose config、CI、workflow dispatch |

## 7. Repository Context

### 7.1 Relevant Entry Points

- 对话 REST/WS：`backend/routers/chat.py` → `backend/application/chat/factory.py` → `ControlledChatUseCase` → `ControlledConversationWorkflow.run()`。
- 报告：`backend/routers/report.py` → `backend/services/agent_service.py` → `_build_initial_state()` → `resolve_stock()` → 四 Agent fan-out。
- 生产工具补全：`Financial-MCP-Agent/src/tools/chat_tushare_tools.py::_resolve_symbol()`。
- 独立 CLI：`Financial-MCP-Agent/src/main.py` 内嵌 `extract_stock_info()`；本轮迁移后删除内嵌策略。
- 历史 Skill executor：不属于公开主链；只维持模块可导入/测试，不重新接回运行时。

### 7.2 Relevant Call Chain

目标链路为：

`user text + confirmed STM entity` → `AuthoritativeEntityResolver.resolve()` → explicit code → exact name → alias → deterministic fuzzy → ambiguity/invalid hard gate → optional model candidate → strict schema/one syntax repair → Catalog validation → canonical entity/result metadata → chat route or report stock Adapter。

报告只有 `entity_type=stock` 且唯一确认才进入 `fundamental/technical/risk/macro` Agent；对话歧义返回 clarification，只有 confirmed entity 才能更新工作状态。

### 7.3 Existing Patterns to Reuse

- `conversation/contracts.py` typed dataclasses/enums 与 `ports.py` Protocol。
- `backend/infrastructure/chat/skill_rerank.py` 的 Pydantic `extra=forbid`、timeout/max retry 和 Settings 注入。
- `backend/infrastructure/memory/candidates.py` 的 async provider、严格 JSON envelope 与 typed errors。
- `Financial-MCP-Agent/src/prompts/chat/registry.py` 的版本化 Prompt 读取。
- `backend/application/chat/factory.py` 的生产依赖集中装配。
- `WorkflowEvent` + `SkillTraceSink` 的低敏结构化 Trace。
- pytest marker、离线 fake provider、Compose E2E 和 protected-live workflow。

### 7.4 Current Test Structure

- 领域/工作流单测：`tests/unit/conversation/`。
- 公共合同：`tests/contract/test_controlled_conversation_contracts.py` 及报告合同测试。
- 实体 eval：`tests/evals/entity/test_entity_eval.py` + `data/smoke.jsonl`。
- 离线应用 E2E：`tests/e2e/test_controlled_chat_chain.py`、`tests/e2e/offline_app.py`、Compose offline。
- 真实链路：`tests/e2e/test_live_controlled_chat_chain.py`，现有 case 使用显式代码，需增加真实 fallback case。
- 报告测试：`backend/test_stock_resolver.py` 当前是非门禁手工脚本，需替换/迁移为 pytest 受控测试；agent_service 相关单元/集成测试需按实际文件确认。

### 7.5 Current Observability Structure

- `conversation/workflow.py` 通过 `TraceSink.emit(WorkflowEvent)` 发阶段事件。
- `backend/infrastructure/chat/trace.py` 映射到 Skill trace，已有 run/stage/status/elapsed 等稳定字段。
- D09 在 `entity_resolution` 阶段增加低敏：`resolver_path`、`candidate_count`、`model_calls`、`repair_count`、`failure_code`、`catalog_status`、`elapsed_ms`；不得记录用户全文、模型原文、authorization header、token 或私有 Prompt。

## 8. Scope Control

### 8.1 In Scope

- 唯一 async Resolver、typed result/failure/path、模型与 Catalog ports。
- code/name/alias/fuzzy/inheritance/ambiguity 的确定性优先级与回归保护。
- OpenAI-compatible 模型 Adapter、严格 schema、一次 syntax repair、稳定错误。
- Tushare A 股目录 Adapter、本地稳定目录、受控缓存与 canonical normalization。
- chat factory/workflow、report adapter/agent_service、生产工具 fallback、CLI 的调用方迁移。
- 删除 `agent_service.extract_stock_info()`、旧 report Resolver 决策逻辑、CLI 内嵌解析函数与其他被确认的生产私有策略。
- Settings、`.env.example`、版本化 Prompt、Trace、测试/eval/live workflow 和必要技术 spec/report。
- GitHub Issue #56 分支上的提交、推送、PR、review、CI 修复、squash merge 与收尾。

### 8.2 Out of Scope

- 修改 `D:/FinanceProject/Finance/金融Agent项目描述文档` 或仓库内面试/成果口径文档。
- D07 报告 Agent 工具隔离、D10 组合/自选股。
- 数据库迁移、实体主数据持久化、别名管理 API/UI、全量定时同步。
- 基金/指数/行业板块的完整动态外部目录。
- 训练 NER/entity-linking 模型、向量检索、spaCy/Rasa runtime。
- 修改 STM/LTM 写入策略、Skill 合同、工具权限、鉴权和报告内容生成逻辑。
- 伪造或覆盖历史 93.9% / 4.4% / 90.7% 指标。

### 8.3 Allowed Files / Modules

- `docs/specs/d09-entity-resolver-fallback/**`。
- `Financial-MCP-Agent/src/conversation/entity.py`、`contracts.py`、`ports.py`、`workflow.py`、必要的 `__init__.py`。
- `Financial-MCP-Agent/src/prompts/chat/**`。
- `backend/application/chat/factory.py` 及仅为 Resolver 装配所需的 chat application 文件。
- `backend/infrastructure/chat/**` 中新/现有 Resolver model/catalog adapter 与 trace 映射。
- `backend/config.py`、`.env.example`。
- `backend/services/stock_resolver.py`、`backend/services/agent_service.py`。
- `Financial-MCP-Agent/src/tools/chat_tushare_tools.py`、`src/agents/skill_executor_node.py`、`src/main.py`，仅限迁移/删除私有 Resolver 调用。
- `Financial-MCP-Agent/src/tools/tushare_client.py`，仅在现有接口不足以做只读目录校验且不改变通用工具语义时。
- `tests/unit/conversation/**`、相关 backend/unit/contract/integration/e2e tests、`tests/evals/entity/**`、protected live workflow。
- CI 配置仅在新文件未进入既有 quality scope 或 live 命令必须精确扩展时修改。

### 8.4 Forbidden Changes

- Do not perform unrelated refactor or split unrelated large files.
- Do not reformat unrelated files.
- Do not modify generated files, build artifacts, eval run artifacts or reports.
- Do not add dependencies unless the user separately approves; current plan explicitly requires no new dependency.
- Do not change database schema, migration history or persisted contracts.
- Do not change public API request/response schema, SSE/WS event names or report output schema.
- Do not modify authentication/authorization, tool permissions, Skills or memory behavior.
- Do not modify secrets, real `.env`, credentials or deployment destinations; `.env.example` may contain safe placeholders only.
- Do not delete user data, branches outside the task, or unrelated files.
- Do not weaken, skip, xfail or remove existing tests/safety checks to obtain green results.
- Do not log raw user prompts, model responses, keys, headers, cookies or personal data.
- Do not touch any interview document or `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md`.
- Do not keep old/new Resolver behind feature flags, shadow mode or compatibility forks after migration.
- Do not reconnect historical `skill_executor_node` as a second public execution mainline.
- Do not touch files outside allowed scope without stopping for approval.

## 9. Interfaces and Dependencies

| Interface / Dependency | Current Role | Planned Change | Compatibility Requirement | Validation |
| --- | --- | --- | --- | --- |
| `AuthoritativeEntityResolver.resolve` | 同步静态解析 | 改为 async，接收可选 model/catalog ports，返回路径/失败元数据 | 所有生产和测试调用方同一提交序列迁移；不保留 sync Resolver | type check、调用图扫描、单元/工作流测试 |
| `EntityResolutionResult` | entity/candidates/confidence/clarification | 增加 typed resolver path、model/repair count、failure/catalog status | 旧消费者访问原字段保持语义 | contract tests |
| model port | 不存在 | 输入最小必要文本/实体类型，输出严格 typed proposal | domain 不依赖 LangChain/OpenAI | fake/contract/timeout/repair tests |
| catalog port | 静态字典内嵌 | lookup/search/validate canonical entity；生产 Tushare Adapter | 本地目录离线可用；外部失败不信任模型 | fake + Tushare adapter tests |
| `ControlledConversationWorkflow` | Resolver 在 route 前同步调用 | await 共享 Resolver，完整 trace metadata | REST/WS 外部协议不变；STM 仅写 confirmed | workflow/e2e/memory regression |
| `build_chat_use_case` | 装配 model/tool/skills | 注入 production Resolver dependencies | 每请求/进程缓存生命周期明确 | factory tests/import smoke |
| `resolve_stock(query)` | 独立 LLM-only 报告解析器 | 变为共享 Resolver 的 stock-only 薄 Adapter | 返回 `(company_name, sh./sz. code)` 形状暂不变 | adapter/report tests |
| report `_build_initial_state` | 解析失败仍继续 | 未确认/歧义在 fan-out 前稳定失败 | 成功报告路径不变 | fan-out spy tests |
| Prompt registry | synthesis/rerank | 增加 versioned entity resolve/repair prompts | Prompt 不散落 service；版本可追踪 | registry/adapter tests |
| Settings/env | 已有 `chat_resolver_model` | 增加 timeout、repair、fuzzy/catalog cache 等必要部署参数 | safe defaults；无业务层 `os.getenv()` | settings tests + `.env.example` review |
| Tushare Client | 异步只读数据 API | 复用 `stock_basic`，必要时只补安全字段适配 | timeout/retry/runtime governance 不绕过 | mocked adapter + protected live |
| Trace event | candidate_count/confidence | 增加低敏 path/calls/repair/failure/catalog/elapsed | 不改对外流事件 schema | trace unit tests |
| protected live workflow | 实码 600519 直达确定性路径 | 增加长尾自然语言 fallback case与环境门禁 | 默认 pytest 不执行；正式验收必须实际 green | local authorized run + workflow dispatch |

## 10. Engineering Implementation Contract

| Category | Files / modules | Required behavior or documentation | Verification | Status |
| --- | --- | --- | --- | --- |
| Architecture and dependency direction | conversation entity/contracts/ports; backend infrastructure/factory/report adapter | domain 不导入 backend/LangChain/Tushare；Adapter 实现 ports；router 薄；唯一 Resolver | import scan、pyright、review | Required |
| Docstrings, types, field meaning, and section navigation | 全部变更 Python 公共接口 | 中文 Google-style docstring；Args/Returns/Raises；字段解释 canonical 格式、置信度、状态和副作用；关键阶段短导航注释 | Ruff/Pyright/self-review | Required |
| Configuration, env, secrets, constants, and prompts | `backend/config.py`、`.env.example`、Prompt registry/assets | Settings 单一加载；Prompt 版本化；稳定 enum/错误码留代码；无真实值或散落 getenv | config/import tests、secret scan | Required |
| Terminal output, logs, traces, metrics, and artifacts | workflow/trace/model/catalog adapters | stable stage/status/elapsed/path/calls/repair/failure/catalog fields；无原文/凭证；live 不保存敏感 artifact | trace assertions、log review | Required |
| Validation, errors, retry/fallback, state, and compatibility | Resolver/model/catalog/report | strict schema；最多一次 syntax repair；语义失败不重试；显式非法代码不问模型；歧义不写 STM；报告不 fan-out；外部 schema 不变 | branch tests + contract/E2E | Required |
| Tests, Agent evaluation, and handoff evidence | unit/contract/evals/integration/e2e/CI/spec reports | tests-first；默认无外呼；真实 protected model+Tushare；历史指标不伪造；每里程碑报告证据 | test commands, PR checks | Required |

## 11. Test and Validation Strategy

### 11.1 Existing Tests to Run

- `uv run --locked pytest tests/unit/conversation tests/contract tests/evals/entity -q`：实体、工作流、合同与当前 eval 基线。
- `uv run --locked pytest backend -q`：报告/配置/service 回归。
- `uv run --locked pytest Financial-MCP-Agent -q -m "not live"`：CLI、工具与历史模块兼容。
- `uv run --locked pytest tests/evals -q -m "eval_smoke and not live"`：Agent 各阶段离线评测。
- `uv run --locked pytest -q`：完整默认回归，期望零失败且零真实外呼。
- CI 中现有 Ruff/Pyright 精确范围、frontend quality、Compose config/build、offline Compose E2E 均需 green。

### 11.2 New or Updated Tests Required

- `tests/unit/conversation/test_entity_*.py`：确定性优先、模糊阈值/差距、显式非法代码、模型触发/不触发、目录 grounding、幻觉拒绝、歧义、继承和 typed failure；行为改变前应有红测。
- model Adapter unit/contract tests：合法 JSON、fenced JSON 是否按严格合同处理、一次 syntax repair、二次失败、timeout、provider error、额外字段、语义错误不 repair、无敏感日志。
- Catalog Adapter tests：A 股 code/name 一致、不同交易所、空结果、重复/歧义、Tushare异常、TTL/cache，使用 fake client。
- workflow/trace tests：await Resolver；resolver metadata 完整；歧义/失败不 route、不工具执行、不写 confirmed STM。
- report tests：薄 Adapter 格式转换；成功才构建 AgentState；未识别/歧义/catalog unavailable 均不启动四 Agent；删除旧兼容函数后无引用。
- CLI/tool migration tests：入口调用统一 Adapter，不含本地解析表/Prompt。
- `tests/evals/entity/data/smoke.jsonl` 与 runner：精确、别名、typo/fuzzy、explicit code、invalid code、ambiguous、inherit、competing history、long-tail fake model、hallucination、repair。
- `tests/e2e/test_live_controlled_chat_chain.py` 或独立同目录 live 文件：真实自然语言长尾 A 股，真实 model + Tushare，从产品 workflow/API 入口执行并断言 path/code/budget。

### 11.3 Manual Smoke Tests

- 输入“帮我分析贵州茅台”：预期 deterministic exact/alias，`model_calls=0`。
- 输入稳定但不在本地目录的 A 股自然语言名称：预期 `model_fallback`，Tushare 确认规范代码，后续只读工具可执行。
- 输入“平安怎么样”：预期候选澄清，不调用工具、不写 confirmed entity。
- 输入不存在的显式六位代码：预期 invalid/not-found，不调用模型。
- 报告输入不可识别公司：预期任务明确失败且四 Agent spy 调用数为 0。

### 11.4 Agent/RAG/Tool Evaluation, if applicable

- 实体 eval 使用版本化 JSONL，至少覆盖上述 10 类行为，并分别统计 `entity_accuracy`、`clarification_accuracy`、`path_accuracy`、`invalid_rejection_rate`、`model_call_budget_violation_count`。
- 默认 eval 全 fake/离线；不把 live 波动混入 deterministic gate。
- 不把材料历史百分比作为当前结果；新 runner 输出实际 case 数和当次指标。
- live 只读，最多一个稳定长尾样例，无整轮自动重试；调用次数与 resolver path 必须可断言。

### 11.5 Expected Terminal / Logs / Trace / Artifacts

- 终端只显示测试摘要、稳定错误码与必要路径，不打印 query、模型原文、API key 或 header。
- Trace 至少包含 `stage=entity_resolution`、`status`、`elapsed_ms`、`resolver_path`、`candidate_count`、`model_calls`、`repair_count`、`failure_code`、`catalog_status`。
- eval artifact 如产生，只能包含脱敏固定样例、版本、聚合指标；不提交临时 `_runs`。
- 每个里程碑在 `docs/specs/d09-entity-resolver-fallback/milestones/mX/MILESTONE_EXECUTION_REPORT.md` 记录真实命令和结果；失败则写 `MILESTONE_EXECUTION_BLOCKED.md`。

### 11.6 Acceptance Criteria

| Behavior / Risk | Test or Check | Command / Method | Expected Result |
| --- | --- | --- | --- |
| 确定性优先 | unit/eval | focused pytest | exact/alias/fuzzy hit，model spy 0 |
| 模型仅兜底 | unit/workflow | fake model + path assertion | 只有 no-match 才调用，path 为 model_fallback |
| 模型 schema | adapter contract | focused pytest | extra/malformed 拒绝；最多一次 repair |
| 目录 grounding | catalog/resolver unit | fake Tushare matrix | code/name/type 一致才返回 entity |
| 幻觉/非法代码 | negative tests | focused pytest | fail closed，语义失败无 model retry |
| 歧义/记忆安全 | workflow/memory regression | focused pytest | clarification；无工具、无 confirmed write |
| 报告 fan-out 安全 | report spy test | backend pytest | 未确认实体时四 Agent 调用数 0 |
| 跨场景一致 | contract/integration | same input to chat/report adapters | canonical entity 相同，场景格式兼容 |
| 旧路径删除 | static scan | `rg` old functions/prompts/rules | 无生产私有 Resolver 定义/调用 |
| 可观测与隐私 | trace/log tests + review | assertions/secret scan | 字段完整，无原始敏感内容 |
| 默认无外呼 | full pytest | `uv run --locked pytest -q` | green；live deselected |
| Packaging | Compose/CI | docker compose/offline E2E | config/build/E2E green |
| 真实产品使用 | protected live | explicit `-m live` with gate | real model + Tushare，长尾路径成功，非 skip |
| Delivery | PR checks/review | `gh pr checks` + review | required checks green，无 P0/P1 review finding |

## 12. Milestones

### Milestone 0: Safety and Baseline Check

**Goal:** 确认分支、用户文件、允许范围、基线测试和外部凭证门禁，不做实现编辑。

**Files / Modules:** 只读 `AGENTS.md`、SOP artifacts、git status、pyproject/CI、相关测试与环境变量“是否存在”状态；不得输出值。

**Implementation Intent:** 建立可比较基线，确认 `docs/specs/D01...` 保持未跟踪/不触碰，记录当前 test count 和既有失败。

**Tests / Checks:** git status/branch；focused entity/contract/eval；backend/agent baseline；必要时完整默认 pytest；检查 live 所需变量仅输出 present/missing。

**Expected Result:** 基线 green 或已有失败被明确归因；没有允许文件上的用户冲突；live 凭证条件可知。

**Stop Condition:** 计划所需文件存在用户改动、基线失败与本任务无法区分、分支错误或 P0 条件缺失。

**Rollback Note:** 无代码编辑，无需回滚。

**Handoff Evidence:** m0 report、命令/通过数/耗时摘要、git status、凭证 present/missing 列表（无值）。

### Milestone 1: Lock Tests and Reproduction

**Goal:** 先用红测/评测锁定新合同、失败语义、跨场景一致性和 live 门禁。

**Files / Modules:** 仅 allowed test/eval/live workflow 文件与 m1 report；不改生产代码。

**Implementation Intent:** 增加 fake model/catalog、async Resolver 预期、repair/grounding/trace/report fan-out/旧路径静态检查和长尾 live case。

**Tests / Checks:** 运行新增 focused tests；确认新增行为测试在旧实现上按预期失败，既有保护测试继续通过；数据 schema 可加载。

**Expected Result:** 每项需求有明确测试，失败原因正好对应 D09 Gap，不因测试代码错误失败。

**Stop Condition:** 无法在现有 pytest/marker 内表达合同、测试要求公共 API/schema 扩张、或真实 case 需要写操作。

**Rollback Note:** 只回滚本里程碑新增/修改测试与 eval 数据，不触碰用户文件。

**Handoff Evidence:** m1 report、红/绿测试列表、case matrix、未运行 live 的明确说明。

### Milestone 2: Shared Async Deterministic Resolver and Catalog Contract

**Goal:** 建立唯一 async 领域 Resolver、typed contracts/ports、确定性 fuzzy 与 Catalog grounding，不接真实模型 Adapter。

**Files / Modules:** conversation entity/contracts/ports/workflow；catalog infrastructure/factory；Tushare client（必要时）；对应 tests/evals；m2 report。

**Implementation Intent:** 保持 exact/alias/inherit/ambiguity；增加 canonical validation、explicit invalid gate、fuzzy threshold/margin、catalog status；迁移 workflow await；fake model port 先能驱动合同。

**Tests / Checks:** focused resolver/catalog/workflow/contract/eval；Ruff/Pyright 变更范围；确认 deterministic hit 模型调用为 0。

**Expected Result:** 除真实模型 Adapter 和调用方迁移外，领域合同与目录校验 green；无 SDK 进入 domain。

**Stop Condition:** 需要数据库/新依赖/公共 API schema，或 async 迁移影响超出允许调用图。

**Rollback Note:** 独立回滚 m2 source/tests；不保留同步/异步双实现作为修复。

**Handoff Evidence:** m2 report、接口/路径说明、focused green、依赖方向扫描。

### Milestone 3: Controlled Model Adapter, Repair, Settings, Prompt, and Trace

**Goal:** 接入受控 OpenAI-compatible fallback，完成 strict schema、一次 syntax repair、错误/预算和低敏 Trace。

**Files / Modules:** backend infrastructure/chat、config、`.env.example`、Prompt registry/assets、workflow/trace、对应 tests；m3 report。

**Implementation Intent:** provider max retry 0；总调用最多 2；本地 Pydantic 严格校验；repair 只为 syntax；catalog semantic failure 不再调用；Settings/factory 注入；trace 完整。

**Tests / Checks:** model adapter contract/timeout/error/log tests；workflow trace tests；focused Ruff/Pyright/pytest；secret scan。

**Expected Result:** fake provider 覆盖成功、repair、二次失败、timeout、额外字段、hallucination；预算和 trace 均可断言。

**Stop Condition:** provider 需要新增依赖、无法禁止 SDK 自动重试、或必须记录原始敏感内容才能工作。

**Rollback Note:** 回滚 adapter/config/prompt/trace 增量；不回退到旧 report Prompt。

**Handoff Evidence:** m3 report、调用预算证据、trace 示例字段、敏感日志检查结果。

### Milestone 4: Migrate Consumers and Delete Old Paths

**Goal:** 让报告、生产工具和 CLI 使用唯一共享 Resolver，删除旧私有策略并冻结报告 fan-out 失败语义。

**Files / Modules:** `backend/services/stock_resolver.py`、`agent_service.py`、chat tool、historical skill executor import、CLI、相关 tests；m4 report。

**Implementation Intent:** report thin adapter 做 stock-only/format mapping；未确认抛稳定应用错误；删除 `agent_service.extract_stock_info`、report inline Prompt/parser、CLI local table；历史 executor 只调用统一 Adapter且不恢复公开主链。

**Tests / Checks:** report/tool/CLI/legacy characterization tests；跨场景 canonical consistency；fan-out spy；`rg` 扫旧符号/Prompt/duplicate mapping；Ruff/Pyright。

**Expected Result:** 所有生产可达解析调用统一；报告未确认时下游调用 0；外部协议/成功路径兼容。

**Stop Condition:** CLI 迁移需要新的反向依赖或 packaging 改造超出范围；出现未知外部消费者依赖被删除函数。

**Rollback Note:** 回滚整个 m4 调用方迁移；不得只恢复旧 Resolver 形成双轨。

**Handoff Evidence:** m4 report、调用图 before/after、旧路径零结果、focused green。

### Milestone 5: Offline, Compose, and Full Regression Verification

**Goal:** 完成所有离线质量门禁、eval、完整回归和 Compose 产品链验证，只修具体失败。

**Files / Modules:** 原则上不新增功能；仅允许修复已证明与 D09 有关的 allowed files/tests，并更新 m5 report/PLAN governance。

**Implementation Intent:** 从窄到宽运行测试；比较 eval 指标；验证默认零真实外呼、Compose 构建和入口可启动。

**Tests / Checks:** focused suites → backend/agent/evals → Ruff/Pyright → full pytest → Compose config/build/offline E2E；检查 git diff/status。

**Expected Result:** 所有默认门禁 green；新 eval 分路径指标达 100% 固定 case 期望；无未解释 warning/error；用户文件未触碰。

**Stop Condition:** 同一失败两次修复仍不通过、需要越界改动、出现不稳定/外部依赖的默认测试。

**Rollback Note:** 只回滚本里程碑窄修；若核心设计失败回到相应里程碑整体处理，不堆兼容补丁。

**Handoff Evidence:** m5 report、完整命令/通过数/耗时、Compose 结果、diff summary。

### Milestone 6: Protected Real API Acceptance

**Goal:** 在用户授权环境从真实产品入口完成 OpenAI-compatible 模型 + Tushare 目录的长尾实体解析验收。

**Files / Modules:** live tests/workflow 仅在发现真实兼容问题时窄修；m6 report；不写敏感 artifact。

**Implementation Intent:** 检查变量存在性（不输出值）；运行一个只读、无整轮自动重试、静态目录未命中的稳定查询；验证 path/canonical code/call budget/catalog status 和下游可恢复结果。

**Tests / Checks:** `RUN_PROTECTED_LIVE_E2E=true uv run --locked pytest <D09 live test> -q -m live`；必要时运行既有 protected live chain；随后重跑受影响离线测试。

**Expected Result:** 测试实际执行且通过，不是 skip；模型调用和 Tushare 回查均由 spy/trace 证实；无敏感输出。

**Stop Condition:** 缺凭证/权限/网络，真实 provider 持续不兼容，或两次窄修失败；写 blocked report，不用 mock 冒充验收。

**Rollback Note:** live 无写操作；兼容窄修可独立回滚。

**Handoff Evidence:** m6 report，记录脱敏 case id、通过数、耗时、provider/model 标识（非密钥）、catalog status；不保存原始响应。

### Milestone 7: Review, PR, CI, Squash Merge, and Handoff

**Goal:** 完成自审、独立审查、提交推送、PR、CI 修复、squash merge 和本地收尾，让功能进入最终仓库。

**Files / Modules:** 仅 allowed source/tests/spec reports；Git/GitHub 元数据。用户 D01 文件继续不暂存。

**Implementation Intent:** diff/secret/old-path review；按仓库规范提交；push 当前分支；创建关联 #56 的 PR；执行独立 code review；修复 P0/P1；等待 required checks；squash merge；确认 main 包含提交且分支状态清晰。

**Tests / Checks:** `git diff --check`、secret scan、targeted/full tests evidence、`gh pr checks --watch`、merge 状态；必要时 rerun protected workflow；最终 `git status --short --branch`。

**Expected Result:** PR merged，CI green，无未解决 P0/P1，main 展示 D09 功能与技术 spec；用户文件未提交。

**Stop Condition:** GitHub auth/branch protection/CI 外部故障、review 发现需越界设计、或 merge 权限不足；输出 blocked report 和精确下一步。

**Rollback Note:** merge 前按里程碑 commit revert；merge 后若需回滚使用 PR revert，不 force-push main，不删除用户数据。

**Handoff Evidence:** PR URL、merge commit、checks、review conclusion、最终测试摘要、m7 report、PLAN Outcomes。

## 13. Execution Protocol

- Execute exactly one milestone at a time.
- Start each milestone by restating its goal and allowed files.
- Run `git status --short` before editing.
- Do not overwrite user changes；`docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` 永远不暂存。
- Do not modify files outside allowed scope.
- Do not move to the next milestone without reporting evidence and updating Progress/Decision Log/Discoveries.
- User has requested completion through acceptance, so after a successful milestone the executor may continue to the next without a new “继续”，但仍必须保持里程碑隔离。
- If a required change is outside scope, stop and ask for approval.
- If tests fail, inspect the narrowest relevant logs and fix only the concrete issue.
- If two consecutive repair attempts fail, stop and produce `MILESTONE_EXECUTION_BLOCKED.md`.
- Do not claim completion without verification evidence；protected live 的 skip 不算验收。
- Satisfy the Engineering Implementation Contract and report any `Not applicable` category explicitly.
- Every milestone report must list files inspected/changed, commands, results, blockers, rollback state and governance updates.

## 14. Rollback Plan

Before implementation, rollback is simply discarding the unexecuted plan. During implementation, each milestone should be isolated so it can be reverted independently.

- Branch strategy: 只在 `feat/56-entity-resolver-fallback` 实现；不直接改 main，不删除其他分支。
- Preserve user work: 始终先检查 status；不 add/commit `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md`；若 allowed file 出现未知用户改动立即停。
- Milestone rollback: 通过该里程碑窄 commit 或明确 diff 反向恢复；禁止 `git reset --hard`、`git checkout --` 和宽范围清理。
- Config rollback: 只回滚新增安全 Settings/.env.example 项，不触碰真实 `.env`。
- Database rollback: Not applicable；禁止迁移。
- Dependency rollback: Not applicable；禁止新增依赖。
- Production rollback: 合并后如必须撤回，用 GitHub revert PR；不在代码中恢复旧 Resolver 双轨。
- Stop instead of continuing: 任何 schema/auth/persistence/new dependency/敏感日志/外部写操作需求，或两次同类修复失败。

## 15. Progress

- [x] Milestone 0: Safety and Baseline Check
  - Completed: 2026-09-08
  - Evidence: focused 163/11/33 passed；full default `450 passed, 16 skipped, 9 deselected, 3 xfailed`；branch/status 与凭证存在性已脱敏核对。
- [x] Milestone 1: Lock Tests and Reproduction
  - Completed: 2026-09-08
  - Evidence: 22 focused cases collected；16 D09 expectations fail on the old implementation and 5 report safety cases pass；entity eval fails at the missing injectable async contract；3 protected live cases collect successfully；Ruff green。
- [x] Milestone 2: Shared Async Deterministic Resolver and Catalog Contract
  - Completed: 2026-09-09
  - Evidence: D09 domain/entity eval/route/rewrite 11 passed；Catalog + affected understanding/Skill/Web News 43 passed；broader conversation/contract/eval 125 passed；Ruff/Pyright green。
- [x] Milestone 3: Controlled Model Adapter, Repair, Settings, Prompt, and Trace
  - Completed: 2026-09-09
  - Evidence: 模型/目录/Trace focused 27 passed；conversation+eval 广回归 154 passed；Ruff/Pyright/diff/敏感日志扫描 green；Provider 自动重试为 0，总调用预算最多 2。
- [x] Milestone 4: Migrate Consumers and Delete Old Paths
  - Completed: 2026-09-09
  - Evidence: 报告/工具/历史执行器/解析 Adapter 81 passed；Ruff/Pyright/diff green；旧 Prompt、`_llm_extract` 和两处 `extract_stock_info` 生产扫描 0 matches；CLI import 与确定性报告入口冒烟成功。
- [x] Milestone 5: Offline, Compose, and Full Regression Verification
  - Completed: 2026-09-09
  - Evidence: full default 473 passed / 16 skipped / 10 deselected / 3 xfailed；eval 29 passed；frontend lint/type-check/54 tests/build green；Compose 367 passed / 7 skipped / 3 xfailed，资源清理后 `ps -a` 为空。
- [x] Milestone 6: Protected Real API Acceptance
  - Completed: 2026-09-09
  - Evidence: `d09-live-01` 真实 WebSocket 链 1 passed / 2 deselected / 0 skipped，64.24s；resolver model `tongyi-xiaomi-analysis-pro`，synthesis `glm-5.1`，Tushare source、`model_fallback`、`601012.SH`、catalog verified 和脱敏均断言通过；随后 22 项离线回归 green。
- [x] Milestone 7: Review, PR, CI, Squash Merge, and Handoff
  - Completed: 2026-09-09
  - Evidence: commit `d56f505` pushed；PR #57 opened and linked to #56；four CI jobs green；two blocking self-review findings fixed before commit；squash merge and final SHA are recorded by GitHub and the final handoff after this governance record is pushed。

## 16. Decision Log

| Date | Decision | Reason | Source |
| --- | --- | --- | --- |
| 2026-09-08 | 选择 Option B 共享异步 Resolver | 是满足模型受控、目录回查、跨场景一致和无双轨的最小可靠方案 | SOLUTION_TRADEOFF.md |
| 2026-09-08 | 模型只提出候选，Catalog 是权威 | 防止幻觉代码进入金融工具和报告 | 用户口径 + CLARIFICATION Q1 |
| 2026-09-08 | syntax repair 最多一次，语义失败不重试 | 有界成本、延迟和失败语义 | CLARIFICATION Q4 |
| 2026-09-08 | 报告未确认实体不启动四 Agent | 避免错误对象报告和无效费用 | CLARIFICATION Q9 |
| 2026-09-08 | 迁移后删除旧路径，不保留 feature flag 双轨 | 用户明确要求 | 用户决定 |
| 2026-09-08 | 真实模型+Tushare 测试为硬验收 | 用户明确要求真实模拟使用 | 用户决定 |
| 2026-09-08 | 历史百分比延后，当前只报可复现实测 | 缺少原始完整数据集 | CLARIFICATION Q12 |
| 2026-09-08 | M0 基线以完整默认 450 passed 为后续比较基准 | 先排除仓库既有失败再进入 tests-first | M0 execution evidence |
| 2026-09-08 | D09 tests freeze `resolve()` as the sole async contract with injectable `model` and `catalog` | 外部 I/O 不可阻塞，且测试必须证明 deterministic-first 与 grounding | M1 red tests |
| 2026-09-08 | 模型 Adapter 合同使用 `entity-resolution-v1` 严格 envelope | 使合法、syntax repair、schema error 和超时可分别断言 | M1 adapter tests |
| 2026-09-09 | 本地冻结目录作为离线权威层，动态 A 股只按 canonical code 经 Catalog Port 回查 | 保证常见路径零外呼，同时让模型候选不可绕过主数据 | M2 implementation |
| 2026-09-09 | fuzzy 使用局部窗口相似度、0.75 阈值和 0.08 top-gap | “贵州矛台”可确定性收敛，近分候选仍澄清 | M2 tests |
| 2026-09-09 | 模型输出使用 `entity-resolution-v1` 严格 Pydantic envelope，只有 JSON 语法错误允许一次修复 | 把格式修复与语义重试分离，确保总调用数可证明不超过 2 | M3 adapter tests |
| 2026-09-09 | 生产模型 SDK `max_retries=0`，超时/Provider/合同错误转稳定 typed error | 避免 SDK 隐式重试突破预算，并让 Trace 可解释失败 | M3 implementation |
| 2026-09-09 | 聊天与报告从 `get_entity_resolver()` 取得同一进程级 Resolver，其他入口只消费报告薄 Adapter | 保证唯一策略所有权，并让 Catalog TTL 缓存跨请求生效 | M4 migration |
| 2026-09-09 | 报告只接受一只 confirmed stock，并在构造 LangGraph state 前抛 `REPORT_ENTITY_UNRESOLVED` | 防止歧义、非股票和未确认候选进入四 Agent fan-out | M4 report tests |
| 2026-09-09 | M5 采用仓库既有分层命令和完整 Compose，而非只重复 D09 focused tests | 验证实体合同未破坏记忆、报告治理、流式协议、前端或容器装配 | M5 verification |
| 2026-09-09 | protected live 固定使用静态目录未包含的“隆基绿能”，并同时要求真实 Tushare 与真实流式 synthesis | 单凭显式代码或只测 Resolver Adapter 无法证明真实产品链的模型兜底 | M6 acceptance |
| 2026-09-09 | PR 前独立视角 review 把代码侧 `allowed_types` 与二次 repair 失败计数列为 blocking | Prompt 不是安全边界，且实际外呼次数必须与 Trace 一致 | M7 review |

## 17. Surprises & Discoveries

| Finding | Impact | Action |
| --- | --- | --- |
| 对话静态优先而报告 LLM-only，方向相反 | D09 不能是单文件补丁 | 共享内核 + 薄 Adapter，删除旧逻辑 |
| 任意六位数字当前会被当作有效实体 | 显式错误代码可污染下游 | 加 Catalog validity gate，且不调用模型修正 |
| `skill_executor_node` 已不在公开主链 | 不能借 D09 恢复第二执行器 | 只迁移其 import/测试兼容 |
| report unresolved 当前仍继续 fan-out | 产生错误对象和四路额外调用 | 入口前稳定失败并用 spy 验证 |
| 现有 live chat case 用显式代码 | 无法证明模型 fallback | 增加静态目录未命中的自然语言公司 case |
| live 配置分布在两个本地 `.env`：模型位于 Agent、Tushare/resolver model 位于 backend | 单一测试进程需沿用仓库现有 dotenv 装载顺序，不能假定 shell env 已设置 | M1/M3 增加仅校验 presence 的门禁与 Settings 装配测试，不读取/记录值 |
| Windows 上直接运行隔离的 `pytest.exe` 可能缺少仓库根导入，而 `python -m pytest` 正常 | 错误命令可产生伪 `ModuleNotFoundError` | 后续本地验证统一使用贡献指南规定的 `uv run --locked python -m pytest` |
| 直接 async 化只影响 9 处领域/eval 调用；公开工作流只需在 entity stage await | 迁移面小于初始风险估计 | 已机械迁移测试调用并用 125 项广回归验证 |
| 对模型 symbol 一律大写会把 `sector:` 变成 `SECTOR:` | 板块候选无法命中领域 canonical 目录 | 增加类型无关的 canonical symbol 规范化 helper，并锁定 sector 回归测试 |
| 共享 Resolver 构造时立即创建 ChatOpenAI，会让本地静态命中也依赖 SOCKS/网络栈 | 违反 deterministic-first，且离线报告入口可在真正解析前失败 | 模型客户端改为首次 fallback 懒构造；构造和失败映射均新增回归测试 |
| 前端 type-check/build 会把 tracked `tsconfig.node.tsbuildinfo` 的 TypeScript 版本改成本机依赖版本 | 构建产物会造成与 D09 无关的工作树噪声 | 用窄补丁恢复运行前内容，未修改前端源码或锁文件 |

## 18. Outcomes & Retrospective

- What changed: 对话、报告、CLI 与生产工具统一为 async deterministic-first Resolver；长尾模型候选经过 strict schema、代码白名单和 Tushare grounding；旧 Prompt/解析器/正则调用路径已删除。
- What was verified: full default 476 passed；frontend 54 passed/build green；offline Compose 367 passed；真实 D09 WebSocket + resolver model + Tushare + synthesis 1 passed；PR #57 四项 CI green。
- What remains risky: 当前动态 Catalog 只覆盖 A 股股票，基金/指数/板块长尾目录仍为 deferred；fuzzy 阈值仅由固定样例校准；仓库既有 deprecation/前端 chunk warnings 未纳入 D09。
- What should be improved next: 收集真实 bad cases 校准 fuzzy 与 alias；若产品要覆盖长尾基金/指数/板块，扩展同一 Catalog Port，不新增第二 Resolver；持续保留 protected live 单例费用门禁。

## 19. Deferred Work

- 完整证券主数据服务、数据库持久化、定时同步、版本和管理 UI。
- 基金/指数/板块全量动态目录与统一数据质量 SLA。
- 向量实体链接、训练模型、alias 人工反馈闭环和在线 A/B。
- 面试材料历史指标原始数据集与 artifact 复现。
- D07 报告 Agent 工具隔离、D10 Portfolio/Watchlist。

## 20. Handoff to Small-step Implementation

Start with Milestone 0 only. Run `git status --short`, confirm the branch, changed surface, user-owned untracked file, baseline tests and live credential presence without printing values. Do not edit implementation or test files until Milestone 1. Record all evidence in `docs/specs/d09-entity-resolver-fallback/milestones/m0/MILESTONE_EXECUTION_REPORT.md`, then update Progress and governance sections before moving forward.
