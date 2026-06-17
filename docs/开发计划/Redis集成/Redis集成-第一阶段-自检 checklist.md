# Redis 集成 · 第一阶段自检 Checklist

> 对照 `Redis集成-第一阶段基础设施-开发计划.md` §3 验收标准。  
> 每项完成后在 ☐ 前打勾（改为 ☑）。证据可保存到 `docs/开发计划/Redis集成/第一阶段验收证据/`。

操作步骤详见：[Redis集成-第一阶段-本地启动手册.md](./Redis集成-第一阶段-本地启动手册.md)

---

## 3.1 启动验收（基础设施层）

- [ ] **1** `docker compose up -d postgres redis pgadmin` 后，`docker ps` 可见 `finance_postgres`、`finance_redis`、`finance_pgadmin` 均为 `healthy`
- [ ] **2** `docker exec finance_redis redis-cli -a finance_redis_123 ping` 返回 `PONG`
- [ ] **3** `REDIS_ENABLED=true` 启动后端，日志含 Redis 初始化与 ping 成功
- [ ] **4** `curl http://localhost:8000/api/health` 含 `"redis":{"status":"ok","latency_ms":...}`
- [ ] **5** `REDIS_ENABLED=false` 启动后端，日志含「Redis 已禁用，跳过初始化」
- [ ] **6** `REDIS_ENABLED=false` 时 `/api/health` 含 `"redis":{"status":"disabled"}`
- [ ] **7** `REDIS_ENABLED=false` 时现有业务路由响应与改动前一致（无异常退化）

---

## 3.2 降级验收

- [ ] **8** `REDIS_ENABLED=true` 且停掉 Redis 容器后，后端进程不崩溃
- [ ] **9** 停 Redis 后 `/api/health` 返回 `"redis":{"status":"degraded","error":"..."}`
- [ ] **10** 停 Redis 后 `/api/redis/demo/get?key=foo` 不返回 500，含 `fallback:true` 与 `reason`
- [ ] **11** 停 Redis 后 `/api/redis/metrics` 中 `redis_error` 或 `cache_fallback` 等指标有变化

---

## 3.3 业务规范验收（demo 路由）

- [ ] **12** `/api/redis/demo/set` 写入后，redis-cli 中 key 格式为 `finagent:dev:demo:item:<id>`
- [ ] **13** Value 为合法 JSON，含 `data`、`schema_version`、`updated_at`、`source`
- [ ] **14** `TTL <key>` 返回正整数（非 `-1`）
- [ ] **15** 对已存在 key 多次 `demo/get`，`cache_hit=true`，且 metrics 中 `cache_hit` 累加
- [ ] **16** 对不存在 key `demo/get`，`cache_hit=false`，且 metrics 中 `cache_miss` 累加

---

## 3.4 可观测验收

- [ ] **17** `curl /api/redis/metrics` 返回 `redis_enabled`、`redis_available`、`counters`、`latency_ms` 结构完整
- [ ] **18** 若干次 demo 调用后，counters 中 hit/miss/set 数值符合预期

---

## 3.5 Trace 对齐验收

- [ ] **19** 一次 `/api/redis/demo/*` 后，trace 产物含 `redis_enabled`、`cache_hit` 等最小字段（若本阶段已接入 trace 埋点）
- [ ] **20** Redis 异常场景 trace 可定位 `redis_status=degraded`、`fallback_reason` 等（若已接入）

> 注：Trace 字段以计划 §3.5 为准；若当前阶段 trace 埋点尚未全部落地，在证据目录注明「延后」并记录 issue。

---

## 3.6 文档与代码规范验收

- [ ] **21** `python scripts/check_redis_single_chain.py` 通过（业务层无直接 `import redis`）
- [ ] **22** 业务代码无手拼裸 Key（统一走 `KeyBuilder`）
- [ ] **23** 已阅读 `Redis遗留扫描报告.md`，遗留链路已收敛
- [ ] **24** `pytest backend/tests/test_redis_*.py -q -m "not integration"` 全部通过
- [ ] **25** `pytest backend/tests/test_redis_integration.py -m integration` 在 Docker Redis 下通过（或记录 skip 原因）

---

## 交付物核对

- [ ] **26** `backend/integrations/redis/` 模块齐全（client、key_builder、envelope、cache_service、metrics、lock、runtime）
- [ ] **27** `backend/routers/redis_admin.py` 已挂载，生产默认 `REDIS_DEBUG_ENDPOINTS_ENABLED=false`
- [ ] **28** `docker/docker-compose.yml` 含 `redis` 服务与 healthcheck
- [ ] **29** `backend/.env.example` 含 `REDIS_*` 模板
- [ ] **30** 本手册与自检清单可读、命令可复制执行

---

## 签字 / 日期（可选）

| 角色 | 姓名 | 日期 | 备注 |
|------|------|------|------|
| 执行人 | | | |
| 复核人 | | | |
