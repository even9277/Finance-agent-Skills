# D05 Report SSE Progress — Milestone 5 Execution Report

## 1. Milestone Status

- Milestone: Milestone 5 — Protected Live, Documentation, Review, and Handoff
- Status: Delivery in progress
- Date: 2026-09-05
- Branch: `feat/50-report-sse-progress`
- Issue: #50
- Pull request: pending

实现、受保护 Live、最终回归与 staged diff review 已经完成；GitHub CI 与 squash merge 完成后，本报告将更新为 `Completed`。

## 2. Frozen Contract Followed

- 只执行 D05 M5，没有进入 D06。
- 真实外部路径仅运行一个固定报告案例；第一次 gate 尝试在整图/外部请求前因本机 SOCKS 依赖与旧解析链失败，不构成真实报告调用。
- Live 使用隔离 SQLite、固定测试身份、临时执行目录和仓库现有只读 Tushare toolkit；没有生产数据库、外部写操作、下单、持仓修改或报告发布。
- 没有整份报告重试；真实 LangGraph event stream 调用 1 次，fallback `ainvoke` 为 0。
- 用户未跟踪的 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` 未编辑、删除或 stage。

## 3. Protected Live Result

- Credentials gate: API Key、base URL、model、Tushare token 均只检查存在性，未输出值。
- Effective run: `1 passed, 6 warnings in 191.97s`。
- Model runs: 14；Tushare read attempts: 39；terminal `completed`。
- Progress: 14 个通知，`10→20→20→20→20→20→35→50→65→80→80→90→95→100`。
- Completed stages: PREPARING、FUNDAMENTAL_ANALYSIS、TECHNICAL_ANALYSIS、VALUATION_ANALYSIS、NEWS_ANALYSIS、SYNTHESIZING；PERSONALIZATION 按关闭配置标记 SKIPPED。
- Content SHA256: `e6318c5fa4fc517a2a22055afd6a50b11529a3afdc24766aec1450aaafbc7daa`。
- Acceptance artifact SHA256: `9bbb19543d470216ad3077506dede9f68e5445dec3f84cc8501913253b290413`；redaction scan passed。

## 4. Failure Diagnosis and Narrow Fixes

### 4.1 Pre-workflow Windows failure

- Evidence: first gated attempt ended in 7.06s with `stream_call_count=0`，没有进入真实报告图或 Tushare。
- Root cause: 旧 `stock_resolver` 实际只有 LLM 单入口；本机 SOCKS proxy 需要临时 `socksio`；解析失败分支打印 emoji 又触发 PowerShell 编码错误。
- Fix: D05 harness 固定已知股票解析结果，避免把报告进度验收扩成实体解析验收；Windows Live 命令按既有策略使用 `uv --with socksio`。

### 4.2 Prompt/report terminal leakage

- Evidence: 有效 Live 中四个旧分析 Agent 以 INFO/`print` 输出完整 Prompt 和模型正文。
- Risk: 不含凭证，但违反终端只输出摘要、长正文进入受控 artifact 的可观测性合同。
- Fix: 四个分析 Agent 的 Prompt 日志降为长度级 DEBUG 元数据，删除正文 `print`；Provider 异常只保留稳定错误类型和安全消息，不再进入日志、Agent state 或 ExecutionLogger。
- Verification: 8 个轻量 fake unit cases 锁定 stdout/INFO/state/artifact 不含 Prompt、模型正文或 raw exception；changed-surface Ruff passed。

### 4.3 Frontend first-frame and stale-response races

- Evidence: 首帧 5 秒计时器原先在 `fetch()` 返回响应头后才启动；响应头永久悬挂时无法进入 polling。另一个迟到的 generate 响应可在用户退出/切换后重新启动 SSE。
- Fix: 5 秒预算覆盖连接、响应头和首个业务帧；以 observation epoch 丢弃停止后的迟到创建响应。
- Verification: composable focused 9 passed，包含 headers hang 和 delayed create 两个回归用例。

### 4.4 Snapshot-to-subscription terminal race

- Evidence: 任务若在首个数据库快照读取后、Hub 注册前完成，终态通知会丢失并最多等待 15 秒周期 reconcile。
- Fix: Hub 注册后立即做一次短会话权威核对；数据库瞬时不可用时保留已建立的 Hub 观察链，不伪造失败。
- Verification: 新增 contract race case；D05 backend focused 25 passed。

## 5. Documentation

- 新增 `D05_REPORT_SSE_PROGRESS_ACCEPTANCE_REPORT.md`，将每个 Claim 映射到代码与运行证据。
- README 和测试策略补充报告 Live gate、Windows SOCKS 命令、隔离范围与 artifact 合同。
- 真实运行 artifact 保留在系统临时目录，未复制或提交正文、数据库、Key、Token。

## 6. Review and Delivery

- Review method: `code-review-excellence` checklist，覆盖 architecture、correctness、security、concurrency、compatibility、tests 和 observability。
- Blocking findings fixed: Prompt/report terminal leakage、raw provider exception leakage、SSE response-header hang、迟到 create 响应重启观察器、snapshot-to-subscription 终态竞态、Windows unresolved-stock stdout 编码失败。
- Remaining P0/P1: 0。
- PR: #51，`https://github.com/even9277/Finance-agent-Skills/pull/51`。
- Initial CI: frontend、Docker packaging、Offline Compose E2E passed；Python job 的 4 个 failure 来自隐私测试隐式继承本机 Provider 环境，CI 无 secrets 时提前走 missing-config 分支。
- CI repair: 测试显式设置无效的离线占位 Provider 配置，使 success/failure fake 路径在任何环境都真实执行；focused 8 passed，Ruff/Pyright passed；CI rerun pending。
- Squash merge: pending green checks。

最终回归已刷新：Python `402 passed, 7 skipped, 8 deselected, 3 xfailed`；frontend `43 passed` 且 lint/type-check/build 通过；最终 Compose `289 passed, 3 skipped, 48 deselected, 3 xfailed`、退出码 0。Compose 临时容器、网络和 `trace-e2e` 卷已通过冻结 cleanup 命令清理，`ps -a` 为空。

## 7. Rollback and Deferred Scope

- D05 无数据库 migration；可通过单个 squash revert 撤销。
- Live 外部动作均只读，隔离 SQLite 和临时产物可直接丢弃。
- Redis snapshot/pub-sub、multi-worker、TTL、idempotency、duplicate task、reconnect/replay 继续留在 D06。
- Compose 全量测试会在 migration 隔离用例临时删除表时让并行 memory worker 记录短暂 `ProgrammingError`；测试与 D05 报告链仍全绿，但该测试夹具噪声应在独立测试基础设施任务治理。
