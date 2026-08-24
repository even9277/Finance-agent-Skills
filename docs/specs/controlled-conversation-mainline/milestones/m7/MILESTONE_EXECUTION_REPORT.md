# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 7 — Observability, Eval, CI, and Real Compose E2E Closure
- Status: Complete, pending GitHub PR delivery at report creation time
- Date: 2026-08-24
- GitHub tracking: [Issue #17 — feat(observability): close controlled-chat trace, eval, CI, and live E2E](https://github.com/even9277/Finance-agent-Skills/issues/17)
- Local branch: `feat/17-controlled-chat-observability-live`

## 2. Scope and Standards

- 没有修改 M6 冻结的公开 API、数据库 Schema、事务边界或鉴权合同。
- JSONL/Langfuse exporter 只接收统一脱敏后的阶段记录；观测失败不改变业务终态。
- 默认测试仅 Fake 外部 Model/Tool Ports；真实调用必须显式开启且禁止生产写。
- Compose 保留真实 Nginx、FastAPI、Application、Orchestrator、Trace Adapter、Repository 和 PostgreSQL。
- 没有新增生产依赖；本机 SOCKS 只通过 uv 临时依赖完成 Live 验收。

## 3. Observability Closure

- `WorkflowEvent` 映射为一个 `controlled-conversation-mainline` root Trace 和稳定的 `controlled_chat.<stage>` Span。
- Trace 携带 `trace_id/run_id/session_id/sequence/stage/status/elapsed_ms/error_code` 和低风险 attributes。
- `context` 首事件创建 root，`termination` 写入唯一 root 终态 `ok/partial/error`。
- JSONL 和可选 exporter 共用递归脱敏；测试覆盖嵌套敏感字段与 exporter 异常隔离。
- Compose 使用共享只读卷让测试执行器核验后端 Trace，验收后删除卷。

## 4. Eval and CI Closure

- 新增版本化 mainline 数据集，覆盖成功、歧义澄清和证据不足有界降级。
- 新增 `terminal_status_accuracy` 与 `required_stage_coverage`，固定数据集均为 `1.0`。
- 默认 CI 的 Ruff/Pyright 扩大到 Application、Infrastructure、Router、Schema、Conversation、Prompt registry、Trace 和 tests。
- 新增仅手工触发的 protected Live workflow；缺少 secrets 会失败而不是跳过。

## 5. Test and Check Evidence

| Check | Result |
| --- | --- |
| Trace adapter + mainline eval focused | `4 passed` |
| M7 scoped Ruff | `All checks passed` |
| M7 scoped Pyright | `0 errors, 0 warnings` |
| Backend offline | `11 passed` |
| Agent offline | `33 passed, 4 deselected` |
| Offline eval smoke | `11 passed` |
| Default full regression | `126 passed, 2 skipped, 5 deselected` |
| Frontend lint/type-check/build | 全部通过；保留既有 bundle size warning |
| Offline Compose | 真实 Nginx/FastAPI/Workflow/Trace/PostgreSQL，Fake 外部 Ports；`73 passed, 1 skipped` |
| Protected live | 真实 LLM + 真实只读 Tushare + HTTP + 临时 SQLite + Trace；`1 passed` |
| Compose cleanup | 容器、网络和 `trace-e2e` 卷已删除 |
| `git diff --check` | 通过 |

## 6. Live Evidence

- 固定问题：贵州茅台 `600519.SH` 基础信息与近期行情。
- 真实 Model Adapter 调用一次，真实 Tushare Adapter 返回非空 `tushare:` 来源事实。
- HTTP 200；临时 SQLite 中消息顺序严格为 `user → assistant`。
- 12 阶段 Span 顺序完整，root `started → ok`，终态 `SUCCEEDED`。
- Trace 索引见 `TRACE_ARTIFACT_INDEX.json`；不保存原始 Prompt、回答、Token 或数据库转储。

## 7. Failure and Recovery Record

测试先行阶段因 Trace Adapter/指标尚不存在而按预期 collection 失败，不计修复次数。首次 Live 命令直接调用虚拟环境 `pytest.exe`，导致 uv 临时 `socksio` 未进入解释器，在 Provider 构造前失败且未产生外部调用；改用 `python -m pytest` 后一次通过。这是命令环境修正，不涉及业务实现修复。其余门禁无实现后失败。

## 8. Remaining Risks and Honest Limitations

- GitHub protected Live workflow 已定义，但 Environment secrets/审批规则由仓库管理员配置；本次真实证据来自本地显式运行。
- Langfuse exporter 通过单元测试证明脱敏与失败隔离，本里程碑没有向真实 Langfuse 项目发送数据。
- 固定 mainline eval 证明合同与终止行为，不代表历史 70.2%→88.4%、95%+ 等指标已经复测。
- WS 仍是终态文本帧，不是 Provider token streaming；Redis、分布式限流、Alembic 和正式 CD 仍为 Deferred Work。
- Compose 仍会打印已登记的 PostgreSQL 旧增量初始化噪声；不影响健康与验收，但应另开 Schema 规格治理。
- Starlette TestClient、`datetime.utcnow()` 与前端大 chunk warning 是存量技术债。

## 9. Rollback

M7 无 Schema 或依赖迁移。合并后可 revert 单个 squash commit，恢复 M6 的日志 Trace 与较窄 CI；M6 受控入口和数据库数据不受影响。Live workflow 只读且不产生可回滚的生产副作用。

## 10. Suggested Commit Message

```text
feat(observability): close controlled chat verification

- map workflow events to redacted root traces and stage spans
- add versioned mainline evals and real-orchestrator Compose assertions
- add explicit real LLM and read-only Tushare live E2E

Closes #17
```

## 11. Handoff

下一个且唯一执行单元是 M8：只做最终窄修、文档与面试口径逐模块事实核对、独立 Review 和最终交付，不扩展新功能。
