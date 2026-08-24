# PLAN.md

## 1. Plan Metadata

- **Plan name:** Finance Agent 受控对话主链迁移与重构
- **Task type:** 跨模块重构、新功能、测试/评测完善、工程治理
- **Status:** Frozen for implementation review
- **Target executor:** Codex / Cursor / Claude Code
- **Related artifacts:**
  - `REQUIREMENT_SPEC.md`
  - `CODEBASE_RECON.md`
  - `CLARIFICATION_QUESTIONS.md`
  - `SOLUTION_TRADEOFF.md`
- **Repository root:** `D:\FinanceProject\Finance-agent-Skills`
- **Historical read-only reference:** `D:\FinanceProject\Finance`
- **Current branch at freeze time:** `docs/1-engineering-contract`
- **Created date:** 2026-08-24
- **Selected solution:** 模块化单体 + Typed Contracts + 单一 Application Orchestrator

## 2. User-facing Purpose

完成后，用户应能从现有 Vue/FastAPI 聊天入口发起金融问题，并由一条唯一的受控主链依次完成实体解析、路由、问题改写、计划、校验、工具执行、证据验收、有界控制和总结。每个阶段都有真实代码、明确输入输出、有限失败语义、Trace 和离线验收，而不是散落在巨型服务中的隐式逻辑。

当前问题是：真实 REST/WS 都进入约 1,812 行的 `backend/services/chat_service.py`，再调用职责混合的 Router/Executor；面试材料描述的多个阶段在目标仓库中未成为独立、统一、可验证的生产路径。现有离线 Compose E2E 又替换了整个 Chat Service，因此不能证明真实受控链已跑通。

本计划成功的可观察标志：

- 最终目录中每个主链模块都有强类型合同和非空壳最小实现。
- 固定贵州茅台 `600519.SH` 请求通过 Fake Model/Tool 从公开入口跑到最终回答和 Trace。
- 歧义、工具超时、证据不足均到达有限且可解释的终态。
- REST 与 WebSocket 共用同一应用用例，不再维护两套业务编排。
- 切换完成后，旧编排、重复 Prompt 和旧导入被删除，不保留长期双 Runtime。
- 默认 CI 和 Compose E2E 全离线，不访问付费模型或生产服务。

## 3. Inputs Reviewed

- **REQUIREMENT_SPEC.md:** 唯一主仓库、受控状态、分层验证、默认离线、无长期 Adapter/双轨。
- **CODEBASE_RECON.md:** 当前入口/调用链、Chat Service/Executor 风险、状态/配置/Trace/测试现状。
- **CLARIFICATION_QUESTIONS.md:** 16 个模块映射、最小实现定义、首个案例和 6 阶段迁移方向。
- **SOLUTION_TRADEOFF.md:** 选择 Option B；拒绝薄门面、LangGraph 大图和纯观察方案。
- **Code files:** `backend/main.py`、`backend/routers/chat.py`、`backend/schemas/chat.py`、`backend/services/chat_service.py`、`backend/config.py`、`backend/db/models.py`、`Financial-MCP-Agent/src/agents/*`、`Financial-MCP-Agent/src/skills/*`、`Financial-MCP-Agent/src/tools/skill_trace.py`、前端 Chat API/composable/store。
- **Tests/CI:** `backend/test_*`、`tests/{unit,contract,integration,e2e,evals}`、`.github/workflows/ci.yml`、`docker/docker-compose.offline.yml`。
- **Project rules:** repository `AGENTS.md`、personal Python/Agent standard。
- **External references:** Anthropic workflow/routing、LangGraph state/context、DeerFlow/OpenClaw Skill 权限与渐进加载、Hermes 分层、Langfuse Trace 语义、OpenTelemetry GenAI 命名。

## 4. Final Unified Direction

本次迭代采用模块化单体：

```text
frontend
  → backend/routers + backend/schemas       # 协议、鉴权、映射
  → backend/application/chat                # 单一用例、事务、事件协调
  → Financial-MCP-Agent/src/conversation    # Typed State、阶段、规则、终止
  ← backend/infrastructure/chat             # DB/Model/Tool/Trace 端口实现
```

Agent Domain/Workflow 不依赖 FastAPI、SQLAlchemy 或 `backend`；Application 负责事务和用例；Infrastructure 实现外部端口；Router 不拼 Prompt、不调工具、不持有 Provider 私有字段。

本次迭代会先冻结现有行为，再创建最终合同和模块，以确定性最小实现 + Fake Provider 跑通全链，然后逐层迁移实体/路由/rewrite、计划/执行、证据/控制/总结，最后同时切换 REST/WS 并删除旧编排。

本次不把对话链迁入 LangGraph，不引入 Redis/消息队列/OTel Collector/微服务，不改数据库 Schema，不重构报告模式或长期记忆，不新增写工具，不承诺历史面试指标已经在新仓库复现。

## 5. Planning Assumptions

- **Confirmed:** 首个业务切片是贵州茅台 `600519.SH` 只读基础快照。
- **Confirmed:** 首版低置信场景返回文字澄清；`skill_confirm` 卡片延后。
- **Confirmed:** Milestone 2 的离线纵向切片通过后，才准备 GitHub Draft PR；实际 commit/push/PR 仍需用户明确授权。
- **Assumption:** 当前 Session/Message 表可以支撑首版，不需要 Schema 变化。
- **Assumption:** 当前只读工具至少能由统一 Tool Port 包装，并可用固定 fixture 模拟。
- **Assumption:** 现有 REST 响应字段和 WebSocket 基础控制帧必须兼容；新增内部状态不强制暴露给前端。
- **Assumption:** 功能分支短期新旧代码共存只用于开发，入口切换里程碑必须删除旧编排。
- **Assumption:** 当前未提交基础设施改动属于应保留工作；执行者不得清理或覆盖。

## 6. Changed Surface

| Surface | Involved? | Why | Risk | Verification |
| --- | --- | --- | --- | --- |
| Frontend | Limited | 保持/扩展流事件兼容，首版不做新卡片 | Medium | TS type-check、事件 contract、build |
| Backend API | Yes | REST/WS 最终共用单一 Use Case | High | API/WS contract + E2E |
| Database | Behavior only | 复用 Session/Message，调整事务所有权 | High | 隔离 PostgreSQL integration；无 Schema diff |
| Cache/Redis | No | 首版不引入 | Low | 确认无 Redis 必需配置 |
| Agent runtime | Yes | 建立全部受控阶段和状态机 | High | unit/contract/eval/full-chain E2E |
| Tool calling | Yes | 权限快照、validated plan、预算、Fake boundary | High | policy/schema/timeout/duplicate tests |
| RAG / Memory | Limited | 只读上下文装配，保留当前写回 | Medium | context unit/integration；不改 LTM 主体 |
| MCP | Limited | 仅作为 Tool Port 的既有实现来源 | Medium | provider contract；默认离线 |
| Skills | Yes | Registry snapshot、渐进视图、SOP 约束 | Medium | schema gate + 单 Skill eval |
| Tests | Yes | Fake 必须穿过真实 Orchestrator | High | 全部分层门禁 |
| Observability | Yes | 阶段 Trace、终止/错误/版本字段 | Medium | Trace assertions + redaction |
| Security/Auth | Compatibility | 必须保留 user/session 隔离 | High | auth contract/isolation test |
| Build/Deployment | CI only | 扩大 lint/type/E2E 覆盖 | Medium | CI/Compose config/build |

## 7. Repository Context

### 7.1 Relevant Entry Points

- `backend/main.py`: FastAPI 装配、DB/Trace/STM/LTM 生命周期。
- `backend/routers/chat.py`: `POST /api/chat/message` 与 `WebSocket /api/chat/stream`。
- `backend/services/chat_service.py`: 当前会话、记忆、Router/Executor、fallback、持久化和流式编排。
- `frontend/src/composables/useChat.ts`: REST/WS 消费和事件状态。
- `Financial-MCP-Agent/src/agents/skill_router_node.py`: 当前 route。
- `Financial-MCP-Agent/src/agents/skill_executor_node.py`: 当前计划/工具/证据/总结混合执行。
- `Financial-MCP-Agent/src/skills/skill_registry.py`: Skill metadata/spec/reference 入口。
- `Financial-MCP-Agent/src/tools/skill_trace.py`: 当前 Trace 事实源。

### 7.2 Relevant Call Chain

```text
POST /api/chat/message
  → chat.send_message
  → chat_service.chat_single_turn

WebSocket /api/chat/stream
  → chat.chat_stream
  → chat_service.stream_chat_single_turn

两者内部
  → Session/Message
  → route_chat_skill
  → execute_skill 或 fallback LLM
  → memory/compaction/persistence
  → response/stream + trace
```

目标调用链：

```text
Router/WS Presenter
  → ChatUseCase
  → Context/Preflight
  → ControlledConversationWorkflow
  → Stage Ports/Policies
  → ConversationResult + StageEvents
  → transaction/persistence
  → REST/WS Presenter
```

### 7.3 Existing Patterns to Reuse

- FastAPI Router + Pydantic Schema。
- SQLAlchemy AsyncSession 和当前 Session/Message/summary 模型。
- Skill Registry、Skill specs 和当前只读工具。
- `SkillExecutionResult`、`ToolEvidence`、claim lineage 中可被合同测试证明有效的行为。
- `skill_trace.py` 的 ContextVar、JSONL、递归脱敏和 exporter 隔离。
- pytest markers、offline eval fixtures、Docker Compose 隔离网络和 PostgreSQL。

### 7.4 Current Test Structure

- `backend/test_*`: 后端服务现有测试。
- `tests/unit`: 纯逻辑和 Trace 脱敏。
- `tests/contract`: HTTP/API 合同。
- `tests/integration`: 隔离 PostgreSQL。
- `tests/e2e`: FastAPI 和 Compose 离线链路；当前 `offline_app.py` 替换整个 Chat Service。
- `tests/evals`: entity/route/rewrite/planner/executor/verifier/synthesis/Skill/web-search 固定样例。

### 7.5 Current Observability Structure

- `Financial-MCP-Agent/logs/chat_traces.jsonl` 为本地 Trace 路径。
- `skill_trace_context` 关联 trace/session/user/turn。
- exporter 失败被隔离；Langfuse 可选。
- 当前仍有 `print`、f-string logger、动态 Trace dict 和 WebSocket 原始异常暴露问题。

## 8. Scope Control

### 8.1 In Scope

- Typed request/run/context/entity/route/rewrite/plan/step/evidence/verification/controller/result/event contracts。
- 单一 Chat Application Use Case 和受控 Conversation Workflow。
- Preflight/context、实体、两阶段路由、rewrite/extractor、Skill/工具权限、planner、validator、executor、verifier、controller/replanner、synthesis 的最小实现和逐步迁移。
- Provider/Tool/Persistence/Trace Ports 及 Fake 实现。
- REST/WS 兼容切换、消息事务语义和必要前端事件兼容。
- 单元、合同、集成、离线 eval、真实 Orchestrator Compose E2E 和可选 protected Live E2E。
- 与实际实现同步的架构、Prompt、接口、测试和面试证据说明。

### 8.2 Out of Scope

- 报告模式、新闻小模型、RAG、LTM 策略大改、持仓/交易和无关前端页面。
- 数据库 Schema/Alembic 迁移。
- Redis/队列/微服务/Kubernetes/OTel Collector/正式 CD。
- LangGraph 对话主链和 checkpoint/HITL。
- Skill Marketplace、动态安装、自修改和自动学习。
- 生产压测、SLA、真实写服务和未测量指标。

### 8.3 Allowed Files / Modules

新增目标模块：

- `backend/application/__init__.py`
- `backend/application/chat/`
- `backend/infrastructure/__init__.py`
- `backend/infrastructure/chat/`
- `Financial-MCP-Agent/src/conversation/`
- `Financial-MCP-Agent/src/prompts/chat/`
- `tests/unit/conversation/`
- `tests/fixtures/conversation/`
- `tests/contract/test_controlled_chat_contract.py`
- `tests/integration/test_controlled_chat_persistence.py`
- `tests/e2e/test_controlled_chat_chain.py`

允许窄改的现有模块：

- `backend/main.py`
- `backend/routers/chat.py`
- `backend/schemas/chat.py`
- `backend/services/chat_service.py`
- `backend/services/stm_context_service.py`
- `backend/services/memory_service.py`
- `backend/config.py`
- `Financial-MCP-Agent/src/agents/skill_router_node.py`
- `Financial-MCP-Agent/src/agents/skill_executor_node.py`
- `Financial-MCP-Agent/src/agents/skill_evidence.py`
- `Financial-MCP-Agent/src/agents/skill_spec_planner.py`
- `Financial-MCP-Agent/src/agents/tushare_reference_planner.py`
- `Financial-MCP-Agent/src/skills/skill_registry.py`
- `Financial-MCP-Agent/src/tools/skill_trace.py`
- `frontend/src/api/index.ts`
- `frontend/src/composables/useChat.ts`
- `frontend/src/stores/chatStore.ts`
- `tests/evals/` 对应模块固定样例和 runner
- `tests/e2e/offline_app.py`
- `docker/docker-compose.offline.yml`
- `.github/workflows/ci.yml`
- `pyproject.toml`
- 本规格目录和直接相关架构/测试文档

执行某个里程碑时，仅使用该里程碑列出的子集。上述列表不是一次性全部修改授权。

### 8.4 Forbidden Changes

- 不执行无关重构、无关重命名或全仓格式化。
- 不修改 `D:\FinanceProject\Finance` 中任何文件。
- 不把 `Finance` 加入 import path、依赖、镜像、测试运行时或同步脚本。
- 不创建旧 Runtime 兼容 Adapter、转发模块、双写或永久同义 feature flag。
- 不新增依赖，除非停止并获得明确批准。
- 不改变数据库 Schema、迁移、持久化字段或删除用户数据。
- 不破坏 REST 路径、请求/响应字段、鉴权或现有基础 WebSocket 事件，除非另立版本化规格并获批准。
- 不修改真实 `.env`、凭证、Secrets、生产服务或部署环境。
- 不启用交易、持仓修改、生产写或带副作用工具。
- 不提交日志、Trace 原文、运行 artifact、数据库、生成物或真实凭证。
- 不删除/放宽断言、ignore、类型规则、安全校验或 CI 门禁来通过测试。
- 不把默认测试改成访问付费模型、真实 Tushare、生产数据库或外部 Langfuse。
- 不把离线 Fake 结果或历史面试数字表述为当前生产指标。
- 不覆盖、清理或还原当前未提交的用户/上一轮基础设施改动。
- 未经明确授权，不 commit、push、创建/合并 PR、修改分支保护、release 或部署。
- 需要触碰允许范围外文件时必须停止并请求批准。

## 9. Interfaces and Dependencies

| Interface / Dependency | Current Role | Planned Change | Compatibility Requirement | Validation |
| --- | --- | --- | --- | --- |
| `POST /api/chat/message` | 同步聊天 | 映射到统一 Chat Use Case | 路径/现有字段不变 | HTTP contract + E2E |
| `/api/chat/stream` | 混合 token/JSON 帧 | 同一 Use Case 的事件 Presenter | 现有基础帧可继续消费 | WS event contract |
| `ChatMessageRequest/Response` | API Pydantic | 内部映射 Typed Request/Result | 现有字段兼容 | Pydantic/OpenAPI contract |
| `chat_single_turn` / `stream_chat_single_turn` | 当前业务入口 | 在切换里程碑由 Use Case 取代或收缩为非编排职责 | 内部调用方同步迁移；不保留转发壳 | import/call-path tests |
| Session/Message ORM | 会话事实源 | Repository Port 实现，事务归 Application | 无 Schema/语义破坏 | PostgreSQL integration |
| `AgentState` | 历史动态图状态 | 新主链使用独立 Typed contracts | 报告模式不受影响 | type/contract tests |
| Skill Registry/spec | Skill 发现/规则 | 只读 snapshot 与阶段视图 | 现有 5 Skill 内容兼容 | startup/schema tests |
| Tool Registry/MCP/Tushare | 外部数据 | Tool Port + permission snapshot | 只读；schema/version 可追踪 | provider contract |
| Model Provider | Router/LLM/synthesis | Structured Model Port | 供应商字段不进入领域状态 | Fake/provider contract |
| Prompts | 分散字符串 | 版本化 Chat Prompt assets | 迁移时删除重复真相源 | prompt snapshot/eval |
| `skill_trace` | JSONL + exporter | Stage/Tool/Event Trace Sink | 本地事实源和脱敏不弱化 | unit + full-chain trace |
| Eval fixtures | 部分模块样例 | 绑定新合同和版本 | 固定 case ID，不虚构基线 | eval smoke |
| `.github/workflows/ci.yml` | 当前离线门禁 | 覆盖新增模块和真实 Orchestrator E2E | 继续无 Secrets/网络 | workflow + CI |

## 10. Engineering Implementation Contract

| Category | Files / modules | Required behavior or documentation | Verification | Status |
| --- | --- | --- | --- | --- |
| Architecture and dependency direction | `backend/application/chat`、`backend/infrastructure/chat`、`src/conversation` | Router→Application→Domain；Infrastructure 实现 Ports；Domain 不 import backend/FastAPI/SQLAlchemy | import-boundary test + Pyright | Required |
| Docstrings, types, field meaning, navigation | 全部新增/修改 Python 公共接口 | 中文 Google-style docstring；跨模块强类型；字段说明来源/范围/持久化/隐私/消费者 | Ruff/Pyright/review | Required |
| Configuration, env, secrets, constants, prompts | `backend/config.py`、`src/prompts/chat`、Adapters | Settings 注入；无散落新 `os.getenv`；稳定枚举在代码；Prompt 版本化；无秘密 | unit + repo secret review | Required |
| Terminal, logs, traces, metrics, artifacts | `skill_trace.py`、Application/Workflow | 无散落 `print`；参数化 logger；stage/status/trace/run/session/elapsed/error；脱敏；Langfuse 可选 | trace/redaction/exporter tests | Required |
| Validation, errors, retry/fallback, state, compatibility | `src/conversation`、Application、Presenters | 边界逐层校验；稳定终态/错误码；瞬时错误有界重试；replan 有界；PARTIAL 明示；API 兼容 | unit/contract/integration/E2E | Required |
| Tests, Agent eval, handoff evidence | `tests/*`、CI、docs | 默认离线；Fake 只替换端口；版本化 fixtures；每里程碑报告命令/结果/风险/回滚 | 分层门禁 + execution report | Required |

## 11. Test and Validation Strategy

### 11.1 Existing Tests to Run

在环境可用且相应里程碑涉及范围时，按从窄到宽顺序运行：

1. `uv run --locked pytest backend -q`
2. `uv run --locked pytest Financial-MCP-Agent -q -m "not live"`
3. `uv run --locked pytest tests/unit tests/contract -q`
4. `uv run --locked pytest tests/integration -q -m integration`
5. `uv run --locked pytest tests/evals -q -m "eval_smoke and not live"`
6. `uv run --locked pytest tests/e2e -q -m e2e`
7. `uv run --locked pytest -q`
8. `uv run --locked ruff check backend Financial-MCP-Agent/src tests`
9. `uv run --locked pyright backend Financial-MCP-Agent/src tests`
10. `npm ci && npm run lint && npm run type-check && npm run build`，工作目录 `frontend`
11. `docker compose -f docker/docker-compose.yml config --quiet`
12. `docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e`
13. 清理：`docker compose -f docker/docker-compose.offline.yml down -v --remove-orphans`

如果现有环境/锁文件导致命令不可用，报告精确命令和原因；禁止修改依赖范围来绕过。

### 11.2 New or Updated Tests Required

| Candidate path | Behavior | Before change | Pass condition |
| --- | --- | --- | --- |
| `tests/unit/conversation/test_state.py` | 状态合法转换和唯一终态 | 不存在 | 非法跳转被拒；所有路径有限终止 |
| `tests/unit/conversation/test_entity.py` | 显式实体、继承、歧义 | 未覆盖统一合同 | 600519 解析；代词安全继承；平安澄清 |
| `tests/unit/conversation/test_route.py` | SOP/实时/fallback 边界 | 当前规则分散 | 路由不改实体；概念问题不误触工具 |
| `tests/unit/conversation/test_rewrite.py` | 三路由 schema 与原意 | 不存在 | 坏输出不能进入 planner |
| `tests/unit/conversation/test_plan_validator.py` | 权限、参数、DAG、证据 | 局部混在 Executor | 越权/环/缺证据全部阻断 |
| `tests/unit/conversation/test_executor.py` | timeout/retry/dedupe/budget | 覆盖不足 | 有界、无重复、required/optional 可区分 |
| `tests/unit/conversation/test_verifier_controller.py` | 空/错主体/stale/重规划终止 | 不统一 | 证据门控和预算动作正确 |
| `tests/unit/conversation/test_synthesis.py` | accepted-only、PARTIAL | 不存在 | rejected 不入上下文；弱证据不强答 |
| `tests/contract/test_controlled_chat_contract.py` | REST/WS/事件/错误码 | 仅最小 REST | 现有字段兼容、事件有序安全 |
| `tests/integration/test_controlled_chat_persistence.py` | 正常/失败/取消事务 | 未覆盖 | 无重复/半写/跨用户访问 |
| `tests/e2e/test_controlled_chat_chain.py` | 公开入口到真实 Orchestrator | 当前替换 Chat Service | Fake 只在端口；完整阶段/Trace 均出现 |
| `tests/evals/*` | entity/route/rewrite/plan/evidence | 部分 skip/静态 prediction | 新合同真实执行固定案例并报告 skip 原因 |

### 11.3 Manual Smoke Tests

- **成功路径:** 输入“查询贵州茅台 600519.SH 的基础信息和近期行情”；期望实体固定、实时链、validated plan、Fake 工具、accepted evidence、受控回答、Trace 完整。
- **歧义路径:** 输入“平安现在能买吗”；期望文字澄清、`NEEDS_CLARIFICATION`、工具调用数 0。
- **概念 fallback:** 输入“ETF 和 LOF 有什么区别”；期望 fallback，不创建金融工具计划。
- **工具超时:** 使用固定 timeout fixture；期望有限 retry 后 PARTIAL/FAILED，响应不暴露栈或凭证。
- **证据不足:** 缺 required evidence；期望 PARTIAL，明确缺口，不给当前强结论。
- **多用户隔离:** 用户 B 请求用户 A session；期望拒绝，A 的消息/画像不泄漏。

### 11.4 Agent/RAG/Tool Evaluation

- 复用现有 `tests/evals`，每个 case 固定 `case_id`、fixture/version、预期 route/tool/evidence/status。
- Milestone 2 最少覆盖上述 5 条纵向案例；后续逐阶段启用已有 entity/route/rewrite/planner/executor/verifier/synthesis 数据。
- 工程正确性与模型质量分开：默认门禁只判合同、状态、权限、证据、终止和 Trace；真实模型准确率只能由 protected Live/固定评测产生。
- 面试材料现有数字不作为本计划 pass threshold；新的 baseline 必须记录模型/Prompt/Skill/Tool schema/数据集版本。

### 11.5 Expected Terminal / Logs / Trace / Artifacts

- 终端仅输出阶段摘要，不输出完整 Prompt、工具 payload 或凭证。
- 每轮至少有 `trace_id`、`run_id`、`session_id`、`turn_index`、`workflow_name`、`contract_version`。
- 每阶段至少有 `stage`、`status`、`elapsed_ms`，失败时有稳定 `error_code`。
- Route 记录 family/skill/confidence/fallback reason；Plan 记录 plan ID/权限快照 hash；Tool 记录 tool/step/call/status/error/latency；Verifier 记录 accepted/rejected/missing/claim level；Controller 记录 action/reason/budget；结束记录唯一终态。
- 测试 artifact 只保存脱敏 Trace/报告，默认不提交运行目录。

### 11.6 Acceptance Criteria

| Behavior / Risk | Test or Check | Command / Method | Expected Result |
| --- | --- | --- | --- |
| 全部模块不是空壳 | import + unit review | Ruff/Pyright/pytest | 无 pass-only/TODO-only 公开实现 |
| 贵州茅台完整链 | offline E2E | controlled chain/Compose | 从公开入口经过所有适用阶段并返回受控回答 |
| 歧义不误调用 | entity/route unit + E2E | 平安案例 | NEEDS_CLARIFICATION，tool_count=0 |
| 计划不越权 | validator unit | 非白名单工具案例 | 在执行前拒绝 |
| 无无限循环 | controller/executor unit | timeout/missing fixture | 在冻结预算内终止 |
| 证据不足不强答 | verifier/synthesis unit/E2E | missing evidence | PARTIAL + 缺失维度 + 低 claim level |
| REST/WS 一致 | contract | 同一 fixture 两入口 | 终态、session、核心结果一致 |
| DB 一致性 | PostgreSQL integration | success/failure/cancel/retry | 无重复 assistant、半写或跨用户访问 |
| Trace 可归因 | Trace assertion | full-chain artifact | 阶段树、错误、版本、终态完整 |
| Secret 安全 | redaction test/review | unit + pattern scan | 常见凭证键不出现在输出 |
| 默认无网络付费 | isolated Compose | internal network + blank keys | 无凭证仍通过；不访问外网 |
| 兼容前端 | frontend checks | lint/type/build/manual | 现有聊天可消费，未知可选事件不崩溃 |

## 12. Milestones

> 后续实现必须严格一次只执行一个里程碑。每个里程碑完成后先报告证据并更新治理区，再等待下一次继续。

### Milestone 0: Safety and Baseline Check

**Goal:** 确认分支、未提交改动、允许范围、命令和重叠风险，建立不覆盖用户工作的安全基线。

**Files / Modules:** 只读检查仓库、`AGENTS.md`、本计划、CI/Test 配置；不编辑代码。

**Implementation Intent:** 记录当前 `git status --short`、分支、Python/Node/Docker 可用性、测试命令；识别现有脏文件是否与后续里程碑重叠。

**Tests / Checks:** `git status --short`、`git branch --show-current`、`uv --version`、`node --version`、`docker version`（不可用只报告）；检查测试收集而不启动外部服务。

**Expected Result:** 获得明确的可编辑/不可覆盖文件清单和命令清单；现有基础设施改动完整保留。

**Stop Condition:** 需要修改的文件含来源不明重叠改动；当前分支策略不允许安全隔离；P0 决策重新出现。

**Rollback Note:** 无代码改动，无需回滚。

**Handoff Evidence:** 状态清单、工具版本、可用命令、重叠风险和是否可进入 Milestone 1。

### Milestone 1: Characterization and Contract Tests

**Goal:** 在改变生产行为前锁定现有 REST/WS、会话事务、Router/Executor 和 Trace 行为。

**Files / Modules:** `tests/contract/`、`tests/unit/`、`tests/integration/`、必要的固定 fixtures；不改生产业务行为。

**Implementation Intent:** 增加正常、异常、取消/断连、歧义、fallback、工具路径和 Trace 的刻画测试；明确哪些是必须兼容行为、哪些是待修缺陷。

**Tests / Checks:** 新增 focused tests；现有 backend/Agent/contract regression；`git diff --check`。

**Expected Result:** 后续拆分最危险的协议、事务和错误路径有自动保护；已知缺陷用 `xfail(strict=True)` 或明确失败规格记录，禁止静默 skip。

**Stop Condition:** 现有行为与需求冲突但无法判定目标；测试需要修改数据库 Schema或访问生产服务；测试路径与现有用户改动冲突。

**Rollback Note:** 只回退本里程碑新增测试/fixture，不触碰已有用户测试。

**Handoff Evidence:** 测试文件、命令、通过/预期失败结果、兼容基线和发现的问题。

### Milestone 2: Typed Contracts and Offline Vertical Slice

**Goal:** 在最终目录建立全部受控阶段合同和最小真实实现，用 Fake 外部端口跑通成功/澄清/超时/证据不足纵向链。

**Files / Modules:** 新增 `Financial-MCP-Agent/src/conversation/`、`backend/application/chat/`、`backend/infrastructure/chat/`、`src/prompts/chat/`、conversation tests/fixtures；生产公开入口暂不切换。

**Implementation Intent:** 建立状态/终态/错误/事件/Ports；实现确定性 Context、Entity、Route、Rewrite、Permission、Planner、Validator、Executor、Verifier、Controller、Synthesis；Fake 只实现 Model/Tool/Persistence/Trace 外部边界。

**Tests / Checks:** 全部 conversation unit/contract；新 offline full-chain test；Ruff/Pyright；Trace/redaction；现有回归。

**Expected Result:** 每个模块均可执行且在同一 Orchestrator 中被真实调用；贵州茅台成功，平安澄清，timeout 有限终止，missing evidence 返回 PARTIAL。

**Stop Condition:** 需要新依赖/Schema/旧 Runtime Adapter；某模块只能用空壳伪造；核心合同无法在不反向依赖 backend 的情况下成立。

**Rollback Note:** 新模块和对应测试可整体回退；尚未切生产入口，不影响当前用户链路。

**Handoff Evidence:** 模块树、合同表、4 条纵向测试、Trace 示例、类型/静态检查、残余风险。

### Milestone 3: Entity, Routing, Rewrite, and Skill Discovery Migration

**Goal:** 将历史/当前有效规则重构进新合同，完成工具调用前的受控理解链。

**Files / Modules:** `src/conversation` 对应 stages；当前 Router/Skill Registry 的必要窄改；`tests/evals/{entity,route,rewrite,skill_activation}`。

**Implementation Intent:** 当前轮优先实体、代词继承/歧义；两阶段路由；三路由 rewrite union；约束/回答偏好窄抽取；Skill snapshot 和渐进视图。不得复制整份历史文件。

**Tests / Checks:** entity/route/rewrite/Skill unit、contract、offline eval；确认 Router 不改实体、坏 rewrite 不进 planner、reference 不扩大权限。

**Expected Result:** 请求在执行前获得稳定主语、能力链和结构化契约；低置信正常澄清。

**Stop Condition:** 历史规则没有可证明案例；需要改变 Skill 公共 Schema；需要前端确认卡片才能继续。

**Rollback Note:** 回退本里程碑 stage 实现，Milestone 2 确定性基线仍可运行。

**Handoff Evidence:** 迁移规则清单、评测命令/结果、bad cases、未迁移历史逻辑说明。

### Milestone 4: Planner, Validator, Executor, and Tool Governance Migration

**Goal:** 让所有工具调用来自权限快照内的 Validated DAG，并具有预算、去重、超时和失败分类。

**Files / Modules:** `src/conversation` plan/execution stages、Infrastructure tool adapters、当前 planner/executor/tool registry 的必要窄改、planner/executor eval/tests。

**Implementation Intent:** 提炼当前和历史中有效的 planner/validator/scheduler 规则；统一 ToolInvoker；禁止 Executor 自行扩展工具；首版仅只读工具和进程内健康状态。

**Tests / Checks:** permission/schema/DAG/dedupe/timeout/retry/budget unit；provider contract；planner/executor eval；full-chain regression。

**Expected Result:** 越权/非法计划执行前被拒；相同 action 不重复；瞬时失败有限恢复；不可恢复失败及时终止。

**Stop Condition:** 需要 Redis/新依赖/写工具/数据库变更；当前工具 Schema 无法稳定描述；两次修复仍无法通过窄测试。

**Rollback Note:** 回退本里程碑执行实现，保留 Milestone 2 Fake deterministic executor。

**Handoff Evidence:** validated plan/permission snapshot 示例、失败矩阵、工具 Trace、测试/eval 结果。

### Milestone 5: Evidence, Controller, Replanner, and Synthesis Migration

**Goal:** 建立唯一 Evidence/Verification/Control/Answer 合同，确保证据不足不会强答。

**Files / Modules:** `src/conversation` evidence/control/synthesis stages、版本化 prompts、当前 evidence/executor synthesis 的必要窄改、verifier/synthesis eval/tests。

**Implementation Intent:** 工具结果归一化；实体/时间/维度/质量/角色验收；规则 Controller；有界补证；Synthesis 只消费 AnswerContextPack。

**Tests / Checks:** empty/wrong-entity/stale/conflict/missing evidence；retry/replan termination；claim-level 和 rejected evidence 隔离；full-chain E2E/eval。

**Expected Result:** SUCCEEDED/PARTIAL/NEEDS_CLARIFICATION/FAILED 等终态清晰；无实时证据不输出当前强结论。

**Stop Condition:** 总结必须读取原始未验收 payload；Controller 不能证明有限终止；Prompt 变更没有固定评测。

**Rollback Note:** 回退本里程碑实现，恢复 Milestone 2 的确定性 Evidence/Answer 基线。

**Handoff Evidence:** VerificationResult/ControllerDecision/AnswerContextPack 示例、终止证明、eval 和 Trace 结果。

### Milestone 6: Persistence, REST/WebSocket Cutover, and Legacy Removal

**Goal:** 将公开 REST/WS 同时切换到单一 Chat Use Case，验证事务/事件兼容，并删除被替代的旧编排。

**Files / Modules:** `backend/routers/chat.py`、`backend/schemas/chat.py`、`backend/application/chat`、`backend/infrastructure/chat`、`backend/services/chat_service.py`、必要的 frontend chat API/composable/store、contract/integration/e2e。

**Implementation Intent:** Application 独占事务时点；REST 聚合结果，WS 映射事件；保留现有字段/基础帧；错误使用安全错误码/文案；删除旧 Chat Service 编排、重复 Prompt 和旧导入，不留转发壳。

**Tests / Checks:** REST/WS contract、PostgreSQL integration、auth isolation、disconnect/cancel、frontend lint/type/build、full regression。

**Expected Result:** 真实应用入口只剩一条主链；同步/流式核心语义一致；消息无重复/半写；前端兼容。

**Stop Condition:** 需要 API/DB/鉴权破坏性变更；无法在一个里程碑内删除旧双轨；当前脏文件重叠无法安全合并。

**Rollback Note:** 入口切换作为独立变更；一个里程碑 revert 恢复上一已验证入口和事务行为，不依赖长期 flag。

**Handoff Evidence:** 调用图、旧代码删除清单、API/WS/DB/frontend 检查、回滚验证说明。

### Milestone 7: Observability, Eval, CI, and Real Compose E2E Closure

**Goal:** 让 CI/Compose 验证真实 Orchestrator，并完成阶段 Trace、脱敏和版本化评测闭环。

**Files / Modules:** `skill_trace.py`、Trace Adapter、tests/evals/e2e、`offline_app.py`、Docker offline compose、CI、必要测试文档。

**Implementation Intent:** 移除“替换整个 Chat Service”的 offline E2E 装配；只注入 Fake external Ports；CI 覆盖所有新增模块；收集安全 Trace 证据。

**Tests / Checks:** 完整 Ruff/Pyright/pytest/eval/frontend/build/Compose；exporter failure/redaction；Compose cleanup。

**Expected Result:** 无网络/无凭证情况下，从前端/Nginx/FastAPI/新主链/PostgreSQL/Fake Tool 走完并通过；Trace 可归因且无秘密。

**Stop Condition:** Compose 需要外网/真实凭证；测试仍绕过 Orchestrator；CI 为通过而降低门禁。

**Rollback Note:** CI/Docker/E2E 变更与业务切换分开，可独立回退；不得删除已有有效门禁。

**Handoff Evidence:** 全命令摘要、Compose 服务/清理结果、Trace artifact 索引、CI 覆盖表、剩余 skips。

### Milestone 8: Verification, Narrow Fixes, Documentation, and Handoff

**Goal:** 只修复已验证失败，完成文档、面试口径状态标注、独立 Review 和 GitHub 交付准备。

**Files / Modules:** 前述已改文件的窄修、规格/架构/测试文档、Issue/PR 草稿材料；不得扩展功能。

**Implementation Intent:** 从窄到宽运行所有门禁；两次失败即停止；更新模块实现状态和“历史指标待复测”；生成里程碑执行报告、Review 输入和回滚说明。

**Tests / Checks:** 全量 Section 11 命令；`git diff --check`；diff/secret/generated artifact review；独立 Agent Review。

**Expected Result:** 所有默认离线门禁通过，未运行 Live 项精确记录，文档与真实代码一致；具备创建 Draft PR 的证据。

**Stop Condition:** 两次连续修复失败；发现未授权 Schema/依赖/API/安全变化；Live 测试需要不明确的生产权限。

**Rollback Note:** 窄修独立；文档不可覆盖历史事实；GitHub 操作前仍需用户明确授权。

**Handoff Evidence:** 最终测试矩阵、diff review、独立 Review 结论、剩余风险、Draft PR 文案、回滚命令说明。

## 13. Execution Protocol

- 严格一次执行一个里程碑，不得自动跨越。
- 每个里程碑开始时复述目标、允许文件和停止条件。
- 编辑前运行 `git status --short` 和分支检查。
- 不覆盖、清理、还原用户或上一轮未提交改动。
- 当前工作区已有 CI、AGENTS、Trace、frontend、pyproject、Docker、tests、docs、lockfile 改动；涉及重叠文件前必须先核对 diff 和归属。
- 不修改当前里程碑范围外文件；需要扩范围时停止请求批准。
- 每个行为变化先有 characterization/contract/regression case。
- 测试失败先运行最窄检查、查看日志并只修具体问题。
- 同一里程碑连续两次 repair attempt 仍失败时停止，生成 `MILESTONE_EXECUTION_BLOCKED.md`，记录命令、错误、推测、触及文件和所需决策。
- 完成里程碑后生成/更新 `MILESTONE_EXECUTION_REPORT.md`，报告文件、命令、结果、skips、Trace、风险和回滚状态。
- 没有验证证据不得宣称完成；离线结果不得宣称真实模型质量。
- 每个里程碑完成后更新 Progress、Decision Log、Surprises & Discoveries、Outcomes & Retrospective。
- 未经明确授权不 commit、push、PR、merge、release 或部署。
- Live E2E 仅在显式 marker、隔离只读账号、费用/次数/超时预算和无生产写的条件下执行；否则报告为未执行，不阻塞默认离线闭环。

## 14. Rollback Plan

在实现前，回滚只是放弃尚未执行的计划。实现期间，每个里程碑必须隔离，使其可以独立回退。

- **Branch strategy:** 每个可交付里程碑使用独立短分支/Issue/PR；当前文档分支不直接充当所有业务里程碑分支。创建或切换分支前需用户授权和重叠改动审计。
- **Preserve user work:** 不使用 `git reset --hard`、`git checkout --` 清理工作区；不移动/删除来源不明文件。需要回退时只对本里程碑明确新增/修改文件使用审查后的 patch 或经授权的 revert。
- **Before cutover:** 新主链未接公开入口，回退新增模块/tests 即可；当前生产行为不变。
- **Cutover milestone:** 入口切换和旧编排删除必须是单一可回滚里程碑；失败时整体回到上一个已验证入口，禁止通过永久 flag 维持双轨。
- **Configuration:** 本计划不新增依赖/必需 env；若意外需要则停止，不自行修改。不存在配置迁移回滚。
- **Database:** 本计划禁止 Schema 变更和数据删除；不存在数据库迁移回滚。任何 Schema 需求必须另开规格。
- **Dependencies:** 本计划禁止新增依赖；锁文件不因主链迁移随意变化。
- **Stop instead of rollback:** 无法区分用户改动与本里程碑改动、出现数据安全风险、需要生产权限或两次修复失败时，保留现场并停止。

## 15. Progress

- [x] Milestone 0: Safety and Baseline Check
  - Completed: 2026-08-24
  - Evidence: `uv run --locked pytest --collect-only -q` 成功收集 66/70 项并按默认规则排除 4 项 `live`；`uv lock --check`、两份 Compose `config --quiet`、Git 状态和工具版本检查通过。
  - Limitation: 当前 `docs/1-engineering-contract` 工作区保留上一轮未提交基础设施改动；进入 Milestone 1 前不得覆盖这些文件，创建/切换独立业务分支仍需用户明确授权。
- [x] Milestone 1: Characterization and Contract Tests
  - Completed: 2026-08-24
  - Evidence: 新增 1 份版本化离线路由 fixture，以及 Router/Executor、Trace、REST/WS、事务提交/失败回滚/跨用户会话隔离的 17 项刻画测试；聚焦测试 `16 passed, 1 xfailed`，仓库默认全量测试 `76 passed, 6 skipped, 4 deselected, 1 xfailed`。
  - Limitation: 严格 `xfail` 登记了当前 WS Router 会把内部异常原文返回客户端；该安全缺陷按冻结计划留到 Milestone 6 修复。现有 Starlette TestClient 与 `datetime.utcnow()` 弃用警告不在本里程碑修改。
- [x] Milestone 2: Typed Contracts and Offline Vertical Slice
  - Completed: 2026-08-24
  - Evidence: 新增 Typed Contracts、显式状态机、12 阶段单一 Orchestrator、Application Use Case、四类 Fake external Ports 和版本化 Prompt；成功/歧义澄清/工具超时/证据不足均从同一用例到达唯一终态。新增聚焦测试 `25 passed`，仓库默认全量 `91 passed, 6 skipped, 4 deselected, 1 xfailed`，离线 Compose `42 passed, 1 xfailed` 且容器/卷已清理。
  - Limitation: M2 按冻结范围尚未切换公开 REST/WS，Compose 中公开 `/api/chat/message` 仍验证旧入口；真实 Orchestrator 通过同一容器测试进程的 `test_controlled_chat_chain.py` 验证。全仓旧代码仍有 Ruff/Pyright 存量债务，新 M2 范围自身 Ruff/Pyright 为零问题。
- [x] Milestone 3: Entity, Routing, Rewrite, and Skill Discovery Migration
  - Completed: 2026-08-24
  - Evidence: 权威实体解析、两阶段路由、三路 typed Rewrite、约束/回答偏好、Skill 快照与渐进视图已接入单一 Workflow；M3 focused/eval/E2E `35 passed`，全量默认测试 `100 passed, 6 skipped, 4 deselected, 1 xfailed`，离线 Compose `51 passed, 1 xfailed` 且容器/网络/卷已清理。
  - Limitation: 公开 REST/WS、Planner/Executor/Evidence/Synthesis 和真实 LLM/Tushare 尚未迁移；高置信 SOP 在工具调用前以 `UNSUPPORTED` 诚实终止。固定离线案例全通过不等于生产准确率。
- [x] Milestone 4: Planner, Validator, Executor, and Tool Governance Migration
  - Completed: 2026-08-24
  - Evidence: 新增只读工具治理目录、冻结权限快照、强类型计划参数、DAG 校验和有界执行器；M4 focused `42 passed`，默认全量 `108 passed, 3 skipped, 4 deselected, 1 xfailed`，离线 Compose `56 passed, 1 xfailed` 且容器/网络/卷已清理。
  - Limitation: 公开 REST/WS 尚未切换；M4 仍使用 M2 的 Evidence/Controller/Synthesis 基线，实体缺失的 SOP 会在工具执行后诚实返回 `UNSUPPORTED`；真实 LLM/Tushare 尚未调用。
- [ ] Milestone 5: Evidence, Controller, Replanner, and Synthesis Migration
- [ ] Milestone 6: Persistence, REST/WebSocket Cutover, and Legacy Removal
- [ ] Milestone 7: Observability, Eval, CI, and Real Compose E2E Closure
- [ ] Milestone 8: Verification, Narrow Fixes, Documentation, and Handoff

## 16. Decision Log

| Date | Decision | Reason | Source |
| --- | --- | --- | --- |
| 2026-08-24 | 选择模块化单体 + Typed Contracts + 单一 Orchestrator | 同时满足快速完整架构、离线可运行、可回滚和长期维护 | User + SOLUTION_TRADEOFF |
| 2026-08-24 | 对话主链不使用 LangGraph | 当前链路线性，图运行时/checkpoint/HITL 成本不匹配 | Clarification + Anthropic/LangGraph evidence |
| 2026-08-24 | 首个案例为贵州茅台 600519.SH | 依赖少、只读、适合纵向证明 | User confirmation |
| 2026-08-24 | 首版低置信用文字澄清 | 避免把前端确认卡片纳入最短关键路径 | User confirmation |
| 2026-08-24 | Milestone 2 离线全链后再准备 Draft PR | 仓库展示不能是不可运行空壳 | User confirmation |
| 2026-08-24 | Redis/Langfuse/真实模型不是首版前置 | 默认离线、控制复杂度和成本 | Requirement + Clarification |
| 2026-08-24 | 功能分支可短期共存，切换时删除旧编排 | 兼顾安全迁移与禁止长期双轨 | Requirement + Solution Tradeoff |
| 2026-08-24 | 历史面试指标标记待复测 | 当前目标仓库没有完整可复现证据 | Codebase Recon |
| 2026-08-24 | 将当前脏工作区视为上一轮已知且受保护的基础设施改动，不在 M0 清理或拆分 | 改动归属可由本任务历史确认，但与后续 tests/CI/Trace 范围重叠 | M0 git audit + user-change protection |
| 2026-08-24 | M0 仅执行测试收集和静态配置检查，不运行测试正文、服务或 Live 调用 | 符合安全基线里程碑的只读目标，并避免把后续验收提前混入 M0 | PLAN Milestone 0 + small-step protocol |
| 2026-08-24 | 用户后续显式授权迁移历史本地测试凭证并执行真实只读 Live 验收 | 验证模型/Tushare/公开入口的真实可用性，同时继续禁止生产写和秘密入库 | User authorization + LIVE_VALIDATION_REPORT |
| 2026-08-24 | 用 GitHub Issue #3 和 `refactor/3-controlled-chat-characterization` 追踪 M1 | 用户授权按企业级 Git 规范创建 Issue；把需求、验收、分支和后续 Review 建立可追溯关联 | User authorization + GitHub Issue #3 |
| 2026-08-24 | M1 仅增加离线 characterization/contract/integration tests 和固定 fixture | 先冻结迁移前可观测行为，不以重构代码改变基线，也不默认访问真实模型或数据源 | PLAN Milestone 1 + small-step protocol |
| 2026-08-24 | WS 内部错误文本泄露用 `xfail(strict=True)` 登记，留到 M6 修复 | 让当前缺陷持续可见，同时避免在只读行为刻画里程碑越界修改 Router 和公开协议 | Contract test evidence + PLAN Milestone 6 |
| 2026-08-24 | 用户持续授权每个里程碑执行 Issue、短分支、commit/push、PR、CI/Review 和 Squash Merge | 后续里程碑不再逐次等待相同 GitHub 操作授权，但仍必须逐个里程碑、全门禁通过且禁止部署/生产写 | User explicit authorization |
| 2026-08-24 | M2 使用 frozen dataclass/StrEnum/Protocol 合同和确定性领域阶段建立纵向基线 | 在不切公开入口、不引入依赖/Schema/旧 Runtime Adapter 的情况下，先证明所有模块能由单一 Orchestrator 执行和回滚 | Issue #7 + M2 implementation |
| 2026-08-24 | M2 仅在 Model/Tool/Repository/Trace 四个外部 Port 使用 Fake | 防止测试替换核心编排，保证成功、澄清、超时、证据不足都覆盖真实新工作流 | PLAN M2 acceptance |
| 2026-08-24 | M3 在两次窄修复后停止，不提交未通过的分支 | 新增 Workflow 测试证明状态机不允许诚实的 M3/M4 边界终止；企业级门禁优先于“先同步不完整代码” | small-step failure cap + Issue #9 |
| 2026-08-24 | M3 恢复时只允许 `REWRITTEN -> SYNTHESIZING` 并增加状态机合同测试 | 支持“理解完成、执行未迁移”时经受控总结返回 `UNSUPPORTED`，同时禁止绕过 Planner 直接执行工具 | Resumed small-step review + focused E2E |
| 2026-08-24 | Stage1 只消费 Skill 冻结元数据，工具白名单和引用按选中 Skill 渐进暴露 | 避免 Router 越权读取执行细节，并让请求内路由和权限版本可复现 | M3 contract/eval evidence |
| 2026-08-24 | M4 用静态版本化 Tool Governance Catalog 与 Skill 执行白名单求交，生成请求级冻结权限快照 | 工具 Schema、只读属性和权限来源可审计，且不会让 Planner 或 Executor 自行扩大能力 | Issue #11 + M4 contract/eval evidence |
| 2026-08-24 | Executor 只接受 `ValidatedToolPlan`，按拓扑层执行并在执行边界再次去重 | 从类型和运行时两层禁止未校验计划、越权调用、重复 action 和依赖未满足执行 | M4 unit/E2E evidence |
| 2026-08-24 | M4 采用确定性 requirement-to-tool 映射，不直接复制历史 scheduler/planner Runtime | 复用历史业务意图但移除 `dict[str, Any]`、Registry 耦合和隐式运行态，保持当前主链为唯一真相源 | Finance comparison + M4 implementation |

## 17. Surprises & Discoveries

| Finding | Impact | Action |
| --- | --- | --- |
| 当前工作区已有大量基础设施未提交改动 | 后续 tests/CI/docker/pyproject 可能重叠 | Milestone 0 必须先审计，无法归属则停止 |
| 当前 Compose E2E 替换整个 Chat Service | 只能证明基础设施，不证明受控业务链 | Milestone 7 改为只 Fake 外部 Ports |
| 当前 `tool.uv.package=false` 且依赖 `sys.path` 注入 Agent 目录 | 正式包重组会扩大范围 | 本轮维持现状，包治理 Deferred |
| 当前 CI 的 Ruff/Pyright 覆盖偏窄 | 新模块可能逃逸静态检查 | Milestone 7 扩大到新增业务模块，但不得降低规则 |
| `pytest --collect-only` 成功收集 66 项，4 项 `live` 被默认排除 | 测试目录、marker 和导入基线可用 | Milestone 1 可从现有合同/单元测试旁新增刻画测试 |
| 测试收集出现 1 条 Starlette `TestClient` 弃用警告 | 当前不影响收集，但未来依赖升级可能放大 | 记录为技术债；本里程碑不升级依赖 |
| 当前分支 HEAD 与 `main`/`origin/main` 同为 `4570ee9`，但工作区有跨 tests/CI/Trace/frontend 的未提交改动 | 技术上可继续只读，直接开启业务开发会混合交付边界 | 下一里程碑编辑前先获得分支授权，并逐文件保留既有改动 |
| 本机使用 SOCKS5 代理，而锁定 Python 依赖没有 `socksio` | 默认项目客户端和 `pytest` Live 命令在请求发出前失败 | 本次用 uv 临时附加依赖验证；正式修复必须另行审查 `pyproject.toml`/锁文件 |
| FastAPI 启动阶段的 `print("✓")` 在 Windows GBK 终端失败 | 默认 Windows 进程无法完成公开入口启动 | Live E2E 用 UTF-8 进程重跑；后续按终端输出规范移除业务入口 `print` |
| 当前真实公开入口已完成 Router→Tushare→Evidence→Synthesis→Persistence | 证明现有旧主链和凭证可用，但不证明待建的新受控主链 | 作为迁移前真实基线保存，不升级为新主链验收结论 |
| Router 的模型选择异常会被静默吞掉并回退规则路由 | 可用性较好，但异常原因缺乏显式错误码和阶段状态 | M1 冻结兼容行为；在新合同/Trace 设计中显式表达降级原因 |
| WS Router 当前把 `str(exc)` 直接作为 error frame 的 message | 可能暴露数据库、模型或基础设施内部细节 | 用 strict xfail 建立安全回归门；M6 切换公开入口时改为稳定错误码和安全文案 |
| Chat Service 成功时提交一对 user/assistant 消息；执行异常依赖请求 Session 关闭回滚 | 当前没有写入半轮消息，但事务所有权仍隐含在入口生命周期 | M1 用 SQLite 集成测试冻结；M2/M6 将事务边界纳入 Application contract |
| M1 全量默认测试通过，但出现 Starlette TestClient 和 `datetime.utcnow()` 弃用警告 | 不阻塞本里程碑，未来依赖/Python 升级可能转为失败 | 记录为独立技术债，不在 characterization 里修改生产代码或依赖 |
| M2 的新范围 Ruff/Pyright 为零问题，但全仓严格扫描仍存在旧 Agent/Backend 的 Ruff 和 111 个 Pyright 错误 | 不能把新增模块的质量结论夸大为全仓无静态债务，也不能在单里程碑中无关扫修 | M2 报告区分新增范围门禁和全仓存量；M7 扩大 CI 时按受控迁移触及范围逐步收敛 |
| M2 Compose E2E 在容器内执行了新 Orchestrator 测试，但公开 HTTP 请求仍由旧 offline Chat Service 处理 | 已证明容器环境可运行新链，不等于公开入口已经切换 | M6 切换 REST/WS，M7 移除替换整个 Chat Service 的 offline 装配后再做真正公开全链验收 |
| Compose 启动旧数据库初始化逻辑会重复执行 `ALTER TABLE` 并在 PostgreSQL 输出事务中止错误，应用仍健康且测试通过 | 暴露既有初始化幂等性/日志噪声问题，不属于 M2 新代码 | 记录为基础设施技术债；禁止在 M2 越界改 Schema 初始化 |
| M2 转换表只允许 `REWRITTEN -> PLANNED/NEEDS_CLARIFICATION/FAILED` | M3 高置信 SOP 曾无法在 Rewrite 后以 `UNSUPPORTED` 诚实停在未迁移执行边界 | 已增加并测试 `REWRITTEN -> SYNTHESIZING -> UNSUPPORTED`；仍不允许绕过 Planner 执行工具 |
| 本地 `python -m pytest` 与 CI `pytest` 控制台入口的仓库根路径行为不同 | 四个新 eval 在首轮 Linux CI 无法导入 `tests.evals.runner`，业务断言尚未执行 | eval 测试显式注入 `PROJECT_ROOT`，并在本地增加与 CI 完全一致的命令复验；不降低 CI 规则 |
| M4 前 planner/executor eval 通过跳过不存在的历史模块而显示为 skip | 评测门禁没有实际运行受控 Planner/Executor | 重写为直接执行 `ControlledPlanner`、`PlanValidator` 和 `BoundedToolExecutor`；eval-smoke 从 6 passed/4 skipped 收敛为 9 passed/1 skipped |
| 工程文档引用 `observability-standard.md`，仓库实际文件为 `observability.md` | 自动导航和新手查找可能混淆，但不影响运行时 | 本里程碑读取并遵循实际文档；记录为文档命名债务，不越界新增重复真相源 |

## 18. Outcomes & Retrospective

- **What changed:** M0/M1 已冻结安全和旧行为基线；M2 建立 Typed Contracts 和完整离线纵向基线；M3 完成理解链；M4 已把版本化只读工具目录、冻结权限快照、强类型计划、DAG 校验和有界执行接入同一 Workflow。
- **What was verified:** 权限、Schema、非法/循环 DAG、预算、去重、依赖、超时、瞬时/永久失败和批次并发均有离线证据。全量默认测试为 `108 passed, 3 skipped, 4 deselected, 1 xfailed`，Compose 为 `56 passed, 1 xfailed`。
- **What remains risky:** 公开 REST/WS 未切换；M5 的 Evidence/Controller/Replanner/Synthesis 仍为 M2 单实体基线，M4 真实 Provider adapter 尚未闭环。旧 WS 泄露、全仓静态债务、数据库初始化噪声和弃用警告仍存在。
- **What should be improved next:** M5 只迁移 Evidence、Verifier、Controller、有界补证和 Synthesis，证明证据不足不强答、重试/补证有限终止；不得提前切公开入口或加入 Live 调用。

## 19. Deferred Work

- LangGraph 对话运行时、checkpoint、跨请求 HITL。
- 根 `src/finance_agent` 包重组和彻底消除 `sys.path` 注入。
- Redis 共享熔断、分布式限流、幂等和热缓存。
- 前端 `skill_confirm`、plan preview、step status、verification summary 卡片。
- OTel Collector、正式监控平台、生产压测/SLA/CD。
- Skill Marketplace、热安装、自修改/自学习。
- 数据库 Schema/Alembic 迁移。
- 真实交易/持仓写入或其他生产副作用。
- 未经版本化评测证明的历史指标升级为当前指标。

## 20. Handoff to Small-step Implementation

Milestone 4 已完成本地实现和全部离线/Compose 验收，待完成 Issue #11 的 commit、PR、CI、Review 和 squash merge 后交接。

下一个执行单元仅为 Milestone 5：Evidence、Controller、Replanner 和 Synthesis。开始前必须从最新 `main` 创建新 Issue 和短分支，保持公开 REST/WS、Schema、依赖与真实外部服务不变；先写空证据、错实体、过期、冲突、缺维度、有限终止和未验收证据隔离测试，再迁移实现。
