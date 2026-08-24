# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 6 — Persistence, REST/WebSocket Cutover, and Legacy Removal
- Status: Complete, pending GitHub PR delivery at report creation time
- Date: 2026-08-24
- GitHub tracking: [Issue #15 — refactor(chat): cut over REST and WebSocket to controlled conversation mainline](https://github.com/even9277/Finance-agent-Skills/issues/15)
- Local branch: `refactor/15-controlled-chat-cutover`

## 2. Scope and Standards

- REST 与 WebSocket 同时切换到唯一 `ControlledChatUseCase`，没有长期开关、双写、旧 Runtime Adapter 或转发壳。
- Application 层决定准备、保存、提交与回滚时点；SQLAlchemy Repository 只实现事务内读写。
- 保留 REST 的 `reply/session_id/memory_profile/context_window` 四字段和 WS 的 `session_id/text/context_update/done` 基础帧。
- 默认测试只注入 Fake Model/Tool/Trace Ports；没有访问付费模型、真实 Tushare 或生产服务。
- 不改数据库 Schema、鉴权合同和生产依赖；只在前端 WS error 类型增加可选稳定 `code`。

## 3. Final Call Graph

```text
POST /api/chat/message ─┐
                       ├─> ChatCommand
WS /api/chat/stream ───┘   -> ControlledChatUseCase
                            -> SqlAlchemyConversationRepository.prepare_turn
                            -> ControlledConversationWorkflow
                            -> ModelPort / ToolPort / TraceSink
                            -> SqlAlchemyConversationRepository.save_result
                            -> Application commit / rollback
                            -> ChatOutcome
                            -> REST response or WS frames
```

会话列表、消息、摘要、重命名和删除独立走 `ChatSessionUseCase -> SqlAlchemyConversationRepository`，不反向调用对话执行链。

## 4. Files and Modules Changed

- `backend/application/chat/contracts.py`、`ports.py`：新增协议无关命令、统一输出、上下文快照、会话读取模型和事务 Port。
- `backend/application/chat/use_case.py`：唯一聊天用例持有完整提交/回滚边界，覆盖 `CancelledError`。
- `backend/application/chat/session_use_case.py`：会话 CRUD 与对话执行解耦。
- `backend/application/chat/factory.py`：集中装配生产 Model、Tool、Trace、Workflow 和 Repository。
- `backend/infrastructure/chat/repository.py`：实现会话隔离、尾窗读取、一对消息原子保存、上下文指标和 CRUD。
- `backend/infrastructure/chat/providers.py`：实现 OpenAI-compatible Synthesis 和 Tushare 只读工具的强类型归一化。
- `backend/routers/chat.py`：成为薄协议适配层；REST/WS 共用同一命令和输出，错误不泄露内部详情。
- `backend/services/stm_compaction_support.py`：承接 STM worker 唯一仍需的压缩模型与摘要画像增强。
- `tests/e2e/offline_app.py`：只替换外部 Fake Ports，保留真实公开入口、Workflow、Repository 和 PostgreSQL。
- `frontend/src/api/index.ts`：WS error frame 增加可选稳定错误码，不破坏旧消费者。

## 5. Legacy Removal List

- 删除 `backend/services/chat_service.py`：旧 REST/WS 双编排、重复 Prompt、动态状态、工具执行、持久化和 Trace 混合实现全部移除。
- 删除 `chat_single_turn`、`stream_chat_single_turn` 及所有 Router 导入；静态合同测试禁止其恢复。
- 删除只覆盖旧 reply action 清理的 `backend/test_chat_service_skill_processing.py`。
- 删除旧 Chat Service 持久化测试，替换为新应用事务、取消回滚和跨用户隔离测试。
- 删除 Compose 对整个 Chat Service 的替换；现在只替换 Model/Tool/Trace Ports。
- 将 `sys.path` 注册集中到 `backend/__init__.py`；彻底安装式包治理仍按 PLAN 延后。

## 6. Test and Check Evidence

| Check | Result |
|---|---|
| M6 focused contract/integration/E2E | `26 passed` |
| Production adapter + session management | `7 passed` |
| M6 scoped Ruff | `All checks passed` |
| M6 scoped Pyright | `0 errors, 0 warnings` |
| CI-same Ruff (`tests` + trace) | `All checks passed` |
| CI-same Pyright (`tests` + trace) | `0 errors, 0 warnings` |
| Default full regression | `122 passed, 2 skipped, 4 deselected` |
| Frontend lint/type-check/build | 全部通过；仅保留既有 bundle size warning |
| Offline Compose | Nginx、FastAPI、真实 Workflow、Fake Ports、PostgreSQL、消息历史全链通过；容器内 `70 passed` |
| Compose cleanup | 容器、网络和临时卷已删除 |
| `git diff --check` | 通过 |

## 7. Failure and Recovery Record

测试先行阶段因新合同和 Repository 尚不存在而按预期 collection 失败，不计修复次数。实现后第 1 次窄修复只处理 LangChain `SecretStr` 和 dataclass 类型收窄；第 2 次窄修复在差异审查中补齐 REST 纯空白输入的 422 边界。之后静态检查、聚焦测试、全量和 Compose 全部通过，没有第三次修复。

## 8. Failure, Cancellation, and Security Semantics

- Repository `prepare_turn` 先暂存用户消息；只有工作流返回唯一终态并保存助手消息后，Application 才提交。
- 任意 `Exception`、`CancelledError` 或其他 `BaseException` 都先回滚再原样传播；测试证明无会话或消息半写。
- 用户传入他人 `session_id` 时创建自己的新会话，不复用或泄露原会话。
- REST 未知异常返回 HTTP 500 安全文案；WS 返回 `CHAT_INTERNAL_ERROR`，不返回 Provider/数据库异常原文。
- Tushare Adapter 只保留首行有限标量 facts、来源和日期；任意嵌套载荷与 Provider 错误原文不进入 Evidence。

## 9. Remaining Risks and Honest Limitations

- 真实 LLM/Tushare Ports 已实现并接入生产装配，但本里程碑默认测试没有真实调用；受保护 Live E2E 属于 M7。
- M6 的 `StructuredLoggingTraceSink` 只提供稳定结构化阶段日志；本地 JSONL/Langfuse 一 Trace 多 Span 和 artifact 回放在 M7 闭环。
- WS 当前把完整终态回答作为一个文本帧发送，不是假 token 流；协议兼容但真实增量 streaming 属于后续增强。
- 新主链读取权威画像用于响应展示，尚未把语义记忆与画像深度注入各阶段；记忆模块仍是后续独立迁移项。
- 历史会话缺失上下文指标时不在读取接口隐式写回；新会话每轮会刷新指标。
- Starlette TestClient、旧 ORM `datetime.utcnow()` 和前端大 chunk warning 是存量技术债，不属于本次入口切换。

## 10. Rollback

M6 不改 Schema 或依赖。合并后可 revert 单个 squash commit 恢复 M5 入口；数据库中新增数据仍使用既有 Session/Message 表，无需数据迁移。回滚会重新引入已知旧双轨和 WS 错误泄露，因此只能用于紧急代码回退。

## 11. Suggested Commit Message

```text
refactor(chat): cut over controlled conversation entrypoints

- route REST and WebSocket through one transactional chat use case
- add SQLAlchemy, OpenAI-compatible, and Tushare production adapters
- remove legacy chat orchestration and whole-service E2E replacement

Closes #15
```

## 12. Handoff

下一个且唯一执行单元是 M7：把 `WorkflowEvent` 接入本地 JSONL/Langfuse 一 Trace 多 Span，扩展离线 eval/CI 覆盖，执行受保护真实 LLM + Tushare + 公开入口 Live E2E，并保存脱敏证据。M7 不得修改已冻结的入口事务和公开协议。
