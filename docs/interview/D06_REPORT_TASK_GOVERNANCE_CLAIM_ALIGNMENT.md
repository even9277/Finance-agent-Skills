# D06 报告任务治理：面试 Claim 与实现证据

## 1. 可直接口述的当前实现

报告生成属于耗时且会消耗模型与金融数据额度的长任务，所以我把“重复请求只执行一次”和“断线后恢复最新状态”作为独立治理边界。没有显式键的旧客户端按“认证用户 + NFKC 规范化命令哈希”生成默认键，终态 600 秒内复用；官方前端为一次用户意图生成 UUID `Idempotency-Key`，网络错误仅携带同键重试一次。同一用户、同一键、同一请求返回原 `task_id/report_id`，同键不同请求返回稳定 409，不同用户互不影响。

正确性不依赖 Redis。PostgreSQL 的 `report_task_governance` 表以 `(user_id, key_digest)` 唯一约束作为竞争裁决，`Report` 与治理行在同一事务创建；并发失败方回滚候选记录并读取获胜行，只有创建获胜请求注册一次 `BackgroundTasks`。任务阶段、终态和单调 `snapshot_version` 也先与 `reports` 在数据库事务中提交。

Redis 只保存带版本、TTL 和严格 Schema 的可重建快照，并用 Pub/Sub 通知其他实例“数据库出现了更新”；消费者仍回查 PostgreSQL。Redis miss、损坏、过期、重启或不可达时，系统回源数据库并保持去重正确性，不能退化为重复创建。Redis key/value 不包含原始用户 ID、命令、幂等键、Token、Prompt 或报告正文。

前端收到创建响应后保存当前用户摘要命名空间下的 `task_id/report_id/key/fingerprint`，刷新时只 GET 状态并恢复 SSE，不重新 POST。SSE 在订阅后读取/对账最新数据库快照，跨实例可由 Redis 唤醒，Redis 不可用时周期轮询数据库收口。这里承诺的是“最新快照 + 后续事件”，不是断线期间所有历史事件的完整回放。

## 2. 不能夸大的边界

- `BackgroundTasks` 仍与 Web 进程同生共死；当前没有 outbox、持久队列、ACK、租约、重试领取或崩溃续跑。
- Redis Pub/Sub 是低延迟唤醒，不是可靠事件日志；完整回放需要 Streams 或数据库事件表等独立设计。
- 幂等解决同一用户意图的重复提交，不等于全局限流、不同任务的并发预算或金融交易幂等。
- D06 没有修改报告 Prompt、Agent 拓扑、Skills、记忆语义或金融分析算法。

## 3. 冻结验收证据

| 层级 | 证据 | 结论 |
| --- | --- | --- |
| PostgreSQL 并发合同 | 20 路同键竞争 | 1 次创建/派发，19 次重放，1 条 task/report |
| Redis/快照集成 | miss、损坏、flush、restart、unreachable、stale | 全部回源 PostgreSQL，终态不回退 |
| 真双后端 Compose | Nginx `least_conn` + 2 backend + PostgreSQL + Redis | 20 请求跨进程收敛；非创建实例可观察终态 |
| 前端 | UUID key、同键一次安全重试、按用户 sessionStorage、刷新恢复 | 恢复不重复 POST，终态/任务隔离单调 |
| 受保护真实 API（2026-09-07） | 两个 ASGI 应用各 10 请求、真实模型与只读 Tushare | 1 `CREATED`、19 `REPLAYED`、1 workflow、17 model runs、46 Tushare calls、终态 `completed`、snapshot version 15、脱敏检查通过 |

这组结果是固定验收样本，不是生产 SLA 或统计显著的性能结论。完整命令、哈希和限制见 `docs/specs/D06_REPORT_TASK_GOVERNANCE_ACCEPTANCE_REPORT.md`。

## 4. 代码导航

- 合同与决策：`backend/application/report_tasks/`
- PostgreSQL/Redis 适配器：`backend/infrastructure/report_tasks/`
- 原子创建与 SSE：`backend/routers/report.py`
- 阶段快照提交：`backend/services/agent_service.py`
- 浏览器幂等/恢复：`frontend/src/composables/useReport.ts`、`frontend/src/composables/reportTaskRecovery.ts`
- 非破坏迁移：`backend/migrations/versions/20260905_05_report_task_governance.py`
- 离线与 Live 证据：`tests/integration/`、`tests/e2e/test_report_task_governance_offline.py`、`tests/e2e/test_live_report_task_governance.py`
