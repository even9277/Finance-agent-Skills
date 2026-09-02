# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone：1 — Lock Tests and Protocol Contract
- Status：Complete with expected red baseline
- Date：2026-08-30

## 2. Development Standards Read

- `PLAN.md`：已读取并确认 Milestone 1 范围。
- `AGENTS.md`：已读取仓库测试先行、强类型边界和禁止双轨规则。
- Python/Agent standard：沿用 Milestone 0 已读取标准。
- nested rules：允许范围内未发现。

## 3. Files Inspected

- `Financial-MCP-Agent/src/conversation/contracts.py`、`ports.py`、`synthesis.py`、`workflow.py`：确认模型和合成边界。
- `backend/application/chat/contracts.py`、`ports.py`、`use_case.py`：确认事务和应用输出边界。
- `backend/infrastructure/chat/providers.py`、`testing.py`：确认真实/离线 Provider 模式。
- `backend/routers/chat.py`、`backend/schemas/chat.py`：确认旧 WS 协议和输入边界。
- `frontend/src/api/index.ts`、`useChat.ts`、`chatStore.ts`：确认旧裸文本消费和已有 placeholder。
- 现有 controlled chat、Skill 和前端契约测试：确认需要直接替换的旧协议断言。

## 4. Files Modified

- `Financial-MCP-Agent/src/conversation/contracts.py`：新增供应商无关 `ModelSynthesisChunk`。
- `backend/application/chat/contracts.py`：新增四类强类型 Application 流式事件。
- `backend/schemas/chat.py`：请求增加可选、受限的 `request_id`。
- `frontend/src/api/index.ts`：冻结 `chat-stream-v2` 信封和事件 union。
- `tests/unit/conversation/test_streaming_synthesis_contract.py`：冻结多 chunk、聚合一致和 PARTIAL 前缀。
- `tests/unit/conversation/test_openai_streaming_provider_contract.py`：冻结 LangChain chunk 转换与空 chunk 过滤。
- `tests/unit/conversation/test_chat_stream_use_case_contract.py`：冻结单 delta 降级、提交、失败回滚。
- `tests/contract/test_controlled_chat_contract.py`：用 v2 JSON 生命周期替换旧裸文本合同。
- `tests/contract/test_skill_confirmation_public_contract.py`：Skill 控制帧进入 v2 信封。
- `frontend/src/api/__tests__/chatStreamingV2Contract.spec.ts`：冻结严格 v2 parser。
- `frontend/src/composables/__tests__/useChat.streaming-v2.spec.ts`：冻结 request_id、多 delta 和 stream_end 行为。

## 5. Implementation Summary

本里程碑只建立协议类型和测试合同，没有实现真实流式生产逻辑。新测试证明旧实现不满足 D03，并把失败精确归因到 Provider、Synthesizer、Application、Router 和 Frontend 五个边界。

## 6. Diff Summary

- 新增强类型的内部模型 chunk、Application 事件和前端 v2 帧。
- 旧 REST 契约保持不变；可选 `request_id` 是向后兼容字段。
- 旧 WS 裸文本断言被 v2 生命周期断言直接替换，没有建立永久双套测试。

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| `git diff --check` | whitespace/scope 检查 | 通过；只有既有 LF/CRLF 提示 |
| focused `ruff check` | Python 测试与合同语法/导入 | Passed |
| focused `pyright` on contract files | 新强类型合同 | 0 errors |
| focused pytest（新 unit + 两个 contract） | 建立旧实现红色基线 | 10 expected failed, 5 passed |
| focused Vitest（v2 parser + composable） | 建立前端红色基线 | 2 expected failed, 1 passed |
| `npm run type-check` | 新 v2 TypeScript union | Passed |

## 8. Test Results

- Passed：ruff、Python 合同 pyright、frontend type-check；pytest 既有/非目标断言 5 个；Vitest v2 delta 类型 1 个。
- Expected failed：pytest 10、Vitest 2。
- Unexpected failed：0。
- Not run：全量回归、live、浏览器属于后续里程碑。
- Limitations：TestClient 仍有既有 Starlette/httpx 弃用警告。

## 9. Failures and Fixes

- Failure：`ControlledSynthesizer.stream` 不存在（2）。
- Root cause：旧合成器只等待完整字符串。
- Planned fix：Milestone 2 使用模型增量并由 `synthesize()` 聚合同一流。

- Failure：`OpenAICompatibleModelProvider.stream_synthesize` 不存在（1）。
- Root cause：旧 Provider 使用 `ainvoke`。
- Planned fix：Milestone 2 使用 `astream` 并过滤空 chunk。

- Failure：`ControlledChatUseCase.stream` 不存在（3）。
- Root cause：旧应用接口只有完整 `execute()`。
- Planned fix：Milestone 2 建立共享执行核心和 typed stream。

- Failure：Router 仍调用 `execute()`（4）。
- Root cause：旧 WebSocket 只发送完整 outcome。
- Planned fix：Milestone 3 消费 Application stream 并映射 v2。

- Failure：Frontend 仍接受 legacy done 且请求无 request_id（2）。
- Root cause：旧 parser 接受任意 type，composable 使用裸文本/旧终态。
- Planned fix：Milestone 4 严格解析并消费 v2。

## 10. Scope Compliance

- Allowed files only：Yes
- Forbidden changes avoided：Yes
- User changes preserved：Yes
- Dependencies changed：No
- Database/config/prompt changed：No
- API change：仅冻结已批准的 WS v2 和向后兼容 request_id。

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
|---|---|---|
| Architecture and dependency direction | Satisfied | 内部 chunk/Application event 不依赖 FastAPI/WebSocket |
| Docstrings, types, field meaning | Satisfied | dataclass/StrEnum/TS union 与中文字段语义 |
| Configuration, secrets, prompts | Satisfied | 无修改、无敏感 fixture |
| Logs, traces, artifacts | Not applicable | 本轮只冻结后续指标合同 |
| Validation, errors, state, compatibility | Satisfied | failed event、request_id 校验、PARTIAL/rollback tests |
| Tests and handoff evidence | Satisfied | 失败均与计划中的未实现能力一一对应 |

## 12. Risks Remaining

- 真模型、Router 断连和 commit 后终态尚未实现。
- 新测试在 Milestone 2-4 完成前保持红色，这是测试先行的预期中间状态。

## 13. PLAN.md Updates

- Progress：Milestone 1 已完成。
- Decision Log：记录内部事件、协议版本、sequence 所有权和单 delta 降级。
- Discoveries：记录宽松 parser 与旧 Router 行为。
- Outcomes：等待实现和验收。

## 14. Suggested Commit Message

```text
test(d03): lock true streaming protocol contracts

- define provider-neutral chunks and application stream events
- replace legacy WebSocket assertions with chat-stream-v2
- capture backend and frontend red baselines
```

## 15. Handoff to User

Milestone 1 已完成。用户已授权持续推进，下一次续跑进入 Milestone 2；本报告不宣称 D03 已实现。
