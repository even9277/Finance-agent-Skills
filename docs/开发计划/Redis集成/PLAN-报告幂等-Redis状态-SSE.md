# PLAN.md — 报告幂等 + Redis 状态快照 + SSE 进度推送

> **计划状态**：已冻结（经 Codex 审查 + 修订后冻结，可进入逐里程碑实现）
> **创建日期**：2026-06-16
> **修订日期**：2026-06-16（根据 Codex 审查意见修订 12 处关键问题，见 §12.2 Decision Log）
> **关联需求**：`REQUIREMENT_SPEC-报告幂等-Redis状态-SSE.md`（v1.0，决策已冻结）
> **所属分支**：`feature/redis-integration-phase1`
> **前置依赖**：Redis 第一阶段基础设施（✅ 已完成，本计划须做 1 处小扩展：CacheService 新增 `set_if_absent()`）
> **下一步**：按 Milestone 0 → 1 → 1A → 2 → 3 → 4 → 5 → 6 逐里程碑实现

---

## 目录

1. [问题概述](#1-问题概述)
2. [已确认决策](#2-已确认决策)
3. [解决方案总览](#3-解决方案总览)
4. [复用现有代码分析](#4-复用现有代码分析)
5. [变更面分析](#5-变更面分析)
6. [范围控制](#6-范围控制)
7. [接口与依赖](#7-接口与依赖)
8. [测试与验收策略](#8-测试与验收策略)
9. [里程碑划分](#9-里程碑划分)
10. [执行协议](#10-执行协议)
11. [回滚方案](#11-回滚方案)
12. [治理文档区](#12-治理文档区)
13. [附录：开源参考与设计思路](#13-附录开源参考与设计思路)

---

## 1. 问题概述

### 1.1 要解决什么问题

在现有的「报告模式」链路中，存在三个用户体验和工程质量问题：

1. **重复提交问题**：用户短时间内多次点击"生成报告"按钮，后端会创建多个相同的后台任务，浪费 LLM / Tushare / Web Search 配额。
2. **进度不可见**：报告生成需要 2–3 分钟，但前端只显示 0–100% 的百分比进度条，用户不知道当前在"基本面分析"还是"新闻分析"阶段，容易误以为系统卡住了。
3. **数据库轮询压力**：前端每 2 秒轮询一次 `/api/report/status/{task_id}`，每次都直接查 PostgreSQL `reports` 表。任务增多时会给 DB 带来不必要的读压力。

### 1.2 为什么需要解决

- **节约成本**：避免重复的 Agent 工作流消耗 LLM 和外部 API 配额。
- **改善体验**：用户看到"基本面分析中 → 技术面分析中 → 报告汇总中"的细粒度进度，而不是干等。
- **工程治理**：Redis 热读 + 降级策略是典型的长任务工程最佳实践，利于项目描述与面试讲述。
- **降低 DB 压力**：用 Redis 吸收高频状态查询，DB 只在缓存 miss 时回源。

### 1.3 期望达到的效果

| 场景 | 当前行为 | 期望行为 |
|------|---------|---------|
| 重复点击"生成报告" | 创建多个相同任务 | 复用已有任务，返回相同 `task_id` |
| 报告生成中查看进度 | 只看到一个百分比数字 | 看到中文阶段名称，如"基本面分析中" |
| 前端查询任务状态 | 每次都查 DB | 优先从 Redis 读，miss 时回源 DB |
| Redis 故障 | 无 Redis | 自动降级到纯 DB 模式，不影响功能 |
| SSE 连接断开 | 无 SSE | 自动降级回 2 秒轮询 |

---

## 2. 已确认决策

以下所有决策已在需求阶段冻结，**实现时不得偏离**：

| # | 决策项 | 选择 | 具体含义 |
|---|--------|------|----------|
| 1 | 幂等时间窗口 | **10 分钟** | 同一用户在 10 分钟内提交**规范化后文本相同**的命令，复用同一任务 |
| 2 | "同一报告"判定 | **user_id + 规范化 command 的 SHA256 hash（前 16 位）** | 忽略空格差异，不依赖 stock_code；注意：此策略判断的是「文本相同」而非「语义相同」——「分析茅台」和「分析贵州茅台」hash 不同 |
| 3 | SSE 端点路径 | **`GET /api/report/events/{task_id}`** | 标准 RESTful SSE 路径 |
| 4 | 前端阶段展示 | **展示中文阶段名称** | 如「基本面分析中」「技术面分析中」；Redis 不可用时前端显示通用「报告生成中」 |
| 5 | Redis 状态 TTL | **终态后保留 10 分钟** | 进行中持续刷新；完成后仍保留 10 分钟供页面重开查看 |
| 6 | 多任务并行 | **允许并行，仅规范化文本相同的请求幂等** | 不同命令可以同时跑多个报告任务 |
| 7 | current_stage 落 DB | **仅存 Redis，不写 DB** | 轮询兜底时 stage 可能为空，但不影响核心流程 |
| 8 | 幂等 Key 形态 | **新增 `report_idempotency_by_user_query`** | 不含 `stock_code` 参数，仅用 `user_id + query_hash` |
| 9 | SSE 鉴权方式 | **复用 ?token= 查询参数** | 与 chat WebSocket 鉴权模式一致 |
| 10 | Hash 算法 | **SHA256，取 hex 前 16 字符** | 跨环境一致，Colission 概率极低 |
| 11 | 幂等命中 HTTP 状态码 | **200**（非 201） | 返回已有任务信息，前端无需区分 |

---

## 3. 解决方案总览

### 3.1 整体思路

本计划不是在改 Agent 报告分析的**业务逻辑**，而是在现有的报告生成链路上，**横向插入三层工程治理能力**：

```
                        用户请求 POST /generate
                              │
                    ┌─────────▼─────────┐
                    │ ① 幂等检查 (Redis) │  ← 新增：原子 SETNX 占位，防止并发重复
                    │   占位成功 → 继续    │
                    │   占位失败 → 返回已有   │
                    │   task_id          │
                    └─────────┬─────────┘
                              │ 未命中
                    ┌─────────▼─────────┐
                    │ ② 创建 DB 行 +     │  ← 现有逻辑（保留）
                    │   BackgroundTasks  │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │ ③ run_report_task │  ← 现有逻辑 + 新增双写 Redis
                    │   每阶段更新 DB    │     每次 _update_report 后同步
                    │   + 双写 Redis     │     写 Redis 状态快照
                    └─────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
     ┌────────▼───┐  ┌────────▼───┐  ┌───────▼──────┐
     │④ GET /status│  │⑤ GET /events│ │⑥ 前端 composable│
     │ Redis 优先  │  │ SSE 推送    │  │ SSE + 轮询兜底│
     │ DB 降级    │  │ 心跳 15s    │  │ 阶段名称展示  │
     └────────────┘  └────────────┘  └──────────────┘
```

### 3.2 本阶段做什么（In Scope）

| 层次 | 具体内容 |
|------|---------|
| **幂等层** | 规范化 command → SHA256 hash → `CacheService.set_if_absent()` 原子占位 Redis Key（TTL 10 分钟）→ 占位成功才创建 DB 任务 → DB 创建成功后更新 Redis Key 为正式 task_id；DB 失败则删除占位 Key 释放槽位 |
| **双写层** | `run_report_task` 每次 DB 更新后，同步写 Redis 轻量状态快照（不含 report content） |
| **读路径** | `GET /status/{task_id}` 优先 Redis → miss 回源 DB；响应增加可选 `current_stage` / `current_stage_label` |
| **SSE 端点** | 新增 `GET /api/report/events/{task_id}`，以 `text/event-stream` 推送状态变更 |
| **前端** | SSE 优先监听 + 2 秒轮询兜底；显示中文阶段名称 |
| **测试** | 幂等命中/miss、Redis 可用/不可用、SSE 推送事件、降级轮询 |
| **trace** | 所有关键路径上报 trace 字段（见 §7.4） |

### 3.3 本阶段不做什么（Out of Scope）

- 不改多 Agent 报告工作流的业务逻辑、Prompt、工具调用
- 不把报告正文存 Redis（仅轻量状态字段）
- 不做工具执行层 Redis 限流 / provider cooldown
- 不做对话模式 STM Redis 化（那是独立需求）
- 不引入消息队列（RabbitMQ/Kafka）、Redis Pub/Sub 复杂方案
- 不新增数据库表或大规模改 schema
- 不修改 `frontend/dist/`、生产环境配置

---

## 4. 复用现有代码分析

> **核心原则**：本项目已有完整的 Redis 基础设施（Phase 1），**严禁重复造轮子**。以下逐项列出可复用的模块及其插入点。

### 4.1 Redis 基础设施（100% 复用）

**位置**：`backend/integrations/redis/`

| 模块 | 文件 | 可复用功能 | 本计划中的用法 |
|------|------|-----------|--------------|
| **CacheService** | `cache_service.py` | `get()`, `set()`, `delete()`, `get_with_version()`, `ttl_with_jitter()` | **核心入口**：幂等 Key 的 `set_if_absent()`（需新增）、状态快照的读写、TTL 管理 |
| **KeyBuilder** | `key_builder.py` | `report_status(task_id)`, `report_idempotency(user_id, stock_code, query_hash)` | **需要扩展**：新增 `report_idempotency_by_user_query(user_id, query_hash)` 方法（不含 stock_code） |
| **CacheEnvelope** | `envelope.py` | JSON 包装（`data`, `schema_version`, `payload_version`, `updated_at`, `source`） | 所有 Redis value 必须包在 Envelope 内 |
| **RedisLockHandle / NoOpLockHandle** | `lock.py` | 分布式锁 + Redis 不可用时的空占位锁 | SSE 推送端避免同一 task_id 的重复推送（可选优化） |
| **Runtime 单例** | `runtime.py` | `get_cache_service()`, `init_redis_runtime()`, `close_redis_runtime()` | 业务代码通过 `get_cache_service()` 获取全局 CacheService 实例 |
| **MetricsCollector** | `metrics.py` | 进程内计数器 + 延迟直方图 | 无须改动，但需关注新增指标的采集 |
| **RedisClient** | `client.py` | 连接池管理、ping、health_snapshot | 不直接使用（通过 CacheService 间接访问） |

### 4.2 报告业务代码（插入点明确）

| 文件 | 当前职责 | 本计划的插入点 |
|------|---------|---------------|
| `backend/routers/report.py` | 路由 + 鉴权 + BackgroundTasks | **①** `generate_report` 开头加幂等检查；**②** 新增 SSE 路由 `GET /events/{task_id}`；**③** `get_report_status` 改为优先 Redis |
| `backend/services/report/workflow_runner.py` | 后台任务 + DB 进度更新 | **④** 在 `_update_report()` 内部加 Redis 双写 |
| `backend/schemas/report.py` | Pydantic 请求/响应模型 | **⑤** `ReportStatusResponse` 增加可选字段 `current_stage` / `current_stage_label` |
| `frontend/src/composables/useReport.ts` | 前端报告状态管理 | **⑥** SSE 监听 + 轮询兜底 + 阶段名称展示 |
| `frontend/src/api/index.ts` | API 类型定义 + Axios 封装 | **⑦** 新增 `ReportStatusResponse` 的 `current_stage` 字段；新增 SSE URL 构建函数 |

### 4.3 鉴权模式（直接复用）

- **SSE 鉴权**：复用 `backend/middleware/auth.py` 中 `authenticate_websocket` 的 `?token=` 模式。SSE 端点从 `request.query_params.get("token")` 取 JWT，调用 `decode_access_token` 验证。
- **用户归属校验**：复用 `ensure_user_access()` 确保用户只能访问自己的 `task_id`。

### 4.4 测试基础设施（直接复用）

- **FakeRedis**（`backend/tests/test_redis_cache_service.py`）：内存 fake Redis，已实现 `get/set/delete/lock`，可直接用于报告幂等和状态快照的单元测试。
- **Redis 测试夹具模式**：`redis_enabled_override` 机制（`runtime.py`）允许测试环境注入 Redis 状态，不依赖真实 Redis。
- **pytest-asyncio** 已就绪，所有新测试使用 `@pytest.mark.asyncio`。

### 4.5 KeyBuilder 需要扩展的具体内容

当前 `KeyBuilder` 已有两个相关方法：

```python
# 已有 — 含 stock_code 参数（本计划不使用，但保留兼容）
def report_idempotency(self, user_id: str, stock_code: str, query_hash: str) -> str:
    return self._join("report", "idempotency", user_id, stock_code, query_hash)

# 已有 — 直接使用
def report_status(self, task_id: str) -> str:
    return self._join("report", "status", task_id)
```

**需要新增**（与决策 #8 对齐）：

```python
# 新增 — 不含 stock_code，仅用 user_id + query_hash
def report_idempotency_by_user_query(self, user_id: str, query_hash: str) -> str:
    return self._join("report", "idempotency", user_id, query_hash)
```

最终 Redis Key 形态：
- 幂等 Key：`finagent:{env}:report:idempotency:{user_id}:{query_hash}`（TTL 600s）
- 状态 Key：`finagent:{env}:report:status:{task_id}`（进行中持续刷新；终态 TTL 600s）

### 4.6 前端代码复用分析

`useReport.ts` 当前结构：
- `generateReport(command)` → 调 API → `_startPolling()` → `setInterval` 每 2 秒轮询
- `_stopPolling()` → `clearInterval`
- `status`, `progress`, `errorMsg` 响应式状态

**需要改造的点**：
1. `generateReport()` 返回的 `ReportTaskResponse` 字段不变（`task_id`, `report_id`, `status`），前端无需额外适配。
2. 新增 SSE 监听函数 `_startSSE(taskId)`，在 `generateReport` 成功后调用。
3. SSE 失败/断开时自动回退到现有 `_startPolling()`。
4. 新增 `currentStage` 响应式状态，展示中文阶段名称。
5. 新增阶段名称映射表（stage id → 中文 label）。

---

## 5. 变更面分析

### 5.1 变更面总览

| 表面 | 涉及 | 风险等级 | 说明 |
|------|------|---------|------|
| **后端 API** | 是 | 🟡 中 | 新增 SSE 端点；`/generate` 增加幂等逻辑；`/status` 增加 Redis 优先读；schema 增加可选字段 |
| **后端 Service** | 是 | 🟡 中 | `workflow_runner._update_report` 增加 Redis 双写；新增 `current_stage` 追踪 |
| **数据库** | 否 | 🟢 低 | `reports` 表不变（`current_stage` 仅存 Redis，不落 DB） |
| **Redis** | 是 | 🟢 低 | 新增两个 Key 族的读写（幂等 + 状态快照），均短 TTL（≤600s） |
| **前端** | 是 | 🟡 中 | 新增 SSE 监听 + 轮询兜底 + 阶段名称展示 |
| **Agent 运行时** | 否 | 🟢 低 | 无逻辑变更，仅在 `workflow_runner` 外围同步状态 |
| **鉴权** | 是 | 🟢 低 | SSE 端点需要鉴权，复用已有 `?token=` 模式 |
| **配置/环境变量** | 否 | 🟢 低 | 无新增配置项（TLL 使用现有默认值或硬编码常量） |
| **文档** | 是 | 🟢 低 | 本 PLAN.md 即为交付物；实现完成后可选补充使用说明 |
| **测试** | 是 | 🟡 中 | 新增 6+ 个测试用例（幂等、双写、SSE、降级） |

### 5.2 风险点与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 命令规范化过强，不同意图被误判为同一报告 | 低 | 中 | 规范化只做空白处理；用户改 wording 即可发起新任务 |
| Redis 与 DB 状态短暂不一致 | 中 | 低 | DB 为权威来源；终态以 DB 为准；SSE 推送的是近实时快照 |
| SSE 单 worker 下连接数过多 | 低 | 中 | 单个用户同时最多几个任务；设置 SSE 心跳 + 超时 |
| SSE 在反向代理（Nginx）下被缓冲 | 中 | 中 | 文档注记需关闭 Nginx 对 `/api/report/events` 的 proxy_buffering |
| 幂等窗口内用户想"强制重新生成" | 中 | 低 | 10 分钟后 Key 过期可新建；后续版本可加 `force=true` 参数 |
| 前端 SSE 和轮询产生竞态 | 低 | 低 | 单一状态源（composable 内合并）；SSE 优先更新，轮询兜底 |

---

## 6. 范围控制

### 6.1 允许修改的文件

```
backend/routers/report.py          # 幂等检查 + SSE 路由 + status 优先 Redis
backend/services/report/workflow_runner.py  # 双写 Redis + current_stage
backend/schemas/report.py          # ReportStatusResponse 增加 stage 字段
backend/integrations/redis/key_builder.py  # 新增 report_idempotency_by_user_query
backend/tests/test_report_idempotency.py   # 新增测试文件
backend/tests/test_report_redis_status.py  # 新增测试文件
backend/tests/test_report_sse.py           # 新增测试文件
frontend/src/composables/useReport.ts     # SSE + 轮询 + 阶段展示
frontend/src/api/index.ts                 # 新增类型 + EventSource URL
```

### 6.2 禁止修改的文件

```
# Redis 基础设施核心逻辑（仅 Minor 扩展，禁止大规模重构）
backend/integrations/redis/cache_service.py      # ⚠️ 本计划需新增 set_if_absent() 方法（约15行），其余逻辑只读
backend/integrations/redis/client.py              # 只读使用
backend/integrations/redis/envelope.py            # 只读使用
backend/integrations/redis/lock.py                # 只读使用（幂等可选使用 lock 消除竞态窗口）
backend/integrations/redis/metrics.py             # 只读使用
backend/integrations/redis/runtime.py             # 只读使用

# 业务核心（不改变现有行为）
backend/db/models.py                    # report 表不新增 current_stage 列
backend/services/agent_service.py       # 仅重导出 run_report_task，不变
backend/services/report/workflow_factory.py  # 不变
backend/services/report/state_builder.py     # 不变
Financial-MCP-Agent/src/agents/*              # 不变（Agent 节点逻辑）

# 前端核心组件（仅扩展，不删除已有行为）
frontend/src/components/*               # 仅通过 composable 暴露新状态

# 禁止区域
frontend/dist/
logs/
__pycache__/
.pytest_cache/
.venv/
node_modules/
```

### 6.3 禁止事项

- 禁止在 `backend/routers/report.py` 或 Vue 组件中直接 `import redis`
- 禁止绕过 `CacheService` 直接操作 Redis 客户端
- 禁止手拼 Redis Key 字符串（必须走 `KeyBuilder`）
- 禁止把报告正文 `content` 写入 Redis
- 禁止修改现有 Agent 节点的业务逻辑、Prompt、工具调用链
- 禁止新增数据库迁移或 `ALTER TABLE`
- 禁止修改 `frontend/dist/` 下的任何文件
- 禁止 Redis 写入失败时抛出 500 错误（必须降级）
- 禁止日志中打印完整 Redis Key 或完整的用户命令
- **⚠️ `CacheService.set_if_absent()` 是唯一允许的 Redis 基础设施扩展**（约 15 行，仅暴露 `redis.set` 的 `nx` 参数），其余 Redis 模块保持只读

---

## 7. 接口与依赖

### 7.1 API 接口变更

#### 7.1.1 `POST /api/report/generate`（扩展行为，接口契约不变）

- **请求**：不变（`command`, `user_id`）
- **响应**：不变（`task_id`, `report_id`, `status`）
- **新行为**：在创建 DB 行之前，先查 Redis 幂等 Key。命中则直接返回已有任务信息（HTTP 200）；未命中则走现有创建流程，并在创建成功后 `SET` 幂等 Key。
- **向后兼容**：✅ 响应字段不变；旧前端无感知。

#### 7.1.2 `GET /api/report/status/{task_id}`（扩展字段，完全向后兼容）

- **现有响应字段**：`task_id`, `status`, `progress`, `report_id`, `error_msg`
- **新增可选字段**：
  - `current_stage: Optional[str]` — 机器可读阶段 ID（如 `"fundamental_analyst"`）
  - `current_stage_label: Optional[str]` — 用户可读中文（如 `"基本面分析中"`）
  - `updated_at: Optional[str]` — ISO8601 时间戳（来自 Redis 快照或 DB）
- **读路径**：优先从 Redis `report:status:{task_id}` 读取；miss 或 Redis 不可用时回源 DB。
- **向后兼容**：✅ 新增字段均为 Optional；旧前端忽略不报错。

#### 7.1.3 `GET /api/report/events/{task_id}`（新增端点）

- **请求**：GET，`?token=<JWT>` 查询参数鉴权
- **响应**：`text/event-stream`（Server-Sent Events）
- **事件类型**：
  ```
  event: status
  data: {"task_id":"...","status":"running","progress":35,"current_stage":"fundamental_analyst","current_stage_label":"基本面分析中","updated_at":"2026-06-16T10:30:00Z"}

  event: completed
  data: {"task_id":"...","status":"completed","progress":100,"report_id":"...","updated_at":"..."}

  event: failed
  data: {"task_id":"...","status":"failed","progress":0,"error_msg":"...","updated_at":"..."}

  event: heartbeat
  data: {"ts":"..."}
  ```
- **心跳间隔**：15 秒（防止连接被中间代理关闭）
- **连接超时**：最长保持与任务生命周期一致（最多 3 分钟 + 10 分钟终态 TTL），任务终态后再推送一次然后关闭。

### 7.2 函数/方法级接口

| 函数 | 所在文件 | 变更类型 | 说明 |
|------|---------|---------|------|
| `generate_report()` | `routers/report.py` | 修改 | 开头增加幂等检查 |
| `get_report_status()` | `routers/report.py` | 修改 | 改为 Redis 优先读 |
| `run_report_task()` | `services/report/workflow_runner.py` | 修改 | `_update_report` 内部增加 Redis 双写 |
| `_update_report()` (闭包) | `services/report/workflow_runner.py` | 修改 | 每次 DB 写后同步写 Redis |
| `CacheService.set()` | `redis/cache_service.py` | **只读使用** | 新的业务调用点，不修改其实现 |
| `CacheService.get()` | `redis/cache_service.py` | **只读使用** | 新的业务调用点，不修改其实现 |
| `KeyBuilder` | `redis/key_builder.py` | **新增方法** | 新增 `report_idempotency_by_user_query()` |
| `authenticate_websocket` | `middleware/auth.py` | **只读参考** | SSE 鉴权复用其逻辑 |

### 7.3 前端接口变更

| 位置 | 变更类型 | 说明 |
|------|---------|------|
| `ReportStatusResponse` 类型 | 扩展 | 新增 `current_stage?`, `current_stage_label?`, `updated_at?` |
| `useReport.ts` | 修改 | 新增 `currentStage` ref, `_startSSE()`, SSE 失败回退逻辑 |
| `api/index.ts` | 扩展 | 新增 `buildReportEventUrl(taskId)` 辅助函数 |

### 7.4 Trace 字段要求

所有关键路径需上报以下 trace 字段（最小集，内容不得包含敏感数据）：

| 字段 | 含义 | 出现场景 |
|------|------|---------|
| `redis_enabled` | Redis 是否启用 | 所有涉及 Redis 的路径 |
| `redis_status` | ok / disabled / degraded | 所有涉及 Redis 的路径 |
| `cache_hit` | 是否命中缓存 | 幂等检查、状态查询 |
| `cache_key_family` | Key 族标识（如 `report_idempotency`） | 所有 Redis 操作 |
| `redis_latency_ms` | Redis 操作延迟 | 所有 Redis 操作 |
| `fallback_reason` | 降级原因（redis_disabled / redis_unavailable / cache_miss / redis_timeout） | 降级时 |
| `redis_error_type` | 错误类型（redis_timeout / redis_error） | 异常时 |
| `report_idempotency_hit` | 幂等是否命中 | `/generate` 调用时 |
| `report_stage` | 当前报告阶段 ID | 报告进度更新时 |
| `report_progress` | 当前报告进度（0–100） | 报告进度更新时 |
| `sse_client_connected` | SSE 客户端连接数 | SSE 连接/断开时（后端日志级别） |

**不记录的敏感值**：完整 command 文本、完整 Redis Key、报告正文、JWT token。

---

## 8. 测试与验收策略

### 8.1 测试分级

| 级别 | 内容 | 最低数量要求 |
|------|------|------------|
| **单元测试** | command 规范化 + hash 稳定性；幂等 Key 命中/miss 逻辑（mock CacheService） | ≥ 3 个 |
| **集成测试** | 双次 generate 同命令 → 同 task_id；Redis 关闭时 generate 仍成功；SSE 推送事件 | ≥ 4 个 |
| **手动验收** | 浏览器完整流程：生成报告 → 见阶段文案 → 完成拉正文；快速双击 generate → 单任务 | ≥ 2 个场景 |
| **降级验收** | 停 Redis → 报告仍可生成完成；前端轮询正常 | ≥ 1 个场景 |
| **质量门禁** | Redis 测试套件 + 单链路检查 + 健康检查 + 指标检查 | 全部通过 |

### 8.2 具体测试用例设计

#### 8.2.1 命令规范化与 Hash（单元测试）

```
test_normalize_and_hash_01: 相同命令不同空白 → hash 相同
  输入1: "  帮我分析茅台  "
  输入2: "帮我分析茅台"
  预期: normalize 后相同，SHA256 前16位相同

test_normalize_and_hash_02: 不同命令 → hash 不同
  输入1: "分析茅台"
  输入2: "分析腾讯"
  预期: hash 不同

test_normalize_and_hash_03: 大小写不影响（若 normalize 策略含）
  输入1: "分析茅台 600519"
  输入2: "分析茅台 600519"
  预期: hash 相同
```

#### 8.2.2 幂等逻辑（集成测试，使用 FakeRedis）

```
test_idempotency_hit:
  前置: 第一次 POST /generate → 创建任务 T1
  动作: 第二次 POST /generate（相同 command, 相同 user_id）
  预期: 返回 T1 的 task_id, HTTP 200, reports 表无新增行

test_idempotency_miss:
  前置: 第一次 POST /generate（command A）
  动作: 第二次 POST /generate（command B，不同）
  预期: 创建新 task_id, reports 表有新增行

test_idempotency_concurrent:  # ⚠️ 最关键用例
  前置: 无
  动作: asyncio.gather(10 个相同 command 的 POST /generate)
  预期: reports 表仅 1 条新记录（其余 9 个请求返回同一 task_id）

test_idempotency_expires:
  前置: 第一次 POST /generate, 幂等 Key TTL 设为 1s（测试用）
  动作: asyncio.sleep(2), 第二次 POST /generate（相同 command）
  预期: 创建新 task_id（旧 Key 已过期）

test_idempotency_redis_write_failure_does_not_block_db:
  前置: mock CacheService.set_if_absent 抛异常
  动作: POST /generate
  预期: 返回 200, reports 表有新行（降级为允许创建任务）

test_idempotency_db_failure_releases_slot:
  前置: mock DB commit 失败
  动作: POST /generate
  预期: 返回错误, 占位 Key 被释放, 后续相同请求可重新建任务
```

#### 8.2.3 Redis 双写（集成测试，使用 FakeRedis）

```
test_dual_write_status_snapshot:
  前置: 模拟 workflow_runner 进度更新
  动作: _update_report(progress=35, status="running", current_stage="fundamental_analyst")
  预期: DB 中 progress=35, Redis 中 report:status:{task_id} 的 progress=35 且 stage 正确

test_dual_write_on_completion:
  前置: 模拟完成任务
  动作: _update_report(status="completed", progress=100, content="...")
  预期: Redis 中 status="completed", content 字段不在 Redis value 中

test_dual_write_redis_failure_does_not_block_db:
  前置: mock CacheService.set 抛异常
  动作: _update_report(progress=50)
  预期: DB 中 progress=50 正常更新, 不抛异常
```

#### 8.2.4 Redis 降级（集成测试）

```
test_generate_without_redis:
  前置: REDIS_ENABLED=False
  动作: POST /generate
  预期: 正常创建任务, 无 Redis 错误, 不 500

test_status_without_redis:
  前置: REDIS_ENABLED=False, 已有任务
  动作: GET /status/{task_id}
  预期: 从 DB 读取, 返回正常
```

#### 8.2.5 SSE 推送（集成测试）

```
test_sse_basic_events:
  前置: 创建任务, 连接到 SSE
  动作: workflow_runner 推状态事件
  预期: 客户端收到至少一条含 current_stage 的事件

test_sse_completed_event:
  前置: 任务正在执行
  动作: 任务完成
  预期: 客户端收到 event: completed

test_sse_reconnect_gets_current_status:
  前置: 任务已运行到 progress=50
  动作: 客户端断开 SSE → 重新连接
  预期: 首次事件包含当前最新状态（progress=50），而非从 0 开始

test_sse_unauthorized:
  前置: 无 token
  动作: 连接 SSE
  预期: 401

test_sse_other_user_task:
  前置: user1 创建任务
  动作: user2 连接 user1 的 SSE（带 user2 的 token）
  预期: 403

test_sse_connection_cleanup:
  前置: 客户端连接后主动断开
  动作: 检查 _sse_connections 字典
  预期: task_id entry 被清理，无残留
```

### 8.3 手动验收清单

```markdown
## 手动验收 A：正常流程
1. 浏览器打开 http://localhost:5173
2. 登录 test1/test1
3. 进入报告模式
4. 输入："帮我生成一份贵州茅台的简要投研报告"
5. 点击生成
6. ☐ 看到阶段名称变化（等待开始 → 基本面分析中 → 技术面分析中 → ... → 生成完成）
7. ☐ 完成后看到报告正文

## 手动验收 B：幂等验证
1. 快速双击"生成报告"按钮
2. ☐ 只创建一个任务（看浏览器开发者工具，只有一次 /generate 返回新 task_id）
3. ☐ 第二次返回相同的 task_id

## 手动验收 C：降级验证
1. 停止 Redis：docker compose stop redis
2. ☐ 报告生成仍正常工作
3. ☐ 前端轮询正常
4. 启动 Redis：docker compose start redis
```

### 8.4 质量门禁命令

```bash
# 1. 全量 Redis 测试
cd /root/Finance && PYTHONPATH=/root/Finance pytest backend/tests/test_redis_*.py -q

# 2. 报告业务测试（新增）
cd /root/Finance && PYTHONPATH=/root/Finance pytest backend/tests/test_report_*.py -q

# 3. 单链路检查（确保没有绕过 CacheService 的直接 redis 导入）
python /root/Finance/scripts/check_redis_single_chain.py

# 4. 健康检查
curl -fsS http://localhost:8000/api/health | python -m json.tool

# 5. Redis 指标
curl -fsS http://localhost:8000/api/redis/metrics
```

---

## 9. 里程碑划分

> **执行规则**：后续实现必须严格按里程碑顺序执行，**每次只执行一个里程碑**。每个里程碑完成后必须报告验收证据，才能进入下一个。

---

### Milestone 0：安全与基线检查（预计耗时 5 分钟）

#### 目标
确保当前代码状态干净、无脏文件，所有已有测试通过，建立变更前的稳定基线。

#### 文件/模块
不涉及代码修改。

#### 实现意图
1. 运行 `git status --short` 确认无意外脏文件。
2. 运行全量 Redis 测试套件确保现有基础设施正常。
3. 启动后端（不启用 Redis）确认报告基本流程可用。
4. 记录当前 commit hash 作为回滚基点。

#### 测试/检查
```bash
cd /root/Finance
git status --short
PYTHONPATH=/root/Finance pytest backend/tests/test_redis_*.py -q
curl -fsS http://localhost:8000/api/health
```

#### 预期结果
- 所有现有测试通过
- 健康检查返回 OK
- Git 状态干净（仅预期文件有变更）

#### 停止条件
- 基线测试未全部通过 → 停止，修复环境问题
- 发现未预期的脏文件 → 确认用户意图

#### 回滚注记
本里程碑不产生变更，无需回滚。

#### 交付证据
`git status --short` 输出 + 测试通过截图 + commit hash。

---

### Milestone 1：KeyBuilder 扩展 + 命令规范化（预计耗时 15 分钟）

#### 目标
在现有 KeyBuilder 中新增 `report_idempotency_by_user_query` 方法，实现命令规范化与 hash 工具函数。

#### 文件/模块
- `backend/integrations/redis/key_builder.py` — 新增方法
- `backend/services/report/command_hasher.py` — **新增文件**，实现 `normalize_command()` + `compute_query_hash()`

#### 实现意图

**1. KeyBuilder 扩展**（约 5 行代码）：
```python
def report_idempotency_by_user_query(self, user_id: str, query_hash: str) -> str:
    """幂等 Key（不含 stock_code）：finagent:{env}:report:idempotency:{user_id}:{query_hash}"""
    return self._join("report", "idempotency", user_id, query_hash)
```

**2. 命令规范化工具**（新文件 `command_hasher.py`，约 30 行代码）：
```python
import hashlib

def normalize_command(command: str) -> str:
    """规范化命令：去首尾空白 + 合并连续空白为单个空格"""
    return " ".join(command.strip().split())

def compute_query_hash(command: str) -> str:
    """SHA256 前 16 位 hex"""
    normalized = normalize_command(command)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
```

**设计说明**：
- 规范化为纯函数，无副作用，便于单元测试。
- 不引入非标准 hash 算法（如 CityHash），SHA256 在 Python 标准库即可获得。
- 前 16 位 hex（64 bit）空间足够，碰撞概率 ≈ 1/2^64，实际影响可忽略。

#### 测试/检查
```bash
# 新增单元测试
PYTHONPATH=/root/Finance pytest backend/tests/test_command_hasher.py -q -v
```

测试用例：
1. 相同命令不同空白 → hash 相同
2. 不同命令 → hash 不同
3. KeyBuilder 新方法产出正确格式 Key

#### 预期结果
- `compute_query_hash("  帮我 分析  茅台  ") == compute_query_hash("帮我分析茅台")` → True
- KeyBuilder 新方法返回 `finagent:dev:report:idempotency:user123:abc123def456...`

#### 停止条件
- 单元测试不通过 → 停止，修复
- Key 格式不符合 `finagent:{env}:{module}:{resource}:{...}` 规范 → 停止

#### 回滚注记
删除新增方法（KeyBuilder 中 1 个方法）和新增文件 `command_hasher.py` 即可。

#### 交付证据
测试通过输出 + Key 格式验证。

---

### Milestone 1A：CacheService 扩展 — `set_if_absent()` 原子写（预计耗时 20 分钟）

> **说明**：本里程碑是为 Milestone 2 的幂等实现提供原子保障。现有 `CacheService.set()` 使用的是普通覆盖写 `client.set(key, raw, ex=ttl)`，不提供 SETNX 语义。本计划需新增一个小方法，暴露 `redis-py` 已有的 `nx=True` 参数。

#### 目标
在 `CacheService` 中新增 `set_if_absent()` 方法，内部使用 `client.set(key, value, ex=ttl, nx=True)` 实现"仅在 Key 不存在时才写入"的原子操作。

#### 文件/模块
- `backend/integrations/redis/cache_service.py` — 新增 `set_if_absent()` 方法（约 15 行）
- `backend/tests/test_redis_cache_service.py` — 新增 `test_set_if_absent_*` 测试用例
- `backend/tests/test_report_idempotency.py` — 后续 M2 使用

#### 实现意图

**`set_if_absent()` 方法签名与行为**：

```python
async def set_if_absent(
    self,
    key: str,
    data: Any,
    ttl_seconds: int,
    source: str,
    payload_version: Optional[int] = None,
) -> Tuple[bool, TraceMeta]:
    """
    仅在 key 不存在时写入（原子 SETNX + EX）。

    Returns:
      (success, trace_meta):
      - success=True  → key 之前不存在，本次写入成功（占位成功）
      - success=False → key 已存在，未修改（被其他请求先占位）
    """
```

**内部实现**：复用 `set()` 的逻辑（Envelope 包装、TTL 抖动、大小检查），区别是调用 `client.set(key, raw, ex=effective_ttl, nx=True)`。

- `nx=True` → Redis 返回 `True` 表示写入成功（Key 之前不存在），返回 `False`/`None` 表示 Key 已存在未写入。
- 如果 `redis-py` 版本中 `nx=True` 返回的是 `None`（而非 `False`），统一判断 `res is True` 为成功。

**降级行为**：Redis 不可用时返回 `(False, fallback_meta)` — 此时幂等逻辑应降级为"允许重复创建任务"。

**FakeRedis 适配**（测试用）：在 `test_redis_cache_service.py` 的 `FakeRedis` 类中，`set` 方法增加 `nx` 参数支持：
```python
async def set(self, key: str, value, ex=None, nx=False, **kw):
    if nx and key in self.store:
        return None  # 模拟 Redis 的 NX 行为
    self.store[key] = value
    return True
```

#### 测试/检查
```bash
PYTHONPATH=/root/Finance pytest backend/tests/test_redis_cache_service.py -q -v -k "set_if_absent"
```

测试用例：
1. `test_set_if_absent_creates_key`：Key 不存在时返回 `success=True`
2. `test_set_if_absent_rejects_existing`：Key 已存在时返回 `success=False`，且 value 未被覆盖
3. `test_set_if_absent_with_ttl`：写入的 Key 有正确的 TTL
4. `test_set_if_absent_redis_unavailable`：Redis 不可用时返回 `(False, fallback_meta)`

#### 预期结果
- 4 个新测试全部通过
- `set_if_absent()` 与现有的 `set()` 共享 Envelope、TTL jitter、max value bytes 逻辑
- 不破坏现有 `set()` 的行为（现有测试仍通过）

#### 停止条件
- `nx=True` 参数在 redis-py 版本中不可用 → 检查依赖版本
- 新方法导致现有测试失败 → 检查是否修改了 `set()` 的默认参数

#### 回滚注记
从 `cache_service.py` 删除 `set_if_absent()` 方法；从测试文件删除相关用例。

#### 交付证据
测试全部通过 + 验证 `nx=True` 写入后再次写入返回 `False`。

---

### Milestone 2：报告幂等层实现（预计耗时 35 分钟，原 30 分钟 + 5 原子占位改造）

#### 目标
在 `POST /api/report/generate` 中集成幂等检查逻辑，同一用户在 10 分钟内对规范化后文本相同的命令的重复请求，**并发安全**地返回同一任务。

#### 文件/模块
- `backend/routers/report.py` — 修改 `generate_report`
- `backend/services/report/idempotency.py` — **新增文件**，封装幂等逻辑
- `backend/tests/test_report_idempotency.py` — **新增文件**

#### 实现意图

**核心流程：原子占位 → 创建 DB → 更新占位 Key**（消除 get-then-set 竞态窗口）：

```
POST /generate
  │
  ├─ ① 计算 query_hash = SHA256(normalize(command))[:16]
  │
  ├─ ② CacheService.set_if_absent(
  │      key="finagent:{env}:report:idempotency:{user_id}:{query_hash}",
  │      value=PLACEHOLDER,  # 占位标记
  │      ttl=600s
  │    )
  │
  ├─ ③ 返回 (success=False) → 占位失败：
  │      CacheService.get(key) → 读取已有 task_id/report_id/status
  │      如果 value 仍是 PLACEHOLDER（前一个请求正在创建DB）→ 等待最多 3s + 重试 get
  │      返回已有任务信息
  │
  └─ ④ 返回 (success=True) → 占位成功：
        创建 DB 行（现有逻辑）
        → DB 创建成功：CacheService.set(key, {task_id, report_id, status}, ttl=600)
          （覆盖占位 value 为正式 value）
        → DB 创建失败：CacheService.delete(key)（释放占位，允许重试）
        → 启动 BackgroundTasks
```

**关键改进点（相比初版）**：
1. **先 SETNX 再建 DB**：原子占位避免了"两个请求都判定为 miss，各自创建 DB"的竞态。
2. **PLACEHOLDER 状态**：占位成功但 DB 尚未创建时，Key 的 value 是一个占位标记。后续请求读到占位标记时短暂等待（最多 3s，poll 间隔 200ms），等待前一个请求完成 DB 创建。
3. **DB 失败释放**：如果 DB 创建失败，删除占位 Key，避免"卡死 10 分钟"。
4. **Redis 不可用时降级**：`set_if_absent` 返回 `(False, fallback_meta)` 时，跳过幂等保护，允许创建任务（但记录 trace 告警）。

**1. 幂等服务层**（新文件 `idempotency.py`，约 130 行）：

```python
# 核心函数：

async def acquire_idempotency_slot(
    cache_service, user_id: str, command: str
) -> tuple[Optional[str], dict]:
    """
    尝试原子占位幂等 Key。
    Returns:
      acquired: 占位成功返回占位 Key 字符串；失败返回 None（已有其他请求占位）
      trace_meta: 上报用
    """

async def read_idempotency_result(
    cache_service, key: str
) -> Optional[dict]:
    """
    读取已完成的幂等 Key 的值。
    如果值是 PLACEHOLDER（前一个请求还在建 DB），poll 等待最多 3s。
    Returns None 如果等待超时（此时应降级为新建）。
    """

async def finalize_idempotency_slot(
    cache_service, key: str,
    task_id: str, report_id: str, status: str
) -> None:
    """DB 创建成功后，更新幂等 Key 为正式值。"""

async def release_idempotency_slot(cache_service, key: str) -> None:
    """DB 创建失败后，释放占位 Key。"""
```

**2. Router 修改**（`routers/report.py` 中 `generate_report` 函数，约 35 行变更）：

```python
async def generate_report(body, background_tasks, db, auth):
    effective_user_id = ensure_user_access(body.user_id, auth)
    await _ensure_user(db, effective_user_id)

    cache_service = get_cache_service()

    # ① 尝试原子占位
    acquired_key, trace_meta = await acquire_idempotency_slot(
        cache_service, effective_user_id, body.command
    )

    if acquired_key is None:
        # ② 占位失败 → 等待前一个请求完成 DB 创建 → 读取已有任务
        existing = await read_idempotency_result(cache_service, acquired_key)
        if existing and existing.get("task_id"):
            return ReportTaskResponse(**existing)
        # 读取失败（前一个请求挂了或超时）→ 降级：允许创建新任务
        logger.warning("幂等占位失败但无法读取已有结果，降级创建新任务")

    # ③ 占位成功（或降级）→ 创建 DB 行
    task_id = str(uuid.uuid4())
    report_id = str(uuid.uuid4())
    report = Report(id=report_id, task_id=task_id, user_id=effective_user_id,
                    status="pending", progress=0)
    db.add(report)
    await db.commit()

    # ④ DB 创建成功后更新幂等 Key（覆盖 PLACEHOLDER）
    if acquired_key:
        await finalize_idempotency_slot(
            cache_service, acquired_key, task_id, report_id, "pending"
        )
    # 如果 acquired_key 为 None（降级模式），则尝试补设幂等 Key
    else:
        await try_set_idempotency_fallback(cache_service, effective_user_id, body.command,
                                           task_id, report_id, "pending")

    background_tasks.add_task(run_report_task, task_id=task_id, report_id=report_id,
                              command=body.command, user_id=effective_user_id)

    return ReportTaskResponse(task_id=task_id, report_id=report_id, status="pending")
```

**PLACEHOLDER 等待逻辑细节**：
```python
async def read_idempotency_result(cache_service, key: str) -> Optional[dict]:
    """轮询等待 PLACEHOLDER 变为正式值，最多 3s"""
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        envelope, meta = await cache_service.get(key)
        if envelope and envelope.data.get("task_id"):
            return envelope.data  # 正式值就绪
        await asyncio.sleep(0.2)
    return None  # 超时
```

#### 测试/检查
```bash
PYTHONPATH=/root/Finance pytest backend/tests/test_report_idempotency.py -q -v
```

测试用例（修订版）：
1. **幂等命中**：相同 command → 同 task_id（串行）
2. **幂等未命中**：不同 command → 新 task_id
3. **并发幂等**（最关键）：**10 个相同请求同时打到 `/generate` → `reports` 表只有 1 行新记录**（使用 `asyncio.gather` 并发发送）
4. **幂等过期**：Key TTL 过后可新建
5. **Redis 降级**：REDIS_ENABLED=False 时正常创建任务，不报错
6. **Redis 写失败不影响 DB 提交**：mock `set_if_absent` 抛异常 → `/generate` 仍返回 200
7. **DB 失败释放占位**：mock DB commit 失败 → 占位 Key 被删除

#### 预期结果
- **并发测试通过**：10 个并发请求只创建 1 条 reports 记录
- 手动 curl：两次相同 command 返回相同 `task_id`
- 降级逻辑：Redis 不可用时 0 个 500 错误

#### 停止条件
- 并发测试不通过（> 1 条记录）→ 检查 `set_if_absent` 的 `nx` 实现
- PLACEHOLDER 等待超时导致正常请求卡住 → 检查 `read_idempotency_result` 的 poll 逻辑
- 降级逻辑导致 500 → 检查 exception handling

#### 回滚注记
- 删除 `routers/report.py` 中新增的幂等检查代码块
- 删除 `services/report/idempotency.py` 文件
- 删除测试文件

#### 交付证据
并发测试通过截图 + 手动 curl 日志 + trace 字段验证。

---

### Milestone 3：Redis 状态快照双写 + status 读路径优化（预计耗时 25 分钟）

#### 目标
`run_report_task` 每次 DB 进度更新后同步写 Redis 轻量状态；`GET /status/{task_id}` 优先从 Redis 读取。

#### 文件/模块
- `backend/services/report/workflow_runner.py` — 修改 `_update_report` 闭包增加双写
- `backend/routers/report.py` — 修改 `get_report_status` 增加 Redis 优先读
- `backend/schemas/report.py` — 扩展 `ReportStatusResponse`
- `backend/tests/test_report_redis_status.py` — **新增文件**

#### 实现意图

**1. Schema 扩展**（约 5 行变更）：
```python
class ReportStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: int
    report_id: Optional[str] = None
    error_msg: Optional[str] = None
    # ⬇️ 以下为新增可选字段
    current_stage: Optional[str] = None       # 机器可读，如 "fundamental_analyst"
    current_stage_label: Optional[str] = None  # 用户可读，如 "基本面分析中"
    updated_at: Optional[str] = None           # ISO8601
```

**2. workflow_runner 双写**（约 40 行变更）：

关键变更：**不使用全局 `_current_stage_cache` 字典**。改为从 LangGraph 事件流中直接获取当前节点名，通过 `_update_report` 的 kwargs 传入 `_sync_status_to_redis`。

`_update_report` 闭包改造：
```python
async def _update_report(**kwargs):
    # 分离 "仅写 DB" 的字段（status/progress/content/stock_code 等）和 "仅写 Redis" 的字段
    # current_stage、current_stage_label 仅写 Redis，不写 DB
    stage = kwargs.pop("current_stage", None)
    stage_label = kwargs.pop("current_stage_label", None)

    async with AsyncSessionFactory() as db:
        result = await db.execute(select(Report).where(Report.task_id == task_id))
        rpt = result.scalar_one_or_none()
        if rpt:
            for k, v in kwargs.items():
                setattr(rpt, k, v)
            await db.commit()
            # ⬇️ 新增：同步写 Redis 状态快照（传入阶段信息）
            await _sync_status_to_redis(
                rpt,
                current_stage=stage or _current_known_stage,
                current_stage_label=stage_label or _current_known_label,
            )
```

设计说明：
- `_current_known_stage` / `_current_known_label` 是 `run_report_task` 闭包内的局部变量（非全局），初始为 `None`。
- LangGraph 事件回调中检测到新节点进入时，更新这两个局部变量，然后调用 `_update_report(progress=...)` 触发双写。
- 任务完成后（completed/failed），局部变量随闭包生命周期自然释放，无内存泄漏问题。
- **不做全局缓存**：服务重启后依赖 Redis 或 LangGraph 事件重新填充。

`_sync_status_to_redis` 独立函数：
```python
async def _sync_status_to_redis(
    report: Report,
    current_stage: Optional[str] = None,
    current_stage_label: Optional[str] = None,
) -> None:
    """将 report 的轻量状态写入 Redis，不写 content"""
    cache_service = get_cache_service()
    if cache_service is None:
        return  # Redis 未初始化，静默跳过
    key = cache_service.key_builder.report_status(report.task_id)
    status_data = {
        "task_id": report.task_id,
        "report_id": report.id,
        "status": report.status,
        "progress": report.progress,
        "current_stage": current_stage,         # 从调用方传入，非全局缓存
        "current_stage_label": current_stage_label,
        "error_msg": report.error_msg,
        "updated_at": datetime.utcnow().isoformat(),
    }
    # 终态（completed/failed）时 write_content=False 确认不写正文
    ttl = 600 if report.status in ("completed", "failed") else 600
    try:
        await cache_service.set(key, status_data, ttl_seconds=ttl, source="workflow_runner")
    except Exception:
        logger.warning("Redis 状态双写失败 task=%s", report.task_id, exc_info=True)
        # 不抛异常，不阻断主流程
```

**LangGraph 事件流中获取 current_stage**（现有 `node_progress` 映射已包含节点名）：

```python
# 在 astream_events 的回调中：
if event.get("event") in {"on_chain_end", "on_chain_complete"} and node in node_progress:
    if node not in finished_nodes:
        finished_nodes.add(node)
        # 更新闭包内的局部变量
        _current_known_stage = node
        _current_known_label = STAGE_LABELS.get(node, node)
        # 触发 DB+Redis 双写（stage 通过 kwargs 传入）
        await _update_report(progress=node_progress[node])

# 任务开始时：
_current_known_stage = "pending"
_current_known_label = "等待开始"
```

**4. Status 读路径优化**（`get_report_status`，约 25 行变更）：
```python
# ① 尝试从 Redis 读取
cache_service = get_cache_service()
if cache_service:
    key = cache_service.key_builder.report_status(task_id)
    envelope, meta = await cache_service.get(key)
    if envelope:
        data = envelope.data
        return ReportStatusResponse(
            task_id=data["task_id"],
            status=data["status"],
            progress=data["progress"],
            report_id=data.get("report_id") if data["status"] == "completed" else None,
            error_msg=data.get("error_msg"),
            current_stage=data.get("current_stage"),
            current_stage_label=data.get("current_stage_label"),
            updated_at=data.get("updated_at"),
        )
# ② Redis miss 或不可用 → 回源 DB（现有逻辑）
# 此时 current_stage 和 current_stage_label 为 None（仅存 Redis）
# 前端降级文案：staus="running" 但 current_stage_label 为空 → 显示「报告生成中」
```

**降级体验说明**（重要）：
- Redis 可用时：用户看到「基本面分析中」「技术面分析中」等精确阶段名称。
- Redis 不可用时（或 Redis Key 已过期）：`current_stage_label` 为 `None`，前端应显示通用文案「报告生成中...」而不是显示空白或报错。
- `current_stage` 不落 DB 是本计划的**取舍**：避免 DB schema 变更带来的迁移成本，代价是轮询兜底时缺少阶段名称。这个代价在需求文档中已经过用户确认（决策 #7）。

#### 测试/检查
```bash
PYTHONPATH=/root/Finance pytest backend/tests/test_report_redis_status.py -q -v
```

测试用例（详见 §8.2.3 和 §8.2.4）：
- DB 更新后 Redis 状态同步正确
- 完成后 Redis 有状态且无 content 字段
- status 接口优先返回 Redis 数据
- Redis 不可用时可从 DB 读取

#### 预期结果
- Redis 快照与 DB 状态一致（允许 <1s 最终一致性延迟）
- `GET /status/{task_id}` 返回新增的可选字段
- 关闭 Redis 后 status 接口仍可工作

#### 停止条件
- 双写导致 DB 提交异常 → 检查 `_sync_status_to_redis` 是否 await（必须不阻塞 DB）
- Redis 写异常导致 500 → 检查 try/except 是否包裹

#### 回滚注记
- 删除 `_sync_status_to_redis` 调用
- 恢复 `get_report_status` 的原有 DB 直读逻辑
- 删除 `ReportStatusResponse` 新增字段

#### 交付证据
测试全部通过 + status API curl 验证新增字段 + trace 字段验证。

---

### Milestone 4：SSE 进度推送端点（预计耗时 40 分钟）

#### 目标
新增 `GET /api/report/events/{task_id}` SSE 端点，实时推送报告进度事件。

#### 文件/模块
- `backend/routers/report.py` — 新增 SSE 路由
- `backend/services/report/sse_manager.py` — **新增文件**，管理 SSE 连接与事件分发的简单内存实现
- `backend/tests/test_report_sse.py` — **新增文件**
- `backend/middleware/auth.py` — 可能需要新增 SSE 事件路径到公开路径列表（实际不走 AuthMiddleware 的 Bearer token，而是 query param 鉴权）

#### 实现意图

**1. SSE 管理器**（新文件 `sse_manager.py`，约 100 行）：

由于本项目部署为**单 uvicorn worker 进程**，可使用简单内存数据结构管理 SSE 连接。**本方案不支持多 worker 部署**（多 worker 时同一个 task_id 的生产者和 SSE 连接可能不在同一进程，消息会丢失。如需多 worker，需改用 Redis Pub/Sub 或 DB/Redis 轮询式 SSE，属于后续版本 Out of Scope）。

核心设计：
```python
import asyncio
from typing import Dict

# 全局连接注册表: task_id → list[asyncio.Queue]
# 每个 task_id 最多 MAX_LISTENERS_PER_TASK = 5 个连接
_sse_connections: Dict[str, list[asyncio.Queue]] = {}

async def subscribe(task_id: str) -> Optional[asyncio.Queue]:
    """建立 SSE 连接，返回消息队列。返回 None 表示连接数已满。"""

async def unsubscribe(task_id: str, queue: asyncio.Queue):
    """断开连接，清理队列。task_id 下无连接时删除整个 entry。"""

async def publish(task_id: str, event: str, data: dict):
    """向所有监听 task_id 的客户端推送事件。无连接时静默跳过。"""

async def publish_status(task_id: str, status_data: dict):
    """推送状态变更事件（workflow_runner 调用）"""
```

**2. SSE 路由**（约 70 行）：

```python
from fastapi.responses import StreamingResponse
from starlette.requests import Request

@router.get("/events/{task_id}", summary="SSE 任务进度推送")
async def report_events(
    task_id: str,
    request: Request,
    token: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    # ① 鉴权：从 ?token= 解析用户身份
    #    注意：本端点被加入 AuthMiddleware 的公开路径列表，
    #    但这不代表免登录。这里通过 query param 独立进行 token 校验。
    #    参见 backend/middleware/auth.py:14 _PUBLIC_PATH_PREFIXES。
    if settings.auth_enabled:
        if not token:
            raise HTTPException(status_code=401, detail="未登录：缺少 ?token= 参数")
        try:
            auth_ctx = _build_auth_context(token)  # 复用 middleware/auth.py:40
        except AuthError:
            raise HTTPException(status_code=401, detail="未登录或 Token 无效")
    else:
        auth_ctx = AuthContext(account_id="anon", username="anon", user_id="")

    # ② 校验任务存在且属于当前用户
    result = await db.execute(select(Report).where(Report.task_id == task_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if settings.auth_enabled:
        ensure_user_access(report.user_id, auth_ctx)

    # ③ 返回 SSE 流
    return StreamingResponse(
        _sse_event_generator(task_id, auth_ctx.user_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )
```

**3. SSE 事件生成器**（约 60 行，增加断线检测和清理）：

```python
async def _sse_event_generator(task_id: str, user_id: str, request: Request):
    """生成器函数：订阅 → 循环 yield 事件 → 取消订阅"""
    queue = await subscribe(task_id)
    if queue is None:
        # 连接数已满
        yield _format_sse("error", {"message": "连接数已满，请稍后重试"})
        return

    try:
        # ⚠️ 先发送当前状态（SSE 重连后能拿到最新状态，而不是从空白开始）
        current = await _get_current_status(task_id)
        if current:
            yield _format_sse("status", current)
            if current.get("status") in ("completed", "failed"):
                # 任务已经是终态 → 推送一次后直接关闭
                yield _format_sse(
                    "completed" if current["status"] == "completed" else "failed",
                    current
                )
                return

        # 持续推送
        while True:
            # ⚠️ 检测客户端是否断开连接
            if await request.is_disconnected():
                break

            try:
                event_data = await asyncio.wait_for(queue.get(), timeout=15)
                yield _format_sse(event_data["event"], event_data["data"])
                if event_data["data"].get("status") in ("completed", "failed"):
                    break
            except asyncio.TimeoutError:
                # 心跳保活（防止中间代理关闭空闲连接）
                yield _format_sse("heartbeat", {"ts": datetime.utcnow().isoformat()})
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("SSE 生成器异常 task=%s", task_id, exc_info=True)
    finally:
        await unsubscribe(task_id, queue)
        # ⚠️ 任务终态后清理内存连接注册表（防止内存泄漏）
        # unsubscribe 已处理空 list → 删除 entry

def _format_sse(event: str, data: dict) -> str:
    """格式化为 SSE 协议"""
    import json
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
```

**4. workflow_runner 集成**：在 `_sync_status_to_redis` 之后调用：
```python
await publish_status(task_id, status_data)
```

**5. AuthMiddleware 调整**：将 `/api/report/events` 加入公开路径前缀（因为 SSE 的 token 走 query param，不走 Authorization header）：
```python
_PUBLIC_PATH_PREFIXES = (
    "/api/health",
    "/api/auth/login",
    "/api/docs",
    "/api/openapi.json",
    "/api/redis/health",
    "/api/redis/metrics",
    "/api/report/events",  # 新增：SSE token 走 ?token= query param
)
```

**⚠️ 重要安全说明**：
- `/api/report/events` 加入公开路径列表**只是跳过 AuthMiddleware 的 Bearer token 解析**，不代表免登录。
- SSE 端点在路由内部自行校验 `?token=` query param。
- 日志中**不得打印完整 URL**（因为 query param 中的 token 会出现在 URL 中），应只记录 `task_id` 和 `client_ip`。

**6. SSE Manager 附加约束**：
- `subscribe()` 中 `asyncio.Queue` 的 `maxsize=32`（防止生产快于消费时内存膨胀）
- `publish()` 中如果 queue 已满，使用 `put_nowait()` + 丢弃旧消息（避免阻塞 workflow_runner）
- `unsubscribe()` 后如果 `task_id` 下无连接 → 删除字典 entry（防止内存泄漏）

**5. AuthMiddleware 调整**：将 `/api/report/events` 加入公开路径前缀（因为 SSE 的 token 走 query param，不走 Authorization header）：
```python
_PUBLIC_PATH_PREFIXES = (
    "/api/health",
    "/api/auth/login",
    "/api/docs",
    "/api/openapi.json",
    "/api/redis/health",
    "/api/redis/metrics",
    "/api/report/events",  # 新增：SSE token 走 query param
)
```

#### 测试/检查
```bash
PYTHONPATH=/root/Finance pytest backend/tests/test_report_sse.py -q -v
```

测试用例（详见 §8.2.5）：
- SSE 连接后可收到状态事件
- 任务完成时收到 completed 事件
- 无 token 连接返回 401
- 他人 task_id 连接返回 403

#### 预期结果
- SSE 推送延迟 < 1s
- 心跳正常（每 15 秒）
- 终态后 SSE 正确关闭
- 鉴权工作正常

#### 停止条件
- SSE 连接导致 worker 泄漏 → 检查 unsubscribe 是否在 finally 调用
- Nginx 代理缓冲导致 SSE 无推送 → 检查 `X-Accel-Buffering` header
- 多客户端连接同一 task_id 导致广播失败 → 检查 list[Queue] 遍历

#### 回滚注记
- 删除 SSE 路由（`report.py` 中新增代码）
- 删除 `sse_manager.py`
- 删除 `AuthMiddleware` 中新增的公开路径
- 删除 `workflow_runner` 中 `publish_status` 调用

#### 交付证据
测试全部通过 + `curl` SSE 手动验证 + AuthMiddleware 公开路径验证。

---

### Milestone 5：前端 SSE 集成 + 阶段展示 + 轮询兜底（预计耗时 35 分钟）

#### 目标
前端使用 SSE 优先监听报告进度，SSE 失败时自动退回 2 秒轮询；展示中文阶段名称。

#### 文件/模块
- `frontend/src/composables/useReport.ts` — 修改
- `frontend/src/api/index.ts` — 扩展类型 + 新增 URL 构建函数

#### 实现意图

**1. API 层**（`api/index.ts`，约 15 行新增）：

```typescript
// ReportStatusResponse 扩展
export interface ReportStatusResponse {
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  report_id?: string
  error_msg?: string
  current_stage?: string        // 新增
  current_stage_label?: string  // 新增
  updated_at?: string           // 新增
}

// SSE URL 构建（复用 buildWsUrl 的 ?token= 模式）
export function buildReportEventUrl(taskId: string): string {
  const protocol = window.location.protocol === 'https:' ? 'https' : 'http'
  const host = window.location.host
  const url = new URL(`${protocol}://${host}/api/report/events/${taskId}`)
  const token = localStorage.getItem(ACCESS_TOKEN_KEY)
  if (token) url.searchParams.set('token', token)
  return url.toString()
}
```

**2. useReport.ts 改造**（约 85 行变更）：

```typescript
// 新增响应式状态
const currentStage = ref<string | null>(null)
const currentStageLabel = ref<string | null>(null)

// 阶段名称兜底文案
const STAGE_FALLBACK_LABEL = '报告生成中'

// 新增 SSE 相关
let _eventSource: EventSource | null = null

function _startSSE(taskId: string) {
  _stopSSE()
  const url = buildReportEventUrl(taskId)
  _eventSource = new EventSource(url)

  _eventSource.addEventListener('status', (e) => {
    const data = JSON.parse(e.data)
    status.value = data.status
    progress.value = data.progress
    currentStage.value = data.current_stage || null
    // ⚠️ Redis 不可用时 current_stage_label 可能为空 → 使用兜底文案
    currentStageLabel.value = data.current_stage_label || STAGE_FALLBACK_LABEL
    errorMsg.value = data.error_msg || null
  })

  _eventSource.addEventListener('completed', async (e) => {
    const data = JSON.parse(e.data)
    status.value = 'completed'
    progress.value = 100
    currentStageLabel.value = '生成完成'
    _stopSSE()
    if (data.report_id) {
      await _fetchReport(data.report_id)  // ⚠️ 必须 await，确保报告加载完成
    }
    isGenerating.value = false
  })

  _eventSource.addEventListener('failed', (e) => {
    const data = JSON.parse(e.data)
    status.value = 'failed'
    errorMsg.value = data.error_msg || '生成失败'
    currentStageLabel.value = '生成失败'
    _stopSSE()
    isGenerating.value = false
    // ⚠️ 失败后不需要轮询（状态已是终态），但保留报告 id 供查看
    if (data.report_id) {
      reportId.value = data.report_id
    }
  })

  _eventSource.onerror = () => {
    // SSE 连接失败 → 回退到轮询
    console.warn('[Report] SSE 连接失败，回退到轮询')
    _stopSSE()
    _startPolling()
  }
}

function _stopSSE() {
  if (_eventSource) {
    _eventSource.close()
    _eventSource = null
  }
}

// 修改 generateReport：使用后端返回的实际 status（不要硬编码 pending）
async function generateReport(command: string) {
  if (isGenerating.value) return
  isGenerating.value = true
  report.value = null
  errorMsg.value = null
  progress.value = 0
  currentStage.value = null
  currentStageLabel.value = null

  try {
    const { data } = await reportApi.generate(command, userStore.userId)
    taskId.value = data.task_id
    reportId.value = data.report_id
    // ⚠️ 使用后端返回的真实 status（幂等命中时可能已是 completed/running）
    status.value = data.status
    if (data.status === 'completed' && data.report_id) {
      // 幂等命中已完成任务 → 直接拉报告
      await _fetchReport(data.report_id)
      isGenerating.value = false
      return
    }
    _startSSE(taskId.value)  // ✅ SSE 优先；失败时 onerror 自动回退轮询
  } catch (e: unknown) {
    errorMsg.value = e instanceof Error ? e.message : '触发失败'
    isGenerating.value = false
  }
}

// 修改 _startPolling：轮询返回的数据中包含 current_stage 时更新状态
//    轮询时 current_stage 可能为空（仅存 Redis），此时显示兜底文案
//    修改 status.value/progress.value 的来源为轮询返回的最新值
// ...
```

**3. 阶段名称映射（前端补充显示层）**：与后端的 `STAGE_LABELS` 保持一致。

#### 测试/检查
- 手动验收 A/B/C（见 §8.3）
- 前端构建不报错：`cd /root/Finance/frontend && npm run build`
- TypeScript 类型检查通过

#### 预期结果
- 前端展示中文阶段名称
- SSE 连接成功时进度更新流畅
- SSE 断开时自动切换到轮询
- 快速双击只创建一个任务
- 现有功能不回归（历史列表、下载、删除）

#### 停止条件
- TypeScript 编译失败 → 检查类型定义
- SSE 跨域问题 → 检查 Vite proxy 配置
- 前端轮询兜底未触发 → 模拟 SSE 断连测试

#### 回滚注记
- 恢复 `useReport.ts` 到仅有轮询的版本
- 删除 `api/index.ts` 中新增类型字段和函数

#### 交付证据
浏览器手动验收截图/视频 + 前端构建成功日志。

---

### Milestone 6：Nginx 反向代理 SSE 适配 + 文档收尾（预计 15 分钟，Docker 部署必须）

> ⚠️ **本里程碑不是可选项**：Docker 部署模式下 Nginx 默认配置会缓冲 HTTP 响应，SSE 事件会被延迟直到缓冲区满。Docker 验收前必须完成此配置。

#### 目标
确保 Docker 部署时 SSE 不被 Nginx 缓冲，事件可以实时推送到浏览器。

#### 文件/模块
- `docker/nginx/default.conf` — **修改现有配置**（真实路径：**`docker/nginx/default.conf`**，非 `docker/nginx.conf`）

#### 现行 Nginx 配置分析

当前配置（`docker/nginx/default.conf:12`）：
```nginx
location /api/ {
    proxy_pass http://backend:8000/api/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;      # 为 WebSocket 服务
    proxy_set_header Connection "upgrade";        # 为 WebSocket 服务
}
```

**问题**：
1. `Connection "upgrade"` 对所有 `/api/` 请求都设了 upgrade header，这不适合普通 HTTP 请求（包括 SSE 长连接）。
2. 没有 `proxy_buffering off`，SSE 事件会被 Nginx 缓冲直到响应积累到一定大小才发送。

#### 实现意图

**方案**：在现有 `/api/` location 之前，新增一个更精确的 SSE 专用 location：

```nginx
# 新增：SSE 端点禁用缓冲，确保事件实时推送
location /api/report/events {
    proxy_pass http://backend:8000/api/report/events;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Connection '';       # 覆盖上一层可能残留的 upgrade
    proxy_buffering off;                  # ⚠️ 关键：禁用缓冲
    proxy_cache off;
    chunked_transfer_encoding on;
}

# 保留现有 /api/ location（WebSocket 等）
location /api/ {
    # ... 现有配置不变
}
```

> **Nginx location 优先级**：更精确的 `/api/report/events` 匹配优先于通配的 `/api/`，两个 location 可以共存。

#### 测试/检查
```bash
# Docker 环境下验证 SSE
curl -N -H "Accept: text/event-stream" \
  "http://localhost:8000/api/report/events/{task_id}?token=<JWT>"
# 期望：事件逐条实时输出，无延迟

# 完整 Docker 启动验证
cd /root/Finance/docker && docker compose up -d --build
```

#### 预期结果
- Docker 部署时 SSE 事件实时推送，无缓冲延迟（< 1s）
- 现有 `/api/` 路由工作不受影响
- Vite dev 模式（开发环境）不受影响（Vite 代理不缓冲 SSE 流）

#### 停止条件
- Docker 环境下 SSE 事件延迟 > 3s → 检查 `proxy_buffering off` 是否生效
- 新增 location 影响现有 API 路由 → 检查 location 优先级

#### 回滚注记
从 `nginx/default.conf` 中删除 `/api/report/events` location block 即可。

#### 交付证据
Docker compose 环境下 SSE 验证通过截图 + `curl -N` 输出。

---

## 10. 执行协议

### 10.1 执行前必做

```bash
cd /root/Finance
git status --short
PYTHONPATH=/root/Finance pytest backend/tests/test_redis_*.py -q
```

### 10.2 逐里程碑规则

1. **只执行当前里程碑**，不得跨越。
2. 执行前运行 `git status --short` 确认无意外变更。
3. 编辑文件前先阅读文件现状（不要凭记忆）。
4. 完成每个里程碑的标志性动作后，**立即运行对应测试验证**。
5. 测试不通过 → 分析失败原因 → 最小修复 → 重新测试。
6. 连续两次修复尝试仍失败 → **停止**，产出失败报告。
7. 测试通过 → 记录证据 → 更新 `Progress` 表 → 进入下一里程碑。
8. 不得在未经验证的情况下声称"完成"。

### 10.3 停止条件

- 发现需要修改 `Forbidden Changes` 范围内的文件 → 停止并请求决策。
- 发现与 `docs/项目描述.md` 或 `AGENTS.md` 冲突 → 停止并说明冲突。
- 连续两次修复失败 → 停止并产出失败报告（含已尝试方案、失败日志、建议）。
- 如果某个里程碑的变更导致现有测试失败 → 停止并修复，不得跳过。

### 10.4 质量门禁

所有里程碑完成后必须通过以下门禁：

```bash
# 1. Redis 测试套件
cd /root/Finance && PYTHONPATH=/root/Finance pytest backend/tests/test_redis_*.py backend/tests/test_report_*.py -q

# 2. 单链路检查
python /root/Finance/scripts/check_redis_single_chain.py

# 3. 健康检查（redis_status 必须是 ok/disabled/degraded 之一）
curl -fsS http://localhost:8000/api/health | python -m json.tool

# 4. 前端构建
cd /root/Finance/frontend && npm run build
```

---

## 11. 回滚方案

### 11.1 实现前

回滚就是丢弃本 PLAN.md。未产生的代码不需要 "还原"。

### 11.2 实现中

每个里程碑的变更范围小且独立，可逐里程碑回滚：

| 里程碑 | 回滚操作 |
|--------|---------|
| M0 | 不涉及代码变更，无需回滚 |
| M1 | 删除 `KeyBuilder` 新增方法；删除 `command_hasher.py` 及对应测试 |
| M1A | 从 `cache_service.py` 删除 `set_if_absent()` 方法；恢复 FakeRedis 的 `set()` 签名 |
| M2 | 删除 `routers/report.py` 中幂等检查代码；删除 `idempotency.py` 及对应测试 |
| M3 | 删除 `workflow_runner.py` 中 `_sync_status_to_redis` 调用和 stage 追踪代码；删除 `ReportStatusResponse` 新增字段；恢复 `get_report_status` 原 DB 直读逻辑；删除测试文件 |
| M4 | 删除 SSE 路由代码；删除 `sse_manager.py`；删除 `AuthMiddleware` 新增公开路径；删除 `workflow_runner` 中 `publish_status` 调用；删除测试文件 |
| M5 | 恢复 `useReport.ts` 至仅有轮询版本；删除 `api/index.ts` 新增类型/函数 |
| M6 | 从 `nginx/default.conf` 删除 `/api/report/events` location block |

### 11.3 紧急回滚

如果整个功能需要快速下线：

1. 将 `REDIS_ENABLED` 设为 `False` — 幂等、双写、SSE 推送全部自动降级。
2. 删除 SSE 路由（可选，不影响核心功能）。
3. 前端保留轮询兜底逻辑即可正常工作。

### 11.4 分支策略

当前分支 `feature/redis-integration-phase1` 已包含 Redis 基础设施。建议：
- 在每个里程碑完成后做一次 commit（含测试通过证明）
- 如果中间发现重大问题，可 revert 单个 commit 而不丢失其他里程碑

---

## 12. 治理文档区

### 12.1 Progress（进度记录）

> **说明**：实现过程中逐项打勾 `[x]`，记录完成日期与验证结果。

| Milestone | 目标 | 状态 | 完成日期 | 验证结果 |
|-----------|------|------|---------|---------|
| M0 | 安全与基线检查 | ⬜ 待开始 | - | - |
| M1 | KeyBuilder 扩展 + 命令规范化 | ⬜ 待开始 | - | - |
| M1A | CacheService.set_if_absent() 原子写 | ⬜ 待开始 | - | - |
| M2 | 报告幂等层（原子占位 + 并发安全） | ⬜ 待开始 | - | - |
| M3 | Redis 双写 + status 读路径 | ⬜ 待开始 | - | - |
| M4 | SSE 进度推送端点（单进程） | ⬜ 待开始 | - | - |
| M5 | 前端 SSE + 轮询兜底 + 阶段展示 | ⬜ 待开始 | - | - |
| M6 | Nginx SSE 适配（Docker 部署必须） | ⬜ 待开始 | - | - |

### 12.2 Decision Log（决策记录）

> **说明**：实现过程中如有与原计划不同的决策，在此记录原因和选择。

| # | 决策项 | 原计划 | 实际选择 | 原因 | 日期 |
|---|--------|--------|---------|------|------|
| 1 | 幂等实现方式 | get-then-set（两层操作，有竞态窗口） | 原子 SETNX 占位（先 `set_if_absent` 再建 DB） | Codex 审查指出原方案在并发下不安全；改为 Redis 层原子占位消除竞态 | 2026-06-16 |
| 2 | CacheService 是否可修改 | 只读（禁止修改） | 允许 Minor 扩展：新增 `set_if_absent()`（约15行，仅暴露 `redis-py` 的 `nx` 参数） | 原"只读"约束与"需要 SETNX"矛盾；`set_if_absent()` 是最小必要扩展 | 2026-06-16 |
| 3 | current_stage 追踪 | 全局 `_current_stage_cache` 字典 | 闭包内局部变量，通过 `_update_report` kwargs 传入 | Codex 指出全局缓存有内存泄漏和重启丢失风险；闭包变量随任务生命周期自然释放 | 2026-06-16 |
| 4 | "语义相同"表述 | 使用"语义相同"描述幂等判定 | 改为"规范化文本相同" | 实际只做空白处理+hash，不能判断语义等价（"分析茅台"和"分析贵州茅台"语义可能相同但hash不同） | 2026-06-16 |
| 5 | SSE 多 worker 支持 | 未明确说明 | 明确标注"本阶段仅支持单 uvicorn worker 进程" | 单进程内存队列方案在多 worker 下消息会丢失；多 worker 方案（Redis Pub/Sub）为后续 Out of Scope | 2026-06-16 |
| 6 | Nginx 配置 | 错误路径 `docker/nginx.conf`，标记为可选 | 正确路径 `docker/nginx/default.conf`，标记为 Docker 部署必做 | 实际文件路径确认；Nginx 缓冲会影响 SSE，Docker 验收必须覆盖 | 2026-06-16 |
| 7 | 前端 completed 事件处理 | `_fetchReport()` 无 await，status 硬编码 pending | completed 事件 async handler + await；generateReport 使用后端返回的实际 status | 原代码可能导致报告未加载完就设为完成；幂等命中已完成任务时需直接拉报告 | 2026-06-16 |
| 8 | 测试覆盖 | 缺并发测试 | 增加 10 并发幂等测试、Redis 写失败不阻塞 DB 测试、SSE 重连测试、跨用户访问测试 | Codex 指出缺少最关键用例 | 2026-06-16 |
| 9 | SSE 鉴权安全 | 未说明 URL 含 token 的风险 | 日志不得打印完整 URL；AuthMiddleware 公开路径 ≠ 免登录，内部自行校验 token | 防止 token 泄漏到日志 | 2026-06-16 |
| 10 | SSE 连接生命周期 | 缺乏断线检测和队列限制 | 增加 `request.is_disconnected()`、队列 `maxsize=32`、终态后清理注册表 entry | 防止内存泄漏和 worker 泄漏 | 2026-06-16 |

### 12.3 Surprises & Discoveries（意外与发现）

> **说明**：实现过程中发现的非预期行为、边界情况、遗漏点。

| # | 发现 | 影响 | 处理方式 | 日期 |
|---|------|------|---------|------|
| - | 暂无 | - | - | - |

### 12.4 Outcomes & Retrospective（结果与回顾）

> **说明**：全部完成后填写。

（待补充）

---

## 13. 附录：开源参考与设计思路

> **本计划的设计不仅基于项目自身的 Requirement Spec，还参考了以下开源实现和大厂最佳实践。这些参考材料帮助确认了技术选型的合理性，并提供了实现细节的参考。**

### 13.1 FastAPI SSE 实现参考

**参考来源**：FastAPI 官方文档 + `sse-starlette` 库

**核心思路**：
- FastAPI 的 `StreamingResponse` 结合 `text/event-stream` media type 即可实现标准 SSE，无需额外依赖。
- `sse-starlette`（GitHub: sysid/sse-starlette）在 FastAPI 生态中广泛使用，提供了 `EventSourceResponse` 封装。
- **本计划采用原生 `StreamingResponse`**，理由：
  - 减少外部依赖，与项目"最小依赖"原则一致。
  - 本项目的 SSE 场景简单（单任务单连接，无广播），不需要 `sse-starlette` 的复杂特性。
  - 原生实现更可控，便于调试和降级处理。

**关键实现模式**（FastAPI 官方示例）：
```python
from fastapi.responses import StreamingResponse
import asyncio

async def event_generator():
    while True:
        data = await get_next_event()
        if data is None:
            break
        yield f"data: {json.dumps(data)}\n\n"
    yield "event: done\ndata: {}\n\n"

@app.get("/events")
async def sse_endpoint():
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
```

**SSE vs WebSocket 对比**（参考 MDN 文档）：
| 特性 | SSE | WebSocket |
|------|-----|-----------|
| 方向 | 单向（服务端 → 客户端） | 双向 |
| 协议 | HTTP（标准） | 独立协议（ws://） |
| 断线重连 | 浏览器自动 | 需手动实现 |
| 适用场景 | 进度推送、通知、日志流 | 实时聊天、协作编辑 |
| 本项目适用性 | ✅ 报告进度推送（单向） | ❌ 不需要双向，过度设计 |

### 13.2 幂等（Idempotency）模式参考

**参考来源**：Stripe API 设计 + Redis `SETNX` 模式

**Stripe 的幂等 Key 模式**（行业标杆）：
- Stripe API 使用 `Idempotency-Key` HTTP header 实现支付请求的幂等。
- 服务端在第一次收到 `Idempotency-Key` 时，将响应缓存在 Redis 中（TTL 24 小时）。
- 后续相同 `Idempotency-Key` 的请求直接返回缓存的响应。
- 我们借鉴了 Stripe 的核心思路，但做了简化适配：不需要前端传 Key，而是后端通过 `user_id + command_hash` 自动生成幂等 Key。

**Redis SETNX 模式**（redis.io 官方文档）：
```python
# 原子操作：只有 key 不存在时才设置（相当于 SET NX）
# 返回 True 表示第一次设置（需创建任务）
# 返回 False 表示 key 已存在（幂等命中）
is_new = await redis.set(key, value, nx=True, ex=ttl)
```

**但本项目使用 CacheService.set() 的间接方式**：
- `CacheService.set()` 使用的是 `redis.set(key, value, ex=ttl)`（覆盖写入），不是 SETNX。
- 因此幂等逻辑的实现方式是：**先 `get`，再根据命中情况决定 `set`**。
- 两个操作之间理论上存在竞态窗口，但考虑到：
  - 同一用户的重复提交间隔在毫秒级
  - 竞态最坏结果是多创建一个任务（而非数据丢失）
  - 使用分布式锁来消除竞态会增加复杂度
- **决定**：先 get 再 set，不引入额外的分布式锁。如果后续发现竞态问题严重，再引入 `CacheService.lock()` 加锁。

### 13.3 Cache-Aside（旁路缓存）模式

**参考来源**：Microsoft Azure Architecture Center

**经典 Cache-Aside 流程**：
```
读：App → Cache → (miss) → DB → 回填 Cache → 返回
写：App → DB → (成功) → 失效/更新 Cache
```

**本项目中的应用**：
- **幂等**：写路径（新任务创建后 SET Redis Key）；读路径（请求前 GET Redis Key）
- **状态快照**：写路径（DB 更新后同步 SET Redis）；读路径（GET 优先 Redis，miss 回源 DB）

**与标准 Cache-Aside 的区别**：
- 标准 Cache-Aside 的写路径通常是"失效 Cache"（invalidate），而非"更新 Cache"。
- 本项目的状态快照选择了"更新 Cache"，理由是：
  - 状态快照是高频读取的数据，invalidate 后会导致大量 cache miss → DB 直接查询
  - Redis 状态与 DB 状态的最终一致性（<1s 延迟）是可接受的
  - TTL 机制保证了即使更新失败，旧数据也会在 600s 内过期

### 13.4 TTL 抖动（Thundering Herd Protection）

**参考来源**：Facebook/Memcache 的 Lease 机制 + Redis 官方建议

**问题**：大量 Key 在同一时间过期，导致瞬时 DB 压力激增（Thundering Herd / 惊群效应）。

**解决方案**（已在 Phase 1 基础设施中实现）：
```python
def ttl_with_jitter(base_ttl: int, jitter_ratio: float = 0.1) -> int:
    """TTL 加 ±10% 随机抖动"""
    delta = max(1, int(base_ttl * jitter_ratio))
    return base_ttl + random.randint(-delta, delta)
```

**本项目直接复用此函数**，不需要额外开发。每个 Key 的实际 TTL 都会在 540s–660s（10min±10%）之间，自然分散过期时间。

### 13.5 降级策略（Graceful Degradation）

**参考来源**：Netflix Hystrix（断路器模式）+ AWS Well-Architected Framework

**核心原则**：
1. Redis 是**加速层**，不是**必需层**。
2. 任何 Redis 操作失败 → 降级到纯 DB 路径。
3. 降级行为对用户透明（功能正常工作，只是可能缺少幂等保护或阶段名称）。

**本项目降级路径**（三层保障）：
```
Layer 1: Redis 可用 → 幂等保护 + 热读 + SSE 推送
Layer 2: Redis 异常 → 自动降级，跳过 Redis 操作
Layer 3: SSE 连接断开 → 前端自动退回 2s 轮询
```

### 13.6 前端 SSE 实现参考

**参考来源**：MDN EventSource API + GitHub 开源项目

**浏览器原生 EventSource**（无需额外 npm 包）：
```typescript
const es = new EventSource('/api/report/events/task123?token=xxx')
es.addEventListener('status', (e) => { /* 处理进度 */ })
es.addEventListener('completed', (e) => { /* 处理完成 */ })
es.onerror = () => { /* 回退到轮询 */ }
```

- `EventSource` API 原生支持自动重连（`Last-Event-ID` header），但本项目选择手动控制重连逻辑以便在失败时切换到轮询。
- SSE 的 `?token=` 鉴权模式在浏览器 `EventSource` 中原生支持（query parameter），不需要自定义 header。

### 13.7 对本计划的启示总结

| 参考来源 | 借鉴了什么 | 做了哪些适配 |
|---------|-----------|------------|
| Stripe API Idempotency | 幂等 Key 的概念 + 缓存的响应返回 | 自动生成幂等 Key（非前端传入）；TTL 从 24h 缩短为 10min |
| Azure Cache-Aside | 读优先 cache + miss 回源 DB 的模式 | 写路径选择"更新 cache"而非"失效 cache" |
| FastAPI SSE 官方示例 | StreamingResponse + text/event-stream | 增加心跳、降级到轮询、?token= 鉴权 |
| Redis SETNX | 原子幂等 Key 创建 | 在 CacheService 新增 `set_if_absent()` 暴露 `nx=True`，实现真正的原子占位（而非 get-then-set） |
| Netflix Hystrix | 降级开关 + 断路器理念 | 简化为 "try Redis → except → fallback DB" |
| Facebook Lease | TTL 抖动防惊群 | 直接复用 Phase 1 的 `ttl_with_jitter` |

---

**计划结束。**  

请按 Milestone 0 → 1 → 1A → 2 → 3 → 4 → 5 → 6 顺序逐里程碑执行。执行结束后更新 §12.1 Progress 表。
