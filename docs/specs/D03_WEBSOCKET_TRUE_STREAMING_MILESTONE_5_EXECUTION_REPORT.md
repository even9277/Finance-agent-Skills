# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone：5 — Full Verification, Live Acceptance and Handoff
- Status：Complete
- Date：2026-09-02
- Branch：`feat/d03-websocket-true-streaming`

## 2. Scope and Standards

- 只补齐真实 WebSocket 入口 E2E、受保护 Live E2E、浏览器验收、断连生命周期修复、最终回归和交付文档。
- 未新增依赖、数据库迁移、Prompt、Skill/Memory/Tool 规则、停止按钮、回放、消息队列或认证协议改造。
- 默认测试保持完全离线；真实 API 仅由 `RUN_PROTECTED_LIVE_E2E=true` 显式启用。
- 保留用户未跟踪的 D01 文档，不纳入 D03 提交。

## 3. M5 Changes

- `tests/e2e/test_websocket_streaming_chain.py`
  - 从实际 FastAPI WebSocket 入口验证多增量、严格 sequence/chunk index、hash、SQLite 原子落库。
  - 验证模型中途失败只返回安全 `stream_error`，数据库不留下本轮消息。
- `tests/e2e/test_live_controlled_chat_chain.py`
  - 升级为两条显式 Live WebSocket 主路径：真实模型 + 确定性只读工具、真实模型 + 真实 Tushare。
  - 验证真实上游多 chunk、完整受控链、持久化一致性、Trace 阶段和 Artifact 脱敏。
- `backend/routers/chat.py`
  - 并发观察发送任务与 ASGI receive-side disconnect；客户端先断开时取消 presenter 并关闭 Application generator。
  - 处理发送完成与断连同时到达的竞态，确定性消费监听任务异常。
- `frontend/src/composables/useChat.ts`
  - 页面退出或组件作用域释放时主动关闭当前流式 WebSocket，避免离开页面后继续保留连接。
- `frontend/src/composables/__tests__/useChat.streaming-v2.spec.ts`
  - 增加页面退出关闭连接、保留本地 partial 且结束 loading 状态的行为测试。

## 4. Offline and Full Regression Evidence

| Command / Method | Result |
|---|---|
| D03 changed-file Ruff | Passed |
| D03 targeted Pyright | `0 errors, 0 warnings, 0 informations` |
| `uv run --locked pytest -q` | `364 passed, 6 skipped, 7 deselected, 3 xfailed` |
| `npm run lint` | Passed |
| `npm run type-check` | Passed |
| `npm run test -- --run` | `15 passed` across 7 files |
| `npm run build` | Succeeded, 401 modules transformed |
| `git diff --check` | Passed；仅工作区 LF→CRLF 提示 |

全仓历史基线仍有两个非 D03 阻断门禁：`ruff check .` 报 97 个既有问题，`pyright` 报 70 个既有错误和 6 个 warning，均位于 legacy、vendor 或本轮未改代码；D03 变更文件的对应聚焦门禁为零问题。

## 5. Protected Live API Acceptance

执行命令：

```text
RUN_PROTECTED_LIVE_E2E=true uv run --locked pytest tests/e2e/test_live_controlled_chat_chain.py -q -m live
```

结果：`2 passed, 33 warnings in 67.29s`。

- `d03-live-01`：真实 OpenAI-compatible 模型流 + 确定性只读金融工具。
- `d03-live-02`：真实 OpenAI-compatible 模型流 + 真实 Tushare 只读工具。
- 两条均证明：至少两个真实模型 chunk、v2 sequence 连续、拼接 hash 正确、SQLite 最终回答一致、受控 workflow Trace 完整且凭证/问题正文未进入验收 Artifact。
- Live 运行中发现宿主机 `ALL_PROXY=socks5h` 但环境未安装 SOCKS 依赖；仅对验收进程移除该变量并保留 HTTPS 代理，没有修改仓库或配置文件。

## 6. Browser Acceptance

实际启动后端和前端开发服务器，使用隔离 SQLite 和测试账号完成以下观察：

- 真实 Tushare + 真实模型问题在同一个助手气泡内持续增长；15 次采样中前 8 次正文长度依次为 `21, 99, 199, 287, 380, 481, 581, 663`，证明不是完成后一次性回填。
- 完成后页面渲染正文长度为 1088；刷新并重新选择会话后内容精确一致，游标回到非流式状态。
- 在另一轮首个可见增量达到 44 字时切换到报告页，页面立即离开聊天流；隔离数据库仍只有此前已提交的两轮 4 条消息，没有保存该未完成轮次。
- 浏览器控制台未观察到 D03 协议或渲染错误。

浏览器经 Vite 代理退出时没有在人工观察窗口内稳定显示 Uvicorn 的最终 disconnect 日志；因此服务端取消的确定性证据由 receive-side disconnect 合同测试（1 秒超时内关闭上游 generator）和数据库零脏提交共同提供。生产代理层的 close-frame 可观测性仍应在部署环境做一次补充观测。

## 7. Final Code Review

Verdict：**Approve for D03**，未发现必须阻止本功能合并的实现缺陷。

审查覆盖：分层所有权、HTTP/WS 单执行核心、模型 chunk 边界、背压与取消、事务提交/回滚、公开 Schema、前端关联/顺序状态机、并发隔离、敏感日志和测试有效性。

已在 review 中修复：

- Router 过去只在发送失败时发现断连，浏览器不再接收但模型仍可能继续；新增 receive-side 监听竞争。
- 页面离开时 WebSocket 只存在于 Promise 局部变量；新增组件/页面生命周期关闭。
- presenter 与 disconnect 同时完成时监听任务异常可能覆盖正常终态；补齐竞态收口。

## 8. Known Non-blocking Risks

1. 当前 WebSocket 认证仍把 token 放在查询参数中，Uvicorn access log 可能打印完整 URL。此项属于冻结范围明确排除的 auth 改造，但具有敏感日志风险，建议下一任务改为安全握手或在入口代理/日志层脱敏。
2. 前端会周期请求不存在的 `/api/notifications/unread`，实际运行产生 404 噪声；与 D03 流式链无关，建议单独修复。
3. 数据库提交与网络终态无法在没有客户端 ACK/outbox 的情况下形成跨系统原子事务。当前选择是先提交再发送 `stream_end`：提交失败会返回 `stream_error`；若仅最终终态帧发送失败，已提交权威回答仍可刷新恢复。D03 已明确排除持久化事件流和回放。
4. Vite 构建保留既有静态/动态导入和大 chunk warning；未由 D03 引入。
5. 仓库仍有历史 Ruff/Pyright 基线债务，不能用全仓静态检查绿色描述当前仓库。

## 9. Scope Compliance

- True upstream streaming：Yes。
- Post-hoc slicing：No。
- One controlled workflow for HTTP/WS：Yes。
- Typed v2-only public protocol：Yes。
- Midstream provider/send/disconnect rollback before commit：Yes。
- Business `PARTIAL` persists as a normal terminal result：Yes。
- Existing Skills/Memory/Tool governance semantics changed：No。
- New dependency/schema/deployment configuration：No。
- User D01 artifact preserved：Yes。

## 10. Handoff

D03 的实现、离线回归、两条真实 API E2E、实际浏览器验收和最终 review 已闭环。下一步只需完成 Git 提交、推送、PR 检查和远端合并流程。
