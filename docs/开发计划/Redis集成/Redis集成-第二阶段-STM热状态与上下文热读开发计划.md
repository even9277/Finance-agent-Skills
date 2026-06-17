# Redis 集成 · 第二阶段（STM 热状态与上下文热读）优化开发计划

> 本计划只覆盖对话模式 STM（短期记忆）相关的 Redis 业务接入。
> 适用范围：`/root/Finance` Finance 智能投研助手。
> 阅读对象：完全不了解 Redis 的小白 + 后续负责执行落地的 AI（Codex/Cursor/Claude Code）。
> 项目最高真相源：`docs/项目描述.md`。
> 承接前置计划：`docs/开发计划/Redis集成/Redis集成-第一阶段基础设施-开发计划.md`。

---

## 0. 一句话总览（先说人话）

第一阶段已经把 Redis 的“水管”接好了：连接池、KeyBuilder、CacheEnvelope、TTL、降级、健康检查和指标都有了。

第二阶段要做的是把这条水管接到对话模式最适合 Redis 的两个地方：

1. **对话短期热状态**：把每轮都会读的 `active_entity / constraints / reply_preference_hint` 放一份短 TTL Redis 副本。
2. **最近上下文热读**：把最近几轮 raw tail 和 last-good rolling summary 放一份 Redis 快照，给 Preflight 和上下文装配快速读取。

但是有一条硬边界：

> **PostgreSQL 仍然是真相源，Redis 只是热读副本。Redis 命中就加速，Redis 挂了、旧了、版本不对，就回源 PostgreSQL，不影响主链路正确性。**

用小白能理解的话说：数据库像“正式账本”，Redis 像“桌面便签”。便签能让你查得更快，但便签丢了、旧了，必须回去看正式账本。

---

## 1. 背景与目标

### 1.1 背景

项目描述里已经把对话模式 STM 设计成一个比较完整的上下文治理链路：

- 用户新消息进来后，先进入 Preflight。
- Preflight 会估算本轮真正要给模型的上下文预算。
- 系统会优先保留当前用户问题和 working state。
- working state 里最关键的三个热字段是：
  - `active_entity`：当前到底在聊哪只股票、基金、板块或指数。
  - `constraints`：用户本轮给的限制，例如“只看 A 股”“不要展开技术面”。
  - `reply_preference_hint`：用户偏好的回答方式，例如“简单说”“先给结论”。
- 最近几轮 raw tail 用来保留精确指代和临时约束。
- rolling summary 用来承接更早的对话主线。

这些内容每轮对话都会被读取，而且体积比较小，非常适合 Redis 热读。

但这些状态也很敏感。比如 Redis 里如果残留旧的 `active_entity=贵州茅台`，而用户本轮已经切换到“中芯国际”，后续 route、rewrite、planner 都可能围绕错误对象执行。所以 Redis 不能成为真相源，只能做带版本校验的缓存。

### 1.2 本阶段目标

本阶段要完成两类能力。

**目标一：STM 三个热字段 Redis 化**

把 `active_entity / constraints / reply_preference_hint` 做成 Redis 热读副本：

- 读路径：先查 Redis，命中且版本有效就使用。
- 未命中：回源 PostgreSQL 的 `Session.working_state`，再回填 Redis。
- 写路径：DB 更新成功后删除或刷新 Redis，避免旧状态污染下一轮。
- 缓存 value 必须带 `state_version / summary_version / updated_at / field_source`。
- Redis 不可用时主链路继续走 DB。

**目标二：最近几轮上下文 + last-good summary Redis 热读**

把最近几轮 raw tail 和 rolling summary 做成 Redis 热读快照：

- recent raw tail 缓存最近 `3-5` 轮 user/assistant 原文或短文本。
- summary 缓存 last-good summary，只缓存质量门控通过的摘要。
- Redis value 必须带 `last_message_id / message_count / summary_version / compressed_until_message_id / updated_at`。
- 缓存命中不能替代 working state，也不能替代最近 raw tail。
- Redis 失效后回源 DB，不中断本轮回答。

### 1.3 为什么这两个点适合 Redis

| 接入点 | 为什么适合 Redis | 为什么不能只放 Redis |
|---|---|---|
| `active_entity` | 每轮 route/rewrite/planner 都读，体积小，访问频繁 | 一旦旧主语被使用，整轮回答会跑偏 |
| `constraints` | 每轮计划和回答边界都要看，体积小 | 用户限制必须可审计，DB 仍要保存事件 |
| `reply_preference_hint` | synthesis 每轮都会用，适合热读 | 不能让旧偏好覆盖当前用户问题 |
| recent raw tail | 最近几轮读多、短生命周期、可从 DB 重建 | 完整消息必须在 `messages` 表，不能丢审计 |
| last-good summary | 读多写少，每轮 Preflight 常用 | 失败摘要、低质量摘要不能覆盖权威摘要 |

---

## 2. 非目标与保持不变的行为

### 2.1 本阶段明确不做

- 不缓存工具调用结果。
- 不缓存 Tushare 行情、新闻、研报、网页搜索结果。
- 不缓存 LLM 最终回答。
- 不缓存完整消息历史。
- 不缓存完整最终报告。
- 不改长期记忆、用户画像、Mem0、pgvector 的真相源设计。
- 不做报告幂等、报告状态、SSE 进度展示；这些放到后续第三阶段。
- 不引入 Redis Stream、Redis Pub/Sub、Redis Cluster、Sentinel。
- 不把 Redis lock 作为本阶段主链路依赖。
- 不修改数据库表结构。
- 不修改前端 UI。

### 2.2 必须保持不变

- Redis 关闭时，对话模式仍然能工作，只是少了热读加速。
- PostgreSQL 仍然保存消息、会话、working state、summary 和审计事件。
- `Session.working_state`、`Session.working_state_version`、`Session.summary_version` 的语义不变。
- 现有 `/api/chat/message` 和流式对话接口的响应字段保持向后兼容。
- 现有 STM 压缩触发条件、summary 质量门控、Context Gateway 优先级不因为 Redis 接入而变弱。
- 不允许因为 Redis 命中而跳过必要的实体解析、约束抽取、证据校验。

---

## 3. 验收标准

### 3.1 功能验收

1. Redis 开启时，连续两轮对话能产生 `stm:state` 缓存：
   - key 由 `KeyBuilder.stm_state(user_id, session_id)` 生成；
   - value 是 `CacheEnvelope`；
   - `data` 内包含 `active_entity / constraints / reply_preference_hint / state_version / summary_version / updated_at`；
   - TTL 为正数。

2. Redis 开启时，Preflight 或上下文装配能读取 `stm:tail`：
   - key 由 `KeyBuilder.stm_tail(user_id, session_id)` 生成；
   - value 包含最近消息 `message_id / role / content / created_at / token_count`；
   - value 包含 `last_message_id / message_count / tail_policy`；
   - 不包含完整长期历史。

3. Redis 开启时，summary 更新成功后能产生 `stm:summary`：
   - key 由 `KeyBuilder.stm_summary(user_id, session_id)` 生成；
   - value 包含 `summary_text / summary_payload / summary_version / last_good_summary_version / compressed_until_message_id / updated_at`；
   - 只有 last-good summary 能写入缓存。

4. Redis 缓存版本落后时：
   - 系统拒绝使用旧缓存；
   - 回源 PostgreSQL；
   - trace 标记 `cache_stale_reject=true` 或等价字段。

5. Redis 关闭或不可用时：
   - 对话接口不返回 500；
   - 对话仍然从 DB 读取 working state、recent tail、summary；
   - trace 标记 `redis_fallback=true` 和具体原因。

### 3.2 正确性验收

1. 用户从“贵州茅台”切换到“中芯国际”后，不允许 Redis 旧 `active_entity` 污染 route。
2. 用户明确说“只看 A 股”后，`constraints` 必须进入 planner 和 synthesis，不允许被旧 summary 覆盖。
3. 用户说“简单说”后，`reply_preference_hint` 可以被 Redis 热读，但不能覆盖后续用户新的表达偏好。
4. summary 缓存命中时，仍然必须保留最近 raw tail 和 working state。
5. summary 质量失败、fallback 或 schema gate 不通过时，不允许刷新 Redis summary。

### 3.3 性能与观测验收

实现后至少要能看到这些指标或 trace 字段：

- `stm_state_cache_hit`
- `stm_state_cache_miss`
- `stm_tail_cache_hit`
- `stm_summary_cache_hit`
- `cache_stale_reject_count`
- `state_cache_fallback_count`
- `summary_cache_fallback_count`
- `preflight_db_read_count`
- `preflight_latency_ms`

验收目标不是一开始就承诺固定性能数字，而是能用日志和 trace 证明：

- Redis 命中时少走 DB 读取。
- Redis 异常时主链路不崩。
- Redis 旧版本被拒绝。
- Preflight P95 延迟有可观测对比口径。

---

## 4. 项目描述对齐

| 项目描述中的约束 | 本计划如何落实 |
|---|---|
| STM 不是简单保留更多历史，而是保证上下文足够少、足够准、优先级正确 | Redis 只热读 working state、recent tail、last-good summary，不改变 Context Gateway 优先级 |
| 当前问题和 `active_entity` 优先级最高 | Redis state 命中后仍要版本校验，旧主语必须回源 DB |
| `constraints` 和 `reply_preference_hint` 决定本轮怎么答 | 缓存 payload 保留这两个字段，并记录 `field_source / updated_at` |
| 最近 `3-5` 轮 raw tail 保留指代和临时约束 | `stm_tail` 只缓存最近尾窗，不缓存完整历史 |
| rolling summary 承接更早主线 | `stm_summary` 只缓存 last-good summary |
| PostgreSQL 仍是权威存储，缓存只是读加速和降级辅助层 | 写入以 DB 为准，Redis miss/fallback/stale 都回源 DB |
| value 带 `state_version / summary_version / updated_at` | `STMStateCachePayload` 和 `STMSummaryCachePayload` 强制保留版本字段 |
| 缓存失败后回源 DB；DB 失败后退到最小上下文 | `STMRedisCache` 返回 fallback meta，不向用户抛 Redis 异常 |
| 高并发下要避免旧状态和击穿 | 版本校验、TTL 抖动、写后删缓存，singleflight 作为可选增强 |
| trace 要能定位 state/summary 问题 | trace 记录 `cache_key_family / cache_hit / version_match / fallback_reason / state_version / summary_version` |

---

## 5. 当前实现现状

### 5.1 Redis 基础设施现状

第一阶段已经具备以下能力：

| 能力 | 当前路径 | 现状 |
|---|---|---|
| Redis 运行时初始化 | `backend/integrations/redis/runtime.py` | 已实现，支持 disabled/degraded |
| 统一 KeyBuilder | `backend/integrations/redis/key_builder.py` | 已有 `stm_state / stm_tail / stm_summary` |
| 统一 CacheEnvelope | `backend/integrations/redis/envelope.py` | 已实现 |
| 统一 CacheService | `backend/integrations/redis/cache_service.py` | 已有 `get / get_with_version / set / delete` |
| TTL 抖动 | `CacheService.ttl_with_jitter()` | 已实现 |
| 版本读取 | `CacheService.get_with_version()` | 已实现 |
| Redis 指标 | `backend/integrations/redis/metrics.py` | 已有基础计数器 |
| Redis lock API | `backend/integrations/redis/lock.py` | 已有薄封装，本阶段不作为主依赖 |

结论：第二阶段不需要重写 Redis 基建，只需要新增 STM 业务适配层。

### 5.2 STM working state 现状

当前 working state 相关路径：

| 路径 | 现状 |
|---|---|
| `backend/services/working_state.py` | 提供 `get_working_state / upsert_active_entity / upsert_constraints / upsert_reply_preference` |
| `Session.working_state` | 保存当前 working state |
| `Session.working_state_version` | 每次字段更新递增 |
| `WorkingStateEvent` | 记录字段变更事件 |
| `backend/services/chat/skill_pipeline.py` | route 前后读取/更新 working state |

当前缺口：

- `get_working_state(session)` 只读 SQLAlchemy session 对象，没有 Redis 热读。
- `upsert_*` 写 DB 后没有缓存失效或刷新。
- trace 里没有明确区分 `state_cache_hit / state_cache_miss / state_cache_stale`。

### 5.3 recent tail 与 summary 现状

当前上下文相关路径：

| 路径 | 现状 |
|---|---|
| `backend/services/stm_context_service.py` | 计算 context token，读取未压缩消息，选择 cutoff |
| `backend/services/stm_summary_runtime.py` | 执行 preflight summary compaction，更新 `running_summary` 和 `running_summary_state` |
| `backend/services/chat/orchestrator.py` | 同步对话入口，保存用户消息后执行 preflight |
| `backend/services/chat/stream.py` | 流式对话入口，执行 preflight 并向前端发压缩状态 |
| `backend/services/chat/memory_bridge.py` | LTM 抽取时读取 `running_summary` |

当前缺口：

- recent raw tail 每次仍主要从 DB 查询和拼接。
- running summary 每次仍从 session/DB 对象读取。
- summary 更新成功后没有 Redis last-good 快照。
- Redis miss/fallback 对 Preflight 延迟的影响还没有 trace 化。

---

## 6. 变更面分析

| 层 | 是否变更 | 说明 |
|---|---|---|
| Redis 基建 | 小改或不改 | 复用现有 `CacheService`，必要时只补 key family meta |
| 后端 service | 需要新增 | 新增 STM Redis 业务适配层 |
| chat orchestrator | 需要小改 | 在 Preflight 前后接入 state/tail/summary 热读与刷新 |
| stream chat | 需要小改 | 与同步对话保持相同缓存逻辑 |
| working state | 需要小改 | DB 更新后触发缓存删除或刷新 |
| summary runtime | 需要小改 | last-good summary 成功写 DB 后刷新 Redis |
| router/schema | 原则上不改 | 对外 API 响应保持兼容 |
| 数据库 | 不改 | 不新增表、不改字段 |
| 前端 | 不改 | 本阶段不新增 Redis 可视化 UI |
| 测试 | 新增 | 增加 STM Redis cache 单测、降级测试、集成冒烟测试 |
| 文档 | 本文件 | 后续实现完成后可补运行验收证据 |

---

## 7. 差距与风险

### 7.1 主要差距

1. 缺少 STM 业务缓存适配层。
2. 缺少 state/tail/summary 的 payload schema。
3. 缺少 Redis 和 DB 版本一致性判断的业务规则。
4. 缺少写 DB 后缓存失效策略。
5. 缺少 summary 质量门控后刷新 Redis 的逻辑。
6. 缺少 Redis 命中、miss、stale、fallback 的 STM 级 trace。
7. 缺少 Redis 不可用时 STM 主链路的回归测试。

### 7.2 核心风险

| 风险 | 表现 | 解决方案 |
|---|---|---|
| 旧 `active_entity` 污染新问题 | 用户切标的后仍按旧股票回答 | 缓存 value 带 `state_version`，不匹配直接回源 |
| 旧 summary 覆盖新上下文 | summary 漏掉新约束 | summary 带 `summary_version / compressed_until_message_id` |
| Redis 写在 DB commit 前 | DB 回滚但 Redis 已经有新状态 | Redis 更新放到 DB 成功后，或只做删缓存 |
| Redis 不可用导致对话失败 | Redis timeout 抛到 API | `CacheService` fallback，业务回源 DB |
| 缓存过大 | recent tail 或 summary value 超过上限 | 限制 content 长度、消息条数、summary token |
| 击穿 | 热 session 缓存过期瞬间多请求回源 | TTL 抖动；singleflight 作为增强项 |

---

## 8. 本地优秀 Agent 实践参考

这些参考仓库不能直接照搬 Redis STM 代码，但可以借鉴工程思想。

| 参考项目 | 参考点 | 映射到本项目 |
|---|---|---|
| `Reference/openclaw/ui/src/ui/views/usage-render-overview.ts` | 把 cache read/write 和 cache hit rate 做成可观测指标 | 本项目要记录 `state_cache_hit_rate / summary_cache_hit_rate` |
| `Reference/cc-haha/adapters/common/message-dedup.ts` | TTL + 容量上限的短期状态设计 | recent tail 必须短 TTL、有大小限制 |
| `Reference/cc-haha/docs/en/agent/03-agent-framework.md` | 上下文压缩不是直接截断，而是分阶段保留关键内容 | Redis 不能替代 Context Gateway，只能加速热读 |
| `Reference/hermes-agent` context/compression 思路 | 保护上下文稳定性，避免动态内容污染缓存边界 | working state 是动态块，必须有版本，不放进固定 prompt cache |

结论：本阶段的本地参考重点不是“Redis 怎么写”，而是“Agent 上下文和缓存必须可观测、有边界、可降级”。

---

## 9. 外部开源与官方实践参考

### 9.1 LangGraph memory

LangGraph 官方文档把短期记忆定义为 agent state，并提供 trim、delete、summarize 等长对话管理方式。它还提供 Redis checkpointer，用于保存 thread-level state。

参考：

- https://docs.langchain.com/oss/python/langgraph/add-memory

映射到本项目：

- 不直接引入 LangGraph RedisSaver 替换现有 DB。
- 借鉴“短期记忆是 agent state，需要裁剪和摘要”的思想。
- 本项目仍以 PostgreSQL 为真相源，Redis 只保存热读副本。

### 9.2 Redis + LangGraph 官方示例

Redis 官方文章和教程把 Redis 用于 agent memory persistence、conversation state、summary node。

参考：

- https://redis.io/blog/langgraph-redis-build-smarter-ai-agents-with-memory-persistence/
- https://redis.io/tutorials/what-is-agent-memory-example-using-langgraph-and-redis/

映射到本项目：

- Redis 可以保存会话级状态和摘要快照。
- 但本项目是金融场景，不能让 Redis 成为金融事实或用户画像真相源。

### 9.3 LangChain RedisChatMessageHistory

LangChain 社区提供 Redis chat message history，支持按 `session_id` 保存聊天消息，并支持 TTL。

参考：

- https://python.langchain.com/api_reference/community/chat_message_histories/langchain_community.chat_message_histories.redis.RedisChatMessageHistory.html

映射到本项目：

- 证明“最近对话历史放 Redis”是成熟常见实践。
- 本项目不直接把完整消息历史搬进 Redis，只缓存 recent raw tail 快照。

### 9.4 AWS 缓存实践

AWS Builders Library 强调缓存必须有明确收益指标，必须考虑安全、缓存污染、thundering herd，并建议 request coalescing。

参考：

- https://aws.amazon.com/builders-library/caching-challenges-and-strategies/
- https://aws.amazon.com/caching/best-practices/

映射到本项目：

- Redis 接入后要看 hit rate、fallback、P95 latency，不只说“更快”。
- Redis 不可用时必须可降级。
- 热 key miss 可以用 singleflight 或短锁作为后续增强。

### 9.5 Redis TTL 与缓存问题

`docs/Redis 与缓存体系.md` 已经总结了穿透、击穿、雪崩：

- 缓存穿透：不存在的数据反复打 DB。
- 缓存击穿：热点 key 过期瞬间大量请求回源。
- 缓存雪崩：大量 key 同时过期。

映射到本项目：

- STM key 由后端生成，不允许用户传任意 key。
- 所有 key 必须有 TTL。
- TTL 必须加抖动。
- 热 session 的 summary miss 可选 singleflight。

---

## 10. 实现策略选择

| 模块 | 策略 | 理由 |
|---|---|---|
| Redis 客户端 | 复用现有实现 | 第一阶段已有 `CacheService`，不再新增 Redis client |
| Key 生成 | 复用现有实现 | `KeyBuilder` 已有 `stm_state / stm_tail / stm_summary` |
| STM payload schema | 新增模块 | 当前没有 state/tail/summary 的业务 payload 规范 |
| state 读路径 | 本地小重构 | 当前 `get_working_state(session)` 只读 DB 对象，需要增加 Redis 读入口 |
| state 写路径 | 本地小重构 | `upsert_*` 后需要缓存删除/刷新 |
| recent tail 读路径 | 新增服务函数 | 当前散落在上下文构造和消息查询中，需要统一快照 |
| summary 缓存 | 本地小重构 | summary runtime 已有 last-good 逻辑，增加刷新缓存即可 |
| singleflight | 推迟 | 个人项目第二阶段先做版本校验和 TTL 抖动，singleflight 写入计划但不强制首版实现 |
| 前端 UI | 推迟 | 本阶段不做 Redis 面板 |
| 数据库迁移 | 不做 | 现有字段足够承载版本和真相源 |

---

## 11. 目标架构与实现方案

### 11.1 目标结构

```text
Chat Orchestrator / Stream Chat / Skill Pipeline
        ↓
STMRedisCache（新增业务适配层）
        ↓
CacheService（第一阶段已有）
        ↓
RedisClient / KeyBuilder / CacheEnvelope（第一阶段已有）
        ↓
Redis

PostgreSQL 仍然保存：
- sessions.working_state
- sessions.working_state_version
- sessions.running_summary
- sessions.running_summary_state
- sessions.summary_version
- messages
- working_state_events
```

### 11.2 新增业务适配层

建议新增：

```text
backend/services/chat/stm_cache.py
```

这个文件只做一件事：把 STM 业务数据转换成 Redis 可以安全存取的 payload。

建议提供这些方法：

```python
class STMRedisCache:
    async def get_state(user_id: str, session: Session) -> tuple[dict | None, dict]:
        ...

    async def refresh_state(user_id: str, session: Session, source: str) -> dict:
        ...

    async def invalidate_state(user_id: str, session_id: str, reason: str) -> dict:
        ...

    async def get_tail(user_id: str, session: Session) -> tuple[dict | None, dict]:
        ...

    async def refresh_tail(user_id: str, session: Session, messages: list[Message], policy: str) -> dict:
        ...

    async def get_summary(user_id: str, session: Session) -> tuple[dict | None, dict]:
        ...

    async def refresh_summary(user_id: str, session: Session, source: str) -> dict:
        ...
```

### 11.3 state 缓存 payload

Redis key：

```text
finagent:{env}:stm:state:{user_id}:{session_id}
```

建议 payload：

```json
{
  "user_id": "u_xxx",
  "session_id": "s_xxx",
  "state_version": 12,
  "summary_version": 7,
  "active_entity": {
    "display_name": "贵州茅台",
    "asset_type": "stock",
    "symbol": "600519.SH",
    "confidence": 0.92,
    "resolution_status": "resolved"
  },
  "constraints": ["只看A股口径"],
  "reply_preference_hint": "简单说，先给结论",
  "field_source": {
    "active_entity": "entity_resolver_v2",
    "constraints": "constraints_extractor",
    "reply_preference_hint": "reply_preference_extractor"
  },
  "updated_at": "2026-06-15T10:00:00Z"
}
```

TTL 建议：

```text
20 分钟，使用第一阶段 CacheService 的 10% jitter。
```

校验规则：

- `session_id` 不一致：拒绝。
- `state_version` 小于 DB 当前版本：拒绝。
- `summary_version` 明显落后且本轮需要 summary：拒绝。
- payload 缺少关键字段：拒绝。
- Redis meta 显示 fallback：回源 DB。

### 11.4 recent tail 缓存 payload

Redis key：

```text
finagent:{env}:stm:tail:{user_id}:{session_id}
```

建议 payload：

```json
{
  "user_id": "u_xxx",
  "session_id": "s_xxx",
  "tail_policy": "recent_3_to_5_turns",
  "message_count": 6,
  "first_message_id": 101,
  "last_message_id": 106,
  "messages": [
    {
      "message_id": 101,
      "role": "user",
      "content": "贵州茅台现在估值还贵吗",
      "token_count": 18,
      "created_at": "2026-06-15T10:00:00Z"
    }
  ],
  "updated_at": "2026-06-15T10:00:02Z"
}
```

TTL 建议：

```text
20 分钟，使用 TTL jitter。
```

安全限制：

- 只缓存最近尾窗，不缓存全量历史。
- 每条 content 截断，例如最多 800 字。
- 总 value 不能超过 `CacheService.max_value_bytes`。
- 不缓存 token、密钥、完整工具 payload、完整报告。

校验规则：

- Redis 的 `last_message_id` 小于当前 session 最新消息：允许作为候选，但如果本轮需要最新消息，必须回源 DB 刷新。
- `message_count` 超过配置上限：拒绝。
- `session_id / user_id` 不一致：拒绝。

### 11.5 summary 缓存 payload

Redis key：

```text
finagent:{env}:stm:summary:{user_id}:{session_id}
```

建议 payload：

```json
{
  "user_id": "u_xxx",
  "session_id": "s_xxx",
  "summary_text": "用户主要在比较贵州茅台估值...",
  "summary_payload": {
    "schema_version": 1,
    "summary_version": 7,
    "active_entities": [],
    "constraints": [],
    "reply_preference_hint": "简单说"
  },
  "summary_version": 7,
  "last_good_summary_version": 7,
  "compressed_until_message_id": 100,
  "summary_quality": {
    "mode": "normal",
    "source": "schema_passed"
  },
  "updated_at": "2026-06-15T10:00:00Z"
}
```

TTL 建议：

```text
60 分钟，使用 TTL jitter。
```

写入规则：

- 只有 summary 质量通过时刷新缓存。
- `summary_quality.mode=fallback` 时不刷新缓存，除非项目描述明确允许 fallback 作为 last-good。
- schema gate 失败时不刷新缓存。
- DB `summary_version` 更新成功后再刷新 Redis。
- Redis 刷新失败不影响本轮对话。

### 11.6 读路径流程

以同步对话为例：

```text
用户发消息
→ 写入 messages 表
→ Preflight 开始
→ 读取 STM state
   → Redis hit + version ok：使用缓存
   → Redis miss/stale/error：回源 Session.working_state，再回填 Redis
→ 读取 recent tail
   → Redis hit + last_message_id 覆盖需要范围：使用缓存
   → 否则查 messages 表，再回填 Redis
→ 读取 summary
   → Redis hit + summary_version ok：使用缓存
   → 否则读 Session.running_summary，再回填 Redis
→ Context Gateway 组装上下文
→ route / rewrite / planner / executor / verifier / synthesis
```

### 11.7 写路径流程

working state 更新：

```text
entity/constraints/preference 抽取成功
→ 调用 upsert_* 更新 DB session.working_state
→ working_state_version + 1
→ 写 WorkingStateEvent
→ DB flush/commit 成功
→ 删除或刷新 Redis stm:state
```

推荐首版策略：

```text
state：写 DB 成功后删除 Redis，下一次读回填。
summary：写 DB 成功且质量通过后刷新 Redis。
tail：消息写入 DB 后删除 Redis，Preflight 查询时重建。
```

为什么 state 和 tail 推荐先删缓存？

- 这两个内容对“当前轮”很敏感。
- 删除缓存比主动刷新更不容易产生 DB 回滚后 Redis 残留旧问题。
- 下一次读会从 DB 重建，正确性更稳。

为什么 summary 推荐刷新？

- summary 读多写少。
- summary 更新成本高，更新成功后主动刷新可以减少下一轮 DB 读取。
- 但必须只刷新 last-good summary。

---

## 12. 代码修改计划

### 12.1 新增文件

| 文件 | 作用 |
|---|---|
| `backend/services/chat/stm_cache.py` | STM Redis 业务适配层，封装 state/tail/summary get/refresh/invalidate |
| `backend/tests/test_stm_redis_cache.py` | 单测 payload、版本校验、fallback、TTL 调用 |
| `backend/tests/test_chat_stm_redis_integration.py` | 对话链路级集成测试，验证 Redis 开关、miss、fallback |

### 12.2 修改文件

| 文件 | 修改点 |
|---|---|
| `backend/services/chat/orchestrator.py` | 同步对话 Preflight 前接入 STM cache 读取和 trace meta |
| `backend/services/chat/stream.py` | 流式对话 Preflight 前接入同样逻辑，避免同步/流式行为分叉 |
| `backend/services/chat/skill_pipeline.py` | route 前读取 cached working state；upsert 后触发缓存失效 |
| `backend/services/stm_context_service.py` | 增加 recent tail 快照构建函数，供 Redis 回填复用 |
| `backend/services/stm_summary_runtime.py` | summary 成功写 DB 后刷新 `stm_summary`；失败不刷新 |
| `backend/integrations/redis/metrics.py` | 如现有指标不够，补充 key family 维度或 STM 计数器 |
| `backend/routers/redis_admin.py` | 可选：debug endpoint 展示 STM key family 指标，不展示敏感 value |

### 12.3 不允许修改的文件

| 文件或目录 | 原因 |
|---|---|
| `frontend/dist/` | 构建产物，不手改 |
| `migrations/` | 本阶段不改 DB schema |
| `backend/db/models.py` | 现有字段够用 |
| `Financial-MCP-Agent/src/` | 本阶段接入点在 backend 对话编排 |
| `Reference/` | 只读参考 |

---

## 13. 数据库与契约变更

### 13.1 数据库

本阶段不做数据库迁移。

原因：

- `sessions.working_state` 已能保存三个热字段。
- `sessions.working_state_version` 已能做 state 版本校验。
- `sessions.running_summary` 已能保存 summary 文本。
- `sessions.running_summary_state` 已能保存结构化 summary payload。
- `sessions.summary_version` 已能做 summary 版本校验。
- `messages` 表仍是 recent raw tail 的权威来源。
- `working_state_events` 已能审计字段变更。

### 13.2 API 契约

对外 API 不新增必需字段。

允许在 trace/debug 信息中新增可选字段：

```json
{
  "redis": {
    "stm_state": {
      "cache_hit": true,
      "version_match": true,
      "latency_ms": 0.8
    },
    "stm_tail": {
      "cache_hit": false,
      "fallback_reason": "cache_miss"
    },
    "stm_summary": {
      "cache_hit": true,
      "summary_version": 7
    }
  }
}
```

这些字段不能成为前端主流程依赖。

### 13.3 配置项

优先复用现有配置：

- `REDIS_ENABLED`
- `REDIS_DEFAULT_TTL_SEC`
- `REDIS_TTL_JITTER_RATIO`
- `STM_KEEP_RECENT`

如需要新增配置，建议只新增这些：

| 配置 | 默认值 | 说明 |
|---|---:|---|
| `STM_REDIS_STATE_TTL_SEC` | `1200` | state 热字段 TTL，20 分钟 |
| `STM_REDIS_TAIL_TTL_SEC` | `1200` | recent tail TTL，20 分钟 |
| `STM_REDIS_SUMMARY_TTL_SEC` | `3600` | summary TTL，60 分钟 |
| `STM_REDIS_MAX_TAIL_MESSAGES` | `10` | 最多缓存消息条数，约 5 轮 |
| `STM_REDIS_MAX_MESSAGE_CHARS` | `800` | 单条消息缓存截断长度 |

如果不想增加配置，也可以在 `stm_cache.py` 里先用常量，并在文档注明后续可配置化。

---

## 14. 测试与验证方案

### 14.1 单元测试

新增 `backend/tests/test_stm_redis_cache.py`。

测试点：

| 测试 | 预期 |
|---|---|
| state payload 构建 | 包含三个热字段和版本号 |
| state 版本匹配 | Redis 命中可用 |
| state 版本落后 | 返回 stale/miss，要求回源 DB |
| tail payload 截断 | 单条 content 不超过上限 |
| tail 消息数限制 | 不超过 `STM_REDIS_MAX_TAIL_MESSAGES` |
| summary last-good 判断 | fallback/quality_failed 不写缓存 |
| Redis disabled | 返回 fallback meta，不抛异常 |
| Redis unavailable | 返回 fallback meta，不抛异常 |
| value 过大 | 拒绝写入，并记录 oversize |

### 14.2 集成测试

新增 `backend/tests/test_chat_stm_redis_integration.py`。

测试点：

| 场景 | 验证 |
|---|---|
| Redis 开启 + 首轮对话 | miss 后回源 DB 并回填 |
| Redis 开启 + 第二轮对话 | state/summary 可命中 |
| 用户切换实体 | 旧 `active_entity` 不被使用 |
| Redis 停止 | 对话不 500，回源 DB |
| summary 质量失败 | Redis summary 不刷新 |
| tail 过期 | 回源 messages 表重建 |

### 14.3 手动验收

本地启动：

```bash
cd /root/Finance/docker
docker compose up -d postgres redis pgadmin

cd /root/Finance
source .venv/bin/activate
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

登录后连续发送：

```text
贵州茅台现在估值还贵吗，简单说
那它最近走势怎么样
换成中芯国际，只看A股口径
```

验收：

- 第二轮能继承贵州茅台。
- 第三轮必须切换到中芯国际。
- Redis 里能看到 `stm:state / stm:tail / stm:summary` 相关 key。
- Redis 停止后再次发送问题，后端不崩。

### 14.4 推荐验证命令

```bash
pytest backend/tests/test_stm_redis_cache.py -q
pytest backend/tests/test_chat_stm_redis_integration.py -q
pytest backend/tests/test_redis_*.py -q
python scripts/check_redis_single_chain.py
```

如果启动了后端：

```bash
curl -fsS http://localhost:8000/api/health
curl -fsS http://localhost:8000/api/redis/metrics
```

Redis key 检查：

```bash
docker exec finance_redis redis-cli -a "$REDIS_PASSWORD" --scan --pattern 'finagent:dev:stm:*'
```

注意：只允许检查 key 和 TTL，不要把敏感 value 打到日志或截图里。

---

## 15. 验收证据包

实现完成后，需要留下这些证据：

1. 测试命令输出：
   - `pytest backend/tests/test_stm_redis_cache.py -q`
   - `pytest backend/tests/test_chat_stm_redis_integration.py -q`
   - `pytest backend/tests/test_redis_*.py -q`

2. Redis key 证据：
   - `finagent:dev:stm:state:<user_id>:<session_id>`
   - `finagent:dev:stm:tail:<user_id>:<session_id>`
   - `finagent:dev:stm:summary:<user_id>:<session_id>`
   - `TTL` 均为正数。

3. trace 证据：
   - `cache_key_family=stm_state`
   - `cache_hit=true/false`
   - `version_match=true/false`
   - `fallback_reason=redis_disabled/redis_unavailable/cache_miss/cache_stale`
   - `state_version`
   - `summary_version`

4. 降级证据：
   - 停止 Redis 后，对话接口仍可返回。
   - trace 出现 Redis fallback。

5. 正确性证据：
   - 多轮追问能正确继承主语。
   - 切换标的后不使用旧主语。
   - 用户约束不被旧 summary 覆盖。

---

## 16. 分阶段实施顺序

### 阶段 2.1：新增 STM Redis 业务适配层

先只做 `stm_cache.py` 和单测，不接入主链路。

目标：

- payload 结构稳定。
- 版本校验清楚。
- Redis disabled/unavailable 能 fallback。

### 阶段 2.2：接入 working state 热读

把 state cache 接入 route 前读取和 upsert 后失效。

目标：

- `active_entity / constraints / reply_preference_hint` 可以热读。
- 版本不一致时回源 DB。
- 旧 active entity 不污染新问题。

### 阶段 2.3：接入 recent tail 热读

把 recent raw tail 构建成可缓存快照。

目标：

- Preflight 和 route context 能复用 tail 快照。
- 新消息写入后 tail cache 失效或刷新。
- 不缓存完整历史。

### 阶段 2.4：接入 last-good summary 热读

summary 成功写 DB 后刷新 Redis。

目标：

- Preflight 优先读 Redis summary。
- 质量失败不刷新。
- Redis miss 回源 DB。

### 阶段 2.5：补 trace、指标、集成测试

目标：

- 能看到 hit/miss/fallback/stale。
- 能证明 Redis 挂了不影响对话。
- 能证明 Redis 旧状态被拒绝。

---

## 17. Codex 执行任务拆分

### Task 1：新增 STM Redis cache 服务

**目标**：新增业务适配层，不接主链路。

**允许修改**：

- `backend/services/chat/stm_cache.py`
- `backend/tests/test_stm_redis_cache.py`

**禁止修改**：

- `backend/services/chat/orchestrator.py`
- `backend/services/chat/stream.py`
- `backend/db/models.py`
- `migrations/`
- `frontend/`

**动作**：

- 新增 `STMRedisCache`。
- 定义 state/tail/summary payload 构建和校验函数。
- 调用现有 `CacheService`。
- 添加 Redis disabled/unavailable 单测。

**验证命令**：

```bash
pytest backend/tests/test_stm_redis_cache.py -q
```

**停止条件**：

- 发现 `CacheService` 无法表达版本校验。
- 发现现有 Redis runtime 无法在测试中注入 fake cache。

---

### Task 2：接入 working state 读写失效

**目标**：让三个热字段可以 Redis 热读，并在写后失效。

**允许修改**：

- `backend/services/chat/skill_pipeline.py`
- `backend/services/working_state.py`
- `backend/services/chat/stm_cache.py`
- `backend/tests/test_chat_stm_redis_integration.py`

**禁止修改**：

- `backend/db/models.py`
- `migrations/`
- `frontend/`

**动作**：

- route 前读取 cached state。
- Redis miss/stale/fallback 时使用 `get_working_state(session)`。
- `upsert_active_entity / upsert_constraints / upsert_reply_preference` 后触发 cache invalidation。
- trace 增加 `stm_state_cache_*` 字段。

**验证命令**：

```bash
pytest backend/tests/test_stm_redis_cache.py -q
pytest backend/tests/test_chat_stm_redis_integration.py -q
```

**停止条件**：

- 发现 DB commit 边界不清，可能导致 Redis 写在回滚前。
- 发现同步和流式路径会产生不一致。

---

### Task 3：接入 recent tail 热读

**目标**：recent raw tail 可以通过 Redis 快照热读。

**允许修改**：

- `backend/services/stm_context_service.py`
- `backend/services/chat/orchestrator.py`
- `backend/services/chat/stream.py`
- `backend/services/chat/stm_cache.py`
- `backend/tests/test_chat_stm_redis_integration.py`

**动作**：

- 新增 recent tail 构建函数。
- Preflight 前优先读 `stm_tail`。
- 新消息写入后失效旧 tail。
- 回源 DB 后回填 tail。

**验证命令**：

```bash
pytest backend/tests/test_chat_stm_redis_integration.py -q
```

**停止条件**：

- tail 查询逻辑和现有 Context Gateway 裁剪逻辑冲突。
- 发现缓存 tail 会绕过现有消息权限校验。

---

### Task 4：接入 last-good summary 热读

**目标**：summary 成功压缩后刷新 Redis，Preflight 可热读。

**允许修改**：

- `backend/services/stm_summary_runtime.py`
- `backend/services/chat/stm_cache.py`
- `backend/tests/test_chat_stm_redis_integration.py`

**动作**：

- 在 summary DB 更新成功后刷新 `stm_summary`。
- fallback/quality_failed/schema_failed 不刷新。
- Preflight 读取 summary 时优先尝试 Redis。
- trace 增加 `stm_summary_cache_*` 字段。

**验证命令**：

```bash
pytest backend/tests/test_stm_redis_cache.py -q
pytest backend/tests/test_chat_stm_redis_integration.py -q
```

**停止条件**：

- 发现当前 summary runtime 无法可靠区分 last-good 与 fallback。
- 发现 summary_version 更新存在并发冲突未处理。

---

### Task 5：补观测、降级和回归证据

**目标**：让 Redis 接入可解释、可验收、可面试讲清楚。

**允许修改**：

- `backend/integrations/redis/metrics.py`
- `backend/routers/redis_admin.py`
- `backend/tests/test_redis_*.py`
- `docs/开发计划/Redis集成/Redis集成-第二阶段-STM热状态与上下文热读开发计划.md`

**动作**：

- 补 STM key family 指标。
- 补 Redis 停止后的 fallback 测试。
- 补验收证据记录。

**验证命令**：

```bash
pytest backend/tests/test_redis_*.py -q
pytest backend/tests/test_stm_redis_cache.py -q
pytest backend/tests/test_chat_stm_redis_integration.py -q
python scripts/check_redis_single_chain.py
```

**停止条件**：

- 指标实现需要改动大量现有 trace 结构。
- 测试依赖真实 Redis 且无法稳定在 CI 或本地运行。

---

## 18. 需要用户决策的问题

### 决策 1：state 写后删除缓存，还是主动刷新缓存？

推荐：首版采用“写 DB 成功后删除 Redis，下一次读回填”。

理由：

- 对 `active_entity` 这种高风险字段更稳。
- 避免 DB 回滚但 Redis 已刷新的问题。
- 实现更简单，面试也更好解释。

### 决策 2：recent tail 是否缓存完整原文？

推荐：只缓存最近尾窗的截断文本。

理由：

- 完整消息必须以 DB 为准。
- Redis 不应存大量长文本。
- 截断文本足够用于 Preflight 和 route 局部上下文。

### 决策 3：summary TTL 多长？

推荐：60 分钟。

理由：

- summary 读多写少，可以比 state/tail 长。
- 但它仍然是会话热状态，不适合永久保存。
- 版本校验比 TTL 更重要。

### 决策 4：首版是否做 singleflight？

推荐：首版不强制实现，写进后续增强。

理由：

- 个人项目低并发下，TTL 抖动 + DB 回源足够。
- singleflight 会增加复杂度。
- 面试时可以讲清楚“如果热点 session 变多，会加短 TTL lock 或 request coalescing”。

### 决策 5：项目描述里如何表述？

推荐后续项目描述使用这个口径：

> 在对话模式 STM 中接入 Redis 运行时状态层，将 `active_entity / constraints / reply_preference_hint`、recent raw tail 和 last-good rolling summary 作为短 TTL 热读副本；PostgreSQL 仍保存会话状态、消息、summary 和审计事件。读取时先查 Redis，命中且 `state_version / summary_version / message_id` 校验通过才使用；否则回源 DB 并回填缓存。Redis 异常只影响热读性能，不影响对话主链路。

这个表述不会把 Redis 夸成主数据库，也能体现工程实践。

---

## 19. 面试问题覆盖建议

后续补项目描述和面试问答时，建议覆盖这些问题：

1. 为什么 STM 三个热字段适合 Redis？
2. 为什么 Redis 不能作为短期记忆真相源？
3. `state_version` 和 `summary_version` 分别解决什么问题？
4. 如果 Redis 里是旧的 `active_entity` 怎么办？
5. last-good summary 为什么不能被 fallback summary 覆盖？
6. Redis 挂了以后对话还能不能继续？
7. recent raw tail 和 rolling summary 的职责有什么区别？
8. 为什么不缓存工具调用结果？
9. 缓存穿透、击穿、雪崩在这个项目里怎么体现？
10. Redis 接入收益怎么衡量？

建议回答主线：

> Redis 不是为了让 Agent 更聪明，而是为了让每轮都会读的短生命周期状态更快、更稳定、更可观测。正确性仍由 PostgreSQL、版本号、trace 和回源逻辑保证。

---

## 20. 最终交付定义

本阶段真正完成时，应该满足：

- Redis 关闭：对话可用。
- Redis 开启：state/tail/summary 可命中。
- Redis 旧版本：被拒绝，回源 DB。
- 用户切换实体：不会被旧缓存污染。
- summary 失败：不会覆盖 last-good cache。
- trace 可解释：能看到 hit/miss/stale/fallback。
- 测试可回归：单测和集成测试覆盖主要路径。

只有同时满足这些条件，才能把第二阶段标记为完成。
