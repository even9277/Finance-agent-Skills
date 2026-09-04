# REQUIREMENT_SPEC.md

## 1. Task Type

Primary type: New Feature

Secondary types: Test / Evaluation Improvement、Engineering Governance、Project Packaging / Interview Demo Improvement

Classification rationale: D05 要把报告模式从“只能轮询任务状态”升级为“优先接收真实阶段进度、失败时自动回到既有轮询”，同时补齐可观测性、端到端验收和 GitHub 交付证据；它不是单纯的前端动画或文档修改。

## 2. Requirement Restatement

报告模式应向当前有权访问该任务的用户持续展示真实工作流阶段，而不是仅按照固定间隔重复查询任务状态。实时通道不可用、建立失败或中途断开时，前端必须针对同一个任务 ID 自动降级到现有轮询，最终报告、失败原因和终态必须与服务端权威状态一致，不能重复创建报告任务或伪造进度。

本任务需要覆盖后端实时进度合同、认证与资源隔离、前端消费和降级状态、错误/终态语义、日志与测试；允许显式调用真实模型和只读金融数据完成一次受保护端到端验收。现有报告生成逻辑、报告历史、查看/下载能力、对话模式、Skills 和记忆系统不得回归。

D05 不承担 Redis 幂等键、持久化状态快照、重复提交保护、跨实例事件广播或断线后的完整事件重放；这些能力属于 D06。

## 3. Problem Source

Source: 用户明确提出的 P0 开发需求、前序 Claim/Gap 审计与面试项目口径一致性要求。

已知口径为“报告模式通过 SSE 推送阶段进度，并保留轮询降级”，但仓库 README 当前仍描述“前端轮询展示”。尚未在本阶段读取实现代码，因此实际任务模型、状态字段、轮询 API、工作流事件源、认证方式和前端组件所有权需要在 Codebase Reconnaissance 中以代码为准。

Tracking: [GitHub Issue #50](https://github.com/even9277/Finance-agent-Skills/issues/50)

## 4. Current Behavior

根据现有项目文档和用户审计结论：

- 用户提交报告请求后，后端创建任务并执行多 Agent 报告流程。
- 前端通过轮询任务状态感知运行中、成功或失败，缺少服务器主动发送的阶段事件。
- 文档希望展示实时阶段进度，但现有可运行产品尚不能证明“每个展示阶段来自真实工作流状态转换”。
- 轮询是现有兼容路径，不能在 D05 中移除。

尚待 Recon 提供的权威证据：

- 报告创建、状态查询、历史和下载的具体路由与响应合同。
- 报告任务是在进程内、后台线程、队列还是其他执行器中运行。
- 真实阶段状态在哪里产生、怎样落库、失败时怎样收口。
- 前端轮询由哪个 composable/store/view 管理，组件卸载时是否停止定时器。
- 当前认证头、用户/任务所有权检查和反向代理超时行为。
- 现有测试是否启动真实 workflow，还是只修改数据库状态。

## 5. Expected Behavior

1. 用户成功创建报告任务后，页面针对该任务优先建立经过认证的实时进度连接。
2. 实时事件必须由真实报告工作流或其权威任务状态产生，至少能够区分连接就绪、阶段开始/完成、任务完成和任务失败；不允许由前端计时器推演假进度。
3. 每个业务事件携带稳定的任务关联、有限阶段/状态、单调顺序或等价去重依据，以及可安全展示的摘要；不携带原始 Prompt、模型回复、工具参数/结果、堆栈或凭证。
4. SSE 正常时，前端停止常规轮询；收到唯一终态后关闭实时连接、停止定时器并获取/展示同一任务的最终报告。
5. SSE 在首事件前失败、中途断开、浏览器/代理不支持或协议校验失败时，前端明确显示“已切换到轮询”或等价降级状态，并继续查询同一任务，不重新提交报告。
6. SSE 与轮询看到的阶段和终态不得互相矛盾。迟到、重复或乱序事件不能把终态回退为运行中，也不能把失败显示为成功。
7. 用户切换任务、离开页面、退出登录或组件卸载时，应关闭旧连接并停止相关定时器；旧任务事件不得污染新任务页面。
8. 未认证用户、非任务所有者、非法任务 ID 和不存在任务必须在建立/开始流之前得到稳定、安全的拒绝，不能泄露任务是否属于其他用户。
9. 空闲时间较长的报告任务应有可验证的连接保活或明确超时/降级语义；连接中断不能使页面永久停留在假运行状态。
10. 既有轮询 API、报告创建、历史查看、最终报告下载/复制等行为保持兼容。

## 6. Scope

### 6.1 In Scope

- 冻结报告阶段进度的公开有限事件合同、顺序、终态和错误语义。
- 从真实报告执行链或权威任务状态产生实时阶段事件。
- 新增经过现有认证/授权约束的报告进度 SSE 入口。
- 正确的 `text/event-stream` 响应、断连清理、保活/超时和代理兼容语义。
- 前端实时事件解析、任务级状态归并、连接状态展示和资源清理。
- SSE 建立失败、中途失败、协议错误和不支持场景下对同一任务的轮询降级。
- 既有轮询、报告历史、详情、下载、错误页和多任务隔离回归。
- 日志/Trace/指标中可按 `task_id`/`report_id` 或等价关联字段排查连接、阶段、终态和降级原因。
- tests-first 的 unit、contract、integration、frontend、offline Compose E2E、浏览器验收和显式 protected Live。
- Requirement、Recon、Clarification、Tradeoff、Plan、Milestone、Acceptance 文档，Issue #50、短分支、PR、自审、CI、squash merge 和回滚证据。

### 6.2 Out of Scope

- D06 的 Redis 幂等键、任务状态快照、重复提交保护、跨进程/跨实例 pub/sub、完整断线恢复和事件重放。
- 为 D05 新增 Kafka、Celery、Redis Streams、消息队列或其他生产依赖。
- 修改报告工作流的研究逻辑、多 Agent 分工、Prompt、模型选择、金融指标计算或投资结论质量策略。
- 报告正文逐 token/逐 chunk 流式输出；D05 只要求阶段进度与终态通知。
- 新增暂停、恢复、重跑、取消或任务优先级能力；已有行为只能保持兼容。
- 修改数据库 Schema、迁移、报告持久化格式、保留策略或历史数据。
- 修改登录/JWT 协议，或把长期凭证放入 SSE URL/query string。
- 修改 D04 对话 WebSocket、Skills、工具治理、短期/长期记忆或报告以外的页面。
- 公开原始 Trace attributes、Prompt、模型思考、完整工具参数/结果、报告草稿、内部异常或真实用户隐私。
- 在 Requirement Definition 阶段读取实现代码、设计最终架构、运行测试或编写功能实现。

### 6.3 Unknown Scope

- 当前报告执行器是否能够直接发布事件，还是只能观察权威状态变化。
- 当前任务表是否已经保存足够阶段信息；D05 禁止 Schema 迁移，若不足需要选择不引入持久化新字段的方案。
- 现有 JWT 是否可通过标准请求头用于流式读取，前端是否能够使用原生 `EventSource`。
- 当前部署是否单实例；D05 只保证不依赖 D06 的跨实例广播，但具体进程内行为需 Recon 核查。
- 现有 Nginx/开发代理对 buffering、read timeout 和 keep-alive 的设置是否足够。
- 报告任务失败是否已有稳定错误码；若只有自由文本，需要在不改变数据库合同的前提下建立公开安全映射。

## 7. Constraints

### 7.1 Hard Constraints

- SSE 是优先实时路径，轮询是可运行、可观察、自动触发的兼容降级；不得删除或假装存在轮询降级。
- 所有阶段必须来自真实执行或权威任务状态，不得用前端定时器、随机数或固定脚本伪造。
- SSE 与轮询必须关联同一任务，降级不得再次创建任务或触发第二次报告生成。
- 保持现有报告创建、状态、历史、详情、下载和认证/授权合同兼容；破坏性变更需另立迁移任务。
- 不新增数据库 Schema、生产依赖、消息队列、Redis 状态或认证方式。
- 长期 JWT/API key/Token 不得出现在 URL、日志、Trace、SSE payload、测试 artifact 或截图中。
- 公开事件必须经过强类型边界校验和白名单投影；未知/畸形事件不能污染前端状态。
- 状态转换必须单调，并只有一个公开终态；断连和异常必须释放连接、生成器、定时器和后台观察任务。
- 默认测试不调用付费模型或生产服务。Live 必须显式开关、只读数据、隔离测试用户/数据库、总超时、一次报告预算和脱敏 artifact。
- 不覆盖、暂存或删除用户的 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md`。
- 一个 D05 Issue、一个短分支、一个 PR 和一个 main 上的 squash commit；CI 未全绿不得合并。

### 7.2 Soft Constraints

- 优先复用现有报告状态模型、轮询 API、前端 Store/composable、认证依赖、日志和 Compose 测试装配。
- 事件命名保持低基数、可口述，前端展示重点阶段而不是调试细节。
- SSE 正常路径应减少无意义状态查询，但不在缺少基线时宣称具体性能提升比例。
- 在现有技术栈能完成需求时不引入新前端或后端库。
- 先锁定失败测试和当前基线，再按一个里程碑一份报告推进。

## 8. Stakeholders and Impact

| Stakeholder / System | Impact |
| --- | --- |
| 报告模式用户 | 能看到报告真实执行到哪个阶段；实时通道异常时仍能得到最终结果，而不是卡死或重复提交。 |
| 前端维护者 | 需要管理实时连接、协议校验、任务状态、轮询降级和组件生命周期，避免 Socket/定时器泄漏。 |
| Backend API | 新增长连接读取边界，同时继续维护既有创建/查询/历史/下载 API。 |
| 报告 Application/Workflow | 需要暴露权威且有限的阶段状态，但不能把 HTTP/SSE 细节或前端字段侵入领域执行逻辑。 |
| 数据库/缓存 | 数据库合同默认不变；Redis 和持久化快照明确留给 D06。 |
| Auth/Security | SSE 必须复用现有身份与任务所有权规则，不在 URL 或日志暴露凭证。 |
| Observability | 运维应能按任务关联实时连接、阶段、断连、降级和终态，同时不记录报告敏感正文。 |
| 测试/CI | 需要在无付费调用的情况下运行完整 SSE→前端→轮询降级→终态链，并用 protected Live 证明真实报告工作流。 |
| 面试评审 | 代码和证据应能够支撑“SSE 主动推送、轮询容灾、单调状态与资源治理”的项目口径。 |

## 9. Engineering Quality Requirements

### 9.1 Interface Documentation and Types

- 报告阶段、状态、事件 ID/sequence、任务 ID、时间和安全摘要使用显式有限类型，不以核心 `dict[str, Any]` 传递。
- 公共 Python 路由、服务、事件/观察器接口使用中文 Google-style docstring，说明输入、输出、断连、副作用和失败。
- 前端协议使用判别联合与运行时校验；字段含义、可选性、长度/范围和终态约束可审查。
- 若事件合同影响兼容性或测试复现，必须声明协议版本或等价稳定版本边界。

### 9.2 Architecture and Module Ownership

- API 层只处理认证、任务所有权、SSE 协议/响应和错误映射。
- Application/Workflow 层拥有报告任务编排、权威状态转换和连接生命周期协调，不依赖 Vue 或 FastAPI 响应对象。
- Infrastructure 负责数据库、模型、工具或外部 Provider；不能把原始 Provider payload 直接公开。
- 前端 API/transport 负责解析与连接，Store 负责单调任务状态，组件只展示和触发 UI 行为。
- 轮询和 SSE 必须汇聚到同一权威状态语义，不能形成两套相互漂移的业务模型。

### 9.3 Configuration, Secrets, Constants, and Prompts

- 若确需可部署参数（连接空闲超时、保活间隔、轮询间隔等），必须从单一 typed Settings 入口读取并给出安全默认和 `.env.example` 说明；Recon/Tradeoff 决定是否需要。
- 稳定阶段枚举、协议版本、错误码与状态规则保留在代码中，不为每个常量增加环境变量。
- 不修改报告 Prompt 或模型供应商配置；真实凭证只从现有秘密入口读取。
- 日志、事件、异常、测试和文档不得打印 Authorization、Cookie、JWT、API key 或完整报告内容。

### 9.4 Terminal Output, Logging, Tracing, and Artifacts

- 重要记录至少包含 `task_id/report_id`、安全用户关联、`stage`、`status`、连接/传输模式、`elapsed_ms`、`error_code` 和降级原因。
- 稳定低基数事件应覆盖 SSE `CONNECTED`、`DISCONNECTED`、`COMPLETED`/`FAILED` 与 polling fallback 的 `STARTED`/`SUCCEEDED`/`FAILED`。
- 断连、发送失败和客户端清理必须可诊断，但不记录原始事件正文、Prompt、工具结果或堆栈给客户端。
- Live artifact 只保存 provider/mode、任务关联的不可逆或测试 ID、阶段序列/计数、耗时、终态、报告 hash 与断言，不保存凭证或报告全文。

### 9.5 Validation, Errors, Retry, State, and Compatibility

- 外部任务 ID、身份、事件字段和状态转换必须在边界校验；任务所有权在开始流式读取前验证。
- 断线本身不应把仍在运行的报告任务改为失败或重新执行；客户端切换到轮询读取权威状态。
- 客户端只对同一任务接受单调事件，忽略确定可识别的重复/迟到事件；协议破坏应安全降级而非静默污染状态。
- 轮询降级使用现有重试/间隔策略或在后续方案中冻结有限退避；必须有终止条件，不能无限泄漏请求。
- 服务端仅对可恢复的传输失败做有限处理；报告工作流失败不因 SSE 而重试或改写成功。
- SSE 和轮询公开的终态、错误类别和最终报告可用性保持一致。

## 10. Success Criteria

### 10.1 Functional Criteria

- **D05-C01 Normal SSE**：创建一个离线完整报告任务后，客户端针对该任务建立实时连接，按真实顺序收到至少两个非终态业务阶段和一个唯一终态，并最终展示同一任务的报告。
- **D05-C02 Authoritative Progress**：改变真实 workflow/task 状态会产生对应公开事件；仅等待前端时间不会凭空推进阶段。
- **D05-C03 Initial Failure Fallback**：实时连接在首个有效事件前失败时，前端自动轮询原任务并到达正确终态，不产生第二个报告任务。
- **D05-C04 Mid-stream Failure Fallback**：收到部分合法事件后断连或遇到畸形事件时，已完成状态不回退，页面显示降级并通过轮询收口同一任务。
- **D05-C05 Terminal Consistency**：SSE 成功、SSE 失败后轮询、直接轮询三条路径对同一权威任务返回一致终态；终态后无业务状态继续更新。
- **D05-C06 Failure and Missing Task**：报告失败、非法 ID、不存在任务、未认证和跨用户读取返回稳定安全语义，不泄露内部异常或他人任务信息。
- **D05-C07 Lifecycle Isolation**：切换报告/页面或卸载组件会关闭旧连接和定时器；旧任务事件不能覆盖当前任务。
- **D05-C08 Existing Report Compatibility**：创建、轮询查询、历史列表、详情、复制/下载以及已有失败展示保持可运行。
- **D05-C09 Protected Live**：显式运行一条真实模型 + 允许的只读金融数据报告，观测真实阶段事件和终态；只验证结构、状态、报告非空/hash 和安全边界，不断言模型措辞。

### 10.2 Compatibility Criteria

- 既有轮询 API 的路径、认证、字段与终态保持兼容。
- 既有报告记录和下载格式无需迁移。
- 对话 D03/D04、Skills、Memory、Auth 与其他页面测试无新增失败。
- 不支持实时流的客户端仍可仅使用轮询完成报告。

### 10.3 Reliability Criteria

- 一次前端任务最多有一个活动实时连接和一个降级轮询循环；两者不能长期并行竞态。
- 每个连接和轮询循环在终态、切换、退出、异常或超时后可证明已清理。
- 重复、迟到和乱序事件不能回退终态或污染其他任务。
- 真实服务超时/限流/部分失败产生明确失败或现有安全降级，不伪造成功。
- 默认离线验证可重复，不依赖网络或付费凭证。

### 10.4 Observability Criteria

- 可从脱敏日志/Trace 重建：连接建立、真实阶段、断连/错误、轮询降级、唯一终态和总耗时。
- SSE 与轮询记录共享同一任务关联字段和有限状态语义。
- 指标/日志不以用户输入、报告标题或动态错误文本作为高基数名称。
- 负向测试证明 Token、Prompt、原始工具/模型载荷、报告正文和内部异常未进入公开事件或日志。

### 10.5 Testing Criteria

- tests-first：先建立当前轮询基线和 D05 缺失能力红测，再实现。
- 后端 unit/contract：事件类型、状态机、投影脱敏、认证/所有权、顺序、终态、断连清理。
- Integration/E2E：真实报告入口、任务执行、SSE、数据库权威终态、轮询 fallback、历史/详情/下载。
- 前端 Vitest：严格 parser、Store 单调更新、连接失败/中断降级、无重复提交、任务切换和 cleanup。
- Offline Compose：启动 PostgreSQL、真实 FastAPI、生产前端和 fake external ports，完成 SSE 主路径与强制 fallback 两条浏览器/HTTP 旅程。
- Browser：桌面和窄屏验证阶段可读、降级提示、最终报告、页面切换和无重复网络循环。
- Protected Live：最多一条报告任务，真实模型和现有允许的只读数据 Provider，显式环境开关、预算、总超时、隔离数据库和脱敏 artifact。
- 交付门禁：锁文件、触达范围 Ruff/Pyright、backend/Agent/report/root regression、frontend lint/type/test/build、Compose config/runtime、secret/generated scan、PR CI。

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| 报告工作流没有统一阶段事件源 | Recon 先找到唯一权威状态转换；不得从 UI 计时或日志文本反推假事件。 |
| 原生 EventSource 无法携带现有 Authorization header | 方案阶段比较认证安全的流式客户端选项；禁止把长期 JWT 放进 query。 |
| SSE 与轮询同时写前端状态产生竞态 | 冻结任务级单一 reducer、单调状态和明确的 transport ownership/切换规则。 |
| 中途断线丢失阶段 | D05 立即以权威状态轮询收口并明确降级；完整 event replay 和 durable snapshot 留给 D06。 |
| 单实例进程内事件无法跨 worker | 不伪造多实例保证；优先依赖当前权威状态，跨实例实时广播由 D06 单独设计。 |
| 代理 buffering/idle timeout 导致看似不实时 | Recon 检查 Nginx/ASGI 设置；contract/Compose 验证 headers、flush、保活与断连。 |
| 长连接或轮询定时器泄漏 | 为终态、断连、页面卸载和任务切换加入明确 cleanup 测试。 |
| Live 报告调用耗时和成本高 | 最多一例、固定只读问题、总超时/调用预算、显式开关，不进入默认 CI。 |
| 公开阶段或日志泄露研究内容 | 固定白名单、长度限制、key-based redaction 和负向测试。 |
| D05 侵入 D06 或改变数据库 | PLAN 明确 forbidden files/behaviors；需要 Redis/Schema/幂等时停止而不是偷做。 |
| 新协议破坏历史报告与轮询 | 保持旧 API，增加兼容回归和三路径终态一致性测试。 |

## 12. Open Questions

### D05-Q01 公开哪些报告阶段？

- Question: 是否逐个公开所有内部 Agent 节点，还是只公开面向用户的有限阶段？
- Why it matters: 过细会泄露内部实现并导致高频事件，过粗则无法证明真实进度。
- Suggested default: Recon 后选取 4～8 个稳定业务阶段，使用白名单摘要；内部节点可以归并，但每次推进必须有权威来源。

### D05-Q02 SSE 如何携带认证？

- Question: 当前 JWT 能否使用标准 Authorization header 完成流式请求？
- Why it matters: 原生 EventSource 不支持任意 header，把长期 JWT 放 query 会泄露到访问日志。
- Suggested default: 保持现有 header/cookie 安全边界，必要时采用支持 header 的 fetch-stream 形式；不修改认证协议、不使用长期 query token。

### D05-Q03 断线后是否重放事件？

- Question: D05 是否需要支持 `Last-Event-ID` 和历史事件重放？
- Why it matters: 可靠重放通常需要 D06 的持久化快照/事件存储。
- Suggested default: D05 不保证完整重放；重新连接时最多先发送当前权威状态，随后实时观察，失败则轮询。完整 replay 留给 D06。

### D05-Q04 多 worker 下怎样保证实时？

- Question: 报告任务与 SSE 请求是否可能位于不同进程/实例？
- Why it matters: 进程内 queue 在多 worker 下无法传播。
- Suggested default: D05 只承诺当前部署可证明的正确性，优先让 SSE 观察权威状态而非依赖不持久的内存广播；Redis/pub-sub 属于 D06。

### D05-Q05 是否新增连接参数配置？

- Question: 是否需要新的保活、空闲超时或客户端 fallback 参数？
- Why it matters: 过多配置会增加部署复杂度，硬编码又可能不适配代理。
- Suggested default: 先复用现有代理和轮询间隔；只有测试证明需要时，再增加最少 typed setting 和安全默认。

### D05-Q06 报告失败向用户展示多少信息？

- Question: 当前数据库是否有稳定错误码，还是只有内部异常文本？
- Why it matters: 原始异常可能泄密，但只有“失败”又难以排查。
- Suggested default: 公开固定错误类别和安全消息；详细异常仅进入脱敏内部日志。

### D05-Q07 是否需要新增取消按钮？

- Question: 报告页是否已有取消语义，D05 是否应同时产品化？
- Why it matters: 取消会改变任务状态和副作用，超出“进度传输”本身。
- Suggested default: 不新增取消；仅保持已有取消/删除行为兼容，若缺少则另立任务。

## 13. Handoff to Next Step

下一阶段必须使用 Codebase Reconnaissance Skill 做只读代码勘察，确认：

- 报告创建、状态、历史、详情、下载路由及认证/所有权链。
- 报告任务模型、持久化字段、执行器、LangGraph/Agent 阶段和终态写入点。
- 前端报告 API、composable/store/view、轮询定时器、页面卸载和错误展示。
- Nginx/Vite/Compose 对 SSE header、buffering、timeout 和断连的影响。
- 可复用的 D03/D04 流式协议、backpressure、typed contracts 和安全投影模式，但不得把聊天协议直接套用为最终方案。
- 现有 report 单元、集成、E2E、浏览器、真实 Provider 测试及 fixture 能否证明完整链路。
- D05 与 D06 的准确边界，以及无需数据库/Redis/新依赖仍能真实实现的方案空间。

Recon 只输出 `D05_REPORT_SSE_PROGRESS_CODEBASE_RECON.md`，不得修改功能代码、运行付费 API 或提前冻结最终架构。

## Decisions Needed Before Codebase Reconnaissance

- [x] SSE 主路径、轮询自动降级和同一任务终态一致性已定义。
- [x] D05 与 D06 的幂等、快照、跨实例和 replay 边界已冻结。
- [x] 认证不得通过长期 query token 降级。
- [x] 默认离线、protected Live 最多一条报告且只读/隔离的测试边界已定义。
- [x] 不新增报告取消、正文 token streaming、数据库迁移或生产依赖。
- [ ] 公开阶段枚举、认证 transport、权威事件源和保活策略等待 Recon 提供代码证据。
