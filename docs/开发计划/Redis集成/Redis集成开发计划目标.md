下面我按 **Redis** 理解你说的 “radius”。从大厂 Agent 开发架构师视角看，你这三个切入点总体是**合理的，而且比“缓存工具结果/缓存金融结论”更适合写进项目**。原因是：它们解决的是 Agent 后端运行时的典型工程问题——**短期状态热读、上下文快照热读、长任务幂等与进度同步**，而不是把 Redis 生硬塞进 AI 链路。

你现有项目文档里，STM 已经有 `active_entity / constraints / reply_preference_hint`、rolling summary、recent raw tail、`state_version / summary_version`、last-good summary、trace 和 eval 等设计；Redis 接入后应当服务这些已有机制，而不是重写一套记忆系统。文档中也已经强调 Redis 不能替代 PostgreSQL 权威状态，缓存值必须带版本校验，冲突时以 DB 和当前请求快照为准。

**整体判断：值得做，但要定位成“运行时状态层”，不要定位成“金融数据缓存层”**

我建议你把 Redis 包装成 **Agent Runtime State Layer（Agent 运行时状态层）**，而不是“缓存系统”。这能和你简历中的 **Context Harness（上下文执行底座）** 自然衔接：你的 Harness 已经负责 route、rewrite、planner、memory、tool、report 等链路，现在 Redis 负责把其中高频、短生命周期、可恢复的状态放到热层里，提高响应速度和稳定性。

Redis 本身适合低延迟缓存和短期状态保存；RedisVL 文档也明确支持 TTL（过期时间）策略，并说明 TTL 可用于临时持有缓存项，避免自己写复杂清理逻辑，还支持多用户场景下用 tag/filter 做访问控制。([Redis][1]) 这和你的三个切入点都匹配：**会话热状态要短 TTL，最近上下文要版本化缓存，报告进度要短期状态和事件推送**。

但要注意一个边界：Redis 不应该保存“权威事实”。完整消息、最终报告、长期画像、候选记忆、审计 trace 仍然落 PostgreSQL / 文件 / pgvector；Redis 只保存**可重建、可过期、可回源**的热状态。这一点说清楚，就不会显得大材小用。

**一、对话短期热状态：合理，而且是最适合写进简历的 Redis 接入点**

这个点非常合理。你的 STM 每轮都要读 `active_entity / constraints / reply_preference_hint`，这些字段体积小、访问频繁、生命周期短，正适合 Redis。它不是替代 PostgreSQL，而是在 route / rewrite / planner 前做热读，减少每轮都查 DB、拼上下文、反序列化状态的开销。

建议设计成：

```text
stm:state:{user_id}:{session_id}
{
  active_entity: {...},
  constraints: [...],
  reply_preference_hint: {...},
  state_version: 18,
  updated_at: "...",
  expire_at: "..."
}
TTL: 10~30 min
```

这里最关键的是 **版本号**。Redis 里缓存的 state 必须带 `state_version`，每次写回时和 PostgreSQL 或当前请求内快照比较。如果 Redis 版本落后，就直接丢弃缓存，回源 DB；如果请求链路中已经产生了新的 working state，Redis 旧值不能覆盖它。你现有文档已经提到短期热状态缓存要带 `state_version / summary_version / updated_at`，版本不一致直接丢弃缓存，这个思路非常对。

这个点不会显得大材小用。因为它解决的是 Agent 系统里非常常见的问题：用户连续追问时，每轮都要快速拿到当前主语和约束，否则 route / rewrite / planner 会反复查库、重复构造上下文。你可以把它说成：**Redis 不是让记忆更聪明，而是让短期状态读取更稳定、更低延迟。**

**二、最近几轮上下文 / last-good summary 热读：合理，但必须强调“快照缓存，不是消息主存储”**

这个点也合理。你的项目已经有 recent raw tail、rolling summary、last-good summary、summary 质量门控等机制，Redis 可以缓存最近几轮原文和 last-good summary 快照，减少 Preflight 每次从 DB 拉消息、拼接、裁剪的开销。你的文档中已经强调，recent raw tail 负责保留最近几轮的精确表达和指代关系，rolling summary 承接更早主线，working state 优先级最高。

建议缓存两类 key：

```text
stm:tail:{user_id}:{session_id}
- 最近 N 轮 user/assistant 摘要或短文本
- message_id 范围
- tail_version
TTL: 10~30 min
```

```text
stm:summary:{user_id}:{session_id}
{
  last_good_summary: "...",
  summary_version: 7,
  covered_until_message_id: 42,
  quality_status: "passed"
}
TTL: 30~120 min
```

这里要防两个问题。第一，Redis 不能存完整长期消息，完整 `messages` 表仍然在 PostgreSQL，因为消息是审计和回放依据。第二，summary 缓存不能只靠 TTL 判断新旧，必须带 `covered_until_message_id` 和 `summary_version`。如果用户在 summary 生成后又连续发了几轮，旧 summary 不能覆盖新上下文。

这个点也不大材小用，因为它正好支撑你的 **Preflight**：Preflight 不只是数 token，还要拼“最近原文 + last-good summary + working state + LTM + 工具 schema + 输出预留”。把最近上下文和 last-good summary 做 Redis 热读，有助于降低 P95 preflight latency。RedisVL 文档提到 TTL 会在 cache 命中时刷新，类似滑动窗口，这一点可以作为设计参考，但你需要小心：如果每次命中都刷新 TTL，可能让旧 summary 活得太久，所以你的 summary 缓存应当同时受 `summary_version / message_id` 控制，而不是只靠 TTL。([Redis][1])

**三、报告幂等 + Redis 状态 + SSE 进度展示：非常适合，而且比前两个更有“后端工程味”**

这个点我认为最值得做，也最适合面试讲。你的报告模式是 2–3 分钟的长任务，包含多 Agent 并行、MCP 工具取数、新闻分析、summary 长文本生成等步骤；文档里也提到性能瓶颈主要在 MCP 工具取数、新闻分析和 summary agent 长文本生成，且通过 execution logger 定位每个 Agent 的耗时。 这类长任务如果用户重复点击“生成报告”，很容易重复跑四个 Agent，浪费模型和工具资源，还可能生成多份重复报告。

这时 Redis 可以做三件事：

第一，用 **幂等键** 防止重复创建任务：

```text
report:idempotency:{user_id}:{stock_code}:{query_hash}
value = task_id
TTL = 10~30 min
```

第二，用 **任务状态快照** 支撑前端进度展示：

```text
report:status:{task_id}
{
  status: "running",
  stage: "news_agent",
  progress: 65,
  current_node: "news_analyst",
  report_id: null,
  updated_at: "..."
}
TTL = 1~24 h
```

第三，用 **Redis Pub/Sub 或 Stream** 给 SSE 连接推送进度事件，前端用 SSE 接收阶段更新。MDN 对 SSE 的定义就是浏览器通过 `EventSource` 建立连接，接收服务端持续推送的事件和数据。([MDN文档][2])

这个设计在大厂实践上也站得住。AWS Builders Library 讲幂等 API 时明确强调，服务端通常会使用调用方提供的唯一 request identifier；相同调用方 + 相同 request identifier 的请求可以被认为是重复请求，并且这个 id 在日志中也有审计价值。它还强调，记录幂等 token 和执行相关变更要满足原子性，否则会出现“资源创建了但 token 没记录”或“token 记录了但资源没创建”的不一致。([Amazon Web Services, Inc.][3]) 对应到你的项目，就是 Redis 幂等键可以挡住短期重复点击，但最终任务创建和报告落库仍然要靠 PostgreSQL 状态机兜底。

这里尤其要注意：**幂等不是分布式锁**。幂等解决“同一个用户同一个请求不要创建多个任务”；锁解决“同一个任务不要被多个 worker 同时执行”；最终一致性还要靠 DB 状态机，例如 `pending / running / succeeded / failed / cancelled`。AWS 文档也提醒，同一个 request id 但参数变化时，应当视为不同意图或返回参数不匹配错误，所以你的幂等 key 不能只用 `user_id`，还要包含 `stock_code / query_hash / report_type / time_window`。([Amazon Web Services, Inc.][3])

**会不会大材小用？**

不算大材小用，但要控制范围。对你这个个人项目/实习项目背景，Redis 最合适的版本是 **轻量运行时状态层**，不是完整分布式缓存平台。

我不建议第一版做这些：金融行情工具结果缓存、网页新闻缓存、LLM 语义缓存、复杂 Redis Stream 工作流、全局分布式限流。这些容易被面试官追问数据新鲜度、一致性、缓存污染和业务风险，反而会拖累你。

我建议第一版只做这三块：

1. **STM 热状态缓存**：`active_entity / constraints / reply_preference_hint`。
2. **最近上下文热读**：recent raw tail + last-good summary。
3. **报告任务状态层**：idempotency key + task status snapshot + SSE progress。

这个范围非常适合你的项目：小而清晰，能跑通，能讲清楚，能体现后端工程能力，不会显得为了 Redis 而 Redis。

**插入到现有项目描述里怎么理解**

你可以把它放到简历第四条“可观测与评估闭环”或第三条“分层记忆与上下文治理”后面，但不要抢主线。更推荐写成一条补充成果点，而不是替换原有记忆设计：

> **Redis 运行时状态层：** 围绕对话 STM 和报告长任务引入 Redis 热状态层，将 `active_entity / constraints / reply_preference_hint`、recent raw tail 与 last-good summary 做 TTL 热缓存，并通过 `state_version / summary_version` 保证缓存与 PostgreSQL 权威状态一致；报告模式使用 Redis 幂等键避免重复生成，通过 Redis 状态快照 + SSE 推送多 Agent 执行进度，最终消息、报告和审计 trace 仍落 PostgreSQL。

这段和你现在项目是能接上的：你的报告模式本来就有 execution logger 和 per-Agent 耗时分析，Redis 只是把长任务进度从“后端日志里可查”进一步做成“前端可见 + 重复点击不重复执行”；你的 STM 本来就有 Preflight 和 working state，Redis 只是把热读链路提速，而不是改变记忆架构。

**面试官可能追问的 Redis 问题与准备口径**

**1. Redis 挂了怎么办？**
回答口径：Redis 不是权威存储，挂了以后回源 PostgreSQL；对话链路可以退化为 DB 读取 recent messages + working state，报告进度可以退化为 `/api/report/status/{task_id}` 轮询。Redis 故障只能影响延迟和实时进度体验，不能影响最终消息、报告和审计结果。

**2. Redis 和 PostgreSQL 不一致怎么办？**
回答口径：DB 是权威。Redis value 带 `state_version / summary_version / updated_at`，读缓存后先校验版本；如果版本落后、session 不匹配、message range 不连续，就丢弃缓存回源 DB。写入时可以采用 write-through 或事件驱动失效，但不允许 Redis 旧状态覆盖 DB 新状态。

**3. 为什么不用 Redis 存完整报告？**
回答口径：完整报告是业务结果和审计对象，必须落 PostgreSQL 或文件系统；Redis 只保存 `task_id / status / progress / stage / report_id` 这类短生命周期状态。报告生成成功后，Redis 只保留短 TTL 快照，最终读取以 DB 的 `report_id` 为准。

**4. 幂等键怎么设计？**
回答口径：key 不能只用用户 ID，要包含 `user_id + normalized_query_hash + stock_code + report_type + time_window`。如果同一个 idempotency key 但参数不同，要返回参数不匹配，而不是复用旧任务。这和 AWS 幂等 API 中“同一 client request id 但不同参数应视为不同意图”的实践一致。([Amazon Web Services, Inc.][3])

**5. 幂等和分布式锁有什么区别？**
回答口径：幂等防止重复请求创建多个任务；分布式锁防止多个 worker 同时执行同一个任务；DB 状态机兜底最终一致性。三者不是一回事，不能只靠 Redis lock 解决重复报告问题。

**6. SSE 断了怎么办？**
回答口径：前端 EventSource 自动重连；Redis 里有 `report:status:{task_id}` 快照，断线后前端可以先调用 status API 补状态，再重新订阅 SSE。SSE 只是进度推送，不是任务执行本身。MDN 对 EventSource 的定义也强调它负责连接、接收事件、处理错误和关闭连接。([MDN文档][2])

**7. 缓存击穿怎么办？**
回答口径：对于 hot session summary 或 hot state，Redis miss 时用 singleflight 或短 TTL 锁，只允许一个请求回源 DB，其余请求等待结果或使用 last-good summary 的 stale-but-safe 快照。这里要强调 stale 只能用于 summary / progress 这类可容忍旧值的状态，不能用于当前用户问题和工具证据。

**8. 缓存雪崩怎么办？**
回答口径：TTL 加随机抖动，不让大量 session 同时过期；报告 status 的 TTL 根据任务完成时间设置；Redis 异常时降级 DB 查询和前端轮询。个人项目里不用讲复杂集群治理，但要知道 TTL 抖动和降级路径。

**9. 缓存穿透怎么办？**
回答口径：Redis key 必须由后端根据已鉴权的 `user_id / session_id / task_id` 生成，不允许用户直接传任意 key；查不到时先做 DB 权限校验，必要时缓存短 TTL 空状态，防止非法 task_id 反复打 DB。

**10. Redis 中要不要存金融数据和工具结果？**
回答口径：第一版不建议。金融数据新鲜度和口径很敏感，缓存 Tushare / 新闻结果容易引入“旧数据被当成实时数据”的风险。更稳的是先缓存运行时状态；工具结果如果后续要缓存，也只能缓存低风险、短 TTL、带数据截止时间和 evidence_version 的结果。

**11. Redis 里的状态要不要加密？**
回答口径：最小化存储，尽量只存摘要、状态和版本，不存完整持仓、交易金额、账号、API token。敏感字段脱敏；Redis 网络访问要内网化和鉴权；日志里不要输出完整 value。

**12. 怎么证明 Redis 接入有效？**
回答口径：不要只说“更快”，要给指标：`state_cache_hit_rate`、`summary_cache_hit_rate`、DB read 次数、P95 preflight latency、report_duplicate_submit_blocked_count、SSE reconnect_count、status_poll_fallback_count、cache_stale_reject_count、version_conflict_count。你文档里已经有把缓存纳入 trace 和压测指标的思路，这个可以直接沿用。

**推荐的最小实现顺序**

第一步，先接入 Redis 基础设施：连接池、健康检查、统一 key builder、JSON 序列化、TTL、指标埋点。

第二步，做 STM 热状态：`stm:state:{user_id}:{session_id}`，只缓存三个字段和版本号，不存大文本。

第三步，做 recent tail / last-good summary：`stm:tail` 和 `stm:summary`，所有值带 `message_id range / summary_version`。

第四步，做报告幂等和进度：`report:idempotency`、`report:status`、SSE `/api/report/{task_id}/events`，DB 保存最终结果。

第五步，再考虑 Redis Stream / PubSub：如果只是单实例开发，Redis Pub/Sub 或进程内队列也可以；如果要支持断线补历史事件，Redis Stream 更稳，但复杂度更高。

**最终建议**

这三个 Redis 接入点可以做，而且建议做。它们不是为了“丰富技术栈”，而是把你现有 Agent 项目从“功能能跑”往“后端运行时更稳”推进一步。最稳的包装方式是：

**Redis 只做短生命周期运行时状态：STM 热字段、recent context 快照、报告幂等和进度；PostgreSQL 仍然是消息、报告、画像和审计 trace 的权威存储。**

这样讲，面试官会觉得你知道 Redis 的边界，也知道 Agent 系统真正需要缓存的不是“金融结论”，而是**高频读、可重建、可过期、可版本校验的运行时状态**。

[1]: https://redis.io/docs/latest/develop/ai/redisvl/user_guide/llmcache/ "Cache LLM Responses | Docs"
[2]: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events "Server-sent events - Web APIs | MDN"
[3]: https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/ "references-details-empty"
