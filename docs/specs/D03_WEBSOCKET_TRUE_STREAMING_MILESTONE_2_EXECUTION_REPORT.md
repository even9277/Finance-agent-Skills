# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone：2 — Implement Core Streaming Runtime
- Status：Complete
- Date：2026-09-01

## 2. Development Standards Read

- `D03_WEBSOCKET_TRUE_STREAMING_PLAN.md`：只执行 Provider → Synthesizer → Workflow/Application 核心增量链。
- 根 `AGENTS.md`：遵守测试先行、单运行时、强类型/中文接口文档、敏感信息不落日志和窄 diff 约束。
- `small-step-implementation`：本轮只完成一个已冻结里程碑并更新治理证据。

## 3. Files Inspected

- `Financial-MCP-Agent/src/conversation/{contracts,errors,ports,synthesis,workflow}.py`
- `backend/application/chat/{contracts,use_case}.py`
- `backend/infrastructure/chat/{providers,testing}.py`
- 受影响 fake models、合成 eval、HTTP live 审计和 D03 流式合同测试。

## 4. Files Modified

- Conversation contracts/ports：新增供应商无关 `ModelSynthesisChunk`，模型端口迁移为 `stream_synthesize`。
- `synthesis.py`：新增安全增量入口；完整回答聚合同一条流；PARTIAL 缺口为显式首段。
- `workflow.py`：在原受控链合成阶段逐段回调，同时重建唯一 `ConversationResult.reply`；Provider 技术失败向 Application 传播。
- Application contracts/use case：新增 typed 生命周期事件、请求标识、TTFT/哈希/数量统计、确认式背压、内容一致性校验和取消回滚。
- Provider/fakes/live audit：真实适配器使用 LangChain `astream`，过滤空 chunk；所有离线替身和真实调用审计迁移到新端口。
- Tests：补齐多 chunk、单 chunk/PARTIAL、技术失败、提交、关闭流取消和回滚合同。

## 5. Implementation Summary

核心运行时现在只有一条模型生成路径：Provider 产生真实上游 chunk，Synthesizer 校验并转发，Workflow 同步累计最终正文，Application 通过容量 1 且需消费确认的事件队列施加背压。流式与 HTTP 都调用同一 `_execute`；流式模式在持久化前验证所有 delta 拼接值与领域终态正文完全一致。Provider 技术失败或消费端取消会越过业务终态并触发 Repository rollback；合法 PARTIAL 和无上游 chunk 的业务分支仍产生可提交的单 delta/Completed 语义。

## 6. Key Engineering Decisions

- 不保留 `ainvoke` 完整回答旁路，避免双运行时漂移。
- 不做字符事后切片；单 chunk 是合法供应商降级，多个 chunk 必须保持上游原序。
- 队列事件携带 acknowledgement；Router 只有在成功发送后继续迭代，才能允许上游继续和最终提交。
- `Completed` 只在 `_execute` 已提交后产生；`Failed` 不携带内部异常正文。
- 非模型/记忆命令分支在提交前发一个权威 delta，使断连和内容一致性获得相同约束。

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| focused `ruff check` | 运行时、适配器与迁移测试静态质量 | Passed |
| targeted `pyright` | chunk/event/stream 公共边界和测试类型 | 0 errors, 0 warnings |
| focused core pytest | Provider、Synthesizer、Application、Workflow、Skills/News/Eval/E2E 回归 | 46 passed, 1 deselected |
| `pytest backend -q` | Backend 子树回归 | 11 passed；56 个既有 datetime deprecation warnings |
| `pytest Financial-MCP-Agent -q -m "not live"` | Agent 子树离线回归 | 33 passed, 4 deselected |
| REST/Skill non-WS contract selection | HTTP 共享核心与响应合同 | 5 passed, 4 deselected；1 个既有 TestClient deprecation warning |
| `git diff --check` | 空白和补丁完整性 | Passed；仅 Git 的 LF→CRLF 工作区提示 |

## 8. Test Results

- 多模型增量严格按序公开并拼接为唯一最终回复。
- 最终 `chunk_count` 与 `content_sha256` 和持久化正文一致。
- 业务 PARTIAL 明确发送缺口首段并正常提交。
- 技术失败返回安全 Failed 事件，Repository rollback 且不保存结果。
- 消费端关闭 Application stream 会取消仍运行的工作流并回滚未提交事务。
- HTTP 与现有 Skills/News/Eval 离线链未回归。
- Router v2 与前端红测未在本里程碑执行修复，分别属于 M3/M4。

## 9. Failures and Fixes

- Pyright 报告主工作流复杂度超限：抽取合成回调和异常策略子过程，保持业务分支不变后恢复 0 error。
- `AsyncIterator` 不公开 `aclose()`：Application 流接口改为更准确的 `AsyncGenerator[ChatStreamEvent, None]`。
- 最初的有界队列仍允许执行在 socket 发送失败前推进：增加逐事件 acknowledgement，把消费者确认传播成真正背压。
- Ruff formatter 自动沿用 CRLF 并扩大 tracked diff：未保留批量重排，使用 Git 功能差异重放和小补丁恢复到窄 diff；生成的 `tsconfig.node.tsbuildinfo` 换行噪声已定向恢复。

## 10. Scope Compliance

- Router/frontend behavior changed：No。
- New dependency/database/config/prompt/Skill/memory/tool rule：No。
- HTTP duplicate workflow：No。
- User untracked documents preserved：Yes。
- Generated artifact retained：No。

## 11. Risks Remaining

- M3 必须用 `contextlib.aclosing` 或等价显式关闭，保证 WebSocket `send_json` 失败/断连立即关闭 Application generator；否则回滚依赖异步生成器最终化时机。
- Router 尚未负责全帧严格 sequence、v2 envelope、skill_confirm 共存和安全观测字段。
- 真实 OpenAI-compatible Provider 可能把 `astream` 退化为单 chunk；必须由受保护 live WebSocket 验收 `>=2` 非空 delta。

## 12. PLAN.md Updates

- Progress：Milestone 2 标记完成。
- Decision Log：记录唯一增量端口、确认式背压、正文一致性和技术失败策略。
- Discoveries：记录普通有界队列的提交竞态和非模型分支降级。
- Outcomes/Handoff：下一步冻结为 Milestone 3。

## 13. Suggested Commit Message

```text
feat(d03): implement core true-streaming runtime

- stream provider chunks through synthesis and workflow
- add acknowledgement-backed application events
- enforce reply consistency and rollback on interruption
```

## 14. Handoff

Milestone 2 完成。下一次续跑只执行 Milestone 3：WebSocket v2 Router、发送/断连取消、终态互斥、sequence 和无正文 observability；前端消费留给 Milestone 4。
