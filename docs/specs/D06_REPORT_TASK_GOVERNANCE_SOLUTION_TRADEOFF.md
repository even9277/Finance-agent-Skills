# D06 报告任务治理方案权衡

## 1. Tradeoff Context

D06 要解决的不是“按钮防重复”，而是报告创建、后台执行和跨实例观察之间缺少可恢复的一致性合同：当前每次 POST 都创建 UUID、写 Report 并注册 BackgroundTasks；进程内 progress hub 无法跨 worker，也无法在断线或重启后还原阶段。核心约束是保留 `user_id + command hash + 600s` 的面试口径，同时将正确性从 Redis 提升到 PostgreSQL，并在不引入通用队列平台的前提下提供 latest-snapshot 恢复。

## 2. Inputs Reviewed

- REQUIREMENT_SPEC.md: `D06_REPORT_TASK_GOVERNANCE_REQUIREMENT_SPEC.md`
- CODEBASE_RECON.md: `D06_REPORT_TASK_GOVERNANCE_CODEBASE_RECON.md`
- CLARIFICATION_QUESTIONS.md: `D06_REPORT_TASK_GOVERNANCE_CLARIFICATION_QUESTIONS.md`
- User decisions: 已授权 D06 开发、隔离真实 API、GitHub 协作、Review 与合并；需求/测试必须先冻结，代码与面试 Claim 必须对应。
- External sources: PostgreSQL、SQLAlchemy、Redis、FastAPI 官方文档；本仓库 D05 端口与 Memory Redis 模式；历史 commit `8ef46f0` 作为 rejected baseline。

## 3. User Decisions and Defaults

### 3.1 Confirmed Decisions

- 同用户相同问题默认 10 分钟复用；显式 `Idempotency-Key` 区分网络重试与主动新生成。
- PostgreSQL 唯一约束保证并发正确性；Redis 仅负责可丢弃加速、快照副本与跨实例唤醒。
- 恢复 latest snapshot 和随后更新，不实现完整历史 replay。
- 保留 BackgroundTasks，本轮不引入 Celery/Kafka/RQ 或任务取消/暂停。
- 真实 API 只执行一份报告，最多 20 个跨实例并发创建请求；默认测试不访问外部服务。

### 3.2 Conservative Defaults Used

- 新增 Alembic 管理的独立治理表，避免修改 legacy `reports` 的 `create_all` 所有权。
- Redis Pub/Sub 只发布 task digest + snapshot version 的失效通知；数据内容从已校验快照读取。
- 任务级持久版本复用 `report-progress-v1.sequence`，保持 wire 字段兼容。
- Redis 故障时回源数据库并标记 degraded，不拒绝报告创建，也不放弃幂等。
- 前端只在 `sessionStorage` 保存最小活动任务引用，不保存原命令、token 或报告正文。

### 3.3 Blocking Decisions

无未决 P0。数据库可回滚迁移、公开 API 的向后兼容新增字段、Redis 报告运行时和受保护 Live 均已在用户授权与冻结边界内。

## 4. Core Decision Point

选择以 PostgreSQL 独立治理记录作为“创建一次 + 最新快照”的事务权威，以 Redis 作为可丢弃快照镜像和跨实例版本通知，并继续让 FastAPI BackgroundTasks 只消费获胜创建请求；拒绝 Redis-only 幂等，也暂不升级为 durable queue。

## 5. Reference Sources and Repository Evidence

### 5.1 Official Docs

#### Source: PostgreSQL INSERT / ON CONFLICT

**Link:** https://www.postgresql.org/docs/current/sql-insert.html
**What was inspected:** 唯一索引冲突仲裁、`ON CONFLICT` 的原子行为与 `RETURNING`。
**Relevant practice:** 并发 get-or-create 必须让唯一索引参与插入，而不是先查再写；冲突方由数据库等待并裁决。
**Reusable part:** Directly reusable。
**Fit for this task:** 治理表唯一键可保证两个应用实例中只有一个创建赢家；失败方 rollback 后读取赢家，不会留下 loser Report。

#### Source: PostgreSQL Constraints / Unique Partial Index

**Link:** https://www.postgresql.org/docs/current/ddl-constraints.html
**What was inspected:** 多列唯一约束和只覆盖部分行的 unique partial index。
**Relevant practice:** 唯一性由数据库约束表达；时间变化条件不适合放入依赖 `now()` 的 partial predicate。
**Reusable part:** Partially reusable。
**Fit for this task:** 使用稳定 `(user_id, key_digest)` 唯一行并在行锁内原子轮换过期 generation，比“按当前时间动态部分索引”更可靠。

#### Source: SQLAlchemy PostgreSQL `INSERT ... ON CONFLICT`

**Link:** https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert
**What was inspected:** PostgreSQL dialect 的 `on_conflict_do_nothing()` / `on_conflict_do_update()` 与 returning 支持。
**Relevant practice:** 在仓库既有 AsyncSession 上使用 dialect 原语，不手写易错字符串 SQL。
**Reusable part:** Directly reusable for PostgreSQL；SQLite 测试需使用等价唯一冲突路径。
**Fit for this task:** 允许服务层将 winner 判定和 ORM 事务保持在现有技术栈内。

#### Source: SQLAlchemy Session transaction / SAVEPOINT guidance

**Link:** https://docs.sqlalchemy.org/en/20/faq/sessions.html
**What was inspected:** flush 触发唯一异常后事务失效、显式 rollback 和 `begin_nested()` 的边界。
**Relevant practice:** 唯一竞争失败后不可继续使用未回滚 Session；测试不能假设 SQLite 与 PostgreSQL 的 savepoint 行为完全一致。
**Reusable part:** Directly reusable。
**Fit for this task:** loser 路径必须结束失败事务后重新读取，避免在 aborted transaction 上查询赢家。

#### Source: Redis Pub/Sub

**Link:** https://redis.io/docs/latest/develop/pubsub/
**What was inspected:** channel fan-out、同发布者顺序和 at-most-once/fire-and-forget 交付语义。
**Relevant practice:** Pub/Sub 适合通知，不适合作为唯一事件记录；离线订阅者永久丢消息。
**Reusable part:** Directly reusable as invalidation/version wake-up；Not suitable as truth or replay log。
**Fit for this task:** subscribe-before-read + 持久 snapshot version + 周期校准可以安全容忍丢通知。

#### Source: Redis Pub/Sub use cases

**Link:** https://redis.io/docs/latest/develop/use-cases/pub-sub/
**What was inspected:** 跨服务/节点实时广播、持久状态与 Pub/Sub 分离、需要 replay 时使用 Streams。
**Relevant practice:** 将 durable state 放在普通 key 或外部数据库，Pub/Sub 仅作实时 fan-out。
**Reusable part:** Directly reusable。
**Fit for this task:** 正好对应“PostgreSQL/Redis snapshot 为状态，Pub/Sub 只提示有新版本”；Streams 因无需历史 replay 而延期。

#### Source: FastAPI Background Tasks

**Link:** https://fastapi.tiangolo.com/tutorial/background-tasks/
**What was inspected:** response 后同进程执行语义，以及跨进程/多服务器重任务应考虑 Celery 等队列的官方 caveat。
**Relevant practice:** 明确 BackgroundTasks 不等于 durable distributed worker。
**Reusable part:** Directly reusable for documenting the D06 boundary；队列建议为 Conceptual only。
**Fit for this task:** D06 可保证创建路由只派发一次，但不能宣称进程崩溃自动续跑。

### 5.2 Open-source Repositories

#### Source: Current repository D05 report progress implementation

**Link:** local repository, base commit `80f4a0c`
**What was inspected:** `backend/application/report_progress/*`、`run_report_task` 的 commit-before-publish、SSE presenter、数据库 snapshot projector、前端严格 parser/reducer 与 protected live harness。
**Relevant practice:** typed protocol-independent publisher、真实节点发布、数据库终态收口、安全错误与单任务前端生命周期。
**Reusable part:** Directly reusable。
**Fit for this task:** D06 应替换/组合基础设施适配器和版本来源，不建立第二套报告状态 UI。

#### Source: Current repository Memory Redis implementation

**Link:** local repository, `backend/infrastructure/memory/redis_cache.py`
**What was inspected:** 版本化 envelope、hashed refs、TTL、malformed delete、fail-open、health/metrics、短超时和测试注入。
**Relevant practice:** Redis 必须可丢弃、严格解码、低敏 key、可观测降级。
**Reusable part:** Partially reusable；接口和运行时需保持 report ownership，不能让 Memory adapter 拥有报告业务。
**Fit for this task:** 可复用编码/故障模式和配置风格，不复用 memory-specific domain types。

#### Source: Historical Redis integration branch

**Link:** local remote ref `origin/feature/redis-integration-phase1`, commit `8ef46f0`
**What was inspected:** `user_id + command hash`、`SET NX EX` 占位、TTL、Redis report snapshot 和旧 SSE。
**Relevant practice:** 命令规范化、10 分钟窗口与轻量快照体现了原面试 Claim。
**Reusable part:** Conceptual only。
**Fit for this task:** Redis-only fail-open、3 秒占位超时、原始 user key、query token 和 fake 测试无法满足 D06 正确性与安全合同。

### 5.3 Local Project Patterns

| Local pattern | Evidence from CODEBASE_RECON.md | How to reuse |
| --- | --- | --- |
| typed Application port | D05 `ReportProgressPublisher` 与 contracts | 扩展为可等待的协调端口，wire/SSE 仍留在 router presenter |
| commit-before-publish | `run_report_task` 先更新 Report 后调用 publisher | 先原子提交 Report + governance snapshot，再写 Redis/通知 |
| DB authoritative fallback | D05 snapshot projector；Memory cache fail-open | Redis miss/error/corruption 时读取 DB，不返回空成功 |
| versioned Redis envelope | Memory Redis adapter | 为 report snapshot 使用独立 schema/version/decoder 和低敏 key |
| centralized typed Settings | `backend/config.py` validators | 新增 report governance TTL/reconcile/timeout，并统一校验 |
| Alembic-managed new tables | Memory 表排除 `create_all` 后由 migrations 创建 | 将新治理表加入 managed set，避免 fresh DB 双创建 |
| strict frontend reducer | D05 `reportProgressStore.ts` | 将 sequence 解释为持久 snapshot version，重复/迟到不回退 |
| protected live opt-in | D04/D05 live tests | 使用显式开关、一次真实报告、低敏 artifact 和无整轮重试 |

## 6. Reusable Patterns

### 6.1 Directly Reusable Patterns

- PostgreSQL 唯一键参与原子 insert；赢家提交，输家 rollback 后 select。
- D05 的 typed stage/status、commit-before-publish、owner-bound snapshot、严格 SSE parser/reducer。
- Redis Pub/Sub 只作为“版本有变化”的通知，状态始终从 versioned snapshot 读取。
- 现有 Redis 的短连接超时、fail-open 回源、schema 校验、malformed delete、health/metrics。

### 6.2 Partially Reusable Patterns

- 历史 command hash/600 秒算法保留产品语义，但 digest、安全键、数据库锚点和冲突合同必须重写。
- D05 进程内 hub 可继续作为 Redis 禁用时的同实例低延迟 fan-out，但不得继续被描述为跨实例真相源。
- Memory Redis runtime 的连接参数可复用；报告模块使用自己的装配/端口，避免交叉业务所有权。

### 6.3 Conceptual References Only

- Redis Streams 可以提供持久 replay；本轮只需 latest snapshot，额外 consumer group、trim 和恢复语义没有验收收益。
- Celery/RQ/Temporal/outbox worker 可以解决进程崩溃续跑；本轮不改变任务执行平台，只准确披露 BackgroundTasks 边界。

### 6.4 Not Suitable for This Iteration

- Redis-only `SET NX EX` 作为幂等权威。
- 先查缓存/数据库再无约束创建、进程锁、前端按钮锁或多标签页浏览器锁。
- 在 Pub/Sub payload 中携带完整状态并假设消息不会丢。
- 从最终报告倒推出阶段，或为恢复制造前端动画。
- 修改 Agent Prompt、金融分析节点、Tool/Skill/Memory 行为来配合治理层。

## 7. Solution Options

### 7.1 Option A: Minimal Fix — Redis-only 幂等与快照

**What changes:** 将历史 `SET NX EX`、command hash、Redis snapshot 和 Pub/Sub 适配到当前路由/D05 SSE。
**What does not change:** 数据库 schema、BackgroundTasks、Report 模型和前端主体。

**Benefits:** 开发量小；能快速复现旧面试口径；Redis 正常时多数重复请求命中。
**Costs:** 必须维护 placeholder/wait；Redis/网络故障时没有最终裁决。
**Risks:** 跨实例超时仍可能双执行；重启/TTL/污染丢映射；不能证明 exactly-once create。
**Testing burden:** 中；真 Redis 并发和故障测试仍多，但无法通过冻结的 DB 权威断言。
**Rollback difficulty:** 低。
**Engineering impact:** architecture 侵入 router/service；untyped Redis 状态容易成为第二真相源；需要错误与降级日志，但无法消除 fail-open duplicate。

**When to choose it:** 仅适用于可接受重复副作用的临时 demo；不满足 D06。

### 7.2 Option B: Structured Improvement — PostgreSQL 治理表 + Redis 快照/通知

**What changes:** 新增独立治理表和 persistence service；创建路由通过原子 create-or-reuse；真实阶段持久 snapshot version；Redis 镜像与 Pub/Sub 唤醒；SSE/前端恢复同一任务。
**What does not change:** Report 正文/任务终态权威、报告 Agent/Prompt/工具、BackgroundTasks 执行模型、D05 REST/SSE 路径、聊天/Skills/Memory。

**Benefits:** 两实例并发和 Redis 故障下仍只创建/派发一次；断线重连有持久 latest snapshot；与面试 Claim 和当前模块边界都一致。
**Costs:** 一条 migration、事务竞争处理、async progress port 演进、Redis runtime、前端恢复和较完整集成测试。
**Risks:** `create_all + Alembic` 混合所有权、winner/loser 回滚、Pub/Sub 竞态、版本与 Report 双写必须严格设计。
**Testing burden:** 中高；需 PostgreSQL/Redis/multi-instance/前端/Live，但每层单一职责且已冻结。
**Rollback difficulty:** 中低；关闭 feature flag 回到旧创建/进程内观察，downgrade 删除独立治理表；不改 Report 核心字段。
**Engineering impact:** application 拥有 idempotency/snapshot contract，infrastructure 实现 DB/Redis；typed Settings；稳定错误码和低敏 metrics；无新生产依赖。

**When to choose it:** 当前选择，满足全部 D06 合同且不扩大为任务平台重写。

### 7.3 Option C: Long-term Architecture Direction — Durable queue/outbox/worker

**What changes:** 创建事务写 Report + idempotency receipt + outbox；独立 worker 消费、租约/heartbeat/重试；持久 event log 或 Streams；支持崩溃续跑。
**What does not change:** 可以保留前端 SSE 合同和报告 Agent，但部署、运维和执行所有权会改变。

**Benefits:** 解决 response 后崩溃、跨进程调度、重试和长期任务恢复；更接近生产任务平台。
**Costs:** 新依赖/服务、投递至少一次语义、副作用幂等、dead-letter、运维监控和迁移成本高。
**Risks:** 超出 D06 与面试现有 Claim；容易把报告专项开发膨胀为通用基础设施。
**Testing burden:** 高；需要 worker crash、lease、redelivery、DLQ、滚动发布和容量测试。
**Rollback difficulty:** 高。
**Engineering impact:** 新 application/worker/infrastructure 边界、部署拓扑、配置和告警体系；必须重新定义执行状态机。

**When to choose it:** 报告成为真实生产重任务、明确要求进程崩溃续跑或多 worker 调度时；本轮 Deferred。

### 7.4 Option D: Observation-first — 只加并发复现与指标

**What changes:** 增加 duplicate/dispatch 计数、并发测试和日志，不改变创建/恢复行为。
**What does not change:** 全部产品语义。
**Benefits:** 风险最低，可量化当前重复。
**Costs:** 用户可见问题不解决。
**Risks:** 继续产生重复真实调用；无法对应已冻结 D06 Claim。
**Testing burden:** 低。
**Rollback difficulty:** 低。
**Engineering impact:** 仅观测层，不能成为本轮交付。

**When to choose it:** 需求或根因未知时；当前静态证据已充分，因此不选。

## 8. Decision Matrix

| Dimension | Option A Minimal Fix | Option B Structured Improvement | Option C Long-term Architecture | Option D Observation-first |
| --- | --- | --- | --- | --- |
| Scope | 小 | 中 | 大 | 小 |
| Development Cost | 低 | 中 | 高 | 低 |
| Risk | 高正确性风险 | 中、可控 | 高 | 低但不解决 |
| Reusability | 低 | 高 | 高 | 中 |
| Fit to Current Requirement | 不满足 DB 权威/故障语义 | 完整满足 | 超出 | 不满足 |
| Local Pattern Fit | 部分 | 高 | 低 | 高 |
| External Pattern Fit | 违背 PostgreSQL/PubSub边界 | 高 | 高但过重 | 中 |
| Test Burden | 中 | 中高 | 很高 | 低 |
| Rollback Difficulty | 低 | 中低 | 高 | 低 |
| Long-term Maintainability | 低 | 高 | 高 | 中 |
| Engineering-standard fit | 低 | 高 | 中（过度设计） | 中 |
| Recommendation | 拒绝 | **选择** | 延期 | 不单独选择 |

## 9. Recommended Solution

Selected option: **Option B — PostgreSQL 独立治理表 + Redis latest snapshot / PubSub version notification + D05 SSE/前端恢复。**

Why selected: 它是能同时证明“10 分钟复用”“两实例只执行一次”“Redis 故障仍正确”“断线恢复真实状态”的最小可靠方案；新表隔离了 legacy Report 的建表风险，也不需要新生产依赖。

Why not the other options: A 不能在 Redis 故障或占位超时下保证唯一；C 能解决崩溃续跑但范围、部署和验证负担远超当前需求；D 只描述问题而不修复。

Local patterns reused: D05 typed progress contract、commit-before-publish、DB snapshot/fallback、严格 reducer；Memory Redis 的 envelope/TTL/health/fail-open；Memory Alembic-managed table 模式；现有 opt-in live harness。

External practices reused: PostgreSQL unique/ON CONFLICT 原子仲裁；SQLAlchemy 明确事务 rollback；Redis Pub/Sub at-most-once 仅作唤醒；FastAPI 官方 BackgroundTasks caveat 明确披露。

Remaining risks: 独立治理表与 Report 的原子创建、过期 generation 轮换、async publisher 改造对 D05 回归、Redis subscribe 生命周期、SQLite 与 PostgreSQL 竞争语义差异、前端 sessionStorage 用户隔离。

What must be verified later: migration upgrade/downgrade/fresh bootstrap；20-way two-instance concurrency；Redis unreachable/restart/corruption；跨实例 SSE version monotonic/reconnect；无第二次 POST；真实 workflow invocation=1；所有敏感字段不进入日志/artifact。

## 10. Unified Technical Direction

- 在独立 report task governance application/domain/infrastructure 边界中实现规范化、digest、原子 create-or-reuse、持久 stage snapshot/version 和 Redis adapter；router 只做 header/command/auth 适配与响应映射。
- 使用稳定 `(user_id, key_digest)` 唯一治理行；winner 在同一事务持久 Report + governance，loser rollback 后读取；过期终态在行锁下原子更新为新 generation，禁止删除后重建竞态。
- 工作流每次真实状态变化先提交 Report/治理快照，再 best-effort 写 Redis 并发布仅含 digest/version 的通知；Redis 不可达、丢通知或 envelope 损坏时回源数据库。
- SSE 使用 subscribe-before-read、任务级持久 sequence 和周期 reconcile；保留 D05 route/schema/安全所有权与 polling fallback，不实现完整 replay。
- 前端为明确点击创建随机 key；同一请求重试沿用，刷新从按用户隔离的最小 sessionStorage 记录恢复相同 task，终态/登出清理；旧客户端继续走 server-derived command hash。
- 增加 typed Settings、`.env.example`、health/低敏 structured logs/metrics、migration、最小充分离线/Compose/Live 测试和面试/README/验收文档；不改 Prompt、Agent、金融规则、Skills/Memory，不引入 durable queue。

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| 并发先查后写产生双 Report | DB 唯一插入参与仲裁；loser 整事务 rollback 后读取 winner；仅 winner 注册 BackgroundTasks |
| 600 秒过期轮换竞态 | 唯一治理行 + `SELECT FOR UPDATE`/等价锁；先判断 pending/running，再原子替换 generation |
| Redis 成为隐式真相源 | 所有 Redis hit 校验 owner/fingerprint/version；状态/内容最终读 DB；故障明确 degraded |
| Pub/Sub 丢消息 | 只发布 invalidation；subscribe-before-read；持久 snapshot version；周期 reconcile |
| DB 已提交、Redis publish 失败 | commit-before-publish；记录低敏错误并允许下一读回填快照 |
| Report 与 stage snapshot 漂移 | 同一短事务更新；持久版本仅在真实状态变化时递增；终态 invariant 测试 |
| 迁移与 fresh create 冲突 | 新表加入 Alembic-managed 排除集合；upgrade/downgrade/fresh bootstrap 验证 |
| SQLite 测试掩盖 PostgreSQL 行为 | unit 可 SQLite；关键并发/locking/upsert 必须真 PostgreSQL integration/Compose |
| sessionStorage 泄密或串用户 | 只存 IDs/key/fingerprint；用户摘要 namespace；恢复先鉴权；登出/终态清理 |
| BackgroundTasks 崩溃不续跑 | README/面试/验收明确限制；pending 检测可观测；durable worker 列为后续 |
| Python 3.11 容器兼容 | 新代码避免 3.12-only typing syntax；容器 compile/import 回归 |

## 12. Verification Direction

### 12.1 Engineering Contract for Plan Freezing

- Architecture/module ownership: API 适配在 router/schema；幂等与快照用例在 application；ORM/Redis 在 infrastructure；报告 Agent 只通过 typed progress port 发布。
- Interfaces/docstrings/types: 公共 class/function/route/port 使用仓库语言的 Google-style docstring 和完整类型；核心状态禁止 `dictbots` 式任意结构。
- Configuration/secrets/constants/prompts: typed Settings 单点校验；digest 使用现有应用 secret 的 domain-separated HMAC 或等强方案；`.env.example` 无真实密钥；不改 Prompt。
- Terminal/logging/tracing/artifacts: `stage/task_id_digest/status/elapsed_ms/error_code/idempotency_status/snapshot_version`；禁止 command/user/key/token/report content；Live artifact 只保留计数、版本、hash 和耗时。
- Validation/errors/retry/state: header 边界验证；稳定 409/422；Redis 只对瞬态故障 best-effort 且有界；DB 错误不伪装 replay；stage/progress/version 单调且 terminal lock。
- Tests/evaluation/delivery evidence: D06-T01..T10；先失败测试再实现；focused -> regression -> Compose -> protected live；diff/security/claim review；PR checks 全绿后合并。

## 13. Deferred Work

- Celery/RQ/Temporal/Kafka/RabbitMQ、transactional outbox、worker lease、crash recovery、DLQ。
- Redis Streams 或数据库完整 event log、`Last-Event-ID` 历史 replay。
- 报告任务取消/暂停/恢复、重试工作流、通用限流/熔断/配额平台。
- 多设备跨标签恢复、BroadcastChannel、长期保存 idempotency history。
- 修改报告内容 streaming、Prompt、Agent 图、分析算法、Tool/Skill/Memory。

## 14. Handoff to Plan Freezing

Next step should use the Plan Freezing Skill and produce `D06_REPORT_TASK_GOVERNANCE_PLAN.md`.

The plan should:

- follow selected option: PostgreSQL governance authority + Redis cache/PubSub wake-up + D05 SSE/latest-snapshot + frontend same-task recovery。
- allow modules/files: report router/schema/application/progress/infrastructure/runtime、models/migration/migration runner、typed config/env example/main health、report frontend API/composable/store/view、targeted tests/Compose/README/spec artifacts。
- forbid modules/files: Agent Prompt/金融节点/工具权限、Skills/Memory 业务行为、认证协议、队列平台、用户 D01 untracked document。
- include required tests: D06-T01..T10，关键并发用 PostgreSQL，Redis 故障用真 Redis，Live 一份报告且无整轮重试。
- include required logs/metrics: created/replayed/conflict、DB contention、Redis hit/miss/malformed/error/rebuild、publish/receive/reconcile、snapshot version；全部低敏。
- include rollback strategy: feature flag 回退旧创建/进程内 D05 路径；独立表 migration downgrade；前端新增字段可忽略；不删除 Report 数据。
- preserve these constraints: DB 唯一正确性、commit-before-publish、owner-bound reads、latest snapshot only、BackgroundTasks crash boundary、Python 3.11 compatibility。
- keep these external references in mind: PostgreSQL unique/ON CONFLICT、SQLAlchemy rollback、Redis Pub/Sub at-most-once、FastAPI BackgroundTasks caveat。
