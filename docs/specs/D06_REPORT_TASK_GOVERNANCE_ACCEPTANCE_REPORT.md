# D06 报告任务治理最终验收报告

## 1. 结论

D06 的冻结验收范围已通过：同一用户意图的重复/并发创建由 PostgreSQL 唯一约束收敛，Redis 仅作可重建快照和跨实例唤醒，前端可以在不重复 POST 的前提下刷新恢复，SSE/轮询最终以 PostgreSQL 最新快照收口。受保护真实 API 只执行了一份报告，且没有自动重跑。

## 2. 受保护真实 API 证据

- 执行日期：2026-09-07（Asia/Shanghai）
- 拓扑：两个独立 FastAPI ASGI 应用，共享本机一次性 pgvector/PostgreSQL；真实 OpenAI-compatible 模型；现有只读 Tushare toolkit
- 并发：20 个相同显式幂等键请求，两个应用各 10 个
- API 结果：`CREATED=1`、`REPLAYED=19`，唯一 task=1，唯一 report=1
- 实际执行：后台派发=1，LangGraph workflow stream=1，fallback invoke=0
- 外部调用：model runs=17，Tushare calls=46；Tushare `sw_daily` 权限不足被既有 Agent 工具容错处理，最终报告不受阻断
- 持久状态：terminal=`completed`，progress=100，snapshot version=15
- 一致性：观察应用的 REST、SSE、数据库终态一致；详情正文与数据库正文 SHA-256 一致
- 耗时：167660.48 ms
- 正文 SHA-256：`dbaabb0715bb0fcfea59d93a9683149a5b740359cf467d322b80b4c948de80e1`
- 临时脱敏 artifact SHA-256：`2432c5083326937777549c2048a9f0163b7479a28311bf4106bf57ceda513f1a`
- 脱敏：通过；验收摘要不含请求正文、原始用户、原始幂等键、API key、Tushare token 或报告正文
- 清理：精确命名的一次性 PostgreSQL 容器已停止并由 `--rm` 删除

两个 ASGI 应用用于证明独立应用对象和连接生命周期；它不是两个 OS 进程。真实 Nginx 双后端进程、PostgreSQL 和 Redis 的跨实例证据由离线 Compose E2E 单独提供，二者不混称。

## 3. 最终验收矩阵

| 验收面 | 结果 | 关键证据 |
| --- | --- | --- |
| 规范化与显式键合同 | 通过 | NFKC/空白折叠、摘要存储、同键冲突 409、跨用户隔离 |
| PostgreSQL 原子创建 | 通过 | `(user_id, key_digest)` 唯一约束；Report + governance 同事务；20 路仅一位获胜者 |
| 终态换代与 TTL | 通过 | pending/running 不因 TTL 失去保护；过期终态行锁换代 |
| 持久快照 | 通过 | stage/status/progress/version 单调；终态不可回退；正文与终态同事务 |
| Redis 非权威语义 | 通过 | 缺失、损坏、陈旧、flush、restart、unreachable 均回源 DB |
| 跨实例观察 | 通过 | Pub/Sub 仅携摘要引用/version；观察端重读 DB；周期 reconcile 兜底 |
| 前端重试与恢复 | 通过 | 每次用户意图 UUID；同键一次安全重试；刷新 GET 恢复，不重复 POST |
| 鉴权与隐私 | 通过 | 所有权先由 DB 校验；key/value/log/artifact 不含冻结敏感字段 |
| 默认回归 | 通过 | 本机 `441 passed, 14 skipped, 9 deselected, 3 xfailed`；前端 53 tests + lint/type/build |
| 真基础设施 | 通过 | Compose `335 passed, 4 protected-live skipped, 48 deselected, 3 xfailed`；D06 定向 27/27 |
| 真实报告 | 通过 | 20 请求、1 workflow、17 model runs、46 只读 Tushare calls、completed |

## 4. 已知边界与后续项

- FastAPI `BackgroundTasks` 不提供进程崩溃后的可靠续跑；生产级需求应另立任务评估 outbox/队列/独立 Worker、ACK、租约、重试与死信。
- Redis Pub/Sub 与最新快照不提供完整历史事件回放。
- 当前未声明生产 SLA、压测容量、跨地域容灾或真实 Langfuse 在线闭环。
- 仓库全量 Pyright 仍有 4 个未触达的 provider 历史错误；D06 触达范围为 0 error。
- Live 中观察到 Starlette TestClient、naive UTC 和 LangGraph legacy factory 的既有弃用 warning，不影响本次合同，后续应独立治理。

## 5. 回滚

功能可通过报告治理/Redis feature flags 回到 D05 兼容路径；迁移使用独立治理表，生产回滚应先关闭功能并保留报告数据。合并后如需撤销，使用独立 revert/forward-fix PR，不重写共享历史。
