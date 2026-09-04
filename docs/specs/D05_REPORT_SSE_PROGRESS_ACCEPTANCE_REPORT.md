# D05 Report SSE Progress — Final Acceptance Report

## 1. Acceptance Result

- Feature: D05 authoritative report progress with SSE and bounded polling fallback
- Branch: `feat/50-report-sse-progress`
- Issue: #50
- Acceptance date: 2026-09-05
- Result: Passed

D05 已实现并验证 `report-progress-v1`：后台报告任务从真实 LangGraph 节点产生阶段事实，数据库保持恢复权威，FastAPI SSE 提供低延迟观察，前端在 SSE 失败后使用串行有界轮询收敛。当前边界仍是单 Uvicorn worker；跨 worker、durable replay 与幂等任务属于 D06。

## 2. Claim-to-Evidence Matrix

| Claim | Code evidence | Runtime/test evidence | Result |
| --- | --- | --- | --- |
| 阶段来自真实执行节点，不由前端按百分比猜测 | `backend/application/report_progress/tracker.py`、`backend/services/agent_service.py` | D05-T02；Compose real-LangGraph report E2E | Passed |
| 进度在并行乱序下单调 | completed-node count + DB progress floor | 两组乱序 unit；Live progress `10→…→100` | Passed |
| 数据库是恢复权威，Hub 可丢且不反压任务 | snapshot projector + bounded Hub | slow subscriber、disconnect、publisher failure tests | Passed |
| 快照读取到订阅注册之间的终态竞态立即收敛 | post-subscribe authoritative reconcile | dedicated contract race case | Passed |
| SSE 首帧、阶段、唯一终态使用稳定公开合同 | `report-progress-v1` schemas + native FastAPI SSE | D05-T01/T04/T08/T09 | Passed |
| Bearer 鉴权与任务存在性隐藏 | pre-stream dependency ownership check | query token rejection；cross-user/not-found 均 404 | Passed |
| 前端严格解析并抵抗畸形/乱序/跨任务帧 | strict parser + Pinia reducer | focused Vitest 16 passed | Passed |
| SSE 失败后串行有界 polling，生命周期资源可清理 | `useReport.ts` observer lifecycle | headers hang、delayed create、fake timers、task switch、unmount、terminal tests | Passed |
| Nginx 不缓冲报告事件且普通 API/WS 不回归 | exact events location | Compose proxy timing + config checks | Passed |
| 真实模型/Tushare 装配未被 fake 掩盖 | protected Live harness | 1 passed；14 model runs；39 read-only Tushare attempts | Passed |
| Prompt、正文、raw exception、Key/Token 不进入公开 SSE、终端或验收 artifact | safe projectors + low-sensitivity artifact | negative contract assertions + agent failure scan + artifact scan | Passed |

## 3. Protected Live Evidence

- Case: `d05-live-report-01`
- Command: `RUN_PROTECTED_LIVE_REPORT_E2E=true uv run --locked --with socksio python -m pytest tests/e2e/test_live_report_progress.py -q -m live -s`
- Result: `1 passed, 6 warnings in 191.97s`
- Model/provider: `glm-5.1` through the configured OpenAI-compatible endpoint
- Real model runs: 14
- Tushare read attempts: 39
- Observed read-only methods: `stock_basic`、`daily`、`pro_bar`、`fina_indicator`、`income`、`balancesheet`、`cashflow`、`index_classify`、`index_member`、`sw_daily`
- Whole-report stream calls: 1
- Whole-report fallback invokes: 0
- Terminal: `completed`, progress 100
- Report content SHA256: `e6318c5fa4fc517a2a22055afd6a50b11529a3afdc24766aec1450aaafbc7daa`
- Ephemeral artifact: `%TEMP%/pytest-of-27411/pytest-293/test_live_report_streams_real_0/d05-live-report-acceptance.json`
- Artifact SHA256: `9bbb19543d470216ad3077506dede9f68e5445dec3f84cc8501913253b290413`
- Redaction: passed；artifact 不含固定问题、API Key、Tushare Token 或报告正文

Tushare `sw_daily` 因当前账号权限不足返回局部错误；tool contract 将其作为缺失证据处理，其他只读接口和整份报告仍正常完成。验收不对实时数值或自由文本质量做脆弱断言。

## 4. Offline and Regression Evidence

| Gate | Evidence |
| --- | --- |
| D05 focused backend | 25 passed |
| Python full | 402 passed, 7 skipped, 8 deselected, 3 xfailed |
| Frontend focused/full | 16 / 43 passed |
| Frontend lint/type/build | Passed |
| Compose production proxy chain | 289 passed, 3 skipped, 48 deselected, 3 xfailed |
| Changed-surface Ruff/Pyright | Passed / 0 errors |
| Secret/redaction scan | No usable credentials found |

## 5. Accepted Limitations

- 当前进程内 Hub 只用于单 worker 低延迟通知，不提供跨进程、跨重启或事件 replay。
- 页面刷新后的恢复依赖数据库快照与轮询，不接受 `Last-Event-ID` replay。
- Tushare 各 API 的账号权限可能不同；单项证据失败不会伪装为成功数据。
- 报告 Agent 的主观文案质量不属于 D05 gate；本轮验证的是真实调用、阶段事实、终态、传输和安全边界。
- Compose 测试运行中的 memory worker 会在 migration 隔离用例临时删除表时记录瞬时错误；不影响 D05 链路或退出码，后续应由测试基础设施任务消除该噪声。

上述基础设施与幂等能力进入 D06，不在 D05 中提前引入 Redis 或新任务系统。
