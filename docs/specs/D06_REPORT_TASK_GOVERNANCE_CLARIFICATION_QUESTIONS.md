# D06 报告任务治理澄清结论

## 1. Clarification Context

- Source requirement: `D06_REPORT_TASK_GOVERNANCE_REQUIREMENT_SPEC.md`
- Code evidence: `D06_REPORT_TASK_GOVERNANCE_CODEBASE_RECON.md`
- Tracking issue: GitHub Issue #52
- User authorization: 已授权继续开发、受保护真实 API 测试、提交、推送、PR、Review 与合并。

本文件把 D06 的开放问题冻结为可进入方案权衡的产品与工程合同。授权只覆盖隔离测试数据、可回滚迁移和本 Issue 的远端协作；不包括破坏性数据库操作、生产数据写入、明文凭据、通用队列平台、任务取消/暂停或修改金融分析结论。

## 2. Frozen Decisions

| ID | Question | Frozen decision | Reason / evidence |
| --- | --- | --- | --- |
| D06-Q01 | 最终幂等口径 | 默认键保持面试 Claim：`user_id + normalized command hash`，有效期 600 秒；API 同时接受可选 `Idempotency-Key`，用于调用方稳定重试与显式新意图 | 兼容既有客户端与面试口径，同时为标准 API 客户端提供更精确的请求意图控制 |
| D06-Q02 | 显式键语义 | 同一用户、同一键、同一 command fingerprint 返回原 `task_id/report_id`；同一键配不同 fingerprint 返回稳定 `409 IDEMPOTENCY_KEY_CONFLICT`；不同用户互不影响 | 防止误复用，又不泄露其他用户任务存在性 |
| D06-Q03 | 未传显式键 | 服务端从规范化 command 生成确定性键；同用户 600 秒内相同命令复用；调用方若确需立即重新生成，必须传新的显式键 | 精确对应面试描述；旧客户端无需改造即可受保护 |
| D06-Q04 | command 规范化 | Unicode NFKC、去首尾空白、连续空白折叠为一个空格；保留大小写和标点；只存 SHA-256 fingerprint，不在治理表或 Redis key 中存原始命令 | 确定、跨实例一致，并降低敏感输入扩散 |
| D06-Q05 | 幂等权威 | PostgreSQL 唯一约束是最终正确性；Redis 仅做短期命中加速、跨实例状态快照和通知 | Redis 故障、重启或过期时仍不能重复触发付费工作流 |
| D06-Q06 | 数据模型 | 新增 Alembic 管理的独立 `report_task_governance` 表，关联既有 report/task/user，保存 key digest、request fingerprint、有效期和持久快照版本/阶段状态；不直接改造 legacy `reports` 建表所有权 | 当前 `create_all + Alembic` 是混合模式；独立表最容易安全迁移和回滚 |
| D06-Q07 | 创建事务 | `Report` 与治理行在同一数据库事务创建；唯一约束竞争的失败方 rollback 后读取获胜行，不创建第二个 Report，不注册第二个后台任务 | 从根源阻止双任务、双模型调用和双副作用 |
| D06-Q08 | 后台任务派发 | 只有成功创建治理行的请求注册一次 `BackgroundTasks`；replay 请求只返回已有标识 | 当前进程内 BackgroundTasks 不可持久恢复，但同进程并发必须 exactly-once dispatch |
| D06-Q09 | 崩溃续跑边界 | D06 不承诺 HTTP 响应后进程崩溃时自动续跑；pending 任务可被状态 API/SSE 观察，但 durable queue/outbox/worker recovery 属于后续任务 | 用户本轮目标是幂等、快照、断线和多实例观察，不是队列平台迁移 |
| D06-Q10 | 进行中 TTL | 治理行不因 600 秒到期而失去进行中任务的复用；`pending/running` 始终复用，终态在创建后 600 秒内复用；过期终态允许新建 | 防止长报告执行超过 10 分钟时被重复提交 |
| D06-Q11 | Redis 故障语义 | fail-open 到 PostgreSQL，而不是 fail-open 到重复执行；请求保持正确但可能增加延迟，并记录低敏、低基数降级日志/指标 | 比历史 Redis-only 实现更可靠，也使数据库权威真正成立 |
| D06-Q12 | Redis key | 版本化 namespace + HMAC/SHA-256 digest，不包含原始 user ID、command、token 或显式 idempotency key；TTL 可配置，默认 600 秒 | 防键名泄露、碰撞和跨环境污染 |
| D06-Q13 | Redis 数据校验 | JSON envelope 含 schema version、user/task/report/key digest、request fingerprint、snapshot version、expires_at；读取时校验全部关联；损坏、错配或未知版本删除并回源 DB | Redis 数据均可丢弃和重建，不能把污染快照当真相 |
| D06-Q14 | 状态快照权威 | `reports` 提供任务级 status/progress/content 终态；治理表持久化 stage map 和全局 snapshot version；Redis 是两者的短期组合投影 | 支持断线后恢复最新完整阶段，又不把 Redis 变成唯一状态源 |
| D06-Q15 | 快照写入顺序 | 工作流状态先在同一短事务更新 Report/治理行并提交，再更新 Redis/通知；Redis 失败不得回滚已提交业务状态 | 延续 D05 的 commit-before-publish，避免假成功和双真相源 |
| D06-Q16 | 跨实例通知 | 优先使用 Redis Pub/Sub 通知“某 task 有新版本”，消费者收到后读取并校验最新快照；丢通知时由周期 DB/Redis 校准收口 | Pub/Sub 只作唤醒，不承载唯一事件历史，断线也可恢复 |
| D06-Q17 | 恢复目标 | latest snapshot + 后续更新，不实现完整历史 event replay；新连接立即返回当前快照并从持久 `snapshot_version` 继续 | 这是当前 UX 所需的最小可靠语义；Redis Streams/完整审计日志不在本轮 |
| D06-Q18 | SSE sequence | `report-progress-v1.sequence` 改为任务级持久 `snapshot_version`，跨连接/实例单调；heartbeat 不占版本；重复版本忽略 | 旧客户端仍接受正整数，新前端可据此去重并恢复，不新增平行协议 |
| D06-Q19 | 快照版本 | 创建任务版本从 1 开始；每次真实状态变化在数据库中原子递增；相同状态重复写不递增；终态锁定 | 提供可测试的单调游标并避免重复帧 |
| D06-Q20 | REST 创建响应 | 保留现有 `task_id/report_id/status`，新增向后兼容字段 `idempotency_status=CREATED|REPLAYED`、`expires_at`；冲突使用稳定结构化错误 | 旧调用方不受影响，新前端可展示复用而不是误报新建 |
| D06-Q21 | 状态与 SSE 所有权 | 所有读路径继续先按认证用户约束 task/report；不存在和跨用户统一安全 404；Redis 命中也必须验证 owner binding | 缓存不能绕过数据库所有权语义 |
| D06-Q22 | 前端提交 | 每次用户明确点击生成创建一个随机显式 key；网络重试和响应丢失恢复复用该 key；刷新时仅持久化活动 task/report/key/command fingerprint 的最小记录，按用户隔离并在登出/终态清理 | 区分“主动再次生成”与“同一请求重试”，同时保留服务端默认 command-hash 兼容语义 |
| D06-Q23 | 前端存储 | 使用 `sessionStorage`，键含认证用户的不可逆短摘要；不保存 command 正文、token、报告正文或画像；恢复前必须向服务端验证所有权和状态 | 只覆盖同一浏览器标签页刷新，降低隐私和陈旧状态风险 |
| D06-Q24 | 刷新恢复 | 页面载入时若存在活动记录，先恢复同一 task 的 SSE；SSE 失败仍轮询同一 task；禁止重新 POST `/generate` | 直接解决响应后断线/刷新导致重复报告的问题 |
| D06-Q25 | 多标签页 | 服务端幂等和数据库唯一约束是最终保证；不新增 BroadcastChannel/全局浏览器锁 | 避免把正确性放到浏览器，并控制 D06 范围 |
| D06-Q26 | 配置 | 在现有 typed Settings 中新增 report governance enable/namespace/TTL/PubSub reconcile/timeout 配置并写入 `.env.example`；生产无默认凭据 | 延续集中配置和可测试注入，不散落 `os.getenv()` |
| D06-Q27 | Redis 不可用启动 | 应用可启动，报告创建和轮询继续通过 PostgreSQL 工作；SSE 退化为 DB 校准；health 暴露 `DEGRADED` 而非整体失败 | Redis 不是 correctness dependency |
| D06-Q28 | 历史实现 | `origin/feature/redis-integration-phase1` / commit `8ef46f0` 只复用规范化、NX+EX、TTL、轻量快照等概念，不复制 Redis-only 权威、占位超时、query token 或 untyped dict | 旧实现存在并发超时重复、重启丢失和安全/测试缺口 |
| D06-Q29 | 真实 API | 仅一条受保护真实报告，最多 20 个并发创建请求、相同 key、跨两个应用实例；断言只有一个 task/report/真实 workflow invocation；整轮不自动重试 | 用户已授权；限制真实模型/金融数据成本和副作用 |
| D06-Q30 | 文档口径 | 更新仓库 README/验收报告和涉及 D06 的项目阐述：保留“user + command hash + 10 分钟”，补充 PostgreSQL 唯一锚点、Redis 非权威、显式 key 与 latest-snapshot 边界 | 让面试 Claim 与真实代码一一对应，不继续宣称 Redis 单独保证幂等 |

## 3. Idempotency Contract

### 3.1 Effective Key

```text
if valid Idempotency-Key header exists:
    effective_key = "client:" + header
else:
    effective_key = "command:" + sha256(normalize(command))

key_digest = HMAC-SHA256(server_secret_or_namespace_salt,
                         user_id + ":" + effective_key)
request_fingerprint = sha256(normalize(command))
```

- Header 限制为 8..128 个可打印 ASCII 字符；非法输入返回稳定 422，不回显原值。
- 数据库和 Redis 只保存 digest/fingerprint，不保存 header 或 command 原文。
- 显式键只在同一用户作用域内唯一；相同字符串不会跨用户复用。

### 3.2 Atomic Outcomes

| Existing row | Fingerprint | State / expiry | Outcome |
| --- | --- | --- | --- |
| none | any | n/a | 创建一个 Report + governance；`CREATED`；仅一次派发 |
| same key | same | pending/running | 返回原任务；`REPLAYED` |
| same key | same | terminal and not expired | 返回原任务；`REPLAYED` |
| same key | same | terminal and expired | 原子创建新 generation；`CREATED` |
| same key | different | any | `409 IDEMPOTENCY_KEY_CONFLICT` |

过期实现不得依赖删除旧行后留下竞态。数据模型必须通过 generation/active 唯一性或等价事务策略支持可证明的原子轮换；方案阶段需给出数据库级做法。

## 4. Snapshot and Recovery Contract

一个权威快照至少包含：

```text
protocol_version = report-progress-v1
task_id / report_id
snapshot_version
task_status / progress
stage_states[]
updated_at
terminal error_code / safe message (optional)
```

- stage 状态继续遵守 D05 的合法转换；持久化层拒绝终态回退和 progress 降低。
- Redis 丢失时，从 `reports + report_task_governance` 重建 latest snapshot。
- SSE 连接先订阅通知，再读取 snapshot，之后对版本去重；以避免“读取与订阅之间”丢更新。
- Pub/Sub 断开时，连接保持有界 DB/Redis reconcile；无法校准才触发前端既有 polling fallback。
- terminal snapshot 必须在报告正文数据库提交后可见；客户端不会收到“完成但正文尚未提交”。

## 5. Failure and Compatibility Matrix

| Situation | Creation result | Execution count | Observation |
| --- | --- | --- | --- |
| 两实例同 key 并发 | 一个 CREATED，其余 REPLAYED | 1 | 都收到同 task/report |
| Redis 完全不可达 | PostgreSQL 正常创建/复用 | 1 | SSE DB 校准或 polling，health degraded |
| Redis 重启/flush | DB 回源并重建 | 不新增 | 恢复 latest snapshot |
| Redis envelope 损坏/串用户 | 删除/忽略，DB 回源 | 不新增 | 不泄露、不错误完成 |
| POST 响应丢失后重试 | REPLAYED | 1 | 返回原标识 |
| 同 key 不同 command | 409 stable conflict | 0 new | 不泄露旧 command |
| 主动重复点击且新显式 key | 新任务 | 1 new | 符合新意图 |
| 旧客户端无 header | 10 分钟 command-hash 复用 | 1 | 响应字段向后兼容 |
| 页面刷新 | 不重新 POST | 不新增 | 恢复同 task latest snapshot |
| 应用进程在执行中崩溃 | 不自动重跑 | 不承诺 | 状态保持 pending/running，后续 durable worker 解决 |

## 6. Frozen Test Scope

| ID | Layer | Single responsibility | Acceptance evidence |
| --- | --- | --- | --- |
| D06-T01 | Unit | command normalization、digest、header validation、冲突与 expiry 决策表 | 幂等合同 |
| D06-T02 | Persistence | PostgreSQL/SQLite 可运行的原子 create-or-reuse；并发竞争、唯一约束、终态过期轮换、跨用户隔离 | DB 权威 |
| D06-T03 | Redis integration | 真 Redis 的命中、TTL、损坏、错配、restart/flush、不可达和重建；断言永不绕过 owner/fingerprint | 缓存安全与故障降级 |
| D06-T04 | Snapshot | Report + governance 原子版本、阶段单调、终态锁定、重建；publish 失败不改变 DB 成功 | 恢复语义 |
| D06-T05 | Contract | POST 新建/replay/conflict/旧客户端/跨用户；20 并发请求只产生一个 report 与一次 dispatch | API 与并发 |
| D06-T06 | Multi-instance SSE | 两个 app 实例共享 PostgreSQL/Redis；A 执行、B 订阅；断连重连从持久版本恢复，不重复、不回退 | 跨实例与恢复 |
| D06-T07 | Frontend | key 生命周期、响应丢失重试、sessionStorage 隔离/清理、刷新同 task 恢复、fallback 不 POST | 用户体验与隐私 |
| D06-T08 | Offline Compose | PostgreSQL + Redis + 两 backend 实例或等价进程；并发去重、Redis restart、Nginx/SSE latest snapshot | 部署合同 |
| D06-T09 | Compatibility | D05 report progress、history/detail/download/delete，以及聊天/Skills/Memory 回归 | 无范围外破坏 |
| D06-T10 | Protected Live | 一份真实报告，20 个跨实例相同 key 创建；唯一 task/report/workflow，SSE/REST/DB 最终一致 | 真实工程证据 |

Explicit exclusions:

- 默认 CI 不访问付费模型、Tushare/MCP 或生产服务；Live 由显式环境开关保护。
- 不固定模型措辞、行情数值、并行 analyst 完成顺序或每个 heartbeat。
- 不为了测试本功能引入新的前端 E2E 框架；沿用 Vitest、backend integration、Compose 和受控浏览器检查。
- 不测试 durable queue、进程崩溃续跑、任务取消/暂停、完整历史 replay 或通用限流熔断。

## 7. Decisions Not Reopened Without New Evidence

- PostgreSQL 是幂等和可重建快照的权威；Redis 不得单独决定创建或完成。
- 不将原始命令、user ID、token、key、Prompt、工具 payload 或完整报告放入 Redis key、普通日志或验收 artifact。
- 不整包迁移历史 Redis 分支，不使用 query token，不把前端按钮禁用当并发保证。
- 不新增 Celery/Kafka/RQ/Streams event log，不把 BackgroundTasks 改造成通用任务平台。
- 不修改报告 Prompt、Agent 节点、金融计算、Skills/Memory/Tool 权限规则。
- 不编辑、暂存或提交用户未纳管的 `D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md`。

## 8. Handoff to Solution Tradeoff

方案阶段至少比较：

1. Redis-only `SET NX EX` + snapshot（历史方案）。
2. PostgreSQL 独立治理表 + Redis cache/PubSub + 持久 snapshot version（冻结合同目标）。
3. Durable queue/outbox/worker + Redis/DB（更强但超出本轮）。

比较必须覆盖：数据库原子竞争与过期轮换、现有 `create_all + Alembic` 所有权、同步/异步 publisher 接口、跨实例 subscribe-before-read、Redis 故障/污染、SSE sequence 兼容、前端恢复隐私、Python 3.11 生产兼容、默认离线测试与单次 Protected Live 成本。推荐方案不得用降低正确性、跳过数据库迁移或扩大到队列平台来换取实现便利。
