# Redis 集成 AGENTS 规则（Finance 项目专项）

> 作用范围：本文件所在目录及其子目录（`docs/开发计划/Redis集成/`）。
> 优先级：用户当前消息 > 更近目录 AGENTS.md > 本文件 > 根目录 AGENTS.md。

## 1. 本阶段定位（必须遵守）

Redis 在本项目里是**运行时状态层**，不是主数据库。

- PostgreSQL 仍是权威真相源（消息、报告、画像、审计）。
- Redis 只存：短生命周期、可过期、可回源、可重建的数据。
- 本阶段只做基础设施，不接业务缓存。

**禁止**：
- 把完整消息、最终报告、长期画像、敏感信息（token/密钥/个人隐私）写入 Redis。
- 让 Redis 故障导致主链路不可用。

## 2. 本阶段目标边界

必须完成：
1. Redis 本地部署与连接配置（Docker + backend 配置）。
2. 统一客户端封装（连接池、超时、健康检查、异常映射）。
3. 统一 KeyBuilder（禁止业务层手拼 key）。
4. 统一 CacheEnvelope（JSON + version + updated_at + source）。
5. 统一 TTL 与抖动策略（禁止永久 key）。
6. Redis 降级路径（不可用时 fallback，不抛到用户端）。
7. 指标接入现有 trace 体系（必须可定位命中、降级、错误）。
8. 单链路约束（只允许 `backend/integrations/redis/*` 作为 Redis 入口）。

本阶段不做：
- 前端 Redis 演示面板。
- AOF/RDB 持久化开启。
- 业务层 Redis 接入（STM/report/summary 真正读写后续再做）。

## 3. 目录与文件约束

允许新增/修改：
- `backend/integrations/redis/`
- `backend/tests/`（Redis 相关测试）
- `backend/config.py`
- `backend/main.py`
- `backend/routers/`（仅 Redis 管理/健康端点）
- `docker/docker-compose.yml`
- `docs/开发计划/Redis集成/`
- `scripts/check_redis_single_chain.py`

禁止修改：
- 业务主链路核心逻辑（chat/report/memory 业务行为）
- 数据库模型和迁移（除非用户明确要求）
- `frontend/dist/`、日志目录、缓存目录

## 4. 代码设计硬规则

1. **单入口**：业务代码不得直接 `import redis` 并调用客户端；统一走 `CacheService`。
2. **强约束 key**：所有 key 必须通过 `KeyBuilder` 生成，格式：
   `finagent:{env}:{module}:{resource}:{...}`
3. **强约束 value**：必须封装为 `CacheEnvelope`。
4. **TTL 必填**：`set()` 必须要求 ttl 参数；ttl<=0 直接报错。
5. **降级优先**：Redis 异常返回 fallback 元信息，不中断主流程。
6. **不记录敏感值**：日志仅记录 key 前缀、耗时、命中、错误类型。
7. **trace 字段必填**（最小集）：
   - `redis_enabled`
   - `redis_status`（ok/disabled/degraded）
   - `cache_hit`
   - `cache_key_family`
   - `redis_latency_ms`
   - `fallback_reason`（有降级时）
   - `redis_error_type`（有错误时）

## 5. 质量与测试门禁

每次改动后至少完成：
- 单测：`pytest backend/tests/test_redis_*.py -q`
- 健康检查：`curl /api/health` 三态（ok/disabled/degraded）
- 指标检查：`curl /api/redis/metrics`
- 单链路检查：`python scripts/check_redis_single_chain.py`

未通过门禁不得标记“完成”。

## 6. 开源/大厂实践对齐（落地基线）

以下实践用于“对齐正确性”，不是照搬目录结构：

- `redis-py asyncio` 官方连接与连接池：
  https://redis.readthedocs.io/en/stable/connections.html
- Cache-Aside（旁路缓存）模式：
  https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside
- Redis 安全基线（认证、网络边界、最小暴露）：
  https://redis.io/docs/latest/operate/oss_and_stack/management/security/

要求：
- 用这些资料校验实现是否正确。
- 不允许“闭门造车”发明非必要协议或复杂抽象。
- 发现与 `docs/项目描述.md` 冲突时，以本项目文档为准。

## 7. 交付格式（每次回复必须包含）

1. 改了哪些文件（路径列表）。
2. 关键改动是什么（3-6 条）。
3. 运行了哪些验证命令与结果。
4. 未完成项/风险项。

