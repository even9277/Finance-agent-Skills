# Redis 集成 · 第一阶段（基础设施）优化开发计划

> 本计划只覆盖 Redis 基础设施搭建，不接入任何业务缓存。
> 适用范围：`/root/Finance` Finance 智能投研助手。
> 阅读对象：完全不了解 Redis 的小白 + 后续负责执行落地的 AI（Codex/Cursor/Claude Code）。
> 配套参考文档：
> - 接入定位与未来业务点：`docs/开发计划/Redis集成/Redis集成开发计划目标.md`
> - 开发规范（缓存原则、key、TTL、降级）：`docs/开发规范/Redis集成.md`
> - 项目最高真相源：`docs/项目描述.md`

---

## 0. 一句话总览（先说人话）

我们现在不写任何业务缓存代码。我们只做一件事：

> **在项目里搭好一层"未来谁来用 Redis 都必须走这条统一通道"的基础设施**，包括：Docker Redis 服务、统一连接客户端、统一 Key 生成器、统一 JSON 值结构（带版本号）、统一 TTL 规范、统一健康检查、统一降级路径（Redis 挂了不影响主业务）、统一指标（命中、未命中、回源、超时、错误），并把 Redis 指标接入现有 trace 体系，支持问题定位。

完成之后，你可以亲自启动 PostgreSQL + Redis + 后端 + 前端，在 `/api/health` 看到 Redis 状态，在 `/api/redis/metrics` 和 trace 产物里看到命中率、错误、降级等指标变化，作为本阶段验收。

---

## 1. 背景与目标

### 1.1 背景

项目目前缺少 Redis：
- `backend/requirements.txt` 没有 `redis` 包；
- `docker/docker-compose.yml` 没有 `redis` 服务；
- `backend/config.py` 没有 Redis 相关配置；
- `backend/main.py` 的 `/api/health` 没有 Redis 健康状态。

而项目描述（`docs/项目描述.md` §2688–2738）明确提出三类未来要落到 Redis 的场景：
1. STM 三个热字段（active_entity / constraints / reply_preference_hint）热缓存；
2. recent raw tail / last-good summary 快照热读；
3. 报告任务幂等键 + 状态快照 + SSE 进度推送。

第一阶段不实现以上业务缓存，只把"通道"修通修稳。

### 1.2 目标（本阶段必须完成）

1. **本地能启动一个安全、可控、可降级的 Redis 服务**，并被后端进程稳定连接。
2. **统一 Redis 客户端封装**：连接池、超时、健康检查、异常转换、JSON 序列化、key 前缀。
3. **统一 Key 生成器（KeyBuilder）**：所有 Key 都符合 `finagent:{env}:{module}:{resource}:{...}` 规范；禁止业务代码手拼 Key。
4. **统一缓存值结构（CacheEnvelope）**：JSON + 版本号 + 更新时间 + 来源标记；禁止裸写字符串值。
5. **统一 TTL 策略表**：所有业务 Key 必须有 TTL，禁止永久 Key；TTL 加随机抖动防雪崩。
6. **统一降级**：Redis 不可用时，主链路继续工作（只是没有缓存加速），不抛错给用户。
7. **统一可观测**：最小指标集（hit/miss/fallback/timeout/error/latency）以 in-process 计数器形式暴露，并提供 `/api/redis/metrics` 端点。
8. **接入现有 trace 体系**：Redis 关键事件（命中、未命中、回源、超时、错误、降级原因）必须进入现有 trace 字段，便于后续定位问题。
9. **遗留链路收敛**：先扫描并判定历史 Redis 代码，统一迁移到单一入口，禁止出现两条 Redis 链路并存。
10. **文档化**：本文件 + 一份开发自检 checklist + 一份本地启动操作手册。
11. **健康检查**：`/api/health` 增加 `redis` 字段（`ok` / `disabled` / `degraded`）。
12. **小白可验证**：通过 curl + redis-cli + trace 日志验证命中、TTL、降级与定位信息。

### 1.3 必须随 Redis 一起接入的"门面"

- 一个 FastAPI 健康检查扩展；
- 一个新的小路由 `/api/redis/*`（debug only）；
- `.env` 模板更新；
- `docker-compose.yml` 新增 `redis` 服务并配置 healthcheck；
- 后端 `requirements.txt` 新增 `redis>=5.0`（asyncio 客户端，已内置在 `redis-py`）。

---

## 2. 非目标与必须保持不变的行为

### 2.1 本阶段明确不做

- ❌ 不实现 STM 热状态缓存（active_entity 等三字段）。
- ❌ 不实现 recent tail / last-good summary 缓存。
- ❌ 不实现报告幂等键、状态快照、SSE 推送。
- ❌ 不缓存任何金融行情、工具结果、LLM 响应。
- ❌ 不引入 Redis Cluster / Sentinel / Stream / PubSub。
- ❌ 不做分布式锁实现（保留 API 占位即可，第一阶段不真正调用）。
- ❌ 不动 `chat_service`、`report` 工作流、`memory_service`、`stm_*` 模块任何业务逻辑。
- ❌ 不修改前端业务逻辑，也**不做 Redis 前端演示小面板**。本阶段全部通过 curl + trace + redis-cli 验证。

### 2.2 必须保持不变

- `/api/health` 当前返回结构需向后兼容：在原 `{"status":"ok","version":...}` 基础上**新增字段**，不删除任何已有字段。
- 默认情况下（`REDIS_ENABLED=false`）后端启动行为、性能、所有现有路由响应必须与改动前完全一致。
- 现有所有单元测试和已有 chat / report 主链路功能不能因为本次接入退化。
- 数据库 schema 一行都不动。

---

## 3. 验收标准

完成本阶段后，下列每一项你都能亲手跑出来。

### 3.1 启动验收（基础设施层）

1. `docker compose up -d postgres redis pgadmin` 后：
   - `docker ps` 能看到 `finance_postgres`、`finance_redis`、`finance_pgadmin` 三个容器均 `healthy`；
   - `docker exec finance_redis redis-cli -a $REDIS_PASSWORD ping` 返回 `PONG`。
2. 设置 `REDIS_ENABLED=true` 后启动后端 `uvicorn backend.main:app`：
   - 启动日志包含 `Redis 客户端已初始化` 和 `Redis ping 成功`；
   - `curl http://localhost:8000/api/health` 返回 JSON，含 `"redis": {"status": "ok", "latency_ms": <number>}`。
3. 设置 `REDIS_ENABLED=false` 后启动后端：
   - 启动日志包含 `Redis 已禁用，跳过初始化`；
   - `/api/health` 返回 `"redis": {"status": "disabled"}`；
   - 所有现有路由响应无变化。

### 3.2 降级验收

4. `REDIS_ENABLED=true`，但**停掉** Redis 容器：
   - 后端不崩；
   - `/api/health` 返回 `"redis": {"status": "degraded", "error": "..."}`；
   - `/api/redis/demo/get?key=foo` 不抛 500，返回 `{"data": null, "fallback": true, "reason": "redis_unavailable"}`；
   - 错误计数器 `redis_error_count` / `redis_timeout_count` 在 `/api/redis/metrics` 中增长。

### 3.3 业务规范验收

5. `/api/redis/demo/set` 写一条数据：
   - Redis 中实际 key 的格式必须是 `finagent:dev:demo:item:<id>`；
   - Value 是合法 JSON，包含 `data`、`schema_version`、`updated_at`、`source` 字段；
   - `TTL <key>` 在 redis-cli 中返回正整数（非 `-1`）。
6. 多次 `/api/redis/demo/get?key=<existing>`：
   - 第一次返回 `cache_hit=true`；
   - 命中次数计数器在 `/api/redis/metrics` 中累加。
7. `/api/redis/demo/get?key=<not_exist>`：
   - 返回 `cache_hit=false`；
   - miss 计数累加。

### 3.4 可观测验收

8. `curl http://localhost:8000/api/redis/metrics` 至少返回：
   ```json
   {
     "redis_enabled": true,
     "redis_available": true,
     "counters": {
       "cache_hit": 5,
       "cache_miss": 3,
       "cache_set": 4,
       "cache_delete": 1,
       "cache_fallback": 0,
       "redis_timeout": 0,
       "redis_error": 0
     },
     "latency_ms": {
       "get_p50": 0.4,
       "get_p95": 1.1,
       "set_p50": 0.6,
       "set_p95": 1.5
     }
   }
   ```

### 3.5 Trace 对齐验收

9. 任意一次 `/api/redis/demo/*`（或后续真实调用）后，现有 trace 中必须出现 Redis 字段，至少包含：
   - `redis_enabled`
   - `cache_hit`
   - `cache_key_family`
   - `fallback_reason`（有降级时）
   - `redis_latency_ms`

10. Redis 异常场景（停 Redis 容器）时，trace 中必须可定位到：
   - `redis_status=degraded`
   - `redis_error_type`
   - `redis_fallback=true`

### 3.6 文档与代码规范验收

11. 全仓搜索 `r\.set\(`、`redis\.set\(`、`Redis\(\)` 时，业务代码（除封装层和测试外）**0 处直接调用 Redis 客户端**。
12. 全仓没有手拼裸 Key（如 `f"stm:state:{user_id}"`）；所有 Key 均通过 `KeyBuilder` 生成。
13. 完成“Redis 遗留链路收敛检查报告”：列出扫描范围、命中结果、处理动作（复用/删除/迁移）。
14. 单元测试覆盖：连接池、KeyBuilder、Envelope 序列化、TTL 抖动、降级路径、版本校验。`pytest backend/tests/test_redis_*.py -q` 全部通过。

---

## 4. 项目描述对齐（来自 docs/项目描述.md）

| 来自项目描述的硬约束 | 在本阶段如何兑现 |
|---|---|
| §2690：PostgreSQL 仍是会话状态的权威存储，缓存只是读加速 | 本阶段不提供任何"写入业务真相到 Redis"的能力；`CacheService` 只提供 get/set/delete，不暴露 incr/atomic 计数器作为业务真相 |
| §2692：缓存 value 必须带 `state_version / summary_version / updated_at`，版本不一致直接丢弃 | `CacheEnvelope` 强制带 `schema_version`、`payload_version`(可选)、`updated_at`；`CacheService.get_with_version()` 接口在第一阶段就交付（虽未被业务调用，但单测覆盖） |
| §2702：缓存失败 → 回源 DB；回源失败 → 最小上下文，不中断 | `CacheService.get()` 出错返回 `(None, fallback=True)`；调用方拿到 fallback 时自行决定回源逻辑 |
| §2706：Redis 业务缓存 ≠ prompt cache | 严格分开：本阶段只做"业务/状态缓存通道"，不触碰 LLM prompt cache 配置 |
| §2734：缓存 key 必须包含租户/用户/会话维度，禁止只用 session_id | KeyBuilder 统一格式 `finagent:{env}:{module}:{resource}:{user_id}:{session_id}:...`，缺失维度时编译期/单测期报错 |
| §2736：高并发下 singleflight + 短 TTL 分布式锁 | 本阶段保留接口签名（`CacheService.lock(name, ttl_ms)`），内部用 `SET NX PX` + token 实现最小可用版本，但不在业务中调用 |
| §2738：缓存观测指标 | 本阶段最小指标集已交付，业务接入后只需扩展业务名 |

---

## 5. 当前实现现状（代码层面）

| 关注点 | 现状 | 文件/路径 | 分类 |
|---|---|---|---|
| Redis 服务部署 | 无 | `docker/docker-compose.yml` | **未实现** |
| Redis 遗留代码扫描（backend/agent/frontend） | 已扫描，当前代码层面未发现 Redis 实现 | 扫描范围：`backend/`、`Financial-MCP-Agent/src/`、`frontend/src/` | **已确认（当前无遗留实现）** |
| Redis Python 依赖 | 无 | `backend/requirements.txt` | **未实现** |
| Redis 配置项 | 无 | `backend/config.py` | **未实现** |
| 统一客户端封装 | 无 | `backend/integrations/` | **未实现** |
| Key 命名规范 | 无 | — | **未实现** |
| Value Envelope | 无 | — | **未实现** |
| 健康检查 Redis 字段 | 无 | `backend/main.py:177` | **未实现** |
| 降级路径 | 无 | — | **未实现** |
| 指标 | 无 | — | **未实现** |
| 既有"`docs/开发计划/Redis缓存体系-优化开发计划1.0.md`" | 有完整方案但与目标文档落点不同，且尚未实现 | 同名文件 | 参考但不强约束 |
| 既有"`docs/Redis 与缓存体系.md`" | 给出过 docker-compose 片段和 `redis.asyncio` 示例 | 同名文件 | 可直接复用其 compose 与 client 片段 |

---

## 6. 变更面分析

| 层 | 是否变更 | 变更说明 |
|---|---|---|
| 部署 / Docker | ✅ 变 | `docker/docker-compose.yml` 新增 `redis` 服务 + volume + healthcheck |
| 后端依赖 | ✅ 变 | `backend/requirements.txt` 新增 `redis>=5.0`（async 客户端已包含） |
| 后端配置 | ✅ 变 | `backend/config.py` 新增 `REDIS_*` 字段 + 开关 |
| 后端代码 | ✅ 新增 | `backend/integrations/redis/` 新目录（client / key_builder / envelope / metrics / cache_service） |
| 后端路由 | ✅ 新增 | `backend/routers/redis_admin.py`（仅用于后端验证与排障，不做前端演示面板） |
| 后端 main.py | ✅ 微改 | `lifespan` 加 Redis 启停；`/api/health` 加 redis 字段；条件挂载 debug router |
| 数据库 / Schema | ❌ 不变 | 一行不动 |
| Agent runtime | ❌ 不变 | 完全不引入 |
| 前端 | ❌ 不变 | 本阶段明确不做任何 Redis 前端演示面板 |
| 测试 | ✅ 新增 | `backend/tests/test_redis_*.py` 覆盖封装层 |
| 文档 | ✅ 新增 | 本文件 + 启动手册 + 开发自检 checklist |

---

## 7. 差距与风险

| 风险 | 影响 | 应对 |
|---|---|---|
| Redis 容器未启动时后端崩溃 | 阻断所有现有业务 | `REDIS_ENABLED=false` 默认值；启动时 `RedisClient.connect()` 异常不抛到 lifespan，只记录降级 |
| Redis 启用但密码错误 | 后端持续报错 | 启动时一次 ping，失败 → `redis_available=false`，进入降级模式 |
| 业务代码绕开封装直接写 Redis | 后期不可控 | 单测：用 grep 检查 `import redis` 出现的非允许路径；CI lint hook（本阶段写成 shell 脚本，先不强制阻断） |
| Key 命名漂移 | 难以排障 | KeyBuilder 单元测试覆盖所有未来模块（stm / report / lock），即使未实现 |
| TTL 永久 key | 内存膨胀 | `CacheService.set()` 强制要求 `ttl_seconds` 参数；为 0 / None / 负数时抛 `ValueError` |
| 缓存敏感数据 | 隐私泄露 | 日志中 value 永不打印；只打印 key 前缀 + size；本阶段也不提供 raw value debug 端点（除非开启 `REDIS_DEBUG_ENDPOINTS_ENABLED`） |
| Redis 重启数据丢失 | 进度类数据短期不可用 | 本阶段 Redis **关闭持久化**（开发够用）；生产再切到 AOF + RDB |
| 测试时污染本地 Redis | 影响其它实验 | 默认连接 `db=0`，测试用 `db=15` 并在 setUp/tearDown 调 `FLUSHDB`（仅限测试 namespace） |

---

## 8. 本地优秀 Agent 实践参考

经过对 `Reference/openclaw/`、`Reference/cc-haha/`、`Reference/hermes-agent/`、`Reference/traveling-agent/` 的查阅，**没有发现直接可复用的 Redis 业务缓存封装**——这些项目主要做的是 prompt cache、session cache、文件 cache。结论：

- **不直接复用**：因为我们的目标是"业务运行时状态层"，而本地参考都是"模型 prompt 缓存"，关注点不同。
- **可吸收的工程思想**：
  - openclaw `cache-trace.ts` → 缓存命中要在 trace 里有字段（我们已经写进项目描述 §2738，本阶段在 metrics 里先体现）；
  - cc-haha `cachedMicrocompact.ts` → 缓存 key 与"逻辑版本号"绑定（对应我们的 `schema_version`）；
  - traveling-agent `差旅出行助手Agent.md` 提到的"redis 中的列表，保存最近10轮对话" → 我们刻意**反向**——recent tail 用 Redis 也要先经过 KeyBuilder + Envelope，不允许直接 LPUSH。

---

## 9. 外部开源与官方实践参考（强烈建议复用）

> AI 在落地时，请优先按下列顺序复用代码片段，不要凭空造轮子。

| 用途 | 推荐来源 | 复用方式 |
|---|---|---|
| Python Redis 异步客户端 | `redis-py` 官方 ≥5.0 (https://redis.readthedocs.io/en/stable/connections.html) | 直接 `from redis.asyncio import Redis, ConnectionPool`；用 `Redis.from_url()`；`max_connections` / `socket_timeout` / `socket_connect_timeout` / `health_check_interval` 全部配置 |
| 连接池最佳实践 | `redis-py` ConnectionPool 文档 | 全局单例池；FastAPI lifespan 启动时 `await client.ping()`；关闭时 `await client.aclose()` |
| Cache-Aside 模式 | Microsoft Learn https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside | `CacheService.get_or_load(key, loader, ttl)` 的语义来自此处；本阶段只交付 API，不在业务中触发 |
| Redis 安全配置 | https://redis.io/docs/latest/operate/oss_and_stack/management/security/ | docker compose 中 `--requirepass`；不暴露 6379 到 0.0.0.0；ACL 留作生产再说 |
| FastAPI 健康检查模式 | FastAPI 官方文档 + `fastapi-health` 库 | 不引入 `fastapi-health`，自己写 `/api/health` 扩展，避免增加无谓依赖 |
| FastAPI 缓存库 | `fastapi-cache2` (https://github.com/long2ice/fastapi-cache) | **不引入**。原因：我们要的是显式 KeyBuilder + Envelope + 版本号，`fastapi-cache2` 的装饰器路线和"endpoint 自动缓存"语义不匹配。但其 backend 抽象设计可借鉴 |
| Redis 分布式锁 | `redis-py` 官方 `Lock` 类（基于 `SET NX PX` + token） | 本阶段封装 `CacheService.lock()` 接口签名，实现内部直接调用 `redis.lock(name, timeout=..., blocking_timeout=...)`，不引入 `redlock-py` |
| 指标采集 | 自实现的 in-process counter，**不引入 Prometheus client** | 第一阶段不引入额外依赖；用 dict + asyncio.Lock 即可；后续接 Prometheus 时只需替换 `MetricsCollector` 内部实现 |
| TTL 抖动 | Microsoft Learn Cache-Aside 文档明确建议；Redis Labs Best Practices 文章 | `ttl = base_ttl + random.randint(-jitter, +jitter)` |
| Pydantic 配置 | `pydantic-settings` 项目已有，复用现有 `Settings` 类 | 新增字段全部走 `Settings` |
| Docker Compose Redis | https://hub.docker.com/_/redis 官方镜像 + docker-compose 健康检查样例 | `image: redis:7.2-alpine`；`healthcheck: redis-cli ping` |

**关键复用代码片段（落地时直接抄）**：

```python
# 来自 redis-py 官方文档
from redis.asyncio import Redis, ConnectionPool

pool = ConnectionPool.from_url(
    "redis://:password@localhost:6379/0",
    max_connections=20,
    socket_timeout=0.5,
    socket_connect_timeout=0.5,
    health_check_interval=30,
    decode_responses=True,
)
client = Redis(connection_pool=pool)
await client.ping()
```

```yaml
# 来自 redis 官方镜像 README + 我们项目已有 compose 风格
redis:
  image: redis:7.2-alpine
  container_name: finance_redis
  restart: unless-stopped
  command: ["redis-server", "--requirepass", "${REDIS_PASSWORD}", "--maxmemory", "256mb", "--maxmemory-policy", "allkeys-lru"]
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
  healthcheck:
    test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
    interval: 10s
    timeout: 3s
    retries: 5
```

---

## 10. 实现策略选择

| 能力 | 策略 | 理由 |
|---|---|---|
| Redis 客户端连接 | **复用官方 redis-py asyncio** | 业界标准，无需自造；项目已是 async FastAPI |
| 连接池 | **复用官方 ConnectionPool** | 不重复造池子 |
| KeyBuilder | **新增模块** | 本仓库无现成；逻辑极简 |
| CacheEnvelope | **新增模块** | 必须，且要 Pydantic 强类型 |
| 健康检查 | **本地小重构** | 在现有 `/api/health` 上扩展字段 |
| 分布式锁 | **复用 redis-py 内置 `Lock`** | 不引入 redlock-py |
| 指标 | **新增极简 in-process collector** | 第一阶段不引 prometheus_client，但接口预留 |
| 降级 | **新增装饰器/异常映射** | 必须，且与未来业务接入解耦 |
| Debug 端点 | **新增独立 router**，开关控制 | 验证用，生产关掉 |
| 前端集成 | **延后** | 第一阶段以 curl 验证即可 |

---

## 11. 目标架构与实现方案

### 11.1 文件目录（最终形态）

```
backend/
├── integrations/
│   └── redis/
│       ├── __init__.py          # 对外导出：RedisClient/CacheService/KeyBuilder/CacheEnvelope/get_metrics
│       ├── client.py            # RedisClient：连接池、ping、close、底层 get/set/delete/exists/ttl
│       ├── key_builder.py       # KeyBuilder：所有 key 通过这里生成
│       ├── envelope.py          # CacheEnvelope (Pydantic)：data/schema_version/updated_at/source/payload_version
│       ├── cache_service.py     # CacheService：业务侧唯一入口，JSON+Envelope+TTL+降级+指标
│       ├── metrics.py           # MetricsCollector：计数器 + 简易 P50/P95
│       ├── exceptions.py        # CacheUnavailable / CacheVersionMismatch
│       └── lock.py              # 包一层 redis-py Lock（本阶段不被业务调用）
├── routers/
│   └── redis_admin.py           # /api/redis/health, /api/redis/metrics, /api/redis/demo/*（debug 开关控制）
├── config.py                    # 新增 REDIS_* 字段
├── main.py                      # lifespan 启动/关闭 Redis；/api/health 扩展；条件挂载 redis_admin
└── tests/
    ├── test_redis_client.py
    ├── test_redis_key_builder.py
    ├── test_redis_envelope.py
    ├── test_redis_cache_service.py
    ├── test_redis_metrics.py
    └── test_redis_health_endpoint.py
```

### 11.2 关键设计

#### 11.2.1 KeyBuilder

```python
# 伪代码（落地时按此实现）
class KeyBuilder:
    """
    所有 Redis Key 的唯一生成入口。
    格式：finagent:{env}:{module}:{resource}:{...}
    其中 env 来自 settings.app_env（dev/test/prod）。
    """
    NAMESPACE = "finagent"

    def __init__(self, env: str):
        self.env = env

    def stm_state(self, user_id: str, session_id: str) -> str:
        return f"{self.NAMESPACE}:{self.env}:stm:state:{user_id}:{session_id}"

    def stm_tail(self, user_id: str, session_id: str) -> str: ...
    def stm_summary(self, user_id: str, session_id: str) -> str: ...
    def report_idempotency(self, user_id: str, stock_code: str, query_hash: str) -> str: ...
    def report_status(self, task_id: str) -> str: ...
    def lock(self, name: str) -> str: ...
    def demo(self, item_id: str) -> str:
        return f"{self.NAMESPACE}:{self.env}:demo:item:{item_id}"
```

> 本阶段只需要 `demo()` 被业务（debug 路由）真实使用，其他方法是为未来业务**预占**，但**必须有单元测试覆盖**它们的输出字符串。

#### 11.2.2 CacheEnvelope

```python
class CacheEnvelope(BaseModel):
    data: Any
    schema_version: int          # envelope schema 版本，本阶段固定为 1
    payload_version: int | None  # 业务版本号（如 state_version、summary_version），可选
    updated_at: str              # ISO8601
    source: str                  # "db_snapshot" / "runtime_event" / "demo"
    expire_at: str | None        # 提示性，非强制（TTL 由 Redis 控制）
```

#### 11.2.3 CacheService 公开 API（本阶段全部交付）

```python
class CacheService:
    async def get(self, key: str) -> tuple[CacheEnvelope | None, dict]: ...
    async def get_with_version(self, key: str, expected_payload_version: int) -> tuple[CacheEnvelope | None, dict]: ...
    async def set(
        self,
        key: str,
        data: Any,
        ttl_seconds: int,
        source: str,
        payload_version: int | None = None,
        ttl_jitter_ratio: float = 0.1,
    ) -> dict: ...
    async def delete(self, key: str) -> dict: ...
    async def ping(self) -> bool: ...
    def lock(self, name: str, ttl_ms: int): ...   # 返回 async context manager
```

返回的 `dict` 是 trace 友好的元信息：`{"cache_hit": True, "latency_ms": 0.6, "fallback": False, "version_match": True}`。

#### 11.2.4 降级语义（极重要）

- Redis **未启用**（`REDIS_ENABLED=false`）：所有 `get/set/delete` 直接返回 `(None, {"fallback": True, "reason": "redis_disabled"})`，**不抛异常**。
- Redis **启用但 ping 失败**：标记 `redis_available=false`；后续 N 秒内 `get/set` 直接走降级，不发起真实 socket 调用（避免雪崩）；定时探活（每 30s 一次）。
- 单次操作超时：返回 `fallback=True, reason="redis_timeout"`，计数 `+1`，**不抛异常给业务**。

#### 11.2.5 健康检查扩展

```python
# /api/health 改为：
{
  "status": "ok",
  "version": "1.2.0",
  "redis": {
    "status": "ok" | "disabled" | "degraded",
    "latency_ms": 0.5,
    "error": "...optional"
  }
}
```

#### 11.2.6 配置项（追加到 `Settings`）

| 字段 | 默认值 | 说明 |
|---|---|---|
| `redis_enabled` | `False` | 总开关；关闭后整个 Redis 子系统无副作用 |
| `redis_url` | `"redis://localhost:6379/0"` | 标准连接串 |
| `redis_password` | `""` | 由 docker compose 注入 |
| `redis_namespace_env` | `"dev"` | KeyBuilder 中的 env 段 |
| `redis_socket_timeout_ms` | `500` | 单次读写超时 |
| `redis_connect_timeout_ms` | `500` | 建连超时 |
| `redis_max_connections` | `20` | 池大小 |
| `redis_health_check_interval_sec` | `30` | redis-py 自带的连接级心跳 |
| `redis_default_ttl_sec` | `1800` | 业务未指定时的兜底 TTL |
| `redis_ttl_jitter_ratio` | `0.1` | TTL 抖动比例 |
| `redis_debug_endpoints_enabled` | `False` | 是否挂载 `/api/redis/demo/*` |
| `redis_metrics_endpoint_enabled` | `True` | 是否暴露 `/api/redis/metrics` |
| `redis_unavailable_recheck_sec` | `30` | 探活间隔 |

---

## 12. 代码修改计划（逐文件）

| # | 文件 | 动作 | 关键内容 |
|---|---|---|---|
| 1 | `backend/requirements.txt` | 修改 | 新增 `redis>=5.0,<6` |
| 2 | `backend/.env.example` | 新建/修改 | 增加 `REDIS_*` 模板 |
| 3 | `backend/config.py` | 修改 | 加入 §11.2.6 全部字段 |
| 4 | `backend/integrations/redis/__init__.py` | 新建 | 导出公共符号 |
| 5 | `backend/integrations/redis/client.py` | 新建 | RedisClient（连接池、ping、close） |
| 6 | `backend/integrations/redis/key_builder.py` | 新建 | KeyBuilder |
| 7 | `backend/integrations/redis/envelope.py` | 新建 | CacheEnvelope (Pydantic) |
| 8 | `backend/integrations/redis/cache_service.py` | 新建 | CacheService（业务唯一入口） |
| 9 | `backend/integrations/redis/metrics.py` | 新建 | MetricsCollector |
| 10 | `backend/integrations/redis/exceptions.py` | 新建 | CacheUnavailable / CacheVersionMismatch |
| 11 | `backend/integrations/redis/lock.py` | 新建 | 薄封装 redis-py Lock |
| 12 | `backend/routers/redis_admin.py` | 新建 | `/api/redis/health`、`/api/redis/metrics`、`/api/redis/demo/set\|get\|delete` |
| 13 | `backend/main.py` | 修改 | lifespan 启停 Redis；`/api/health` 扩展；条件挂载 `redis_admin.router` |
| 14 | `backend/middleware/auth.py` | 修改 | 把 `/api/redis/health`、`/api/redis/metrics` 加入白名单（可选：demo 路由要求登录） |
| 15 | `docker/docker-compose.yml` | 修改 | 新增 `redis` 服务、`redis_data` volume；backend `depends_on` 增加 redis |
| 16 | `backend/tests/test_redis_*.py` | 新建 | 单测 + 集成测试 |
| 17 | `docs/开发计划/Redis集成/Redis集成-第一阶段-本地启动手册.md` | 新建 | 给小白用的"复制粘贴就能跑"操作步骤（本计划之外的配套文档，由本计划 §17 任务产出） |
| 18 | `docs/开发计划/Redis集成/Redis集成-第一阶段-自检 checklist.md` | 新建 | 验收清单，配合 §3 使用 |

---

## 13. 数据库与契约变更

- **数据库**：无任何变更。
- **API 契约**：
  - `/api/health` 响应**新增** `redis` 字段（向后兼容，老字段不删）。
  - 新增三个 debug-only 路由（默认关闭）：
    - `GET /api/redis/health` → `{"redis": {...}}`（与 `/api/health` 中 redis 字段一致）
    - `GET /api/redis/metrics` → 见 §3.4
    - `POST /api/redis/demo/set` → body `{"id": "...", "data": {...}, "ttl_seconds": 60}`
    - `GET /api/redis/demo/get?key=<id>` → 返回 envelope + cache_hit
    - `DELETE /api/redis/demo/delete?key=<id>` → ok
- **前端契约**：无影响。

---

## 14. 测试与验证方案

### 14.1 单元测试（pytest，使用 `fakeredis` 或真实 Redis）

> 推荐使用 `fakeredis>=2.20`（开发依赖，不进生产 requirements），避免 CI 必须有 Redis。

| 测试文件 | 用例 |
|---|---|
| `test_redis_key_builder.py` | 所有 KeyBuilder 方法输出字符串格式正确；env 改变后 key 也变；缺失必填参数抛错 |
| `test_redis_envelope.py` | Envelope 序列化/反序列化；缺字段报错；payload_version 可选；updated_at 自动填充 |
| `test_redis_client.py` | ping 成功；ping 失败时 `redis_available=False`；close 不抛错；连接池 reuse |
| `test_redis_cache_service.py` | get miss → fallback=False, data=None；set 后 get → hit；TTL 实际生效（≤ base+jitter）；version mismatch → 返回 None 且计数；ttl=0 → ValueError |
| `test_redis_metrics.py` | 计数自增；P50/P95 计算；reset 工作 |
| `test_redis_health_endpoint.py` | `/api/health` 在 enabled/disabled/degraded 三态下返回正确 |
| `test_redis_lock.py` | 同一 key 并发只能拿到一个；超时自动释放 |
| `test_redis_admin_router.py` | demo set/get/delete 流程；权限：开关关闭时返回 404 |

### 14.2 集成测试（真实 Redis）

- 启动 docker-compose 后跑 `pytest -m integration`；
- 用例覆盖：set → get → ttl 倒计时 → 过期后 miss。

### 14.3 手动验收脚本（小白可复制粘贴）

```bash
# 1) 启动
cd /root/Finance
docker compose -f docker/docker-compose.yml up -d postgres redis pgadmin
docker exec finance_redis redis-cli -a finance_redis_123 ping       # 期望 PONG

# 2) 编辑 backend/.env，开启
echo "REDIS_ENABLED=true"                                  >> backend/.env
echo "REDIS_URL=redis://:finance_redis_123@localhost:6379/0" >> backend/.env
echo "REDIS_NAMESPACE_ENV=dev"                             >> backend/.env
echo "REDIS_DEBUG_ENDPOINTS_ENABLED=true"                  >> backend/.env

# 3) 启后端
source .venv/bin/activate
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# 4) 健康检查
curl -s http://localhost:8000/api/health | jq .
# 期望：{"status":"ok","version":"...","redis":{"status":"ok","latency_ms":...}}

# 5) 写入一条 demo
curl -s -X POST http://localhost:8000/api/redis/demo/set \
  -H 'Content-Type: application/json' \
  -d '{"id":"hello","data":{"msg":"world"},"ttl_seconds":60}'

# 6) 读取
curl -s "http://localhost:8000/api/redis/demo/get?key=hello" | jq .
# 期望 cache_hit=true

# 7) 看真实 key
docker exec finance_redis redis-cli -a finance_redis_123 KEYS 'finagent:dev:demo:*'
# 期望：finagent:dev:demo:item:hello

# 8) 看 TTL
docker exec finance_redis redis-cli -a finance_redis_123 TTL finagent:dev:demo:item:hello
# 期望：正整数

# 9) 看指标
curl -s http://localhost:8000/api/redis/metrics | jq .

# 10) 关掉 redis 看降级
docker stop finance_redis
curl -s http://localhost:8000/api/health | jq .                  # status:"degraded"
curl -s "http://localhost:8000/api/redis/demo/get?key=hello" | jq .  # fallback:true
curl -s http://localhost:8000/api/redis/metrics | jq .           # redis_error_count++
```

---

## 15. 验收证据包

落地完成后，请保留以下证据（截图或终端日志）到 `docs/开发计划/Redis集成/第一阶段验收证据/`：

1. `docker compose ps`（postgres + redis + pgadmin 全 healthy）。
2. `curl /api/health` 在三种状态（ok / disabled / degraded）下的 JSON 各一份。
3. demo set / get / delete 完整往返日志。
4. `redis-cli KEYS 'finagent:dev:*'` 输出。
5. `redis-cli TTL <key>` 输出。
6. `curl /api/redis/metrics` 在 0 调用、若干调用、Redis 宕机三种状态下输出各一份。
7. trace 证据：正常命中与降级两种情况下的 trace 片段各一份（含 `cache_hit`、`fallback_reason`、`redis_latency_ms`）。
8. `pytest backend/tests/test_redis_*.py -v` 通过截图（≥ 25 个用例全绿）。
9. 单链路校验证据：`python scripts/check_redis_single_chain.py` 输出通过。

---

## 16. 分阶段实施顺序（粒度 = 一个 Codex 任务）

> 强烈建议**严格按顺序执行**，每完成一步先跑一次 §3 对应的验证，绿了再走下一步。

| 阶段 | 名称 | 主要交付 | 完工标志 |
|---|---|---|---|
| 0 | 准备 | 阅读本计划 + `Redis集成开发计划目标.md` + `开发规范/Redis集成.md` | 能口述本阶段目标 |
| 1 | 依赖与配置 | requirements.txt 加 redis；config.py 加 REDIS_*；`.env.example` 加模板 | `pip install -r` 通过；`python -c "from backend.config import settings; print(settings.redis_enabled)"` 输出 False |
| 1.5 | 遗留链路收敛 | 输出 Redis 遗留扫描报告；确认单链路 | `Redis遗留扫描报告.md` 存在，且单链路校验通过 |
| 2 | docker-compose | 加 redis 服务、volume、healthcheck | `docker compose up -d redis` + `redis-cli ping`=PONG |
| 3 | 客户端 + KeyBuilder + Envelope + Exceptions | 4 个新文件 + 对应单测 | `pytest backend/tests/test_redis_{client,key_builder,envelope}.py -v` 全绿 |
| 4 | Metrics | 1 个新文件 + 单测 | `test_redis_metrics.py` 全绿 |
| 5 | CacheService + Lock | 2 个新文件 + 单测 | `test_redis_cache_service.py`、`test_redis_lock.py` 全绿 |
| 6 | main.py 集成 + /api/health 扩展 | lifespan 启停；health 扩展 | `curl /api/health` 三态正确 |
| 7 | redis_admin router | 新增 router + 开关；middleware 白名单 | demo set/get/delete 跑通 |
| 8 | 集成测试 + 手动验收 | 跑通 §14.3 全部 10 步 | 截图归档到 §15 |
| 9 | 收尾文档 | 启动手册 + 自检 checklist | 两份新文档完成 |

---

## 17. Codex 执行任务拆分（每个任务都可独立执行）

> 每条任务都自带：目标、允许改的文件、禁止改的文件、动作、验证、停止条件、证据。
> AI 在执行下一条任务前必须先确认上一条所有验证通过。

### Task 1 · 依赖与基础配置

- **目标**：在不改任何业务代码的前提下，让仓库具备 Redis 配置能力。
- **允许修改**：
  - `backend/requirements.txt`
  - `backend/config.py`
  - `backend/.env.example`（若无则新建）
- **禁止修改**：任何其他文件。
- **动作**：
  1. `requirements.txt` 追加 `redis>=5.0,<6`。
  2. `config.py` 追加 §11.2.6 列出的所有 `redis_*` 字段（默认值见表）。
  3. `backend/.env.example` 增加示例：
     ```
     REDIS_ENABLED=false
     REDIS_URL=redis://localhost:6379/0
     REDIS_PASSWORD=
     REDIS_NAMESPACE_ENV=dev
     REDIS_DEBUG_ENDPOINTS_ENABLED=false
     REDIS_METRICS_ENDPOINT_ENABLED=true
     ```
- **验证**：
  ```
  pip install -r backend/requirements.txt
  python -c "from backend.config import settings; assert settings.redis_enabled is False; print('ok')"
  ```
- **停止条件**：任何字段类型校验失败；其他模块 import settings 报错。
- **证据**：终端输出 `ok`。

### Task 1.5 · Redis 遗留链路盘点与收敛（禁止双链路）

- **目标**：确保仓库内只保留一条 Redis 实现链路（统一走 `backend/integrations/redis/*`）。
- **允许修改**：
  - `backend/**`、`Financial-MCP-Agent/src/**`、`frontend/src/**`（仅删除/替换 Redis 相关遗留代码时）
  - `docs/开发计划/Redis集成/Redis遗留扫描报告.md`（新建）
- **禁止修改**：任何与 Redis 无关业务逻辑。
- **动作**：
  1. 全仓扫描 Redis 关键字与直接客户端调用；
  2. 分类每个命中项：`复用` / `迁移` / `删除`；
  3. 若存在历史 Redis 封装，统一迁移到 `backend/integrations/redis/*`；
  4. 输出 `Redis遗留扫描报告.md`，包含扫描命令、命中位置、处理结论；
  5. 在 CI 校验脚本中增加“禁止业务层直接 import redis”检查。
- **验证**：
  ```
  # 允许路径仅限 backend/integrations/redis 和 tests
  python scripts/check_redis_single_chain.py
  ```
- **停止条件**：发现多条 Redis 链路且无法在当前任务收敛时，立即停下并提用户决策。
- **证据**：`Redis遗留扫描报告.md` + 校验脚本通过输出。

### Task 2 · docker-compose 增加 Redis 服务

- **目标**：本地 `docker compose up -d redis` 可用。
- **允许修改**：`docker/docker-compose.yml`。
- **禁止修改**：其他 compose / Dockerfile。
- **动作**：
  1. 加 `redis` service（参考 §9 给的 YAML）；
  2. 加 `redis_data` volume；
  3. `backend.depends_on` 增加 `redis: { condition: service_healthy }`（**但** 设为可选；本阶段后端无强依赖，故只加 `service_started` 即可，避免 redis 异常阻塞后端启动）。
- **验证**：
  ```
  docker compose -f docker/docker-compose.yml up -d redis
  docker exec finance_redis redis-cli -a "$REDIS_PASSWORD" ping
  ```
- **停止条件**：端口冲突、镜像拉取失败、健康检查持续失败。
- **证据**：`PONG` 输出 + `docker compose ps` 截图。

### Task 3 · RedisClient + KeyBuilder + Envelope + Exceptions

- **目标**：交付 4 个核心模块和单测。
- **允许修改/新建**：
  - `backend/integrations/redis/__init__.py`
  - `backend/integrations/redis/client.py`
  - `backend/integrations/redis/key_builder.py`
  - `backend/integrations/redis/envelope.py`
  - `backend/integrations/redis/exceptions.py`
  - `backend/tests/test_redis_client.py`
  - `backend/tests/test_redis_key_builder.py`
  - `backend/tests/test_redis_envelope.py`
- **禁止修改**：`backend/services/*`、`backend/routers/*`、`backend/main.py`。
- **动作**：
  - 按 §11.2.1 / 11.2.2 实现；
  - `RedisClient` 使用 `redis.asyncio.Redis.from_url` + `ConnectionPool`；
  - 必须暴露 `is_available()`、`connect()`、`close()`、`ping()`；
  - 单测使用 `fakeredis.aioredis.FakeRedis` 注入。
- **验证**：
  ```
  pytest backend/tests/test_redis_client.py backend/tests/test_redis_key_builder.py backend/tests/test_redis_envelope.py -v
  ```
- **停止条件**：`fakeredis` 安装失败 → 使用真实 redis；任何用例失败。
- **证据**：单测全绿截图。

### Task 4 · Metrics

- **目标**：交付 MetricsCollector + 单测。
- **允许修改/新建**：`backend/integrations/redis/metrics.py`、`backend/tests/test_redis_metrics.py`。
- **动作**：实现 in-process 计数器（`Counter`、`Histogram[P50/P95]`），线程/协程安全；提供 `snapshot()`、`reset()`。
- **验证**：`pytest backend/tests/test_redis_metrics.py -v` 全绿。
- **停止条件**：性能明显异常（单次 record 超过 1ms）。
- **证据**：单测输出。

### Task 5 · CacheService + Lock

- **目标**：交付业务唯一入口 + 锁封装 + 单测。
- **允许修改/新建**：`backend/integrations/redis/cache_service.py`、`backend/integrations/redis/lock.py`、`backend/tests/test_redis_cache_service.py`、`backend/tests/test_redis_lock.py`。
- **动作**：
  - `CacheService` 内部持有 `RedisClient + KeyBuilder + MetricsCollector`；
  - `set(...)` 内部用 `await client.set(key, json.dumps(envelope.model_dump()), ex=ttl_seconds_with_jitter)`；
  - `get(...)` 内部 `await client.get(key)` → 反序列化 Envelope；异常 → 计数 + fallback；
  - `lock(...)` 直接 `client.lock(self.key_builder.lock(name), timeout=ttl_ms/1000)`。
- **验证**：单测全绿；并发锁测试通过。
- **停止条件**：TTL 抖动后超出 [base*0.9, base*1.1]；序列化失败时未正确 fallback。
- **证据**：单测输出。

### Task 6 · main.py 集成 + /api/health 扩展

- **目标**：后端启动时按开关初始化 Redis；health 增加 redis 字段。
- **允许修改**：`backend/main.py`、`backend/middleware/auth.py`（仅白名单列表）。
- **禁止修改**：除上述外的业务文件。
- **动作**：
  1. 在 `app` 的 `lifespan`（如无则新建）中：
     - 启动时若 `settings.redis_enabled` → 创建全局 `RedisClient` 单例 + `await client.connect()` + ping；失败仅日志降级；
     - 关闭时 `await client.close()`。
  2. `/api/health` 改为：
     ```python
     redis_info = {"status": "disabled"}
     if settings.redis_enabled:
         redis_info = await get_redis_health_snapshot()  # ok / degraded + latency_ms
     return {"status": "ok", "version": settings.app_version, "redis": redis_info}
     ```
  3. middleware 白名单加入 `/api/redis/health`、`/api/redis/metrics`（demo 路由要求登录可选）。
- **验证**：
  - `REDIS_ENABLED=false` 启动 → `/api/health` 含 `"redis":{"status":"disabled"}`；
  - `REDIS_ENABLED=true` + Redis 已起 → `"redis":{"status":"ok","latency_ms":...}`；
  - `REDIS_ENABLED=true` + 停止 redis 容器 → `"redis":{"status":"degraded","error":"..."}`。
- **停止条件**：默认 `REDIS_ENABLED=false` 启动后任意现有路由响应变化。
- **证据**：三种状态的 curl 输出。

### Task 7 · redis_admin Router

- **目标**：交付 `/api/redis/health`、`/api/redis/metrics`、`/api/redis/demo/{set,get,delete}`，并由 `REDIS_DEBUG_ENDPOINTS_ENABLED` 控制是否挂载。
- **允许修改/新建**：`backend/routers/redis_admin.py`、`backend/main.py`（仅挂载逻辑）、`backend/tests/test_redis_admin_router.py`。
- **动作**：
  - `redis_admin` 内部用全局 `CacheService` 单例；
  - `demo/set` 接收 `{id, data, ttl_seconds}`，调用 `cache_service.set(key_builder.demo(id), data, ttl_seconds, source="demo")`；
  - `demo/get?key=<id>` 调用 `cache_service.get(key_builder.demo(id))`，返回 envelope + meta；
  - `demo/delete?key=<id>` 调用 `cache_service.delete(...)`；
  - 任何 endpoint 在 `redis_enabled=False` 时返回 `503 {"error":"redis_disabled"}`；
  - 整个 router 只在 `redis_debug_endpoints_enabled=True` 时挂载。
- **验证**：§14.3 手动脚本第 5–9 步全部通过；单测覆盖开关关/开两种挂载状态。
- **停止条件**：路由在生产默认配置下被错误暴露。
- **证据**：手动脚本输出 + 单测绿。

### Task 8 · 集成测试 + 手动验收 + 文档

- **目标**：完成 §14.2 集成测试 + §14.3 手册执行 + §17 末两份配套文档。
- **允许修改/新建**：
  - 测试：`backend/tests/test_redis_integration.py`（标记 `@pytest.mark.integration`）；
  - 文档：`docs/开发计划/Redis集成/Redis集成-第一阶段-本地启动手册.md`、`docs/开发计划/Redis集成/Redis集成-第一阶段-自检 checklist.md`。
- **动作**：
  - 集成测试：启 docker redis；跑 set→get→等待 ttl→get 应 miss；
  - 启动手册：把 §14.3 内容整理成"零基础也能照抄"形式；
  - 自检 checklist：对应 §3 每一条加一个空 ☐。
- **验证**：`pytest -m integration backend/tests/test_redis_integration.py -v` 全绿；两份文档可读。
- **停止条件**：集成测试因 docker 不可用失败 → 标注为 skip 并说明前置条件。
- **证据**：测试通过 + 文档存在。

---

## 18. 风险预案与未来接入"陷阱预案"

> 这一节专门列出"将来真正接入 STM / report 业务时最容易踩的坑"，并在本阶段就把"防御点"内建到封装里。

### 18.1 缓存与数据库一致性

- **风险**：未来 STM 写库成功 → 写 Redis 失败 → Redis 留旧值；下次读拿到旧值。
- **本阶段防御**：
  - `CacheService.set()` 失败时**不抛错**，但**返回 `success=False`**，让调用方能够选择"删 key 而非保留旧值"。
  - 提供 `cache_service.delete()` 作为推荐的"写 DB 后失效缓存"动作（业务接入时优先用 `delete`，不要 `set` 覆盖）。

### 18.2 缓存击穿

- **风险**：热 key 过期瞬间，多个请求同时回源 DB。
- **本阶段防御**：`CacheService.lock()` 已内置；未来业务用 `async with cache_service.lock("regen:" + key, ttl_ms=2000):` 包住"回源 → 写缓存"块。

### 18.3 缓存雪崩

- **本阶段防御**：所有 `set()` 默认开启 TTL 抖动（`ttl_jitter_ratio=0.1`）。

### 18.4 缓存穿透

- **风险**：恶意/异常请求传不存在的 key，每次都打 DB。
- **本阶段防御**：KeyBuilder 强制 key 由后端拼接，调用方传入的是业务 ID（user_id / session_id / task_id），无法传入任意 Redis key；未来业务接入 demo 之外的 key 时，必须通过 KeyBuilder。

### 18.5 大 key / 大 value

- **风险**：把整段消息历史塞进一个 key，阻塞 Redis 单线程。
- **本阶段防御**：`CacheService.set()` 默认 value 上限 256KB（可配置），超过抛 `ValueError`；并在 metrics 中记录 `oversize_count`。

### 18.6 敏感数据

- **风险**：日志或 debug 端点泄露 token / 持仓金额。
- **本阶段防御**：
  - 日志统一只记录 `key` 前缀 + `value_size`，**绝不记录 value 内容**；
  - `/api/redis/demo/get` 返回 value 仅在 `REDIS_DEBUG_ENDPOINTS_ENABLED=true` 下可用，且需登录。

### 18.7 多用户 / 多租户

- **本阶段防御**：KeyBuilder 中所有业务 key 都强制带 `user_id`，未来加 `tenant_id` 只需扩展 KeyBuilder 即可，业务无感知。

### 18.8 测试污染

- **本阶段防御**：单测全用 `fakeredis`；集成测试切 `db=15`；CI 退出前 `FLUSHDB`（受 namespace 保护，只删 `finagent:test:*`）。

### 18.9 版本升级

- **本阶段防御**：`CacheEnvelope.schema_version` 固定 `1`；未来升级到 `2` 时，`get()` 遇到老版本 envelope 直接当 miss 处理（避免反序列化炸）。

### 18.10 监控与 trace 对接

- **本阶段防御**：`MetricsCollector` 提供 `snapshot()` 字典，同时在现有 trace 入口（后端请求 trace / execution logger / Langfuse exporter）写入 Redis 关键字段。
- **落地要求**：不是“未来再接”，而是本阶段就打通最小 trace 字段，确保出现 Redis 问题时可按 trace 快速定位。

---

## 19. 需要用户决策的问题（继续确认）

> 你已经在上一轮做了 12 项决策，全部按"小白稳妥版"。本阶段无新增决策项。如有以下变更需求请告知：

1. 前端 Redis 演示小面板：**本阶段明确不做**。
2. Redis 持久化（AOF/RDB）：**本阶段明确不启用**。
3. Redis 指标接入现有 trace：**本阶段必须完成**。
4. 单测 `fakeredis`：默认允许，仅放开发依赖。
5. Redis 遗留链路收敛：**本阶段必须输出扫描与处理报告，禁止双链路并存**。

以上 5 条作为已确认约束，AI 后续必须严格执行。

---

## 20. 给小白的"为什么这么做"附录

- **为什么要先做基础设施而不是直接缓存 STM？**
  因为如果先做 STM 缓存，你会被业务一致性、版本号、降级、和单测一起淹没；先把"通道"修通修稳，再让 STM 走通道，每一步都能独立验证。
- **为什么所有 key 必须经过 KeyBuilder？**
  因为半年后你写新功能时，绝对会忘掉 key 是怎么拼的；KeyBuilder 是"未来的你"留给"现在的你"的礼物。
- **为什么所有 value 必须是 Envelope？**
  因为 Redis 里只有字符串；如果不加版本号和更新时间，你永远没法回答"这条缓存是不是已经过时了"。
- **为什么 Redis 挂了不能让后端挂？**
  因为 Redis 是"便利贴"，PostgreSQL 是"档案室"；档案室还在，业务就能跑，只是慢一点。
- **为什么本阶段不做业务缓存？**
  因为每个业务接入都会带出一堆细节（version、singleflight、stale-but-safe、SSE 重连…）；通道没修好，业务接入只会更乱。修好通道后，未来每接一个业务都是"一文件一接入"。

---

（本文件 = 第一阶段可执行计划。配套文档：本目录下的"目标文档"+"开发规范"。如需修订，请同时修订本计划与对应配套文档。）
