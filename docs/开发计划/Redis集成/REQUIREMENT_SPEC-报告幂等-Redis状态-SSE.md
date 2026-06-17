# REQUIREMENT_SPEC.md

> **模块**：报告模式 · Redis 任务治理（幂等 + 状态快照 + SSE 进度）
> **版本**：v1.0
> **日期**：2026-06-16
> **状态**：需求已冻结（用户决策 A/B/A/B/A/A 已确认）
> **下一步**：Codebase Reconnaissance → Requirement Clarification → Solution Tradeoff → Plan Freezing

---

## 1. Task Type

**Primary type:** New Feature

**Secondary types:**
- Performance Optimization（减少重复长任务与 DB 轮询压力）
- Engineering Governance（长任务幂等、状态治理、降级策略）
- Project Packaging / Interview Demo Improvement（简历/面试可讲述的工程能力）

**Classification rationale:**
本任务不是在改 Agent 报告分析逻辑，而是在现有 2–3 分钟报告长任务链路上，新增 Redis 幂等、任务状态热读与 SSE 进度推送三层工程治理能力，属于典型的新增运行时状态层能力。

---

## 2. Requirement Restatement

### 2.1 要改什么

在现有「报告模式」链路中，增加以下能力：

1. **报告幂等（Idempotency）**  
   同一用户在短时间内对**语义相同**的报告请求重复提交时，只创建一个后台任务；后续请求直接返回已有 `task_id / report_id / status`，不再重复跑多 Agent 工作流。

2. **Redis 任务状态快照（Task Status Snapshot）**  
   后台报告任务在关键阶段更新时，除写 PostgreSQL `reports` 表外，同步写入 Redis 轻量状态（不含报告正文）。状态查询优先读 Redis，miss 或 Redis 不可用时回源 DB。

3. **SSE 实时进度（Server-Sent Events）**  
   新增 `GET /api/report/events/{task_id}`，以 `text/event-stream` 向浏览器推送任务阶段与进度变更。前端展示阶段名称（如「基本面分析中」），SSE 失败时自动退回现有 2 秒轮询。

### 2.2 为什么需要

- 用户重复点击「生成报告」会创建多个相同后台任务，浪费 LLM / Tushare / Web Search 配额。
- 报告耗时 2–3 分钟，用户缺少细粒度进度反馈，容易误以为系统卡住。
- 前端每 2 秒轮询 `reports` 表，任务增多时增加不必要 DB 读压力。
- 相比「工具结果缓存」，本能力更贴近长任务工程治理，适合项目描述与面试讲述。

### 2.3 期望结果

- 误点重复生成时，系统复用同一任务，不重复跑 Agent。
- 用户能看到「正在做哪一步」的阶段文案与进度百分比。
- Redis 可用时减轻状态查询 DB 压力；Redis 不可用时主链路仍可用。
- PostgreSQL 仍是报告正文与权威状态的最终存储。

### 2.4 明确不改变

- 多 Agent 报告工作流的业务逻辑与分析内容。
- 报告正文、审计 trace、execution logger 的持久化方式（仍落 PostgreSQL / 文件系统）。
- 现有 REST 接口契约的向后兼容（`/generate`、`/status/{task_id}`、`/report/{id}`、`/history`）。
- 对话模式 STM Redis 化（属于独立需求，不在本 spec 范围）。

---

## 3. Problem Source

| 来源 | 说明 |
|------|------|
| Developer observation | 报告生成 2–3 分钟，重复点击会重复起任务 |
| Developer observation | 进度仅百分比，无阶段名称，体验像「卡住」 |
| Developer observation | 前端 2 秒轮询直接查 DB |
| Product requirement | 长任务需要幂等与进度可观测 |
| Interview/project packaging need | 需要可讲述的 Redis + 长任务治理故事 |

---

## 4. Current Behavior

### 4.1 报告创建（`POST /api/report/generate`）

- 每次请求生成新的 `task_id`、`report_id`（UUID）。
- 在 `reports` 表插入一行：`status=pending`，`progress=0`。
- 通过 `BackgroundTasks` 调用 `run_report_task`。
- **无幂等**：相同 `command` 重复提交会创建多个任务。

**相关模块：**
- `backend/routers/report.py`
- `backend/services/report/workflow_runner.py`
- `backend/db/models.py`（`Report` 模型）

### 4.2 后台任务进度（`run_report_task`）

- 启动时：`status=running`，`progress=10`。
- 按 LangGraph 节点事件更新 `progress`：
  - `fundamental_analyst` → 35
  - `technical_analyst` → 50
  - `value_analyst` → 65
  - `news_analyst` → 80
  - `memory_read_node` → 85
  - `summarizer` → 95
  - 完成 → `status=completed`，`progress=100`，写入 `content`
- 失败 → `status=failed`，`progress=0`，`error_msg` 有值。
- **仅写 PostgreSQL**，不写 Redis。

### 4.3 状态查询（`GET /api/report/status/{task_id}`）

- 直接查询 `reports` 表。
- 返回：`task_id`、`status`、`progress`、`report_id`（完成时）、`error_msg`。
- **无 `current_stage` 字段**（阶段信息未暴露给前端）。

### 4.4 前端（`frontend/src/composables/useReport.ts`）

- `POLL_INTERVAL = 2000` ms。
- 生成后 `setInterval` 轮询 `/api/report/status/{task_id}`。
- 完成时拉取 `/api/report/{report_id}` 获取正文。
- **无 SSE / EventSource**。

### 4.5 Redis 基础设施（已存在，未接入报告业务）

- `KeyBuilder.report_idempotency(user_id, stock_code, query_hash)` 已定义。
- `KeyBuilder.report_status(task_id)` 已定义。
- `CacheService`（Cache-Aside、Envelope、TTL 抖动、降级）已实现。
- 默认 `REDIS_ENABLED=False`；Redis 故障不阻断应用启动。

### 4.6 用户可感知症状

- 短时间内多次点击「生成报告」→ 多个任务并行跑，可能产生多份报告。
- 进度条只有 0–100%，不知道当前在「基本面」还是「新闻」阶段。
- 网络或后端慢时，2 秒轮询间隔带来进度更新延迟。

---

## 5. Expected Behavior

### 5.1 报告幂等

**Given** 用户 U 在 10 分钟内，对规范化后语义相同的 `command` 多次调用 `POST /api/report/generate`  
**When** 第一次请求已成功创建任务 T1  
**Then** 后续请求应返回 T1 的 `task_id`、`report_id`、`status`，**不**新建 `reports` 行、**不**再起 `run_report_task`

**Given** 用户 U 提交语义不同的 `command`（规范化 hash 不同）  
**When** 已有其他报告任务在运行  
**Then** **允许**并行创建新任务（不限制单用户同时只能一个报告）

### 5.2 Redis 状态快照

**Given** 报告任务 T 处于 running / completed / failed 任一状态  
**When** `workflow_runner` 更新 DB 进度  
**Then** 应同步写入 Redis `report:status:{task_id}`，value 仅含轻量字段（见 §7.2 已决字段），不含 `content`

**Given** 前端或 SSE 查询任务 T 的状态  
**When** Redis 命中且数据有效  
**Then** 从 Redis 返回；miss 或 Redis 不可用时回源 `reports` 表

**Given** 报告任务完成或失败  
**When** 状态写入 Redis  
**Then** Key TTL 为 **10 分钟**（完成后仍保留 10 分钟供页面重开查看）

### 5.3 SSE 进度推送

**Given** 用户已创建任务 T 且持有有效鉴权  
**When** 前端建立 `EventSource` 连接 `GET /api/report/events/{task_id}`  
**Then** 服务端以 `text/event-stream` 推送状态变更事件，包含 `status`、`progress`、`current_stage`（阶段名称）

**Given** SSE 连接断开或建立失败  
**When** 前端检测到错误  
**Then** 自动回退到现有 2 秒轮询 `/api/report/status/{task_id}`，用户仍可完成报告生成流程

### 5.4 阶段名称展示（前端）

**Given** 报告任务进入某 LangGraph 节点  
**When** 前端收到 SSE 或轮询状态  
**Then** UI 应展示用户可理解的阶段文案，例如：
- `pending` → 「等待开始」
- `fundamental_analyst` → 「基本面分析中」
- `technical_analyst` → 「技术面分析中」
- `value_analyst` → 「估值分析中」
- `news_analyst` → 「新闻与舆情分析中」
- `summarizing` / `summarizer` → 「报告汇总中」
- `completed` → 「生成完成」
- `failed` → 「生成失败」+ 错误信息

---

## 6. Scope

### 6.1 In Scope

**后端**
- `generate_report`：幂等 Key 读写（`SET NX` 或等价封装）；命中则返回已有任务信息。
- `command` 规范化与 hash（用于幂等 Key，不存原文）。
- `run_report_task`：DB 更新时双写 Redis 状态快照；补充 `current_stage` 语义（DB 或仅 Redis，见 Unknown Scope）。
- `get_report_status`：优先 Redis，降级 DB；响应增加 `current_stage`（若采用）。
- 新增 `GET /api/report/events/{task_id}` SSE 端点；鉴权与 `task_id` 归属校验。
- Redis 关闭/异常时的降级路径与 trace/日志字段。

**前端**
- `useReport.ts`（及相关 UI）：SSE 优先 + 轮询兜底；展示阶段名称与进度。

**测试**
- 幂等命中/miss、Redis 可用/不可用、SSE 推送、降级轮询的单元/集成测试。

**文档（最小）**
- 本 spec 与后续 Plan 对齐；可选在 `docs/项目描述.md` 增加一小节（实现完成后）。

### 6.2 Out of Scope

- 多 Agent 报告内容、Prompt、工具调用逻辑变更。
- Redis 存储报告正文、完整 command 原文、用户敏感信息。
- 工具执行层 Redis 限流 / provider cooldown / 跨任务 inflight 槽位（后续独立需求）。
- 对话模式 STM Redis 化（`stm:state` / `stm:tail` / `stm:summary`）。
- 新消息队列（RabbitMQ/Kafka）、Redis Pub/Sub 复杂方案、Redis Cluster。
- 数据库表结构大改（若仅需增加 `current_stage` 列，可在 Solution Tradeoff 阶段再定，本 spec 不强制）。
- 修改 `frontend/dist/`、生产环境配置提交。

### 6.3 Unknown Scope（待 Codebase Recon 后确认）

- `current_stage` 是否持久化到 `reports` 表，还是仅存在于 Redis 快照（影响 SSE 断线后轮询能否拿到 stage）。
- SSE 推送机制：短轮询 Redis 快照 vs 内存订阅（单进程足够；多 worker 需 Recon 评估）。
- 幂等 Key 中 `stock_code` 是否在解析前为空时使用占位符（解析在 `run_report_task` 内较晚发生）。
- `report_idempotency` KeyBuilder 签名含 `stock_code`，与决策 B（仅 normalized command hash）的 Key 形态需在 Tradeoff 中统一。

---

## 7. Constraints

### 7.1 Hard Constraints

| 约束 | 说明 |
|------|------|
| DB 为权威真相源 | 报告正文、`status`、`progress` 最终以 `reports` 表为准 |
| Redis 故障不阻断主链路 | `REDIS_ENABLED=False` 或 Redis 不可用时，生成/查询/完成报告仍可用 |
| 接口向后兼容 | 未升级前端时，仅靠 `/generate` + `/status` 仍可完成全流程 |
| 不写完整报告到 Redis | Redis value 仅轻量状态字段 |
| 鉴权不变 | SSE 与 status 均需校验用户只能访问自己的 `task_id` |
| 日志不泄露敏感信息 | 不打印完整 command、完整 Redis Key；command 用 hash 标识 |
| 本阶段不写业务代码外的无关重构 | 遵循 AGENTS.md 最小改动原则 |

### 7.2 Soft Constraints

- 复用现有 `CacheService`、`KeyBuilder`、`CacheEnvelope`，不新建第二套 Redis 客户端。
- 用户可见文案使用中文。
- 幂等与状态逻辑便于面试口述（Key 设计、降级、幂等 vs 锁）。
- SSE 实现从简，单实例部署可工作；多 worker 行为在 Plan 中说明。

### 7.3 用户已确认决策（冻结）

| # | 决策项 | 用户选择 | 具体含义 |
|---|--------|----------|----------|
| 1 | 幂等时间窗口 TTL | **A** | **10 分钟**；窗口内相同语义请求复用同一任务 |
| 2 | 「同一报告」判定 | **B** | **`user_id` + 规范化 `command` 的 hash**；不依赖原始空格/大小写差异 |
| 3 | SSE 端点路径 | **A** | **`GET /api/report/events/{task_id}`** |
| 4 | 前端阶段展示 | **B** | **展示阶段名称**（如「基本面分析中」），不仅进度条 |
| 5 | Redis 状态 TTL | **A** | 任务完成/失败后，状态 Key **再保留 10 分钟** |
| 6 | 多任务并行 | **A** | **允许**同一用户同时跑多个不同语义的报告；仅对语义相同请求幂等 |

### 7.4 幂等与状态 Key 约定（需求层，非最终实现）

**幂等 Key（逻辑形态）：**
```text
finagent:{env}:report:idempotency:{user_id}:{query_hash}
```
- `query_hash` = 规范化后的 `command` 字符串的哈希（算法在 Tradeoff 阶段选定，如 SHA256 前 16 位）。
- TTL = **600 秒（10 分钟）**。
- Value = `{ task_id, report_id, status, created_at }`（轻量 JSON，包在 CacheEnvelope 内）。

**状态 Key（逻辑形态）：**
```text
finagent:{env}:report:status:{task_id}
```
- TTL = 任务进行中刷新；终态（completed/failed）后 **600 秒** 过期。
- Value 字段（不含 `content`）：
  - `task_id`
  - `report_id`
  - `status`（pending / running / completed / failed）
  - `progress`（0–100）
  - `current_stage`（机器可读 stage id，如 `fundamental_analyst`）
  - `current_stage_label`（用户可读中文，如「基本面分析中」）
  - `error_msg`（失败时）
  - `updated_at`（ISO8601）

**command 规范化（需求层规则）：**
- 去除首尾空白；
- 连续空白合并为单个空格；
- 全角/半角标点不做激进替换（避免误合并不同语义）；
- 规范化后再计算 `query_hash`。

---

## 8. Stakeholders and Impact

| 干系人/系统 | 影响 |
|-------------|------|
| 终端用户 | 误点不重复跑任务；可见阶段进度，减少「卡住」焦虑 |
| 开发者/维护者 | 新增幂等、双写、SSE 逻辑；需补充测试与排障文档 |
| 面试官/简历阅读者 | 获得「长任务幂等 + Redis 热状态 + SSE + 降级」完整叙事 |
| `backend/routers/report.py` | 幂等、status 读路径、新增 SSE 路由 |
| `backend/services/report/workflow_runner.py` | 进度更新时双写 Redis、写入 stage |
| `frontend/src/composables/useReport.ts` | SSE + 轮询兜底 + 阶段 UI |
| PostgreSQL `reports` | 仍为权威；轮询读压力有望降低 |
| Redis | 新增短 TTL 小对象读写；故障时降级 |
| Agent 运行时 | 无逻辑变更；仅外围状态同步 |

---

## 9. Success Criteria

### 9.1 Functional Criteria

1. **幂等-命中**：同一 `user_id` + 相同规范化 `command`，10 分钟内第 2 次 `POST /generate` 返回与第 1 次相同的 `task_id`，且 `reports` 表无新增行。
2. **幂等-未命中**：不同规范化 `command` 可并行创建多个任务。
3. **Redis 双写**：`run_report_task` 每次 DB 进度更新后，Redis `report:status:{task_id}` 存在且字段与 DB 一致（允许短暂最终一致延迟 &lt; 1s）。
4. **状态读-Redis 优先**：`GET /status/{task_id}` 在 Redis 可用时优先返回 Redis 快照。
5. **SSE 推送**：连接 `GET /api/report/events/{task_id}` 后，能收到至少一次含 `current_stage` / `current_stage_label` 的事件；终态时推送 completed 或 failed。
6. **阶段 UI**：前端在生成过程中展示中文阶段名称，而非仅百分比。

### 9.2 Compatibility Criteria

1. 现有 `ReportTaskResponse`、`ReportStatusResponse` 字段保持兼容；新增字段（如 `current_stage`）为可选扩展，旧前端忽略不报错。
2. `REDIS_ENABLED=False` 时，行为与当前版本一致（无幂等、纯 DB 轮询），除可选新增 `current_stage` 外无回归。
3. 现有报告历史、删除、下载接口不受影响。

### 9.3 Reliability Criteria

1. Redis 连接失败、超时、写入失败：**不**导致 `/generate` 或报告生成失败；记录 `fallback_reason`。
2. 幂等 Redis 写入失败：允许降级为「可能重复任务」，但须打日志；**不** 500。
3. SSE 客户端断开后，用户通过轮询仍可获得最终状态。
4. 非法或他人 `task_id` 访问 SSE/status 返回 403/404，不泄露任务信息。

### 9.4 Observability Criteria

关键路径日志或 trace 应能回答：
- `report_idempotency_hit`（true/false）
- `cache_hit` / `fallback_reason`（redis_disabled / redis_unavailable / cache_miss）
- `report_stage` / `report_progress`
- `sse_client_connected` / `sse_push_count`（至少后端可统计）

不记录：完整 command、完整 Redis Key、报告正文。

### 9.5 Testing Criteria

| 测试类型 | 最低要求 |
|----------|----------|
| 单元测试 | command 规范化与 hash 稳定性；幂等 Key 命中逻辑（mock CacheService） |
| 集成测试 | 双次 generate 同 command → 同 task_id；Redis 关闭时 generate 仍成功 |
| 集成测试 | workflow_runner 更新后 Redis 快照字段正确 |
| 手动验收 | 浏览器：生成报告 → 见阶段文案 → 完成拉正文；快速双击 generate → 单任务 |
| 手动验收 | 停 Redis → 报告仍可生成完成；前端轮询正常 |

**性能基线：** Not provided（本阶段不强制量化 P95；可在 Release Observation 阶段补采）。

---

## 10. Risks and Mitigations

| 风险 | 缓解 |
|------|------|
| 规范化过强，不同意图被误判为同一报告 | 规范化规则保守（仅空白处理）；hash 冲突概率极低；用户可改 wording 发起新任务 |
| 规范化过弱，细微差异导致幂等失效 | 文档说明规则；后续可加 stock_code 到 Key（Out of Scope 本阶段） |
| Redis 与 DB 状态短暂不一致 | DB 为权威；status 接口可对比 `updated_at`；终态以 DB 为准 |
| SSE 多 worker 下推送不到正确连接 | Recon 确认部署形态；Plan 中选型（Redis 轮询推 SSE 或单 worker 假设） |
| `KeyBuilder.report_idempotency` 含 `stock_code` 与决策 B 不一致 | Tradeoff 阶段统一：扩展 KeyBuilder 或新增 `report_idempotency_by_query` |
| 幂等窗口内用户想「强制重新生成」 | 10 分钟后 Key 过期可新建；或后续加 `force=true`（本阶段 Out of Scope） |
| SSE 长连接占用 worker | 设置合理超时与心跳；连接数有限 |
| 前端 SSE 与轮询双写状态冲突 | 单一状态源（composable 内合并）；SSE 优先更新，轮询兜底 |

---

## 11. Open Questions

以下问题**不阻塞**进入 Codebase Reconnaissance，但应在 Recon / Tradeoff 阶段闭合：

| # | Question | Why it matters | Suggested default |
|---|----------|----------------|-------------------|
| 1 | `current_stage` 是否写入 `reports` 表？ | 轮询兜底时能否展示阶段名 | **仅 Redis**；status 接口从 Redis 读 stage，miss 时 stage 为空 |
| 2 | 幂等 Key 是否调整 KeyBuilder 去掉 `stock_code` 参数？ | 与决策 B 对齐 | **新增** `report_idempotency_by_user_query(user_id, query_hash)` |
| 3 | SSE 鉴权：Query `?token=` 还是 Header？ | 浏览器 EventSource 限制 | **复用** chat WebSocket 的 `?token=` 模式 |
| 4 | 规范化 hash 算法 | 跨环境一致性 | **SHA256**，取 hex 前 16 字符 |
| 5 | 幂等命中时 HTTP 状态码 | REST 语义 | **200** 返回已有任务（非 201） |

---

## 12. Handoff to Next Step

**Next step:** 使用 **Codebase Reconnaissance** skill，只读勘察以下内容：

1. `backend/routers/report.py` — 路由、鉴权、BackgroundTasks 调用链  
2. `backend/services/report/workflow_runner.py` — 进度更新点、节点名与 progress 映射  
3. `backend/services/agent_service.py` — `run_report_task` 入口关系  
4. `backend/integrations/redis/` — CacheService、KeyBuilder、lock 可复用 API  
5. `backend/schemas/report.py` — 请求/响应 schema 扩展点  
6. `frontend/src/composables/useReport.ts`、`frontend/src/api/index.ts` — 轮询与 API 类型  
7. `frontend` 报告相关 Vue 组件 — 进度 UI 挂载点  
8. 现有 chat WebSocket/SSE 鉴权模式 — 复用参考  
9. `backend/tests/` — Redis 测试 fixture 与 report 相关测试空白  

**Recon 产出物：** `CODEBASE_RECON.md`（或等价文档），含相关文件清单、数据流、风险区、与本文 Unknown Scope 的闭合建议。

**本步骤禁止：** 修改业务代码、写实现计划中的具体函数签名、跑实现性改动。

---

## Decisions Needed Before Codebase Reconnaissance

用户已确认项（**无需再议**）：

- [x] 幂等 TTL = 10 分钟
- [x] 幂等判定 = `user_id` + 规范化 command hash
- [x] SSE 路径 = `GET /api/report/events/{task_id}`
- [x] 前端展示阶段名称
- [x] Redis 状态终态后保留 10 分钟
- [x] 允许多报告并行，仅语义相同幂等

Recon 阶段需闭合的技术项（**有建议默认值，可静默采用**）：

- [ ] `current_stage` 是否落 DB（建议：仅 Redis）
- [ ] KeyBuilder 幂等 Key 形态调整（建议：新增 by_user_query 方法）
- [ ] SSE 鉴权方式（建议：`?token=`）
- [ ] hash 算法（建议：SHA256 前 16 位）

---

## 附录 A：面试追问防守（本需求专用）

| 追问 | 答法要点 |
|------|----------|
| 为什么报告适合 Redis？ | 长任务、重复提交、高频状态查询；Redis 存短 TTL 状态，不存正文 |
| Redis 为什么不能存最终报告？ | 报告是交付物与审计依据，必须 PostgreSQL；Redis 只缓存进度 |
| 幂等和分布式锁区别？ | 幂等防重复创建；锁防并发执行同一任务；本需求以幂等为主 |
| Redis 挂了怎么办？ | 降级：无幂等可能重复任务、status 直查 DB、SSE 不可用则轮询 |
| SSE 断了怎么办？ | EventSource 重连 + 2 秒轮询兜底 |
| 为什么还要保留 DB status？ | DB 是权威；Redis 是热读加速层 |
| 缓存穿透/击穿/雪崩？ | key 来自已鉴权 task_id；TTL 抖动；miss 回源 DB；非热点商品场景风险可控 |

---

## 附录 B：与项目其他 Redis 需求的关系

| 需求 | 关系 |
|------|------|
| Redis 第一阶段基础设施 | **前置依赖**（已完成） |
| STM 热状态 / 上下文热读 | **并行独立**，不在本 spec |
| 工具执行 Redis 限流 | **后续扩展**，不在本 spec |

---

*文档结束。供 Solution Tradeoff / Plan Freezing 使用。*
