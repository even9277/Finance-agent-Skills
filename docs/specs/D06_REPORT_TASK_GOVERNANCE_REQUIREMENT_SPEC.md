# REQUIREMENT_SPEC.md

## 1. Task Type

Primary type: New Feature

Secondary types: Reliability Improvement、Test / Evaluation Improvement、Engineering Governance、Project Packaging / Interview Demo Improvement

Classification rationale: D06 要治理报告任务的重复提交、跨实例运行态和断线恢复；它会触达公开 API、持久化状态、Redis、并发控制、前端生命周期和端到端测试，属于跨模块且兼容性敏感的可靠性功能，必须通过完整 Spec Coding 链推进。

## 2. Requirement Restatement

报告模式必须把一次用户提交识别为一个稳定、可恢复的业务命令。浏览器重试、重复点击、网络超时重发或多个应用实例并发收到同一命令时，只能创建和执行一个权威报告任务；合法重放返回同一任务，复用同一幂等键但请求语义不同则显式拒绝。

报告任务运行过程中，当前状态、阶段、单调版本和安全摘要应具有可跨进程读取的可重建快照。用户刷新页面、SSE 中断后重连或请求落到其他实例时，客户端能够先恢复最新权威状态，再继续接收进度或以现有轮询收口。PostgreSQL 继续保存报告任务、所有权和最终结果等权威事实；Redis 只承担有界 TTL 的幂等协调、运行态快照和必要的跨实例加速，不能成为报告正文或用户权限的唯一真相源。

本任务需要覆盖后端幂等合同、并发正确性、状态快照与恢复、Redis 故障语义、前端重复提交和刷新恢复、认证与租户隔离、可观测性、离线 Compose E2E 以及一次受保护的真实 API 验收。既有 D05 SSE/轮询、报告历史/详情/下载、对话、Skills 和记忆系统不得回归。

## 3. Problem Source

Source: 用户明确提出的 D06 P0 开发项、前序 Claim/Gap 审计、D04/D05 冻结边界以及面试口径一致性要求。

前序文档已经明确：D05 只实现单进程实时 Hub、数据库权威状态和轮询降级，Redis 幂等键、可恢复状态快照、跨实例协调、重复提交保护及刷新/重连恢复属于 D06。现阶段未读取 D06 相关实现代码，因此现有 Redis 适配器、报告数据模型、创建接口、前端请求生命周期和部署拓扑必须由 Codebase Reconnaissance 以代码事实确认。

Tracking: [GitHub Issue #52](https://github.com/even9277/Finance-agent-Skills/issues/52)

## 4. Current Behavior

根据已冻结的 D05 文档和审计材料：

- 每次报告创建请求按独立提交处理，尚无已验收的公开幂等键合同。
- D05 的实时进度 Hub 位于应用进程内，数据库状态是权威来源；Hub 重启或请求切换进程后不能提供共享运行态。
- SSE 断开后可以轮询同一已知任务收口，但刷新、创建响应丢失或客户端重发时没有统一的任务找回与重复执行保护。
- 现有文档不能证明并发重复请求只会启动一次报告图、模型调用和工具调用。
- 记忆模块已经使用 Redis 的文档证据只说明仓库可能存在可复用基础设施，不代表报告任务治理已经实现。

尚待 Recon 提供的权威证据：

- 报告创建事务、任务 ID 生成、后台调度和 workflow 启动之间的准确时序。
- 报告表是否已有可承载幂等指纹、创建状态或恢复信息的字段与唯一约束。
- Redis 客户端、命名空间、序列化、TTL、健康检查、故障注入和 Compose 装配能否复用。
- D05 Hub、SSE 快照、轮询状态和终态落库的接口与竞态窗口。
- 前端是否会禁用重复点击、怎样重试创建请求、刷新后怎样找回当前任务。
- 当前多 worker/多实例配置、测试拓扑和真实任务调用计数能力。

## 5. Expected Behavior

1. 前端对一次明确的报告创建意图生成稳定幂等键，并在网络重试期间复用；后端在认证用户作用域内校验并处理该键。
2. 同一用户、同一幂等键和同一规范化请求在有效期内重复或并发到达时，只创建一个权威任务，只启动一次报告 workflow，并向所有合法调用者返回同一任务身份和一致的创建/重放语义。
3. 同一用户复用幂等键但提交不同业务请求时，返回稳定冲突错误，不能覆盖旧任务、启动新任务或泄露原请求内容。
4. 不同用户使用相同外部幂等键时必须相互隔离；所有重放、快照、SSE、轮询、历史和详情访问仍先执行权威所有权校验。
5. 运行中任务发布带协议版本、任务关联、有限状态/阶段、单调快照版本、更新时间和安全摘要的可重建快照；重复、迟到、乱序更新不能回退状态或覆盖终态。
6. 页面刷新、SSE 中断重连或请求切换应用实例后，客户端能够以已知任务或幂等提交恢复最新快照，并继续实时接收后续进度；若共享实时通道不可用，则沿用 D05 轮询读取 PostgreSQL 权威状态。
7. Redis 失联、超时、重启、键过期、数据损坏或快照落后时必须产生明确、可观察且保持正确性的行为；不得静默放行可能触发第二次付费报告执行的重复请求。
8. PostgreSQL 中任务所有权、最终状态、最终报告和历史记录始终具有最终裁决权。Redis 数据可删除、过期或重建，不能单独证明任务存在、授权或完成。
9. 终态只发布一次且不可回退；客户端恢复后看到的 SSE、Redis 快照、轮询和详情结果必须经权威状态归并而一致。
10. 未提供幂等键的旧客户端保持既有创建能力；官方前端必须使用新合同。具体兼容形式由方案阶段冻结，不能让隐式全局去重改变用户主动创建两份报告的能力。
11. 所有公开错误、日志、Trace、Redis key/value 和测试 artifact 均不得暴露原始幂等键、完整请求、Prompt、报告正文、模型/工具载荷、Token 或内部异常。

## 6. Scope

### 6.1 In Scope

- 报告创建的幂等键输入、响应、重放、冲突、有效期和兼容性合同。
- 用户作用域的请求规范化/指纹与并发唯一性保护。
- PostgreSQL 权威任务与 Redis 幂等记录之间的创建、恢复和一致性语义；若 Recon 证明必要，允许最小、可回滚的非破坏性 Schema 迁移。
- 版本化、带 TTL、可重建的报告运行态快照及单调写入规则。
- 跨应用实例读取最新快照和传播后续进度所需的最小 Redis 协调能力。
- D05 SSE 在连接/重连时的快照恢复、跨实例继续和轮询权威收口。
- 前端幂等键生命周期、重复点击保护、创建请求重试、刷新/重连恢复和任务隔离。
- Redis 不可用、超时、重启、过期、损坏、陈旧和竞态的稳定失败/降级行为。
- 脱敏日志、Trace、低基数指标、健康状态和受控故障注入。
- tests-first 的 unit、contract、real Redis/PostgreSQL integration、多实例 Compose E2E、前端与浏览器验收及显式 protected Live。
- Requirement、Recon、Clarification、Tradeoff、Plan、逐里程碑报告、最终验收、Issue #52、功能分支、PR、自审、CI、squash merge 和回滚证据。

### 6.2 Out of Scope

- 通用任务队列、Celery、Kafka、Redis Streams 全量事件日志或跨地域灾备。
- 断线期间每一条历史进度事件的完整重放；D06 要恢复最新权威快照和后续事件，不承诺审计级事件回放。
- 报告暂停、继续、取消、优先级、批量任务、定时任务或人工审批。
- 报告正文逐 token/chunk 流式输出，或修改报告研究质量、Prompt、模型、Skills、工具选择和金融指标算法。
- 把报告正文、原始用户问题、模型输出或工具响应缓存到 Redis。
- 修改登录/JWT 协议、长期凭证传递方式或报告资源所有权规则。
- 把报告幂等治理泛化到对话、记忆或全部 API；通用限流、共享熔断器也不在本任务内。
- 破坏性数据库迁移、历史数据重写或删除既有报告。
- 修改 D07 及后续 Gap，或顺带清理 Issue #20 的仓库级静态检查债务。
- 在 Requirement Definition 阶段读取实现代码、冻结最终类/表/协议细节、运行测试或编写功能代码。

### 6.3 Unknown Scope

- 是否必须为报告表新增幂等字段/唯一索引，还是现有模型与独立记录足以提供重启后的正确性。
- 现有 Redis 抽象是否支持原子 claim、带 fencing 的租约、compare-and-set、版本化 envelope 和安全故障注入。
- 跨实例实时传播应复用轮询、Redis Pub/Sub 或其他现有能力；完整 Streams replay 不作为默认要求。
- 创建响应丢失时，客户端能否通过重复 POST 直接拿回任务，还是需要单独查询入口。
- 官方前端当前是否有可持久化但不含敏感信息的“活动报告任务”状态。
- 幂等有效期、运行任务最长时限和终态快照 TTL 的现有产品约束。
- Redis 故障时最小数据库兜底需要悲观锁、唯一约束、事务外盒或其他现有模式中的哪一种。

## 7. Constraints

### 7.1 Hard Constraints

- PostgreSQL 是报告任务、用户所有权、终态和报告内容的唯一持久权威；Redis 只保存可重建的协调和运行态数据。
- 并发重复请求不能重复执行报告图、模型调用或工具调用；不能以“通常不会重复”代替可证明的原子性。
- 幂等范围至少包含认证用户、键和请求语义；跨用户数据、存在性和键命中不能互相泄露。
- 同键同请求合法重放返回同一任务；同键异请求显式冲突；不得静默覆盖或创建第二任务。
- 快照版本和业务状态必须单调，终态不可回退；Redis 陈旧数据必须以 PostgreSQL 权威事实校正。
- Redis 故障不能被包装为成功，也不能静默降低重复付费执行保护。可用性与严格正确性的取舍必须在 Tradeoff/PLAN 中冻结并测试。
- 保持 D05 报告创建、SSE、轮询、历史、详情、下载及认证合同的兼容性；任何公开变更必须显式版本化和测试。
- 默认测试不得调用付费模型或生产服务。Live 仅显式开关、隔离用户/数据库/Redis、只读金融数据、总超时和一次权威报告执行预算。
- 不新增未论证的生产依赖；优先复用已有 Redis、数据库、Settings、日志、Trace 和 Compose 装配。
- 配置统一进入 typed Settings；真实 Redis URL、密码、API key 和 Token 不得提交、打印或写入 artifact。
- 不覆盖、暂存或删除用户的 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md`。
- 一个 D06 Issue、一个短分支、一个 PR 和一个 main 上的 squash commit；CI、自审和必要回归未完成不得合并。

### 7.2 Soft Constraints

- 官方前端优先使用标准 `Idempotency-Key` 请求头并在一次用户意图的网络重试中复用；旧客户端缺省行为保持兼容。
- 默认冲突使用 HTTP 409 和稳定错误码，合法重放使用与首次创建兼容且可辨识的响应。
- 优先采用“最新快照 + 后续事件 + PostgreSQL 校正”，不为 D06 引入全量事件存储。
- 幂等键和指纹在存储/日志中使用命名空间与不可逆摘要；公开显示只使用任务 ID 和有限状态。
- TTL、等待和重试参数保持最少且有安全默认，不把稳定业务状态枚举配置化。
- 先建立并发红测和 D05 兼容基线，再按一个里程碑一份报告推进。

## 8. Stakeholders and Impact

| Stakeholder / System | Impact |
| --- | --- |
| 报告模式用户 | 重复点击、刷新和网络重试不会重复扣费或生成多份意外报告；断线后能找回同一任务。 |
| 前端维护者 | 需要管理用户意图级幂等键、请求重试、活动任务恢复、SSE 重连和页面生命周期。 |
| Backend API | 创建接口增加幂等边界与冲突语义，状态/SSE 需要从共享快照恢复但仍执行数据库授权。 |
| 报告 Application/Workflow | 必须将“创建权威任务”和“只启动一次执行”组合为可证明的应用用例，发布单调状态。 |
| PostgreSQL | 继续承担权威任务、所有权和终态；可能需要最小非破坏性约束来封闭 Redis 故障窗口。 |
| Redis | 承担有界 TTL 的幂等协调、共享快照和跨实例加速，任何数据均应可过期、重建和隔离。 |
| Auth/Security | 必须防止跨租户键碰撞、任务枚举、原始请求/键泄露和绕过所有权验证。 |
| Observability | 运维应能区分首次创建、合法重放、冲突、Redis 降级、快照恢复、陈旧校正和唯一执行。 |
| 测试/CI | 需要可重复的并发、多实例、Redis 故障/重启和前端刷新测试，默认不调用付费 API。 |
| 面试评审 | 代码证据应支撑“DB 真相源 + Redis 可重建运行态 + 原子幂等 + 断线恢复”的口径。 |

## 9. Engineering Quality Requirements

### 9.1 Interface Documentation and Types

- 幂等键、请求指纹、claim 结果、任务状态、快照 envelope、版本和恢复来源使用显式类型/枚举，核心链路不得依赖 `dict[str, Any]`。
- 公共 Python 路由、服务、存储端口、Redis 适配器和状态发布接口使用中文 Google-style docstring，说明业务约束、副作用、TTL、原子性和失败语义。
- 前端创建响应、冲突错误、快照和连接状态使用判别联合与运行时校验。
- 公开请求/响应、Redis envelope 和快照协议在影响兼容或可复现时具有稳定版本。
- 数据字段必须说明单位、来源、隐私、允许范围、持久化/过期行为和消费者，尤其是时间、版本、摘要和 TTL。

### 9.2 Architecture and Module Ownership

- API 层只负责认证、输入校验、幂等头适配、调用应用用例和安全响应映射。
- Application 层拥有幂等创建、权威任务恢复、唯一调度、状态归并和失败补偿，不把 Redis 命令或 FastAPI 对象扩散到 workflow。
- Domain/contract 层拥有有限状态、单调转换、快照和幂等结果语义。
- Infrastructure 层实现 PostgreSQL/Redis 原子操作、序列化、TTL、健康和故障映射；不能把 provider payload 直接公开。
- D05 Hub/SSE 只消费统一状态发布/恢复端口；Redis 不得侵入 Vue 组件或报告 Agent 节点。
- 前端 transport 管理请求头与解析，Store 管理任务级单调状态和恢复，组件只触发用户动作与展示。

### 9.3 Configuration, Secrets, Constants, and Prompts

- Redis endpoint、连接/命令超时、幂等 TTL、运行态 TTL 和必要重试预算从单一 typed Settings 入口读取、校验，并在 `.env.example` 提供安全占位说明。
- 幂等键长度、状态枚举、协议版本、错误码、key namespace 和最大 payload 等稳定规则保留在代码常量。
- 不修改报告 Prompt、模型参数和金融数据 Provider 策略；真实凭证继续走现有秘密入口。
- Redis key、日志、异常、Trace、测试输出和文档不得包含原始幂等键、Authorization/Cookie、API key、Prompt、报告正文或完整请求。

### 9.4 Terminal Output, Logging, Tracing, and Artifacts

- 关键记录至少包含 `task_id/report_id`、安全用户关联、`stage`、`status`、幂等结果、快照版本、恢复来源、Redis 模式、`elapsed_ms` 和稳定 `error_code`。
- 幂等结果采用低基数值，例如 `CREATED`、`REPLAYED`、`CONFLICT`、`IN_PROGRESS`、`RECOVERED`、`FAILED`；不把用户输入或动态错误作为标签。
- 记录 Redis 超时、损坏、陈旧校正和 fallback 决策，但不输出 key/value 原文或堆栈给客户端。
- Live artifact 只保存测试关联 ID、请求/键不可逆摘要、创建与重放任务 ID、workflow/model/tool 调用计数、快照版本序列、耗时、终态和报告 hash。

### 9.5 Validation, Errors, Retry, State, and Compatibility

- 在边界校验幂等键格式/长度、任务 ID、请求字段、快照 envelope、协议版本和状态转换。
- 请求指纹必须使用稳定规范化，不能因 JSON 字段顺序等非业务差异产生冲突，也不能忽略会改变报告语义的字段。
- Redis 原子 claim、数据库事务和 workflow 调度之间必须有可恢复的状态机；进程崩溃或响应丢失不能永久占用假任务或重复调度。
- 仅对可恢复的 Redis/网络错误做有限重试；有副作用步骤需要幂等保护、总时限和明确终止。
- 损坏/未知版本快照不得被当作空结果或成功；应记录稳定错误并从 PostgreSQL 重建或按冻结策略失败。
- 旧客户端未传幂等键时保持既有行为；官方前端重试必须复用同一键，用户主动开始新报告必须使用新键。
- SSE、Redis 快照、轮询和数据库终态通过同一 reducer/状态规则归并，任何来源都不能回退终态。

## 10. Success Criteria

### 10.1 Functional Criteria

- **D06-C01 First Create**：带合法幂等键创建报告时生成一个权威任务并只调度一次 workflow，响应明确表示首次创建。
- **D06-C02 Sequential Replay**：同用户同键同请求重复提交返回同一任务，数据库报告数和 workflow/model/tool 执行计数不增加。
- **D06-C03 Concurrent Replay**：至少 20 个同步并发的同键同请求跨两个应用实例时只产生一个权威任务和一次执行，其余请求得到同一任务或稳定的进行中/重放响应。
- **D06-C04 Conflict**：同用户同键异请求返回稳定 409/冲突错误，不创建或修改任务，公开响应不暴露原请求与指纹。
- **D06-C05 Tenant Isolation**：两个用户使用相同外部键各自独立创建任务；任何用户不能通过重放或快照读取他人任务。
- **D06-C06 Refresh/Reconnect Recovery**：任务运行中刷新页面或让 SSE 请求落到另一实例，客户端恢复同一任务的最新单调快照并继续至唯一终态，不重新创建报告。
- **D06-C07 Redis Restart/Expiry**：Redis 重启、运行快照过期或丢失后，已知任务可以由 PostgreSQL 权威状态重建；终态和所有权不丢失。
- **D06-C08 Redis Failure Safety**：Redis 超时/不可用时执行 PLAN 冻结的正确性策略，不能静默触发第二次付费 workflow；错误/降级对客户端和运维均可辨识。
- **D06-C09 Corrupt/Stale Snapshot**：损坏、未知版本、乱序或落后快照不会回退状态或覆盖数据库终态，并产生脱敏诊断记录。
- **D06-C10 Compatibility**：无幂等键旧客户端、D05 SSE/轮询、历史、详情、下载和报告失败语义继续可运行。
- **D06-C11 Protected Live**：显式执行一条真实模型 + 允许的只读金融数据报告，再用同一幂等键重放；两次请求指向同一任务且只有一组真实 workflow/model/tool 调用证据。

### 10.2 Compatibility Criteria

- 既有报告记录和最终报告格式可继续读取，无破坏性迁移。
- 未传幂等键的旧客户端继续按旧合同创建任务；官方前端默认使用新合同。
- D05 已验收的 SSE 主路径、轮询 fallback、状态/历史/详情/下载 API 保持兼容。
- D03/D04 对话、Skills、Memory、Auth 和其他页面测试无新增失败。
- Redis 报告 key 与记忆模块 key namespace 隔离，不改变其 TTL、健康或故障语义。

### 10.3 Reliability Criteria

- 并发唯一性由真实原子约束证明，而不是仅依赖前端按钮禁用或进程内锁。
- 创建、claim、调度、快照、终态和恢复均有有限状态、超时与崩溃窗口测试。
- 快照版本单调，终态唯一；重复、迟到和乱序消息不能污染任务。
- Redis 全部数据均可过期/删除并从 PostgreSQL权威事实安全恢复。
- 默认离线验证确定、可重复、可并行隔离，不依赖互联网或付费凭证。

### 10.4 Observability Criteria

- 可从脱敏日志/Trace 重建一次请求的首次创建/重放/冲突、权威任务、唯一调度、状态版本、断线恢复、Redis 故障决策和终态。
- 两个应用实例共享稳定任务/Trace 关联，不以原始幂等键、用户输入或报告标题作为标签。
- 健康/指标能够区分 Redis 可用、降级和错误，但不能把 Redis 当作应用总体健康的唯一判据。
- 负向测试证明凭证、原始幂等键、Prompt、模型/工具载荷、报告正文和内部异常未进入公开响应、Redis 明文、日志或 artifact。

### 10.5 Testing Criteria

- tests-first：先锁定现有报告基线，并为顺序重放、并发唯一、冲突、跨用户、恢复和 Redis 故障建立红测。
- Unit/contract：键校验、规范化指纹、幂等结果、状态机、快照序列化/版本、单调 reducer、错误映射和脱敏。
- Integration：真实 PostgreSQL + Redis 验证原子 claim、并发事务、TTL、重启、损坏、陈旧校正和唯一调度。
- Multi-instance E2E：至少两个真实 FastAPI 实例共享 PostgreSQL/Redis，验证跨实例提交、SSE 恢复和轮询终态。
- Frontend Vitest：键生命周期、重复点击、网络重试、冲突、刷新恢复、任务切换、SSE 重连和 cleanup。
- Offline Compose：真实生产前端、PostgreSQL、Redis、后端和 fake external ports，完成首次创建→并发重放→跨实例恢复→终态以及故障注入旅程。
- Browser：桌面与窄屏验证按钮状态、重放/冲突/降级提示、刷新恢复、最终报告和无重复网络循环。
- Protected Live：最多一个权威报告执行，真实模型和允许的只读数据 Provider，显式开关、预算/总超时、隔离数据库/Redis/用户和脱敏 artifact。
- 交付门禁：锁文件、触达范围 Ruff/Pyright、backend/report/Agent/root regression、frontend lint/type/test/build、Compose config/runtime、secret/generated scan、PR CI。

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Redis claim 成功但数据库/调度失败形成悬挂键 | 用显式状态机、有限租约/fencing、事务事实和恢复测试封闭崩溃窗口。 |
| 数据库任务已创建但响应丢失导致客户端重发 | 将幂等映射与权威任务持久关联，使重放能找回同一任务。 |
| 只有 Redis 去重，重启后重复执行 | PostgreSQL 保留足够权威约束/事实；Redis 丢失后先重建或安全失败。 |
| 多 worker 进程内锁无效 | 使用跨实例可证明的原子约束，并用双实例并发测试验收。 |
| 同键异请求错误复用 | 稳定规范化指纹 + 冲突响应 + 不记录原请求的负向测试。 |
| 快照比数据库终态陈旧 | 单调版本与终态优先规则，读取时校正并按需重建缓存。 |
| Redis Pub/Sub 丢消息 | 不把 Pub/Sub 当权威；连接时读取最新快照，断开后仍可轮询 PostgreSQL。 |
| Redis 故障在高并发下放行重复付费任务 | 冻结 correctness-first fallback/fail-closed 语义，以故障注入证明没有重复执行。 |
| 幂等键或请求内容泄露 | 用户命名空间、不可逆摘要、长度限制、白名单 envelope 和日志/Redis 扫描。 |
| TTL 过短导致长任务保护失效 | TTL 不短于最大运行预算并支持运行中续期；具体值以 Recon/Tradeoff 决定。 |
| 前端把一次主动新建误当重试 | 以“用户意图”管理键：网络重试复用，新的明确提交生成新键。 |
| Schema 变更破坏历史报告 | 仅允许非破坏性、可回滚迁移，先做兼容读写和真实数据库升级/降级验证。 |
| Live 验收重复产生真实成本 | 只允许一个权威任务，第二次仅重放；设置调用计数、总超时和失败即停。 |

## 12. Open Questions

### D06-Q01 幂等键放在哪里、由谁生成？

- Question: 使用 `Idempotency-Key` header、请求体字段还是独立命令 ID？
- Why it matters: 影响公开 API 兼容、代理行为、前端重试和日志脱敏。
- Suggested default: 官方前端生成 UUID 类随机键并通过 `Idempotency-Key` header 发送；一次用户意图的传输重试复用，主动新建生成新键。旧客户端可不传。

### D06-Q02 正确性的持久化锚点是什么？

- Question: Redis 丢失后，现有报告表能否识别同一命令，是否需要最小 Schema 迁移/唯一约束？
- Why it matters: 只依赖 Redis 无法证明重启后的幂等，随意改表又会扩大兼容风险。
- Suggested default: Recon 先复用现有字段；若不能封闭重复执行窗口，允许 Alembic 增加 nullable 摘要/状态与用户作用域唯一约束，不保存原始键。

### D06-Q03 Redis 失联时偏可用还是偏正确？

- Question: 新报告能否继续创建，重复/不确定请求怎样处理？
- Why it matters: fail-open 可能重复调用付费模型，fail-closed 会暂时降低可用性。
- Suggested default: correctness-first；能由 PostgreSQL 原子约束证明唯一时继续，否则对带键的不确定创建返回稳定可重试错误，不静默启动第二次执行。

### D06-Q04 快照与事件传播采用什么最小模型？

- Question: 只存最新快照并 Pub/Sub 后续事件，还是需要 Redis Streams 完整重放？
- Why it matters: Streams 会引入消费组、保留和清理复杂度，超出“恢复最新状态”可能得不偿失。
- Suggested default: 版本化最新快照 + 最小跨实例通知 + PostgreSQL 轮询校正；不承诺完整历史事件重放。

### D06-Q05 TTL 和运行中续期如何确定？

- Question: 幂等映射、运行态快照和终态快照各保留多久？
- Why it matters: 过短会失去保护，过长会扩大存储和数据保留范围。
- Suggested default: 运行态 TTL 覆盖最大报告执行预算并在权威推进时续期；终态幂等映射默认 24 小时，最终值依据现有 Settings 与真实任务耗时冻结。

### D06-Q06 创建重放的 HTTP 状态和响应怎样兼容？

- Question: 首次创建、进行中重放和已完成重放是否都返回相同状态码？
- Why it matters: 前端和旧客户端可能依赖现有创建状态码/字段。
- Suggested default: 保持既有成功状态码和响应主体字段，新增可选、稳定的幂等结果元数据；冲突使用 409 + 稳定错误码。

### D06-Q07 刷新后活动任务 ID 保存在哪里？

- Question: 使用路由、受控浏览器存储、幂等重放还是服务端当前任务查询？
- Why it matters: 本地持久化可能残留跨账号状态，单靠内存无法跨刷新。
- Suggested default: 优先以报告 ID 路由/服务端响应为主，必要时保存不含请求正文和凭证的用户作用域活动任务引用；登出时清理并始终由服务端重新授权。

### D06-Q08 是否同时实现通用 Redis 限流/熔断？

- Question: 面试口径还提到共享限流和熔断，本任务是否一并开发？
- Why it matters: 会显著扩大 D06，并与报告幂等/恢复的验收目标混杂。
- Suggested default: 否；D06 只实现报告任务幂等、状态快照和必要的跨实例协调，通用限流/熔断另立任务。

## 13. Handoff to Next Step

下一阶段必须使用 Codebase Reconnaissance Skill 做只读代码勘察，确认：

- 报告创建路由、请求/响应模型、认证/所有权、数据库事务、后台调度和 workflow 启动的完整时序。
- 报告模型、迁移、状态枚举、终态写入、失败补偿和可用于持久幂等锚点的现有字段。
- D05 progress Hub、SSE snapshot/subscribe、轮询 fallback、前端 Store/composable/view 和刷新生命周期。
- 记忆模块 Redis runtime/cache/lease、typed Settings、key namespace、versioned envelope、TTL、故障/健康/指标与 Compose 装配的可复用边界。
- 多 worker/实例部署方式以及是否存在 Pub/Sub、锁、fencing、outbox 或数据库唯一约束模式。
- 现有测试如何计数 workflow/model/tool 调用，怎样启动真实 Redis/PostgreSQL/双应用实例和注入故障。
- `.env.example`、CI、Compose、Nginx/Vite 代理和 protected Live harness 的配置与秘密边界。

Recon 只输出 `D06_REPORT_TASK_GOVERNANCE_CODEBASE_RECON.md`，不得修改功能代码、运行付费 API 或提前冻结最终架构。

## Decisions Needed Before Codebase Reconnaissance

- [x] PostgreSQL 权威、Redis 可重建运行态的边界已冻结。
- [x] 同用户同键同请求唯一执行、同键异请求冲突、跨用户隔离已定义。
- [x] 恢复目标是“最新快照 + 后续进度 + 数据库校正”，不做完整历史事件重放。
- [x] 旧客户端兼容、官方前端使用幂等合同的方向已定义。
- [x] 默认离线、protected Live 只产生一个权威报告执行的测试边界已定义。
- [x] 通用队列、取消/暂停、限流/熔断、Prompt/模型/Skills/Memory 变更不在范围内。
- [ ] 数据库持久化锚点、Redis 原子原语、HTTP 精确合同、TTL 和跨实例传播方式等待 Recon 提供代码证据。
