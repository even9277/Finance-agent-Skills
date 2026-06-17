# Redis 集成 · 第一阶段本地启动手册

> 面向零基础：按顺序复制命令即可验证 Redis 基础设施。  
> 本阶段**不接业务缓存**，只验证 Docker Redis、后端连接、健康检查、demo 路由与指标。

---

## 0. 你需要准备什么

| 项目 | 说明 |
|------|------|
| 项目目录 | `/root/Finance`（或你的克隆路径） |
| Docker | 用于启动 `finance_redis` 容器 |
| Python 虚拟环境 | 项目 `.venv`，已安装 `backend/requirements.txt` |
| 可选工具 | `jq`（美化 JSON）、`redis-cli`（已在容器内） |

---

## 1. 启动 Redis（Docker）

```bash
cd /root/Finance/docker
docker compose up -d redis
docker compose ps
```

期望：`finance_redis` 状态为 `healthy`。

验证 Redis 能响应：

```bash
docker exec finance_redis redis-cli -a finance_redis_123 ping
```

期望输出：`PONG`。

> 默认密码是 `finance_redis_123`，与 `docker-compose.yml` 中 `REDIS_PASSWORD` 默认值一致。

---

## 2. 配置后端环境变量

若还没有 `backend/.env`，先复制模板：

```bash
cd /root/Finance
test -f backend/.env || cp backend/.env.example backend/.env
```

在 `backend/.env` 中**追加或修改**以下行（开启 Redis + demo 排障路由）：

```bash
REDIS_ENABLED=true
REDIS_URL=redis://:finance_redis_123@localhost:6379/0
REDIS_NAMESPACE_ENV=dev
REDIS_DEBUG_ENDPOINTS_ENABLED=true
REDIS_METRICS_ENDPOINT_ENABLED=true
```

说明：

- `REDIS_ENABLED=false`（默认）时，后端行为与未接入 Redis 前一致。
- `REDIS_DEBUG_ENDPOINTS_ENABLED=true` 才会挂载 `/api/redis/demo/*`（生产默认应关闭）。

---

## 3. 启动后端

**必须从项目根目录启动**（避免 Agent 路径注入错误）：

```bash
cd /root/Finance
source .venv/bin/activate
python -c "import redis; print('redis-py ok')"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

期望启动日志包含类似内容：

- `Redis 客户端已初始化，Redis ping 成功 ✓`（`REDIS_ENABLED=true` 且 Redis 正常时）
- 或 `Redis 已禁用，跳过初始化`（`REDIS_ENABLED=false` 时）

---

## 4. 健康检查（`/api/health`）

新开终端执行：

```bash
curl -s http://localhost:8000/api/health | jq .
```

**Redis 开启且容器正常**时期望：

```json
{
  "status": "ok",
  "version": "...",
  "redis": {
    "status": "ok",
    "latency_ms": 0.5
  }
}
```

**Redis 关闭**（`REDIS_ENABLED=false`）时期望：

```json
"redis": { "status": "disabled" }
```

专项健康接口（需 `REDIS_ENABLED=true`）：

```bash
curl -s http://localhost:8000/api/redis/health | jq .
```

---

## 5. Demo 写入 / 读取 / 删除

前提：`REDIS_DEBUG_ENDPOINTS_ENABLED=true`。

写入：

```bash
curl -s -X POST http://localhost:8000/api/redis/demo/set \
  -H 'Content-Type: application/json' \
  -d '{"id":"hello","data":{"msg":"world"},"ttl_seconds":60}'
```

读取：

```bash
curl -s "http://localhost:8000/api/redis/demo/get?key=hello" | jq .
```

期望：`cache_hit: true`，`data.msg` 为 `world`。

在 Redis 中查看真实 Key：

```bash
docker exec finance_redis redis-cli -a finance_redis_123 KEYS 'finagent:dev:demo:*'
```

期望存在：`finagent:dev:demo:item:hello`。

查看 TTL（秒，正整数）：

```bash
docker exec finance_redis redis-cli -a finance_redis_123 TTL finagent:dev:demo:item:hello
```

删除：

```bash
curl -s -X DELETE "http://localhost:8000/api/redis/demo/delete?key=hello" | jq .
```

再次读取应 `cache_hit: false`。

---

## 6. 指标接口（`/api/redis/metrics`）

```bash
curl -s http://localhost:8000/api/redis/metrics | jq .
```

期望包含：

- `redis_enabled`、`redis_available`
- `counters`：`cache_hit`、`cache_miss`、`cache_set` 等
- `latency_ms`：`get_p50`、`get_p95`、`set_p50`、`set_p95`

---

## 7. 降级验证（Redis 停掉后后端不崩）

保持后端运行，停止 Redis 容器：

```bash
docker stop finance_redis
```

再次请求：

```bash
curl -s http://localhost:8000/api/health | jq .redis
curl -s "http://localhost:8000/api/redis/demo/get?key=hello" | jq .
curl -s http://localhost:8000/api/redis/metrics | jq .counters
```

期望：

- `/api/health` 中 `redis.status` 为 `degraded`，带 `error`
- demo get **不返回 500**，而是 `fallback: true`、`reason` 说明 Redis 不可用
- `counters` 中 `redis_error` 或 `cache_fallback` 可能增加

恢复 Redis：

```bash
cd /root/Finance/docker
docker compose up -d redis
```

---

## 8. 自动化测试

### 8.1 单元测试（不依赖真实 Redis）

```bash
cd /root/Finance
source .venv/bin/activate
PYTHONPATH=/root/Finance pytest backend/tests/test_redis_*.py -q \
  -m "not integration"
```

### 8.2 集成测试（需要 Docker Redis）

```bash
cd /root/Finance/docker && docker compose up -d redis
cd /root/Finance
PYTHONPATH=/root/Finance pytest backend/tests/test_redis_integration.py -v -m integration
```

若 Redis 未启动，用例会 **skip** 并提示启动命令（符合计划要求）。

### 8.3 单链路检查（禁止业务层直接 import redis）

```bash
python scripts/check_redis_single_chain.py
```

期望：`Redis single-chain check passed`。

---

## 9. 常见问题

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| `Connection refused` 连 Redis | 容器未启动或端口未映射 | `docker compose up -d redis` |
| `/api/redis/demo/*` 404 | debug 开关未开 | 设置 `REDIS_DEBUG_ENDPOINTS_ENABLED=true` 并重启后端 |
| `/api/redis/health` 503 | `REDIS_ENABLED=false` | 在 `backend/.env` 开启 `REDIS_ENABLED=true` |
| 启动无 `redis-py` | 虚拟环境缺依赖 | `pip install -r backend/requirements.txt` |
| pytest 集成测试全 skip | 本机 6379 无 Redis | 先启动 docker redis |

---

## 10. 相关文档

- 开发计划：`docs/开发计划/Redis集成/Redis集成-第一阶段基础设施-开发计划.md`
- 自检清单：`docs/开发计划/Redis集成/Redis集成-第一阶段-自检 checklist.md`
- 遗留扫描：`docs/开发计划/Redis集成/Redis遗留扫描报告.md`
