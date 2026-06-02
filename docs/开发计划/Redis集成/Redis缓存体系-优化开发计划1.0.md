# Redis缓存体系优化开发计划

> 草稿版本：2026-06-01  
> 当前阶段：只做信息收集和方案设计，不改业务代码。  
> 面向读者：完全不了解 Redis 和本项目的新同学。

## 1. 背景与目标

`docs/Redis 与缓存体系.md` 的核心结论是：Redis 不是替代 PostgreSQL/MySQL 的数据库，而是放在主数据库旁边的一层高速状态层。它适合保存短期、热点、可过期、可重建的数据，例如会话摘要、工具调用结果、任务进度、限流计数、分布式锁和幂等键。

放到本项目里，Finance 的主链路不是普通 CRUD，而是金融 Agent 链路：用户提问后，系统可能会做实体解析、路由、rewrite、读取 STM/LTM、规划工具、调用 Tushare/Web Search/LLM、校验证据、生成回答、写 trace 和前端状态。每一步都有“重复查、重复算、重复调外部接口、重复提交任务、多个 worker 状态不共享”的问题。

本计划的目标是设计一套 Redis 集成方案，让它先解决当前项目最明显的工程问题：

1. 把已经存在的进程内 TTL 状态迁移到可共享的 Redis，支持多 worker 和容器部署。
2. 缓存可重建的热点数据，减少外部工具、搜索和数据库重复访问。
3. 用 Redis 原子操作做限流、幂等和轻量锁，避免重复任务和成本放大。
4. 保持 PostgreSQL/SQLite 仍然是权威数据源，Redis 失败时主链路可降级。
5. 让 Redis 的收益可以被 trace、日志和 eval 指标量化，而不是只凭感觉说“更快”。

## 2. 非目标与保持不变的行为

### 非目标

1. 不把 Redis 当作最终事实库。
2. 不迁移 `messages`、`sessions`、`reports`、`ltm_write_tasks`、`trace_sessions`、`trace_spans` 等权威表。
3. 不优先引入 Celery/RQ/Arq 等完整任务框架，除非后续验证 `BackgroundTasks + Redis` 已经不够。
4. 不改变前端 API 响应字段，不改变现有登录、对话、报告、记忆画像的用户可见行为。
5. 不缓存强时效金融结论，不让 Agent 用过期行情伪装成实时事实。

### 必须保持不变的行为

1. 对话最终消息仍写入 `messages` 表，报告最终内容仍写入 `reports` 表。
2. LTM 结构化画像仍以 `user_invest_profiles` 为主数据，Mem0/pgvector 仍是语义增强层。
3. trace 本地 JSONL、artifact、Langfuse、DB sink 语义不变。
4. Redis 不可用时，系统应回退到现有 DB 或进程内路径，不能导致聊天和报告完全不可用。
5. 金融回答仍必须保留证据约束、时间戳、降级说明和风险提示。

## 3. 验收标准

开发完成后，至少要能证明以下事情：

1. 后端启动时能按开关初始化 Redis 客户端，`/api/health` 能展示 Redis 可用或降级状态。
2. Redis 关闭时，聊天、报告、记忆、Web Search 至少能按现有逻辑降级运行。
3. Web Search 缓存命中时不再调用 provider，限流计数在多 worker 下共享。
4. HITL 技能确认状态可以跨 worker 读取，且确认后只消费一次。
5. route runtime 状态可以用 `session_id` 在 Redis 中短期保存，TTL 到期后自动失效。
6. 报告重复提交能通过幂等键返回已有 `task_id` 或明确提示“正在生成”。
7. trace 中出现 Redis 相关字段：`redis_enabled`、`cache_hit`、`cache_key_family`、`rate_limited`、`lock_acquired`、`fallback_reason`。
8. 评测报告能给出 Redis 接入前后的 p50/p95 延迟、缓存命中率、外部工具调用次数、重复任务数、降级次数。

## 4. 项目描述对齐

`docs/项目描述.md` 强调本项目的核心是可追溯、可调试、可评估的投研 Agent，而不是只靠模型自由发挥。相关约束包括：

1. 报告模式是多 Agent 并行分析，工具调用和日志审计是性能优化依据。
2. 对话模式包含实体解析、路由、rewrite、memory、planner、executor、verifier、synthesis 和 trace。
3. Skills 和 Tushare 数据链路共享统一执行内核，不能拆出另一套不可观测的工具执行系统。
4. trace 是事实账本，大对象应作为 artifact，主 trace 保留路径、hash、耗时、状态和降级原因。
5. LTM/STM 有明确边界，长期画像和正式消息不能只放临时缓存。

因此，Redis 在本项目中的定位应该是：

```text
PostgreSQL / SQLite：保存最终事实、正式消息、报告、任务主状态、长期画像、trace 主记录
Redis：保存短期状态、缓存、限流、幂等键、轻量锁、worker 唤醒、可重建中间结果
Langfuse / JSONL：保存观测和回放视角
```

## 5. 从 Redis 文档提炼出的 Agent 可用点

`docs/Redis 与缓存体系.md` 中和本项目最相关的内容可以收敛为 8 类：

1. 会话状态缓存：缓存最近 N 轮消息、会话摘要、当前活跃标的、回答偏好。
2. 短期记忆缓存：缓存当前会话的 working state，例如用户本轮关注的股票、行业、风险约束。
3. Agent 任务状态：缓存报告任务、文档解析、批量 eval 的实时进度。
4. 模型和接口限流：按 user、IP、route、tool family、provider 做计数。
5. 工具调用缓存：缓存股票基础信息、基金基础信息、交易日历、行业目录、短期 Web Search 结果。
6. RAG 或检索结果缓存：缓存 query rewrite 后的检索结果，但必须带知识库版本。
7. 分布式锁：防止同一报告、同一 LTM 写入、同一缓存重建被多个 worker 同时执行。
8. 幂等控制：防止用户重复点击生成报告、WebSocket 重连重复提交消息。

对金融 Agent 特别重要的边界：

1. 实时行情、新闻和财务口径要设置短 TTL，并在回答里保留数据时间戳。
2. 用户画像可以缓存，但权威记录必须在数据库。
3. 工具结果可以缓存，但 trace 需要说明本轮是缓存命中还是实时调用。
4. 不能因为缓存命中而跳过 verifier，缓存数据仍然要经过证据校验。

## 6. 当前实现现状

### 已有但没有 Redis 的能力

1. 配置集中在 `backend/config.py`，已有 STM、Memory、Trace、Web Search TTL/限流、Tushare、Langfuse 等开关，但没有 Redis 配置。
2. `docker/docker-compose.yml` 当前只有 `postgres`、`backend`、`frontend`、`pgadmin`，没有 Redis 服务。
3. `backend/main.py` 启动时初始化 DB、trace runtime、Mem0、LTM worker，适合增加 Redis 初始化和健康检查。
4. `backend/services/chat_hitl_pending.py` 使用进程内 `_PENDING` 保存 Skill 确认状态，TTL 30 分钟，天然适合迁移 Redis。
5. `backend/services/chat_route_runtime.py` 使用进程内 `_ROUTE_RUNTIME_BY_SESSION` 保存路由运行态，TTL 25 分钟，天然适合迁移 Redis。
6. `Financial-MCP-Agent/src/agents/web_search/service.py` 使用进程内 `_CACHE`、`_REQUEST_TIMESTAMPS`、`_DAILY_COUNTER` 做缓存和限流，多 worker 不共享。
7. `backend/routers/report.py` 用 FastAPI `BackgroundTasks` 启动报告生成，进程退出时任务不具备可靠队列语义。
8. `backend/services/report/workflow_runner.py` 已经把报告进度写入 `reports` 表，Redis 可以只做进度加速和幂等，不替代表。
9. `Financial-MCP-Agent/src/memory/ltm_worker.py` 通过 DB outbox `ltm_write_tasks` 处理 LTM，PostgreSQL 下有 `FOR UPDATE SKIP LOCKED`，应保留为权威队列。
10. `Financial-MCP-Agent/src/tools/skill_trace.py` 已有 JSONL、artifact、Langfuse、DB sink，Redis 只适合做异步缓冲，不适合替代 trace 账本。

### 已有缓存但仍是进程内

1. Web Search runtime cache。
2. Web Search 分钟限流和日配额。
3. 实体解析股票/基金目录缓存。
4. Tushare 行业目录缓存。
5. Tushare client 的 `TTLCache`。
6. HITL pending。
7. route runtime state。

这些都是第一批 Redis 化的候选，因为它们本来就是“短期、可过期、可重建”的状态。

## 7. 变更面分析

### 后端配置和启动

影响文件：

1. `backend/config.py`
2. `backend/main.py`
3. `backend/.env.example`
4. `Financial-MCP-Agent/.env.example`
5. `docker/docker-compose.yml`

计划新增：

```text
ENABLE_REDIS=false
REDIS_URL=redis://localhost:6379/0
REDIS_NAMESPACE=finance:
REDIS_SOCKET_TIMEOUT_MS=500
REDIS_HEALTHCHECK_TIMEOUT_MS=500
ENABLE_REDIS_WEB_SEARCH_CACHE=false
ENABLE_REDIS_RATE_LIMIT=false
ENABLE_REDIS_HITL_STATE=false
ENABLE_REDIS_ROUTE_RUNTIME=false
ENABLE_REDIS_REPORT_IDEMPOTENCY=false
```

### 后端服务层

影响文件候选：

1. 新增 `backend/integrations/redis_client.py`
2. 新增 `backend/services/cache/redis_store.py`
3. 修改 `backend/services/chat_hitl_pending.py`
4. 修改 `backend/services/chat_route_runtime.py`
5. 修改 `backend/routers/report.py`
6. 修改 `backend/services/report/workflow_runner.py`

### Agent runtime

影响文件候选：

1. `Financial-MCP-Agent/src/agents/web_search/service.py`
2. `Financial-MCP-Agent/src/tools/chat_tushare_tools.py`
3. `Financial-MCP-Agent/src/agents/executor/execution_scheduler.py`
4. `Financial-MCP-Agent/src/tools/skill_trace.py`

### 数据库

第一阶段不要求新增 DB 表。已有 `web_search_cache` 表暂时不作为主方案，原因是当前 Redis 更适合承接短 TTL 和多 worker 共享状态；若后续需要长期 Web Search cache 审计，再把 DB 表接入二级缓存。

### 前端

第一阶段不改前端 API 类型。Redis 是后端内部实现。只有当新增“排队中”“限流中”“缓存命中说明”等用户可见状态时，才改 `frontend/src/api/index.ts` 和相关组件。

## 8. 差距与风险

### 差距

1. 项目当前没有 Redis 依赖，`backend/requirements.txt` 需要新增 `redis` 或等价 async client。
2. Docker 没有 Redis 服务，本地开发和全 Docker 验收都缺少基础设施。
3. 目前多个 TTL 状态是进程内 dict，多 worker 下会不一致。
4. Web Search 虽有缓存和限流测试，但只验证单进程内存。
5. 报告生成没有幂等键，重复点击可能生成多个任务。
6. trace 还没有系统记录 cache hit、rate limit、lock 等 Redis 观测字段。

### 风险

1. Redis 宕机导致主链路异常，所以必须默认 feature flag 关闭，并实现降级。
2. 缓存过期策略不当会导致金融回答使用旧数据。
3. 大 key 会拖慢 Redis，不应缓存完整 trace、完整 prompt、完整报告。
4. Redis 与数据库跨系统不具备自动事务一致性，关键状态仍要由 DB 状态机兜底。
5. 如果过早引入完整任务队列框架，会扩大改动面并影响现有报告链路。

## 9. 本地优秀 Agent 实践参考

### OpenClaw

可参考逻辑：

1. `Reference/openclaw/src/plugin-sdk/webhook-memory-guards.ts`：固定窗口限流、最大 tracked keys、定期 prune，适合映射为 Redis `INCR + EXPIRE` 或 Lua 脚本。
2. `Reference/openclaw/src/shared/scoped-expiring-id-cache.ts`：按 scope + id 做 TTL 去重，适合做 `session_id + message_hash` 的重复提交保护。
3. `Reference/openclaw/src/utils/queue-helpers.ts`：队列上限、drop policy、summary line，适合报告和 WebSocket 输入排队时借鉴。
4. `Reference/openclaw/extensions/memory-core/src/memory/manager-cache.ts`：`cache + pending` 去重，适合做工具缓存重建 singleflight。

不照搬原因：OpenClaw 多为 TypeScript 插件和内存实现，本项目应落到 Python async Redis + PostgreSQL 权威状态。

### Hermes Agent

可参考逻辑：

1. `Reference/hermes-agent/gateway/platforms/api_server.py` 的 `_IdempotencyCache`：TTL + LRU + inflight task，适合报告重复提交和同一请求复用。
2. `Reference/hermes-agent/agent/nous_rate_guard.py`：429 后写共享 cooldown，避免跨会话重试放大，适合 LLM/Tushare/Web Search 供应商限流。
3. `Reference/hermes-agent/gateway/session_context.py`：用 contextvars 隔离 session/trace，适合 Redis 观测字段贯穿 trace。
4. `Reference/hermes-agent/agent/memory_provider.py`：memory provider 化，适合本项目保留 STM、LTM、Redis cache 的分层。

不照搬原因：Hermes 很多共享状态用本地文件，Finance 的部署目标是 Docker/PostgreSQL/Redis，跨容器文件锁不可靠。

### cc-haha

可参考逻辑：

1. `Reference/cc-haha/adapters/common/chat-queue.ts`：同一 chat 串行，避免并发输入互相踩踏。
2. `Reference/cc-haha/adapters/common/message-dedup.ts`：TTL + 容量去重，可迁移为 Redis 幂等 key。
3. `Reference/cc-haha/src/services/SessionMemory/sessionMemory.ts`：记忆抽取后台化、受控化，适合 LTM 写入不要阻塞主回答。

不照搬原因：cc-haha 更偏前端/桌面/文件记忆，Finance 应以 DB、Mem0/pgvector 和 trace 为主。

### traveling-agent

可参考逻辑：

1. `Reference/traveling-agent/README.md` 描述了 Redis 短期记忆、用户偏好热数据、LLM 总结缓存。
2. `Reference/traveling-agent/context/short_term_memory.py` 是最近 N 轮滑动窗口，适合理解 STM 入门模型。
3. `Reference/traveling-agent/context/memory_manager.py` 把短期和长期记忆统一管理，适合本项目做 Redis cache provider。

注意：traveling-agent 文档写了 Redis，但代码主要是内存列表和 JSON 文件，所以只能参考设计意图，不能当作可复制实现。

## 10. 外部开源与官方实践参考

### Redis 官方 Cache Aside

来源：https://redis.io/docs/latest/develop/use-cases/cache-aside/

可迁移结论：

1. Redis 适合重复读、高频读、可接受 TTL 有界陈旧的数据。
2. in-process cache 在多实例下会各自变热，无法统一失效，Redis 可作为共享缓存。
3. 要防止热门 key 过期时大量请求同时回源，也就是缓存击穿。

映射到本项目：

1. Web Search、股票/基金/行业目录、交易日历适合 cache aside。
2. Redis miss 后查 Tushare/Web Search/DB，再回填 Redis。
3. 热门缓存重建要加 singleflight 或 Redis lock。

### Microsoft Azure Cache-Aside Pattern

来源：https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside

可迁移结论：

1. cache aside 要在更新数据库后让缓存失效。
2. 缓存不保证和主数据强一致，要识别 stale data。
3. 不适合缓存敏感或安全关键数据。

映射到本项目：

1. 用户画像缓存必须以 `user_invest_profiles` 为准，画像更新后删 Redis。
2. 金融实时数据必须有短 TTL 和数据时间戳。
3. prompt、token、用户隐私内容不应长期放 Redis。

### Redis INCR Rate Limiter

来源：https://redis.io/docs/latest/commands/incr/

可迁移结论：

1. `INCR` 可用于 API 限流计数。
2. `INCR + EXPIRE` 组合最好用 Lua 保证原子性。

映射到本项目：

1. 对 `/api/chat/message`、`/api/chat/stream`、`/api/report/generate` 做 user/IP 维度限流。
2. 对 Web Search、Tushare、LLM provider 做 provider/family 维度限流。
3. trace 要记录 `rate_limited` 和 `reset_after_seconds`。

### Redis Streams

来源：https://redis.io/docs/latest/develop/use-cases/streaming/

可迁移结论：

1. Streams 是带历史的 append-only log。
2. Consumer group 支持 at-least-once delivery、ack、pending recovery。
3. Streams 可用 `MAXLEN` 控制大小。

映射到本项目：

1. 不建议第一阶段直接替换 DB outbox。
2. 第二阶段可用 Redis Stream 做报告任务、trace exporter、LTM worker 唤醒。
3. `reports` 表、`ltm_write_tasks` 表仍做权威状态，Redis Stream 只做派发和缓冲。

### LangGraph Redis Checkpointer

来源：https://github.com/redis-developer/langgraph-redis

可迁移结论：

1. Redis 可以做 LangGraph checkpoint saver 和 store。
2. checkpoint 支持 TTL，适合自动清理临时线程状态。
3. 需要注意 RedisJSON/RediSearch 等模块依赖。

映射到本项目：

1. 当前报告模式已经有 DB 报告状态和 execution logger，不建议第一阶段替换为 Redis checkpointer。
2. 如果未来要支持可恢复的长工作流，可以评估浅 checkpoint，只保存最新状态并设置 TTL。
3. 由于依赖 Redis 模块较多，不能作为最小接入方案。

### Redis Agent Memory / Google ADK Redis

来源：

1. https://redis.io/tutorials/redis-agent-memory-with-langgraph/
2. https://redis.io/docs/latest/integrate/google-adk/
3. https://redis.io/docs/latest/integrate/google-adk/examples/

可迁移结论：

1. Agent memory 通常拆为 short-term session memory、long-term memory、memory candidates。
2. 长期记忆不是每条对话都直接写入，而是先抽取候选，再筛选和持久化。
3. ADK Redis 把 session、memory、semantic search、response caching 做成 framework abstraction。

映射到本项目：

1. 本项目已经有 STM/LTM/Mem0/pgvector，不需要整体换成 Redis Agent Memory。
2. 可以学习“两层记忆”和“候选记忆”的边界，把 Redis 用于短期 working state 和候选状态。
3. LTM 主数据继续在 DB/Mem0，不要让 Redis 直接成为长期画像库。

### Google Cloud Memorystore Best Practices

来源：https://docs.cloud.google.com/memorystore/docs/redis/general-best-practices

可迁移结论：

1. Redis 需要私有网络访问，不要把敏感信息放在资源名或明文配置中。
2. 要监控内存使用、响应效率和告警。

映射到本项目：

1. Docker 本地可暴露端口，生产应只走内网。
2. Redis key 不放完整问题、完整 prompt、手机号、token、API key。
3. 需要监控 hit rate、used_memory、evicted_keys、latency、connected_clients。

### FastAPI Redis Rate Limiter 开源库

来源：https://github.com/long2ice/fastapi-limiter

可迁移结论：

1. FastAPI 可以用 dependency 形式对单个路由限流。
2. 开源库适合参考接入姿势，但不要立即引入为核心依赖。

映射到本项目：

1. 本项目限流需要结合 user_id、route、tool family、provider 和 trace，不只是简单 IP 限流。
2. 建议先自建很薄的 Redis rate limiter adapter，后续再评估库。

## 11. 实现策略选择

| 能力 | 策略 | 原因 |
| --- | --- | --- |
| Redis 基础客户端 | 新增模块 | 当前没有 Redis 依赖和统一连接管理 |
| Web Search 缓存/限流 | 本地重构 | 已有内存实现和测试，替换存储层即可 |
| HITL pending | 本地重构 | 当前是进程内 TTL dict，适合 Redis JSON + TTL |
| route runtime | 本地重构 | 当前是进程内 TTL dict，适合 Redis JSON + TTL |
| 报告幂等 | 新增小模块 | 现有报告表有 task_id，但没有请求 hash 幂等 |
| 报告任务队列 | 推迟到二期 | 改动面大，先保留 BackgroundTasks 和 reports 表 |
| LTM 队列 Redis 化 | 推迟到二期 | DB outbox 已经可靠，不应急着替换 |
| trace Redis Stream 缓冲 | 推迟到三期 | trace 已有 JSONL/DB/Langfuse，多一个缓冲要谨慎 |
| LangGraph Redis checkpoint | 推迟 | 当前需求不需要，且依赖 Redis 模块更多 |
| Redis semantic cache | 推迟 | 金融回答语义缓存风险高，容易返回不对应的用户/时间答案 |

## 12. 目标架构与实现方案

### 12.1 小白版链路说明

可以把系统理解成三层：

```text
第一层：数据库，负责可靠保存
例如用户、消息、报告、长期画像、trace 主记录。

第二层：Redis，负责快和临时状态
例如最近会话、确认态、搜索缓存、限流计数、重复任务保护。

第三层：Agent，负责分析和回答
先查 Redis 和数据库拿上下文，再调用工具和模型，最后把正式结果写数据库。
```

一次对话可以这样走：

```text
用户提问
→ Redis 检查 user/IP 限流
→ Redis 读取 route runtime / HITL / 最近状态
→ DB 读取正式 session、messages、profile
→ Redis 尝试读取 Web Search / Tushare 缓存
→ 未命中才调用外部工具
→ Agent verifier 校验证据
→ DB 保存正式消息和 trace
→ Redis 更新短期状态和计数
```

一次报告可以这样走：

```text
用户点击生成报告
→ Redis 用 user_id + command_hash 做幂等检查
→ 如果已有同类任务，返回已有 task_id
→ 如果没有，DB 创建 reports 行
→ BackgroundTasks 启动报告任务
→ DB 保存权威进度，Redis 可保存短期进度快照
→ 报告完成后 DB 保存最终报告，Redis 幂等键短期保留
```

### 12.2 Redis key 设计草案

统一前缀：

```text
finance:{env}:{feature}:{id...}
```

示例：

```text
finance:dev:web_search:cache:{sha256}
finance:dev:web_search:rate:{provider}:{minute}
finance:dev:chat:hitl:{session_id}
finance:dev:chat:route_runtime:{session_id}
finance:dev:report:idem:{user_id}:{command_hash}
finance:dev:report:lock:{report_id}
finance:dev:tool:stock_basic:{ts_code}
finance:dev:tool:trade_calendar:{year}
finance:dev:provider:cooldown:{provider}
```

key 规则：

1. key 不直接包含完整用户问题，使用 hash。
2. key 不包含 token、API key、手机号、身份证等敏感信息。
3. value 只保存必要摘要，不保存完整 prompt 和完整 trace。
4. 每类 key 都要有 TTL 或明确清理策略。

### 12.3 TTL 草案

| 数据 | 建议 TTL | 原因 |
| --- | --- | --- |
| HITL pending | 30 分钟 | 用户确认窗口，过期后重新路由 |
| route runtime | 25 分钟 | 与当前内存实现一致 |
| Web Search cache | 15 分钟 | 当前配置已有 `web_search_cache_ttl_min` |
| Web Search rate window | 60 秒 | 分钟级限流 |
| Web Search daily quota | 到当天结束 | 日配额 |
| 股票/基金基础信息 | 1 天 | 变化频率低 |
| 交易日历 | 30 天 | 变化频率低 |
| 实时行情 | 30 秒到 3 分钟 | 高时效，必须记录时间戳 |
| 新闻搜索 | 5 到 15 分钟 | 有时效但可短期复用 |
| 报告幂等键 | 1 到 6 小时 | 防重复点击，不长期占用 |
| provider cooldown | 按 header reset | 避免 429 后重试放大 |

## 13. 代码修改计划

### 第一阶段：Redis 基础设施和只读健康检查

允许修改：

1. `backend/config.py`
2. `backend/main.py`
3. `backend/routers/*` 中健康检查所在文件
4. `backend/.env.example`
5. `Financial-MCP-Agent/.env.example`
6. `docker/docker-compose.yml`
7. `backend/requirements.txt`
8. 新增 `backend/integrations/redis_client.py`
9. 新增相关测试

执行动作：

1. 增加 Redis 配置和 feature flags。
2. 增加统一 async Redis client，支持 lazy connect、ping、close、超时、失败降级。
3. Docker Compose 增加 `redis` 服务、volume、healthcheck。
4. 健康检查返回 Redis 状态，但 Redis disabled 或失败不影响主服务启动。

禁止修改：

1. Agent 业务逻辑。
2. DB schema 和迁移。
3. 前端组件。

验收命令：

```bash
.venv/bin/python -m py_compile backend/config.py backend/main.py backend/integrations/redis_client.py
.venv/bin/python -m unittest tests/test_redis_client.py
curl -fsS http://localhost:8000/api/health
docker compose -f docker/docker-compose.yml config
```

停止条件：

1. 当前 venv 无法安装 `redis`。
2. `/api/health` 现有 schema 不允许兼容增加字段。
3. Docker Compose 与现有 postgres/backend 依赖冲突。

### 第二阶段：Web Search 缓存和限流 Redis 化

允许修改：

1. `Financial-MCP-Agent/src/agents/web_search/service.py`
2. `Financial-MCP-Agent/src/agents/web_search/config.py`
3. `backend/config.py`
4. Web Search 测试

执行动作：

1. 把 `_CACHE` 抽象为 cache store：内存 store 和 Redis store。
2. 把 `_REQUEST_TIMESTAMPS`、`_DAILY_COUNTER` 抽象为 rate limiter。
3. Redis 版本使用 `INCR + EXPIRE` Lua 或 pipeline，保证计数与 TTL 绑定。
4. Redis 不可用时回退内存路径。
5. payload 中保留 `cache_hit`、`cache_backend`、`rate_limit_backend`。

禁止修改：

1. planner、verifier、synthesis。
2. Web Search provider 的返回结构。

验收命令：

```bash
.venv/bin/python -m unittest tests/test_web_search_service.py
.venv/bin/python -m pytest tests/evals/web_search -q
```

停止条件：

1. 缓存命中导致 `source_policy`、`warnings` 或 `injection_suspected` 丢失。
2. 限流先后顺序变化导致测试语义改变。

### 第三阶段：HITL pending 和 route runtime Redis 化

允许修改：

1. `backend/services/chat_hitl_pending.py`
2. `backend/services/chat_route_runtime.py`
3. `backend/services/chat/orchestrator.py` 如需要注入 store
4. 相关测试

执行动作：

1. 保留现有函数签名，内部按开关选择 Redis 或进程内实现。
2. HITL pending 使用 Redis JSON + TTL，并保证 `pop` 是 consume-once。
3. route runtime 使用 Redis JSON + TTL，保留当前 25 分钟语义。
4. trace 记录 `hitl_state_backend`、`route_runtime_backend`。

禁止修改：

1. 前端确认交互契约。
2. Skill 路由决策模型和 prompt。

验收命令：

```bash
.venv/bin/python -m unittest tests/test_chat_route_runtime.py
.venv/bin/python -m unittest tests/test_chat_service_skill_processing.py
```

停止条件：

1. Redis pop 无法保证一次性消费。
2. 多 worker 模拟下出现确认态串会话。

### 第四阶段：报告任务幂等和轻量锁

允许修改：

1. `backend/routers/report.py`
2. `backend/services/report/workflow_runner.py`
3. 新增 `backend/services/report/idempotency.py`
4. `backend/schemas/report.py` 如需兼容字段
5. 报告相关测试

执行动作：

1. 计算 `user_id + normalized_command` 的 hash。
2. Redis `SET idem_key task_id NX EX ttl` 抢占幂等键。
3. 重复请求若任务仍 pending/running，则返回已有 task_id。
4. 报告执行使用 `lock:report:{task_id}` 防止同一任务被多个 worker 执行。
5. DB `reports` 表仍为权威状态。

禁止修改：

1. 报告 LangGraph 节点。
2. 报告最终内容结构。

验收命令：

```bash
.venv/bin/python -m unittest tests/test_report_idempotency.py
curl -sS -X POST http://localhost:8000/api/report/generate ...
```

停止条件：

1. 现有前端依赖“每次点击都创建新任务”的行为。
2. Redis 锁释放无法安全校验 owner。

### 第五阶段：工具结果缓存和 provider cooldown

允许修改：

1. `Financial-MCP-Agent/src/tools/chat_tushare_tools.py`
2. `Financial-MCP-Agent/src/tools/tushare_client.py`
3. `backend/services/entity_resolver.py`
4. `Financial-MCP-Agent/src/agents/executor/execution_scheduler.py`
5. 相关测试和 eval fixtures

执行动作：

1. 对低时效数据加 Redis cache aside：股票基础信息、基金基础信息、交易日历、行业目录。
2. 对高时效数据只允许短 TTL，并把 `data_timestamp` 写入 evidence envelope。
3. 对 429/配额异常写 provider cooldown key，后续请求直接降级或等待。
4. 工具缓存命中仍走 evidence verifier。

禁止修改：

1. `required_evidence` 语义。
2. synthesis 的证据边界。

验收命令：

```bash
.venv/bin/python -m unittest tests/test_chat_tushare_tools_envelope.py
.venv/bin/python -m unittest tests/test_execution_scheduler.py
.venv/bin/python -m pytest tests/evals/executor tests/evals/verifier -q
```

停止条件：

1. 缓存数据无法携带时间戳。
2. 缓存命中绕过 evidence verifier。

### 第六阶段：Redis Stream 评估，不默认实现

允许修改：

1. 仅新增实验文档或 PoC 测试，不接主链路。

评估对象：

1. 报告任务队列。
2. LTM worker 唤醒。
3. trace exporter 异步缓冲。

停止条件：

1. Redis Stream 让 DB outbox 语义变复杂。
2. 无法证明比现有 DB outbox + BackgroundTasks 更稳定。

## 14. 数据库与契约变更

第一阶段到第三阶段不需要 DB schema 变更。

第四阶段报告幂等优先用 Redis，不新增 DB 字段。如果后续要把幂等状态做成可审计记录，再考虑新增 `report_request_idempotency` 表。

前端契约默认不变。若后续需要展示限流或排队状态，新增字段必须保持可选：

```ts
redis_status?: "disabled" | "ok" | "degraded"
cache_hit?: boolean
rate_limit?: {
  limited: boolean
  retry_after_seconds?: number
}
```

## 15. 测试与验证方案

### 单元测试

1. Redis client 初始化、ping、关闭、连接失败降级。
2. Redis cache store：set/get/ttl/expired/malformed JSON。
3. Redis rate limiter：并发 `INCR`、首次设置 TTL、超过阈值拒绝。
4. HITL pending：set/get/pop/expired/consume-once。
5. route runtime：写入、读取、TTL 到期、Redis 不可用回退。
6. 报告幂等：同请求复用 task，不同 command 新建 task。

### 集成测试

1. 启动 Redis 后跑 `/api/chat/message`，确认 trace 写出 backend。
2. 重复 Web Search 查询，第二次 `cache_hit=true`，provider 调用次数不增加。
3. Redis 关闭后重复 Web Search，系统降级为内存缓存或 cache miss。
4. 重复报告生成，返回同一 running task。
5. LTM 开启时，Redis 不影响 `ltm_write_tasks` 入队和 worker 处理。

### 端到端手动验收

1. `docker compose up -d postgres redis pgadmin`
2. 后端启动看到 Redis health 日志。
3. 前端登录 `test1/test1`。
4. 发送 `贵州茅台今天怎么样` 两次，检查第二次搜索或低时效工具缓存命中。
5. 触发低置信度 Skill HITL，刷新或换 worker 后仍能确认。
6. 连续点击生成报告两次，确认不会生成重复任务。
7. 停掉 Redis，再发送普通问题，确认后端有降级日志但不崩溃。

## 16. 验收证据包

每个开发阶段完成后，应提供：

1. 修改文件列表。
2. 运行命令和结果。
3. Redis key 样例，必须脱敏。
4. 一条 cache hit trace 样例。
5. 一条 Redis unavailable fallback 日志。
6. 一条 rate limit 或 provider cooldown 样例。
7. 如果改报告幂等，提供重复提交前后 `task_id` 对比。
8. 如果改 HITL，提供 pending set、confirm pop、二次 pop 失败的测试结果。

## 17. 预期收益与评测指标

### 性能指标

| 指标 | 解释 | 目标 |
| --- | --- | --- |
| `chat_p50_latency_ms` | 对话中位耗时 | 不劣化 |
| `chat_p95_latency_ms` | 对话尾延迟 | 缓存命中场景下降 |
| `web_search_cache_hit_rate` | Web Search 缓存命中率 | 稳定后 30% 以上 |
| `tool_cache_hit_rate` | 工具低时效缓存命中率 | 按工具族统计 |
| `provider_call_count_per_turn` | 单轮外部调用次数 | 高频重复问题下降 |
| `db_query_count_per_turn` | 单轮 DB 查询次数 | route/HITL 状态下降 |

### 稳定性指标

| 指标 | 解释 | 目标 |
| --- | --- | --- |
| `duplicate_report_task_count` | 重复报告任务数 | 明显下降 |
| `rate_limited_requests` | 被限流请求数 | 可观测且不打爆 provider |
| `provider_cooldown_hits` | 供应商 cooldown 命中 | 429 后能阻断重试放大 |
| `redis_fallback_count` | Redis 降级次数 | 可观测，不影响主链路 |
| `cache_stampede_prevented` | 缓存击穿保护次数 | 热点 key 过期时可观测 |

### 质量指标

| 指标 | 解释 | 目标 |
| --- | --- | --- |
| `stale_market_data_incidents` | 使用过期行情造成错误回答 | 0 |
| `evidence_cache_hit_with_timestamp_rate` | 缓存证据带时间戳比例 | 100% |
| `verifier_bypassed_by_cache_count` | 缓存绕过 verifier 次数 | 0 |
| `overclaim_rate` | 缓存新闻导致强因果错误 | 不上升 |

### 成本指标

| 指标 | 解释 | 目标 |
| --- | --- | --- |
| `web_search_provider_calls_saved` | 搜索调用节省量 | 逐周上升 |
| `tushare_calls_saved` | Tushare 调用节省量 | 低时效工具明显下降 |
| `llm_retry_amplification_count` | 429 后重复调用放大 | 下降 |
| `tokens_saved_by_summary_cache` | 摘要缓存节省 token | 二期后评估 |

### 评测方法

1. 选 30 条重复查询样例：同一股票、同一基金、同一板块、同一新闻问题。
2. 每条连续跑 3 次，记录第 1 次冷启动和第 2/3 次热缓存。
3. 对比 Redis disabled 与 Redis enabled。
4. 用 trace 统计 cache hit、工具调用次数、latency、evidence accepted。
5. 人工抽查金融回答，确认缓存没有制造过期结论。

## 18. 分阶段实施顺序

建议顺序：

1. 基础设施：Redis client、配置、Docker、healthcheck。
2. 低风险缓存：Web Search cache 和 rate limit。
3. TTL 状态：HITL pending、route runtime。
4. 幂等控制：报告重复提交、轻量锁。
5. 工具缓存：Tushare 低时效工具、实体目录、交易日历。
6. 任务队列/Stream：只在前面收益明确后再评估。
7. LangGraph checkpoint/semantic cache：最后评估，不作为近期目标。

## 19. Codex 执行任务拆分

### Task 1：Redis 基础设施

任务目标：加 Redis 配置、client、Docker 服务和健康检查，不接业务逻辑。

允许修改：

1. `backend/config.py`
2. `backend/main.py`
3. `backend/.env.example`
4. `Financial-MCP-Agent/.env.example`
5. `docker/docker-compose.yml`
6. `backend/requirements.txt`
7. `backend/integrations/redis_client.py`
8. `tests/test_redis_client.py`

禁止修改：

1. `Financial-MCP-Agent/src/agents/`
2. `backend/services/chat*`
3. `backend/services/report*`
4. `frontend/src/`
5. `migrations/`

验收命令：

```bash
.venv/bin/python -m unittest tests/test_redis_client.py
.venv/bin/python -m py_compile backend/config.py backend/main.py backend/integrations/redis_client.py
docker compose -f docker/docker-compose.yml config
```

停止条件：

1. Redis 依赖安装失败。
2. 健康检查需要破坏现有响应契约。

### Task 2：Web Search Redis cache/rate limit

任务目标：Web Search 优先使用 Redis 缓存和限流，失败时回退当前内存实现。

允许修改：

1. `Financial-MCP-Agent/src/agents/web_search/service.py`
2. `Financial-MCP-Agent/src/agents/web_search/config.py`
3. `tests/test_web_search_service.py`

禁止修改：

1. planner/verifier/synthesis。
2. 前端文件。

验收命令：

```bash
.venv/bin/python -m unittest tests/test_web_search_service.py
.venv/bin/python -m pytest tests/evals/web_search -q
```

停止条件：

1. Web Search payload 字段丢失。
2. Redis unavailable 不能降级。

### Task 3：HITL pending 与 route runtime

任务目标：把两个进程内 TTL 状态改为可选 Redis backend。

允许修改：

1. `backend/services/chat_hitl_pending.py`
2. `backend/services/chat_route_runtime.py`
3. `tests/test_chat_route_runtime.py`
4. `tests/test_chat_service_skill_processing.py`

禁止修改：

1. 前端确认 UI。
2. Skill 选择策略。

验收命令：

```bash
.venv/bin/python -m unittest tests/test_chat_route_runtime.py
.venv/bin/python -m unittest tests/test_chat_service_skill_processing.py
```

停止条件：

1. HITL pop 不能保证 consume-once。
2. route runtime 与 session 隔离失效。

### Task 4：报告幂等

任务目标：重复点击同一报告请求时复用已有 running task。

允许修改：

1. `backend/routers/report.py`
2. `backend/services/report/idempotency.py`
3. `tests/test_report_idempotency.py`

禁止修改：

1. 报告工作流节点。
2. 报告内容生成 prompt。

验收命令：

```bash
.venv/bin/python -m unittest tests/test_report_idempotency.py
```

停止条件：

1. 前端或用户明确需要每次都生成新报告。
2. 现有 `reports.task_id` 唯一约束与幂等逻辑冲突。

### Task 5：低时效工具缓存

任务目标：缓存股票/基金/交易日历/行业目录等低时效工具结果，保留证据时间戳。

允许修改：

1. `Financial-MCP-Agent/src/tools/chat_tushare_tools.py`
2. `Financial-MCP-Agent/src/tools/tushare_client.py`
3. `backend/services/entity_resolver.py`
4. 相关测试

禁止修改：

1. verifier 证据标准。
2. synthesis 结论边界。

验收命令：

```bash
.venv/bin/python -m unittest tests/test_entity_resolver.py
.venv/bin/python -m unittest tests/test_chat_tushare_tools_envelope.py
.venv/bin/python -m pytest tests/evals/executor tests/evals/verifier -q
```

停止条件：

1. 缓存结果无法序列化。
2. 缓存结果缺少数据时间戳。

## 20. 初步结论

本项目最适合的 Redis 路线不是“大而全重构”，而是先把当前已经存在的进程内 TTL 状态变成可共享、可降级、可观测的 Redis 状态层。第一批应做 Web Search 缓存/限流、HITL pending、route runtime。第二批再做报告幂等、provider cooldown、低时效 Tushare 缓存。报告队列、LTM 分发、trace Stream 和 LangGraph checkpoint 都应该放到后续评估阶段。

这样做的好处是改动小、收益明确、风险可控，并且与 `docs/项目描述.md` 的项目叙事一致：Redis 只负责加速、临时状态和并发治理，真正的金融证据、用户消息、报告结果、长期画像和 trace 事实账本仍由数据库和现有观测体系兜底。
