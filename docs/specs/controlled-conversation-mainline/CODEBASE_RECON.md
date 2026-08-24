# Controlled Conversation Mainline: Codebase Reconnaissance

> 本文是只读代码勘察产物。它记录 `Finance-agent-Skills` 当前代码事实、可复用模式、风险和未知项，不是最终架构设计，也不批准实现变更。`Finance` 仅作为历史行为和模块资产的参考来源。

## 1. Reconnaissance Target

- **目标仓库**：`D:\FinanceProject\Finance-agent-Skills`
- **历史参考仓库**：`D:\FinanceProject\Finance`
- **勘察范围**：受控对话主链的前端入口、FastAPI 路由、应用服务、Agent Router/Executor、会话与记忆、配置、Trace、测试/E2E/CI，以及历史仓库的对应模块文件。
- **勘察限制**：本阶段只读；未修改业务代码、未运行测试、未启动 Docker、未调用模型或生产服务。
- **当前分支**：`docs/1-engineering-contract`。工作区已有基础设施改动，本报告不覆盖或回滚这些改动。

## 2. Project Overview

这是一个 Vue + FastAPI + SQLAlchemy 异步后端 + `Financial-MCP-Agent` Python Agent Runtime 的模块化单体。前端提供普通 REST 聊天和 WebSocket 流式聊天；后端负责鉴权、会话/消息持久化、短期上下文压缩、可选长期记忆、Skill 路由和 Skill 执行；Agent 目录提供金融 Skill、工具、证据和 Trace 能力。

当前运行时真相源是 `Finance-agent-Skills`。`Finance` 目录不应进入运行时依赖、`PYTHONPATH`、镜像或长期双轨同步；它只用于核对历史实现和已公开项目口径。

## 3. Directory Structure Summary

```text
Finance-agent-Skills/
├─ backend/
│  ├─ main.py                         # FastAPI 装配和 lifespan
│  ├─ routers/chat.py                 # REST/WebSocket 协议适配
│  ├─ services/chat_service.py       # 当前对话编排、持久化、模型/Skill/记忆混合实现
│  ├─ services/memory_service.py     # 结构化画像和 Mem0 访问
│  ├─ services/stm_context_service.py# 上下文预算、压缩入队
│  ├─ db/models.py                    # User/Session/Message/记忆/摘要等 ORM
│  ├─ schemas/chat.py                 # 聊天 API 请求/响应模型
│  └─ config.py                       # Pydantic Settings 和 feature flags
├─ Financial-MCP-Agent/src/
│  ├─ agents/skill_router_node.py    # 当前 Skill 路由
│  ├─ agents/skill_executor_node.py  # deterministic/agentic/hybrid 执行和证据
│  ├─ agents/skill_evidence.py       # 证据/claim lineage 辅助
│  ├─ agents/skill_spec_planner.py   # Skill spec 计划
│  ├─ agents/tushare_reference_planner.py
│  ├─ skills/                         # skill_spec.yaml、SKILL.md、skill registry
│  ├─ tools/skill_trace.py            # JSONL Trace、脱敏、可选 Langfuse exporter
│  └─ utils/state_definition.py       # 历史 AgentState，核心字段仍含 Dict[str, Any]
├─ frontend/src/
│  ├─ api/index.ts                    # Axios REST 和 WebSocket URL
│  ├─ composables/useChat.ts          # 聊天请求/流事件消费
│  ├─ stores/chatStore.ts
│  └─ views/ChatView.vue
├─ tests/
│  ├─ unit/                           # Trace 脱敏等纯逻辑
│  ├─ contract/                       # HTTP 健康和聊天响应契约
│  ├─ integration/                    # 隔离 PostgreSQL 探针
│  ├─ e2e/                            # FastAPI 离线链路和 Compose 入口
│  └─ evals/                          # entity/route/rewrite/planner/executor/verifier/synthesis 等离线样例
├─ docker/                            # 生产 Compose 和 offline Compose/E2E Dockerfile
└─ .github/workflows/ci.yml           # lint/type/unit/eval/pytest/Compose 门禁
```

## 4. Entry Points

### 4.1 HTTP REST

```text
POST /api/chat/message
  -> backend.routers.chat.send_message
  -> backend.services.chat_service.chat_single_turn
```

`send_message` 负责 Pydantic 请求映射、鉴权上下文和响应映射；它不应成为未来 Prompt、工具或业务状态的拥有者。

### 4.2 WebSocket streaming

```text
WebSocket /api/chat/stream
  -> backend.routers.chat.chat_stream
  -> backend.services.chat_service.stream_chat_single_turn
```

客户端首帧发送 JSON（`user_id`、`message`、可选 `session_id`）。服务端目前发送混合协议：普通文本 chunk 与 JSON 控制帧并存。已观察到的控制帧包括 `session_id`、`context_update`、可选 `compaction_queued`、`done` 和 `error`。每次连接只处理一轮。

### 4.3 Process lifecycle

`backend/main.py` 的 FastAPI lifespan 依次初始化数据库、Trace runtime、可选 Mem0/LTM worker、可选 STM compaction worker，关闭时停止 worker 并 flush Trace exporter。应用仍通过 `sys.path` 注入 `Financial-MCP-Agent`，这是后续重构的明确边界风险。

## 5. Relevant Call Chain

### 5.1 Current target-repository chain

```text
API/WebSocket
 -> session lookup/create
 -> optional user JSON profile action normalization
 -> persist user Message
 -> _run_skill_chat_if_enabled
      -> memory read (optional)
      -> recent history/running_summary route context
      -> route_chat_skill
      -> execute_skill
          -> skill registry/spec
          -> deterministic/agentic/hybrid tool planning and execution
          -> result normalization/evidence validation/claim lineage
          -> trace artifacts
 -> fallback LLM path when skills disabled or route=fallback
      -> clean profile action from reply / optional profile write
      -> persist assistant Message and turn counters
      -> enqueue STM compaction and LTM write (optional background task)
      -> commit and return REST tuple or stream events
      -> log_trace_finished
```

### 5.2 Responsibility concentration

`backend/services/chat_service.py` is approximately 1,812 lines / 87 KB. It currently owns session CRUD, history selection, STM compression, LTM context and enqueue, prompts, fallback model calls, Skill route/execution calls, profile-action parsing, response cleanup, persistence, terminal output, and Trace finalization. This is the principal refactoring seam and a high regression-risk area.

### 5.3 Agent route/execution boundary

- `skill_router_node.route_chat_skill` supports deterministic rules, optional LLM route, follow-up context, financial-SOP recognition, and Skill metadata discovery.
- `skill_executor_node.execute_skill` exposes a typed `SkillExecutionResult`, but its nested runtime trace and state still contain dynamic mappings. It has deterministic/agentic/hybrid paths, bounded/concurrent tool execution, normalization, evidence validation, degradation status, and artifact references.
- `skill_evidence.py` provides evidence and claim-lineage support; `skill_spec_planner.py` and `tushare_reference_planner.py` provide Skill/Tushare planning paths.

## 6. Related Files

### 6.1 Target repository

- Protocol: `backend/routers/chat.py`, `backend/schemas/chat.py`, `frontend/src/api/index.ts`, `frontend/src/composables/useChat.ts`, `frontend/src/stores/chatStore.ts`.
- Application/runtime: `backend/services/chat_service.py`, `backend/services/agent_service.py`, `backend/main.py`.
- State and persistence: `backend/db/models.py`, `backend/services/stm_context_service.py`, `backend/services/stm_compaction_worker.py`, `Financial-MCP-Agent/src/utils/state_definition.py`.
- Memory: `backend/services/memory_service.py`, `backend/services/profile_extractor.py`, `Financial-MCP-Agent/src/memory/*`.
- Routing/execution: `Financial-MCP-Agent/src/agents/skill_router_node.py`, `skill_executor_node.py`, `skill_evidence.py`, `skill_spec_planner.py`, `tushare_reference_planner.py`, `Financial-MCP-Agent/src/skills/*`.
- Observability: `Financial-MCP-Agent/src/tools/skill_trace.py`, `Financial-MCP-Agent/src/tools/trace_exporters/langfuse_exporter.py`, `backend/main.py` lifecycle initialization.

### 6.2 Historical `Finance` reference

The historical repository contains a more granular chat runtime under `backend/integrations/agent_runtime/{chat_runtime.py,contracts.py}` and `backend/services/chat/{orchestrator.py,preflight.py,session.py,memory_bridge.py,route_bridge.py,skill_pipeline.py,stream.py,artifacts.py}`. Its Agent directory additionally contains `entity_resolver_v2.py`, `route_stage1.py`, `route_stage2.py`, `query_rewriter.py`, `constraints_extractor.py`, `reply_preference_extractor.py`, `skill_runner_v2.py`, planner/validator, executor budget/scheduler/evidence envelope, verifier, controller, bounded replanner, and synthesis modules.

These files are candidate evidence only. Their behavior, test coverage, and compatibility with the target repository must be verified function-by-function before any direct refactor.

## 7. Existing Patterns to Reuse

- FastAPI routers already separate protocol adaptation from most service calls.
- Pydantic schemas exist for REST request/response boundaries.
- SQLAlchemy async sessions and explicit commits provide an existing persistence boundary.
- Skill specs (`skill_spec.yaml` + `SKILL.md`) and a registry provide a discoverable Skill contract.
- `SkillExecutionResult` and evidence/claim lineage are stronger than the current fallback path and are candidates for a stable application boundary.
- `skill_trace.py` already emits JSONL envelopes with `trace_id`, `session_id`, `stage`, `status`, duration, metrics, refs, recursive redaction, and optional exporter isolation.
- The repository already has marker-separated unit, contract, integration, E2E, and eval test directories plus offline Compose wiring.
- Pull request and issue templates require tests, Trace/artifact references, rollback notes, and redacted diagnostics.

## 8. Data Flow and State

### 8.1 Persistent state

- `Session`: user ownership, mode, title, `running_summary`, turn count, context budget/usage, compression status and timestamps.
- `Message`: ordered user/assistant/system content, token estimate, compression and LTM processing flags.
- `SessionSummary`: append-only compression snapshots and message/time range metadata.
- `UserInvestProfile`: structured risk/horizon/return/sectors/constraints/response preference; intended authoritative profile.
- `LtmWriteTask` and `StmCompactionTask`: outbox-like asynchronous work status and bounded retry counters.

### 8.2 In-memory Agent state

`Financial-MCP-Agent/src/utils/state_definition.py` defines an `AgentState` with append-only messages and merge-style `data`/`metadata`, summary/digest/thread/memory fields. The core `data` and `metadata` remain `Dict[str, Any]`; there is no single typed state contract shared by HTTP, session persistence, route runtime, and Skill execution.

### 8.3 Current state risks

- REST and WebSocket duplicate substantial orchestration and can drift in persistence, memory, and error semantics.
- User message is persisted before route/model execution; failure cleanup and idempotency behavior need explicit characterization.
- Background `asyncio.create_task` LTM writes are not represented as a durable request-level completion contract.
- Feature flags materially change the chain and are mostly disabled by default, so “code exists” does not mean “mainline is active.”

## 9. External Dependencies

- LLM: LangChain-compatible provider configured through OpenAI-compatible settings; router and skill synthesis can have separate model settings.
- Financial data/tools: Tushare client, MCP client/config and Skill-specific tools.
- Database: SQLite default for local development; PostgreSQL/asyncpg for Compose/integration.
- Memory: optional Mem0 client and embedding configuration; LTM worker.
- Observability: local JSONL Trace and optional Langfuse exporter; `langfuse` is an optional runtime dependency.
- Frontend: Vue/Vite/Axios/WebSocket; Nginx proxy in Compose.

External calls and live credentials are not used by default tests. `ENABLE_LANGFUSE`, model credentials, Tushare and live database URLs are environment-gated.

## 10. Tests and Evaluation Assets

- `tests/unit/test_trace_redaction.py`: Trace sanitization and exporter-failure isolation.
- `tests/contract/test_api_contract.py`: health and REST chat response mapping.
- `tests/integration/test_postgres_isolation.py`: optional isolated PostgreSQL probe; skips without `TEST_DATABASE_URL`.
- `tests/e2e/test_offline_chat_chain.py`: FastAPI request with patched fake chat service and failure contract.
- `tests/e2e/test_offline_compose_stack.py`: optional full frontend/Nginx/backend/isolated-PostgreSQL offline stack; skips without `OFFLINE_STACK_BASE_URL`.
- `tests/evals/*`: fixed smoke datasets for entity, route, rewrite, planner, executor, verifier, synthesis, Skill activation and web search. Some planner/executor/verifier suites are conditionally skipped when fixtures/providers are unavailable.
- `.github/workflows/ci.yml`: Ruff, Pyright, backend tests, Agent tests excluding live, eval smoke excluding live, full pytest, Docker config validation, and offline Compose E2E.

Current E2E evidence is infrastructure-level: the Compose test substitutes `tests.e2e.offline_app` and verifies proxy/API/response shape. It does not yet prove the real controlled Agent chain, evidence quality, streaming behavior, or cross-stage state transitions.

## 11. Logging and Observability

`skill_trace.py` creates a contextvar-based trace, span stack, JSONL envelope, recursive sensitive-key redaction, and exporter isolation. The backend initializes it during lifespan and flushes exporters during shutdown. Chat service records route, model, reply, memory enqueue, compaction enqueue and final status events; Skill executor records tool/evidence/artifact details.

Current gaps to verify later:

- `enable_trace`/`enable_langfuse` settings and lower-level `os.getenv` checks are not yet one unified typed injection path.
- `run_id` is not consistently visible in the public chat protocol or every stage; current root correlation is primarily `trace_id` + session/turn.
- Error payloads in WebSocket currently expose `str(exc)` directly, which may leak implementation details.
- `print` and logger calls coexist in entry/service code, with some f-string logging and potentially oversized diagnostics.
- Trace artifact retention, CI artifact collection, and exact Langfuse field mapping need verification.

## 12. Engineering Baseline Recon

- Python code has partial type annotations and Google-style documentation, but the main service and Agent state still rely heavily on dynamic dictionaries.
- API, orchestration, persistence, provider and reporting responsibilities are not consistently separated; `chat_service.py` is the clearest violation.
- Configuration is centralized in `backend/config.py`, but legacy Agent modules still read environment variables directly and startup injects `sys.path`.
- The repository has the requested engineering scaffolding (`AGENTS.md`, `CONTRIBUTING.md`, issue/PR templates, CI, Compose offline E2E), but business migration has not yet consumed the full contract.

## 13. Risk Areas

1. **High**: Splitting `chat_service.py` can change transaction ordering, duplicate message writes, stream completion, or fallback behavior.
2. **High**: REST and WebSocket implementations have duplicated branches; fixing one without a shared application contract can create protocol drift.
3. **High**: The historical `Finance` modules claim a richer controlled chain, but no equivalence matrix or characterization suite currently proves which behavior is safe to migrate.
4. **High**: Dynamic `AgentState` and nested trace dictionaries make cross-module contracts implicit and easy to break.
5. **Medium**: Feature flags defaulting off mean existing CI may exercise fallback paths rather than the intended Skill mainline.
6. **Medium**: Direct `sys.path` and environment injection couple backend startup to a sibling-style Agent directory and complicate packaging/rollback.
7. **Medium**: Optional Mem0/Langfuse/network dependencies can fail during startup or background tasks; failure semantics and user-visible status need explicit tests.
8. **Medium**: WebSocket error frames return raw exception text and the mixed text/JSON stream protocol requires careful compatibility testing.
9. **Medium**: Current offline E2E patches the service instead of traversing real route/router/executor/evidence stages.
10. **Low/Medium**: Database model comments and phase flags describe historical states; they may be stale relative to active behavior and migrations.

## 14. Unknowns and Assumptions

- It is not yet proven which feature-flag combination is the deployment baseline for the controlled conversation path.
- It is not yet proven whether any v2/history modules in the target repository are importable and tested but intentionally disconnected, or simply abandoned experiments.
- Exact frontend event parsing and behavior for all WebSocket control frames requires a focused read of `useChat.ts` and store tests.
- Exact database migration history and production schema compatibility were not changed or tested in this reconnaissance.
- `Finance` implementation quality, test evidence, and metrics remain unverified; documentation claims are not treated as runtime facts.
- The first migration slice remains open between (a) a shared typed run/state contract and (b) extracting a thin application orchestrator around the existing active Skill path.

## 15. Handoff to Next Step

Requirement Clarification should resolve, with plain-language examples:

1. Which externally visible behavior is the first milestone: fallback chat, one read-only Skill, or the complete controlled route through evidence and synthesis.
2. Whether REST and WebSocket must share one application use-case implementation in milestone one, and how mixed stream frames are versioned.
3. The minimum active feature flags and allowed providers for offline Compose E2E.
4. Whether session/message persistence may be reorganized without a schema change, and the required rollback point.
5. The first historical `Finance` module to migrate after the active boundary is frozen (candidate: entity resolution, typed run context, or application orchestration).
6. The protected Live E2E trigger, isolated account/data policy, model/tool budget, and evidence retention policy.

After these questions are answered, the next Spec Coding stages are `solution-tradeoff` and `plan-freezing`; implementation must then proceed one approved milestone at a time.
