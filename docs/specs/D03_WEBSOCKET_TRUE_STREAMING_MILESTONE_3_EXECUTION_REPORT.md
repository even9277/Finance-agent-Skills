# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone：3 — WebSocket v2, Cancellation and Observability
- Status：Complete
- Date：2026-09-01

## 2. Scope and Standards

- 仅修改 WebSocket 协议适配、公开 Schema、流失败码和相邻测试。
- 未实现前端消费、停止按钮、heartbeat、续传、D04 控制 UI 或新依赖。
- 遵守根 `AGENTS.md` 的薄路由、强类型边界、中文接口文档、无敏感日志和测试先行规则。
- 按 `small-step-implementation` 只完成冻结的 Milestone 3。

## 3. Files Modified

- `backend/routers/chat.py`：切换 Application stream，映射 v2 生命周期，统一 sequence，显式关闭上游，记录低敏发送指标。
- `backend/schemas/chat.py`：新增 v2 Pydantic 帧 Schema，终态和错误码使用有限类型。
- `backend/application/chat/contracts.py`：新增稳定 `ChatStreamFailureCode`。
- `backend/application/chat/use_case.py`：使用强类型技术失败码。
- `tests/contract/test_controlled_chat_contract.py`：v2 生命周期、安全错误、非法 JSON、发送断连和无正文日志合同。
- `tests/contract/test_skill_confirmation_public_contract.py`：Skill control frame 进入统一 v2 sequence。
- `tests/unit/conversation/test_chat_stream_use_case_contract.py`：提交失败和首 chunk 后技术失败回滚。

## 4. Implementation Summary

WebSocket Router 不再调用完整结果 `execute()`，而是在数据库会话有效期内消费唯一 `ControlledChatUseCase.stream()`。Application 的 Started/Delta/Completed/Failed 被映射为 `chat-stream-v2` Pydantic Schema；Router 对正文和所有控制帧统一分配严格递增 sequence。Completed 可以附带 Skill、Memory、Context 控制帧，随后发送不含正文的 `stream_end`；Failed 映射为安全 `stream_error`。两种终态发送后立即返回，禁止晚到 chunk。

`contextlib.aclosing` 把 WebSocket 发送异常和客户端断连确定性传播为 Application generator 关闭；M2 的确认式背压随后取消模型流并回滚未提交事务。边界 JSON/validation 失败也使用 v2 error envelope，不保留旧协议旁路。

## 5. Public Protocol

每帧固定包含：

- `protocol_version = chat-stream-v2`
- `request_id`
- `session_id`
- 从 1 开始严格递增的 `sequence`
- 有限 `type`：`stream_start`、`content_delta`、`skill_confirm`、`memory_command`、`context_update`、`stream_end`、`stream_error`

`stream_end` 只包含 status、chunk_count、content_sha256，不重复最终正文；`stream_error` 只包含稳定 code、安全 message 和已发送 chunk_count。

## 6. Failure and Cancellation Semantics

- 首 chunk 前模型失败：Started → Error，Repository rollback。
- 首 chunk 后模型失败：已展示 delta 保留，随后 Error；不发送 End，Repository rollback。
- commit 失败：不产生 Completed，已暂存结果被 rollback 清空。
- WebSocket send/disconnect：`aclosing` 立即关闭 Application stream，不遗留后台生成任务。
- Application 无终态结束或帧计数不一致：Router 视为技术协议失败，不静默成功。
- Completed/Failed 之后 Router 立即结束，不消费任何晚到事件。

## 7. Observability

成功、失败和断连日志包含：`request_id`、`session_id`、`stage`、`status`、`chunk_count`、`output_chars`、server/application TTFT、`elapsed_ms`、`disconnect_reason` 或 `error_code`。测试确认回答正文不进入日志。内部异常只记录 `error_type`，不记录 Provider 原始异常正文或 stack payload。

## 8. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| focused `ruff check` | Router/Schema/Application/tests 静态质量 | Passed |
| targeted `pyright` | v2 Schema、事件和 presenter 类型 | 0 errors, 0 warnings |
| M3 WS/Application suite | 生命周期、Skill、失败、commit、断连、边界错误 | 18 passed, 1 existing warning |
| combined D03 core/WS regression | Provider/Synthesizer/Application/Router/E2E | 33 passed, 1 existing warning |
| `pytest backend -q` | Backend 子树回归 | 11 passed；56 个既有 datetime warnings |
| `pytest Financial-MCP-Agent -q -m "not live"` | Agent 子树离线回归 | 33 passed, 4 deselected |
| `git diff --check` | whitespace/patch 检查 | Passed；仅 Git LF→CRLF 工作区提示 |

## 9. Test Coverage Evidence

- v2 start → multi delta → control → end 生命周期与严格 sequence。
- Skill confirmation 与 explicit Skill 同 session 关联。
- end 无正文且 hash/count 与 Application 一致。
- 安全技术错误不泄漏内部异常。
- 非法 JSON 不回退旧 error 帧。
- send failure 确定性执行 async generator `finally`。
- commit failure 清空已保存结果。
- 首 chunk 后失败公开正确 chunk_count 且不产生 Completed。
- 日志包含低敏指标且不包含完整回答。

## 10. Scope Compliance

- Legacy WS execute/text path retained：No。
- HTTP behavior duplicated or broken：No；额外透传可选 request_id。
- Frontend behavior changed：No，留给 M4。
- Prompt/Skill/Memory/Tool/database/config/dependency changed：No。
- User documents and generated artifacts preserved：Yes。

## 11. Risks Remaining

- 前端 parser/composable 仍接受旧裸文本和 legacy control frame，必须在 M4 原子切到 v2。
- 发送 `stream_end` 前 Application 已按冻结合同提交；极端情况下 end 帧网络失败不能撤销已完成数据库事务，但正文发送阶段的断连仍会在提交前取消。这是传输与数据库之间不可原子提交的固有限制，M5 需在验收报告明确。
- 真实 Provider 多 chunk、真实工具链和浏览器同消息增长尚需 M5 live/browser 证据。

## 12. PLAN.md Updates

- Progress：Milestone 3 标记完成。
- Decision Log：记录 v2 Schema、Router sequence、`aclosing`、唯一终态和低敏日志。
- Discoveries：记录边界错误关联字段和跨层错误码收敛。
- Handoff：下一步固定为 Milestone 4 前端 v2 消费。

## 13. Suggested Commit Message

```text
feat(d03): expose websocket v2 streaming lifecycle

- map application chunks to typed ordered frames
- cancel upstream work on websocket send failure
- add safe stream metrics and failure contracts
```

## 14. Handoff

Milestone 3 已完成。下一次续跑只执行 Milestone 4：严格 v2 parser、request_id、按 sequence 更新同一助手消息，以及 stream_end/stream_error 状态处理；不实现 D04 工具或证据 UI。
