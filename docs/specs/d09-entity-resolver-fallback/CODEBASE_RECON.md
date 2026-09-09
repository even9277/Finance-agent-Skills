# CODEBASE_RECON.md

## 1. Reconnaissance Target

Requirement source: `docs/specs/d09-entity-resolver-fallback/REQUIREMENT_SPEC.md`、Issue #56、用户确认的 D09 Gap 与只读面试 Claim。

Focus areas: 对话/报告/CLI 实体入口、目录与别名、模型 Provider、结构修复、canonical 校验、STM 继承、Trace、评测和真实 API 门禁。

Out-of-scope reminders: 不修改面试文档、数据库/API/前端、D07/D10、Skills/Memory/工具执行业务；不触碰用户未跟踪 D01。

## 2. Project Overview

Project type: 金融 Agent 模块化单体，包含 FastAPI 后端、Vue 前端、自研受控对话工作流与 LangGraph 报告工作流。

Languages: Python 3.12、TypeScript/Vue。

Frameworks: FastAPI、SQLAlchemy、LangGraph、LangChain/OpenAI-compatible、Tushare、Pydantic、pytest。

Runtime / package manager: `uv.lock` + 项目 `.venv`，`pyproject.toml` 统一依赖和工具配置。

Main service type: FastAPI；Chat 使用 REST/WebSocket，Report 使用异步任务/SSE。

Frontend/backend split: `frontend/` 与 `backend/`；领域工作流主要位于 `Financial-MCP-Agent/src/`。

Test framework: pytest + marker（unit/contract/integration/e2e/eval_smoke/live）；Ruff；Pyright。

Deployment clues: Docker Compose；`.github/workflows/ci.yml` 跑 Python/前端/Docker/Compose；`live-e2e.yml` 仅手动触发受保护 Live。

Confirmed facts:

- 对话与报告当前没有共享一个实体解析实现。
- `chat_resolver_model` 已存在于 typed Settings 和 `.env.example`，但受控对话 resolver 未消费。
- 项目已有 Pydantic strict output、Prompt registry、低敏 WorkflowEvent、protected live 等可复用模式。

Assumptions: D09 不要求重做全量证券主数据平台，但必须让模型结果只能通过可替换的权威目录 Port 被接受。

## 3. Directory Structure Summary

| Path | Apparent role | Relevance | Notes |
| --- | --- | --- | --- |
| `Financial-MCP-Agent/src/conversation/` | 对话领域合同与受控工作流 | Direct | 当前同步静态 resolver 和 route 前调用点 |
| `backend/infrastructure/chat/` | 对话外部 Provider 适配 | Direct | 已有 OpenAI-compatible 结构化 rerank 模式 |
| `backend/services/` | 报告服务与历史股票解析 | Direct | 当前 `stock_resolver.py` 是不受控 LLM-only 实现 |
| `Financial-MCP-Agent/src/prompts/chat/` | 版本化 Chat Prompt | Direct | 可新增聚焦实体解析 Prompt，不散落在 Service |
| `Financial-MCP-Agent/src/tools/` | Tushare 客户端与工具 | Supporting | 可作为权威目录 Adapter 的既有外部能力来源 |
| `Financial-MCP-Agent/src/agents/` | 旧 Skills/报告 Agent | Medium | 两处反向导入 backend resolver；CLI 仍有重复正则 |
| `tests/evals/entity/` | 实体离线 golden set | Direct | 目前只有 7 条确定性样例 |
| `tests/unit/conversation/` | 对话理解与路由回归 | Direct | 多处同步调用 resolver，需迁移合同 |
| `tests/e2e/` | 对话/报告完整链路 | Direct | 当前 Live 对话使用显式代码，报告 Live 会 patch resolver |

## 4. Entry Points

### 4.1 Startup Entry

- `backend/main.py`：FastAPI lifespan 和 Router 装配。
- `backend/application/chat/factory.py::build_chat_use_case`：每请求装配受控对话 Workflow，目前没有实体 Provider 注入。
- `backend/services/agent_service.py::run_report_task`：报告后台入口，调用 `_build_initial_state` 后进入编译的 LangGraph。
- `Financial-MCP-Agent/src/main.py`：可运行 CLI 报告入口，内部仍定义独立正则 `extract_stock_info`。

### 4.2 Request / Task Entry

- Chat：`backend/routers/chat.py` → `ControlledChatUseCase` → `ControlledConversationWorkflow.run`。
- Report：`backend/routers/report.py` → `run_report_task` → `_build_initial_state`。
- Tool/legacy Skill：`chat_tushare_tools._resolve_symbol` 与 `skill_executor_node` 在缺少 symbol 时调用 `backend.services.stock_resolver.resolve_stock`。

## 5. Relevant Call Chain

```text
Chat message
-> build_chat_use_case
-> ControlledConversationWorkflow.run
-> ContextBuilder.build
-> AuthoritativeEntityResolver.resolve（同步、静态目录/别名/继承）
-> WorkflowEvent(entity_resolution: candidate_count/confidence)
-> route -> rewrite -> planner -> tools

Report command
-> run_report_task
-> _build_initial_state
-> backend.services.stock_resolver.resolve_stock
-> direct ChatOpenAI prompt + permissive JSON slicing
-> (company_name, sh./sz. stock_code) or silent (None, None)
-> AgentState -> LangGraph analysts

CLI report command
-> src/main.py local 20-pattern regex
-> AgentState -> LangGraph analysts
```

Confirmed segments:

- `workflow.py:392` 同步调用 `AuthoritativeEntityResolver.resolve`，随后 route 才运行。
- 对话 resolver 仅有代码正则、10 项代码内目录、alias substring、固定“平安”歧义和会话继承；不存在模型 Port。
- 报告 `stock_resolver.py` 每次构造 ChatOpenAI，并允许“根据常识补全代码”；没有目录回查或严格 Pydantic envelope。
- 报告未解析成功只记录 `REPORT_STOCK_CODE_UNRESOLVED`，仍可能把缺失实体交给四个分析 Agent。

Inferred segments:

- 受控对话 resolver 改为异步后，直接调用它的 unit/eval/route/rewrite tests 需要同步迁移。
- 报告 Adapter 可继续返回旧 `sh.600519` 格式以保护下游，但内部应消费 `.SH` canonical ID。

Unknown segments:

- 真实 Tushare 账户对全量 `stock_basic/fund_basic/index_classify` 的权限与延迟，需要 protected live 验证。
- 当前配置模型是否稳定支持 `with_structured_output`；本地现有供应商在 Skill rerank 已使用该能力，但实体用例仍需 Live 证明。

## 6. Related Files

### 6.1 Definitely Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `Financial-MCP-Agent/src/conversation/entity.py` | 确定性解析与继承 | 当前对话真源，但缺模型/目录 Port/路径字段 | candidate modification | High |
| `Financial-MCP-Agent/src/conversation/contracts.py` | Entity/result/error typed contract | 需表达 resolver path、模型/repair 计数和稳定错误 | candidate modification | High |
| `Financial-MCP-Agent/src/conversation/ports.py` | 领域外部依赖边界 | 当前无 Entity Model/Catalog Port | candidate modification | Medium |
| `Financial-MCP-Agent/src/conversation/workflow.py` | route 前解析调用与 Trace | 当前同步调用且只观测候选/置信 | candidate modification | High |
| `backend/infrastructure/chat/skill_rerank.py` | 结构化模型本地模式 | 可复用 Pydantic/structured output/Settings 方式 | read-only pattern | Low |
| `backend/application/chat/factory.py` | 生产装配 | 需要注入生产实体解析依赖 | candidate modification | Medium |
| `backend/services/stock_resolver.py` | 报告/旧工具解析入口 | 当前 LLM-only、散落 env/prompt、静默失败 | replace with thin adapter | High |
| `backend/services/agent_service.py` | 报告初始 state | 有废弃正则和 unresolved 继续执行 | candidate modification | High |
| `Financial-MCP-Agent/src/prompts/chat/registry.py` | Prompt 版本真源 | 当前无 entity prompt | candidate modification | Medium |
| `tests/evals/entity/*` | 实体 golden set | 现有 7 条，无法证明 D09 | candidate modification | Medium |

### 6.2 Probably Relevant

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/config.py`、`backend/.env.example` | typed Settings | 已有模型名，缺 provider/timeout/repair/目录边界 | candidate modification | Medium |
| `backend/infrastructure/chat/entity_resolution.py`（不存在） | 可能的 Provider/目录 Adapter 所有者 | 可隔离 LangChain/Tushare 与领域 | candidate addition | High |
| `Financial-MCP-Agent/src/tools/chat_tushare_tools.py` | 工具内缺 symbol 解析 | 当前反向导入 backend resolver | candidate migration | High |
| `Financial-MCP-Agent/src/agents/skill_executor_node.py` | 旧 Skill 执行预解析 | 当前反向导入 backend resolver | candidate migration/read-only after mainline check | Medium |
| `Financial-MCP-Agent/src/main.py` | CLI 报告入口 | 仍维护一套 20-pattern 正则 | candidate migration | Medium |
| `tests/e2e/test_live_controlled_chat_chain.py` | 真实 Chat 链 | 当前不会触发实体 fallback | candidate modification/add D09 harness | High |
| 报告 E2E/live harness | 报告真实链 | 当前 patch 掉 resolver | candidate extension | High |

### 6.3 Supporting Context

| Path | Role | Why relevant | Later action | Risk |
| --- | --- | --- | --- | --- |
| `backend/infrastructure/memory/candidates.py` | async strict JSON Provider | 可参考 envelope 校验和 `max_retries=0` | read-only | Low |
| `backend/infrastructure/chat/trace.py` | WorkflowEvent → JSONL | 已有低敏桥接，不应另建日志系统 | read-only/reuse | Medium |
| `Financial-MCP-Agent/src/tools/tushare_client.py` | 现有 Tushare SDK、缓存、超时 | 可为目录回查提供既有依赖，但当前错误日志会透传异常文本 | careful reuse | High |
| `.github/workflows/ci.yml` | 默认门禁 | 定义 Ruff/Pyright/pytest/Compose | read-only | Low |
| `.github/workflows/live-e2e.yml` | protected live | 可新增 D09 显式用例或复用本地保护开关 | candidate modification only if needed | Medium |

### 6.4 Out of Scope

| Path / Area | Reason |
| --- | --- |
| `D:/FinanceProject/Finance/金融Agent项目描述文档/` | 用户明确禁止修改，只读 Claim 来源 |
| `frontend/`、公共 schema/router | D09 不改变产品协议或交互 |
| 数据库模型/migrations | 实体解析不持久化新结构 |
| Report Agent 工具白名单、Portfolio | D07/D10 已明确暂停 |
| Skills/Memory 业务规则 | 只验证其消费同一解析结果，不改策略 |
| `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` | 用户未跟踪工作，不得触碰 |

## 7. Existing Patterns to Reuse

| Pattern | Example file | Why reuse it |
| --- | --- | --- |
| 领域 Port + backend Adapter 注入 | `conversation/ports.py`、`chat/factory.py` | 保持领域不反向依赖 LangChain/backend |
| 严格 Pydantic structured output | `backend/infrastructure/chat/skill_rerank.py` | 已验证候选范围、extra forbid、无 SDK 自动重试 |
| async JSON Provider + typed Settings | `backend/infrastructure/memory/candidates.py` | 适合模型异常翻译和离线 fake client |
| 版本化 Prompt registry | `src/prompts/chat/registry.py` | Prompt 变化可复现，不散落 Service |
| WorkflowEvent 低敏 Trace | `workflow.py` + `backend/infrastructure/chat/trace.py` | 复用单轮 trace，不记录 Prompt/响应 |
| protected live 开关和低敏 artifact | `tests/e2e/test_live_controlled_chat_chain.py` | 防误触发并证明真实产品入口接线 |

## 8. Data Flow and State

### 8.1 Input Data

- 当前用户消息；已裁剪 recent messages；STM `working_entity/working_candidates`。
- 报告入口只有 command 和 user_id。
- 生产模型配置与 Tushare Token 来自 Settings/.env。

### 8.2 Intermediate State

- Chat：`ContextPacket` → `EntityResolutionResult` → route/rewrite。
- Report：自由 JSON → `(company_name, stock_code)` → `AgentState.data`。
- 当前无统一候选 score、resolver path、repair count 或模型调用状态。

### 8.3 Persistent State

- D09 不新增持久化；对话已通过 working state 保存已确认实体，报告保存最终任务/报告。

### 8.4 Output Data

- Chat：`Entity` 使用 `600519.SH` canonical 格式；歧义通过 clarification/error code 终止。
- Report：下游期望 `sh.600519`/`sz.002594` 旧格式二元组。

### 8.5 Potential Data Mismatch Points

- `.SH` 与 `sh.` 两种格式并存。
- 对话静态目录允许任意 6 位代码构造未知实体；报告允许模型凭常识补代码。
- 报告模型返回合法 JSON 不代表实体存在或 name/code 对应。
- 报告 unresolved 继续进入 Agent；对话则通常澄清。
- CLI、报告 Service、工具/旧 Skill 存在重复或反向依赖解析路径。

## 9. External Dependencies

| Dependency | Where called | Input | Output | Error handling / fallback |
| --- | --- | --- | --- | --- |
| OpenAI-compatible LLM | `stock_resolver.py` | 完整 query + 内嵌 Prompt | 松散 JSON | 所有异常转 `(None,None)`；日志含异常原文 |
| OpenAI-compatible structured output | `skill_rerank.py` | 最小 top-K metadata | Pydantic envelope | 结构/候选越界抛 ValueError；无 SDK retry |
| Tushare | `tushare_client.py`/工具 | code 或目录 API 参数 | DataFrame/payload | 有 timeout/retry/cache；异常文本可能进现有工具日志 |
| Langfuse/skill_trace | `SkillTraceSink` | WorkflowEvent | JSONL/可选 exporter | Sink 失败隔离；当前实体字段不足 |

## 10. Tests and Evaluation Assets

### 10.1 Existing Tests

- `tests/evals/entity/data/smoke.jsonl`：7 条，覆盖静态股票、无实体、平安歧义、继承、多实体、代码格式、基金比较。
- `tests/unit/conversation/test_understanding_stages.py` 等：同步 resolver 与 route/rewrite 联动。
- `backend/test_stock_resolver.py`：手工脚本，不是受保护 pytest；会调用真实模型，且断言容许 company name 缺失。
- `test_live_controlled_chat_chain.py`：真实模型/Tushare，但显式 `600519.SH` 使 entity fallback 不会被调用。
- 报告 Live harness patch `resolve_stock`，不能证明真实解析接线。

### 10.2 Coverage Gaps

- 无确定性命中“模型调用数 0”合同。
- 无模型 fallback 成功、超时、限流、损坏结构、一次 repair、二次失败、幻觉 ID 或目录不匹配测试。
- 无 report/chat canonical 一致性或 unresolved 报告前置停止测试。
- 无 resolver path/repair/model count Trace 合同。
- 无 protected live 实体 fallback 与歧义“零工具调用”证据。

### 10.3 Candidate Test Locations

- `tests/unit/conversation/test_entity_resolution_fallback.py`
- `tests/contract/test_controlled_conversation_contracts.py`
- `tests/evals/entity/data/d09_v1.jsonl` + `test_entity_eval.py`
- `tests/unit/report/test_report_entity_adapter.py`
- `tests/e2e/test_controlled_chat_chain.py`
- `tests/e2e/test_live_entity_resolution.py`

### 10.4 Visible Test Commands

- `.venv/Scripts/python.exe -m pytest tests/unit/conversation tests/contract tests/evals -q`
- `.venv/Scripts/python.exe -m pytest tests/e2e -m "not live" -q`
- `.venv/Scripts/python.exe -m pytest -q`
- `.venv/Scripts/python.exe -m ruff check ...`
- `.venv/Scripts/python.exe -m pyright ...`
- protected live 需显式环境开关与 `-m live`。

## 11. Logging and Observability

### 11.1 Existing Logs

- Chat `entity_resolution` span：`candidate_count`、`confidence`、error code。
- Report task：仅 `resolved/unresolved` 状态；关联 task_id。
- 历史 `stock_resolver.py`：记录模型名、company/code 和异常原文。

### 11.2 Missing Logs

- resolver path、model called、repair count、confidence band、catalog validation、stable model failure code、prompt version。

### 11.3 Observability Risks

- 历史 f-string 日志包含模型解析出的实体与异常详情；Provider 异常可能携带 URL/请求信息。
- 面试口径要求 failure audit，但当前只能看候选数量和最终置信度。

### 11.4 Output-channel Separation

| Channel | Current implementation | Stable fields / format | Redaction | Gaps |
| --- | --- | --- | --- | --- |
| User/API result | Chat clarification / report task status | 现有协议 | 基本安全 | 缺 D09 精细错误投影 |
| Terminal progress | pytest/应用启动摘要 | 非统一 | 部分 | 手工 resolver 测试打印实体 |
| Logs | module logger/execution logger | task/阶段不完全统一 | 部分 | stock resolver 输出内容和异常 |
| Traces | WorkflowEvent → JSONL/Langfuse | trace/run/session/stage/status | key-based 低敏 | D09 path/repair/model 字段缺失 |
| Artifacts | protected live JSON、报告产物 | 测试自定义 | Live 较严格 | 无实体解析专用低敏验收 artifact |

## 12. Engineering Baseline Recon

| Area | Status | Evidence | Gap / implication |
| --- | --- | --- | --- |
| API/orchestration/domain/infrastructure boundaries | Partial | Chat 边界清楚；report/tools 反向导入 `backend.services.stock_resolver` | 需要共享领域底座和薄 Adapter |
| Agent/workflow/tool/prompt/model/memory/evaluation boundaries | Partial | Chat workflow/evals 已分层 | report resolver 把 Prompt、SDK、env、解析规则混在一文件 |
| Docstrings, types, and key intent comments | Partial | Chat dataclass/Protocol 较完整 | 历史 resolver Optional tuple 丢失失败语义，文档与实现过期 |
| File-section navigation vs module separation | Partial | 大工作流有职责分段 | `src/main.py` 内嵌 20-pattern parser，`agent_service.py` 留死兼容路径 |
| Typed configuration and secret handling | Partial | `backend.config.Settings` 已有 resolver model | 历史 resolver 散落 `os.getenv/load_dotenv` |
| Error, retry, fallback, and state semantics | Missing | Chat 有 AMBIGUOUS/ENTITY_REQUIRED | 模型异常静默为空、无 repair/semantic validation、报告继续执行 |

## 13. Risk Areas

| Area | Why risky | Likely touched? | Recommended handling |
| --- | --- | --- | --- |
| 金融实体正确性 | 错实体会让后续所有工具查错对象 | Yes | 目录真源、显式代码校验、语义失败前置停止 |
| 外部模型费用/稳定性 | fallback/repair 可能重复计费 | Yes | 确定性优先、调用计数、timeout、max_retries=0、最多一次 repair |
| Tushare 目录权限/频控 | 目录回查可能增加调用和延迟 | Maybe | Adapter/cache/受控 fallback；Live 验证权限 |
| async 合同迁移 | resolver 当前同步，直接调用点和 tests 较多 | Yes | tests first，一次迁移所有调用方，不保留同步双轨 |
| 报告兼容 | 下游依赖 `sh.` 格式和可空 tuple | Yes | 薄适配保持格式；未解析在 Agent 前稳定失败 |
| 日志隐私 | 当前记录模型实体与原始异常 | Yes | 删除内容日志，仅留低敏状态/异常类型 |
| 旧 CLI/Agent 路径 | 多份 parser 与 backend 反向依赖 | Yes/Needs decision | 迁移活跃入口；删除无调用兼容函数；历史独立测试脚本不作为生产真源 |

## 14. Unknowns and Assumptions

### 14.1 Unknowns From Missing Code Access

- 无；相关仓库和面试材料均可读。

### 14.2 Unknowns From Incomplete Requirement

- 是否必须复现材料中的历史百分比；按 P2 延后，不作为本轮硬门禁。

### 14.3 Unknowns From Ambiguous Architecture

- `skill_executor_node` 是否仍由公开产品入口运行；需在方案/计划前确认调用图，不能盲删。
- Tushare 目录 Adapter 是按候选 code 点查还是加载快照，需结合接口权限与验证成本选型。

### 14.4 Assumptions

- 用户“D09 按你的要求编写”允许使用既有 OpenAI-compatible 和 Tushare 依赖，但不允许新增生产依赖。
- `backend.services.stock_resolver.resolve_stock` 可以暂作为报告场景 Adapter 文件名保留，但内部旧 LLM 实现必须删除；这不是长期双轨。
- 产品公共协议不增加 resolver 私有字段；详细路径只进入领域结果和低敏 Trace。

## 15. Handoff to Next Step

下一步产生 `CLARIFICATION_QUESTIONS.md`，应明确：

- 权威目录回查的生产来源与不可用时行为。
- 哪些 legacy/CLI 调用方属于本轮必须迁移的活跃路径。
- report unresolved/ambiguous 是否在四 Agent 之前直接失败。
- 模型 fallback 的置信门禁、调用预算和 syntax repair 边界。
- protected live 用例的可复现长尾输入与费用边界。

后续方案重点考虑：`conversation/entity.py`、contracts/ports/workflow、Chat factory、独立 backend entity Adapter、Prompt registry、report stock Adapter、agent_service、实体 eval/live tests。

以下高风险区域在修改前需要由冻结计划明确授权：异步 resolver 公共签名、报告 unresolved 失败语义、Tushare 目录调用、旧 CLI/legacy Agent 路径删除。
