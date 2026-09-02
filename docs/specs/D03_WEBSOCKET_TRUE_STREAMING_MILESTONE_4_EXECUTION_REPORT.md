# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone：4 — Frontend v2 Consumption
- Status：Complete
- Date：2026-09-01

## 2. Scope and Standards

- 只修改前端 API parser、聊天 composable/store 和相邻合同测试。
- 不实现停止按钮、工具/证据/计划卡片、D04 控制台或新依赖。
- 遵守冻结的原子协议升级：不保留 legacy `done/error/session_id` 或裸 token fallback。
- 按 `small-step-implementation` 只收口 Milestone 4。

## 3. Files Modified

- `frontend/src/api/index.ts`：完整 v2 union、终态/错误码、运行时类型守卫和严格 parser。
- `frontend/src/composables/useChat.ts`：request_id、生命周期状态机、关联/顺序校验、delta/control/end/error 处理。
- `frontend/src/stores/chatStore.ts`：只追加已校验 delta，并把新建 session 关联到当前流式占位消息。
- `frontend/src/api/__tests__/chatStreamingV2Contract.spec.ts`：严格 parser 与拒绝 legacy/private/raw。
- `frontend/src/api/__tests__/chatSkillContract.spec.ts`：Skill 确认帧升级为完整 v2 envelope。
- `frontend/src/composables/__tests__/useChat.streaming-v2.spec.ts`：正常多 delta、乱序拒绝和部分内容后失败。

## 4. Implementation Summary

前端现在只接受 `chat-stream-v2` JSON。Parser 先验证共同 envelope，再按事件白名单验证正文、终态、错误、Skill、Memory、Context 和既有压缩控制载荷。legacy JSON、Provider 私有事件、字段不完整 JSON 和裸文本全部返回 `null`，composable 将其视为协议失败而不是正文。

每轮 WebSocket 请求生成并发送唯一 request_id。消费状态机要求 sequence 从 1 严格连续、request_id 一致、Started 后 session_id 固定、chunk_index 从 1 连续且 End/Error 的 chunk_count 等于已接受数量。只有通过这些校验的 `content_delta` 才追加到同一助手占位消息。

## 5. User-visible Semantics

- `stream_start`：绑定真实 session，并更新当前占位助手消息 session。
- `content_delta`：按序追加，不创建多条助手消息。
- `stream_end`：结束生成、刷新画像/会话，不重复全文。
- `stream_error`：保留已经展示的部分内容，在同一消息追加安全错误状态。
- 协议错误/连接错误/异常关闭：停止接受后续帧并显示可重试提示。
- Skill、Memory、Context 和压缩控制能力继续工作，但必须位于 v2 envelope。

## 6. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| targeted Vitest | parser、Skill、v2 composable | 7 passed |
| `npm run test -- --run` | 完整前端回归 | 14 passed across 7 files |
| `npm run lint` | ESLint | Passed |
| `npm run type-check` | Vue/TypeScript 类型 | Passed |
| `npm run build` | 生产类型检查与 Vite build | Succeeded, 401 modules transformed |
| `git diff --check` | whitespace/patch 检查 | Passed；仅 Git LF→CRLF 工作区提示 |

## 7. Failure Coverage

- Legacy `done`、未知 Provider 帧和裸 token 被 parser 拒绝。
- request_id 或 sequence 不一致触发协议失败并关闭连接。
- chunk_index 不连续、session 变化、End/Error 数量不一致触发协议失败。
- stream_error 保留已显示内容，但结束 sending/streaming 状态且不接受晚到内容。
- onerror/onclose 只收口一次，不会重复追加错误。

## 8. Build Notes

- 构建保留两个既有非阻塞警告：`api/index.ts` 同时被静态/动态导入；部分 bundle 超过 500 kB。
- D03 不扩大到代码分包或依赖升级；这些警告不由本次变更引入。
- `vue-tsc -b` 会更新 tracked `tsconfig.node.tsbuildinfo` 的本地编译器版本；每次检查后已定向恢复，最终 diff 不包含生成物。

## 9. Scope Compliance

- Legacy WS compatibility branch retained：No。
- Multiple assistant messages per chunk：No。
- New dependency/config/build setting：No。
- D04 UI added：No。
- Existing Skill/Memory/context behavior retained：Yes，通过 v2 control frame。
- User files preserved：Yes。

## 10. Risks Remaining

- 浏览器真实 WebSocket 是否在模型完成前发生至少两次 DOM 内容增长，需要 M5 实际运行证据。
- content_sha256 当前用于协议和后端一致性证据；浏览器只验证 chunk_count，不在主线程同步重算 SHA-256，避免为了 M4 引入依赖或异步终态竞态。
- 生产 bundle 既有体积警告留作独立性能任务。

## 11. PLAN.md Updates

- Progress：Milestone 4 标记完成。
- Decision Log：记录严格 parser、关联/sequence、单消息增量和 control frame v2 化。
- Discoveries：记录旧 parser 绕过风险和 tsbuildinfo 生成噪声。
- Handoff：下一步固定为 Milestone 5 全量/live/browser/final review。

## 12. Suggested Commit Message

```text
feat(d03): consume ordered websocket v2 deltas

- reject legacy and malformed stream frames
- correlate request session and sequence in the client
- keep partial content while surfacing stream failures
```

## 13. Handoff

Milestone 4 已完成。下一次续跑只执行 Milestone 5：全量门禁、最多两条受保护真实 API E2E、实际前后端浏览器验收、最终 code review 和 D03 验收报告。
