# D03 WebSocket 真实流式输出验收报告

## 1. Conclusion

D03 已达到可合并状态：真实模型 chunk 从 Provider 经受控 Workflow、Application 事务和 WebSocket v2 到达前端，同一助手消息持续增长；最终拼接、hash 和数据库消息一致；模型/提交/传输中途失败与断连不会把残缺回答保存为成功结果；HTTP、Skills、Memory 和工具治理相关回归通过。

## 2. Requirement-to-Evidence Matrix

| Claim / Acceptance | Authoritative evidence | Result |
|---|---|---|
| 真模型在结束前产生至少两个非空 delta | protected Live 2/2 | Pass |
| 不做完整回答事后切片 | `ModelPort.stream_synthesize -> ChatOpenAI.astream` + provider contract | Pass |
| 同一公开生命周期严格有序 | WS contract/E2E sequence 与 chunk_index | Pass |
| End 不重复完整正文 | v2 Schema、parser contract | Pass |
| 拼接正文 = hash = 持久化回答 | offline WS E2E + protected Live | Pass |
| 首 chunk 前/中途 Provider 失败安全收口 | Application contract + offline WS E2E | Pass |
| Commit 失败不发送成功终态且回滚 | Application contract | Pass |
| 客户端断连关闭上游且未提交轮次回滚 | receive-side disconnect contract + browser DB check | Pass |
| 两个并发请求/会话不串流 | concurrent isolation contract | Pass |
| 前端只更新一个助手气泡 | Vitest + browser sampling | Pass |
| 刷新后权威历史一致 | browser reload/session selection | Pass |
| HTTP 和现有控制事件不回归 | full pytest 364 passed + frontend 15 passed | Pass |
| Live 默认不误触发 | `RUN_PROTECTED_LIVE_E2E` gate | Pass |
| Artifact/Trace 不含凭证和问题正文 | Live assertions | Pass |

## 3. Public v2 Lifecycle

```text
stream_start
  -> content_delta (1..N)
  -> optional skill_confirm / memory_command / context_update
  -> exactly one of stream_end | stream_error
```

所有帧携带 `protocol_version=request/session/sequence`；正文只出现在 `content_delta`；`stream_end` 只携带业务终态、chunk 数和 SHA-256。

## 4. Verification Summary

- 后端全量：364 passed，6 skipped，7 deselected，3 xfailed。
- 前端：lint、类型检查、15 个测试、生产构建全部通过。
- Live：2 passed；覆盖真实模型和真实 Tushare。
- 浏览器：同一气泡多次增长、完成后刷新一致、生成中离开不产生数据库脏写。
- D03 变更集 Ruff/Pyright：零问题。

## 5. Review Decision

**Approved**。本轮没有未解决的 D03 blocking finding。认证查询参数日志、通知 404、全仓静态检查基线和部署代理 close-frame 观测已明确记录为后续工作，不应被误写成 D03 已解决。
