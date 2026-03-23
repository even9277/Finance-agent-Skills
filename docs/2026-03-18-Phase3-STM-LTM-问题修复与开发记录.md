## 2026-03-18：Phase 3（LTM）+ STM 增量开发与问题修复记录

> **目的**：把今天这轮“从现象 → 根因 → 修复 → 验证”的全过程沉淀为可复盘文档  
> **适用范围**：Finance 智能投研助手（FastAPI + Vue3 + PostgreSQL + Mem0/pgvector）  
> **阅读收益**：后续遇到类似问题（数据库缺列、Mem0 不生效、入队不消费、Memory Items 为空、embedding 模型 404）能快速定位与恢复

---

### 1. 背景与目标

今天的核心目标分两条线：

- **STM（短期记忆）体验增强**：摘要历史从“压缩比例”改为更直观的展示：  
  **“压缩了 X 条用户消息 + Y 条助手消息 + 时间轴范围（开始→结束）”**，并写入数据库以支持后端/前端一致展示。
- **LTM（长期记忆）稳定性修复**：确保 Phase 3 的 outbox 入队、worker 消费、Mem0 写入、Memory Items 展示链路可用，并可在 PostgreSQL 环境下稳定运行。

---

### 2. 现象 → 根因 → 解决（按时间顺序）

#### 2.1 STM 压缩写快照时报 `UndefinedColumnError`

- **现象**
  - 后端执行 STM 压缩时写入 `session_summaries` 报错：  
    `column "compressed_user_count" of relation "session_summaries" does not exist`
- **根因**
  - 代码已开始写新列，但 PostgreSQL 表还没补齐列。
- **解决**
  - 在 PostgreSQL 执行一次补列（只需一次）：

```sql
ALTER TABLE session_summaries
  ADD COLUMN IF NOT EXISTS compressed_user_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS compressed_assistant_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS start_message_id INTEGER,
  ADD COLUMN IF NOT EXISTS end_message_id INTEGER,
  ADD COLUMN IF NOT EXISTS start_created_at TIMESTAMP,
  ADD COLUMN IF NOT EXISTS end_created_at TIMESTAMP;
```

- **代码侧兜底**
  - `backend/services/chat_service.py::compress_if_needed` 增加了 **“缺列时降级插入旧字段”** 的容错：  
    即使没补列也不影响主链路（对话仍可继续），只是新 UI 信息不完整。

---

#### 2.2 LTM：`'coroutine' object has no attribute 'get_all' / 'search'`

- **现象**
  - 访问 Memory Items 或语义召回时出现：
    - `get_all_memories 失败: 'coroutine' object has no attribute 'get_all'`
    - `search_semantic 失败: 'coroutine' object has no attribute 'search'`
- **根因**
  - `mem0.AsyncMemory.from_config()` 在当前安装的 mem0 版本中可能返回 **协程 coroutine**。  
  - 旧实现未 `await`，导致 `_mem0_client` 实际是 coroutine。
- **解决**
  - `Financial-MCP-Agent/src/memory/mem0_client.py::init_mem0_client` 做了兼容：  
    若 `from_config()` 返回 coroutine，则 `await` 后得到真正的 client。

---

#### 2.3 LTM：Mem0 连接 PostgreSQL 用了默认 `postgres/postgres` 导致认证失败

- **现象**
  - 启动日志出现：`password authentication failed for user "postgres"`
- **根因**
  - Mem0 初始化读取的是 `os.environ`（`os.getenv`），但最初只在 `.env` 里配置了 `DATABASE_URL`，且未确保这些值注入进程环境变量；于是 Mem0 退回默认 `PG_USER=postgres/PG_PASSWORD=postgres`。
- **解决**
  - `backend/main.py` 在初始化 Mem0 之前显式 `load_dotenv(backend/.env)`，并进一步加载 `Financial-MCP-Agent/.env`（模型等配置）。
  - `mem0_client.py::_build_mem0_config()` 增强：当 `PG_*` 缺失时，**从 `DATABASE_URL` 自动解析 host/port/db/user/password**。
- **验证点**
  - 启动日志出现：`[Mem0] AsyncMemory 初始化成功 ✓`

---

#### 2.4 LTM：入队成功但 Memory Items 为空（“明明入队了，为啥看不到？”）

- **现象**
  - `ltm_write_tasks` 表里有大量 `pending`，但 `/api/memory/items` 返回 `items: []`
- **根因（最关键）**
  - **outbox 写到了 PostgreSQL**，但早期的 `ltm_worker` **只读本地 SQLite**（`backend/finance.db`），导致 worker 根本消费不到 Postgres 的 pending 任务，Mem0 无写入。
- **解决**
  - `Financial-MCP-Agent/src/memory/ltm_worker.py` 支持 PostgreSQL outbox：
    - 检测 `DATABASE_URL` 以 `postgresql` 开头则使用 SQLAlchemy 读取/更新 `ltm_write_tasks`
    - 否则才走 SQLite 兼容分支
- **加固**
  - 增加“回收卡住 processing 任务”的逻辑，避免任务长期停留在 `processing` 导致队列不推进。

---

#### 2.5 LTM：Mem0 写入失败（`dict.replace` / `string indices` / 超时）

- **现象**
  - `AttributeError: 'dict' object has no attribute 'replace'`
  - `TypeError: string indices must be integers, not 'str'`
  - `TimeoutError`
- **根因**
  - Mem0 内部对 `messages` 有严格格式预期（`str / dict / list[dict]`），并且在 `infer=True` 时会走 **LLM 抽取 facts** → **对 facts 做 embedding** 的路径；当抽取结果里出现非字符串（dict）就会触发 `.replace()` 崩溃。
  - worker 写入耗时较长时会超时。
- **解决**
  - `ltm_worker.py` 增加：
    - **写入超时**（默认 90s，可通过环境变量调）
    - **消息格式兼容层**（多格式回退）
    - 最关键：**worker 写 Mem0 时 `infer=False`**，跳过“抽取 facts”链路，直接将我们给定的文本入库。

---

#### 2.6 LTM：embedding 模型 404（DashScope compatible-mode 不支持 OpenAI embedding 模型名）

- **现象**
  - `The model text-embedding-3-small does not exist or you do not have access to it`
  - 或 `Unsupported model qwen... for OpenAI compatibility mode`（把聊天模型误当 embedding）
- **根因**
  - DashScope OpenAI compatible-mode 的 embedding 模型命名不是 OpenAI 的 `text-embedding-3-small`；必须使用 DashScope 支持的 embedding 模型名。
- **解决**
  - 引入独立配置：`MEM0_EMBED_MODEL`
  - 将 embedding 模型切换为：**`text-embedding-v2`**（与 1536 维默认维度匹配）
  - `mem0_client.py` 增加启动日志 `config preview`，在启动时打印：
    - `llm_model`
    - `embed_model`
    - `pg host/port/db`
  - 通过触发热重载确保 `.env` 改动被进程加载。

---

#### 2.7 验证：重置部分 failed 任务后，worker 成功写入 Mem0

- **做法**
  - 将一小段任务（例如 id 40-47）从 `failed` 重置回 `pending`，让 worker 在新配置下重跑验证写入链路：

```sql
UPDATE ltm_write_tasks
SET status='pending', retry_count=0, error_msg='', processed_at=NULL
WHERE user_id='<你的user_id>' AND id BETWEEN 40 AND 47;
```

- **结果**
  - `done` 数量明显上升（包含 `add_conversation` 与 `explicit_update`）
  - `/api/memory/items` 返回的条目 id 变成 UUID（Mem0 真实条目），说明已落入向量库。

---

### 3. 关键改动点（文件/模块清单）

#### 3.1 STM（短期记忆）增强

- **后端**
  - `backend/services/chat_service.py`
    - `compress_if_needed`：计算并写入
      - `compressed_user_count`
      - `compressed_assistant_count`
      - `start_message_id/end_message_id`
      - `start_created_at/end_created_at`
    - commit 缺列时降级（仅写旧字段）
- **数据库**
  - `session_summaries` 补列 SQL（见 2.1）
- **前端**
  - `frontend/src/views/ChatView.vue`（摘要历史弹窗展示 X/Y/时间轴；本次不在此文重复展开）

#### 3.2 LTM（长期记忆）稳定性修复

- **Mem0 客户端**
  - `Financial-MCP-Agent/src/memory/mem0_client.py`
    - `from_config` coroutine 兼容（必要时 await）
    - 从 `DATABASE_URL` 解析 PG 连接信息（PG_* 缺失时）
    - `MEM0_EMBED_MODEL` 独立配置与启动时 `config preview` 日志
- **Worker**
  - `Financial-MCP-Agent/src/memory/ltm_worker.py`
    - 支持 PostgreSQL outbox（不再只读 SQLite）
    - 处理超时、失败重试、processing 回收
    - 写 Mem0 时 `infer=False`
- **后端启动**
  - `backend/main.py`
    - 启动前 `load_dotenv(backend/.env)` + `load_dotenv(Financial-MCP-Agent/.env)`
- **配置**
  - `backend/.env`、`Financial-MCP-Agent/.env`
    - 增加并统一：`MEM0_EMBED_MODEL=text-embedding-v2`

---

### 4. 最小可用的“功能路径”（开发/运行路径）

#### 4.1 STM 路径（对话压缩 → 摘要历史）

1) 用户在同一 session 连续对话  
2) 未压缩消息数达到阈值（默认 10）  
3) `compress_if_needed`：
   - 更新 `sessions.running_summary`
   - 标记 `messages.is_compressed`
   - 写入 `session_summaries` 快照（含 X/Y/时间轴字段）
4) 前端“摘要历史”弹窗展示更直观的信息

#### 4.2 LTM 路径（入队 → worker → Mem0 → Memory Items）

1) 对话/显式画像更新触发写入：
   - `explicit_update`：更新画像字段 + 入队任务
   - `add_conversation`：按阈值/压缩轮次入队对话线索
2) 入队落表：PostgreSQL `ltm_write_tasks(status=pending)`
3) `ltm_worker` 轮询 pending：
   - 处理任务 → `mem0_client.add(..., infer=False)`
   - 成功：status=done
   - 失败：retry_count+1；超过阈值标 failed
4) `/api/memory/items`
   - Mem0 有条目时展示 Mem0 真实结果
   - Mem0 暂时为空时回退展示 outbox 轨迹（避免 UI 空白）

---

### 5. 常见坑与排查清单（非常实用）

#### 5.1 启动即失败（Mem0 认证/连接问题）

- 看启动日志是否有：
  - `[Mem0] AsyncMemory 初始化成功 ✓`
  - `config preview: llm_model=..., embed_model=..., pg=...`
- 若出现 `password authentication failed for user "postgres"`：
  - 检查 `backend/.env` 的 `PG_USER/PG_PASSWORD` 是否正确
  - 确认 `backend/main.py` 是否 load_dotenv 生效

#### 5.2 Memory Items 为空

- 先查 outbox 是否有入队：
  - `SELECT COUNT(*) FROM ltm_write_tasks WHERE user_id='<uid>';`
- 如果 outbox 有，但 Mem0 为空：
  - 检查 worker 是否消费 Postgres（是否还在读 SQLite）
  - 查看 `ltm_worker` 日志是否在处理 pending

#### 5.3 embeddings 404（最常见）

- DashScope compatible-mode 下，embedding 模型建议：
  - `MEM0_EMBED_MODEL=text-embedding-v2`
- 若出现：
  - `model_not_found`：模型名不对/无权限
  - `model_not_supported`：把聊天模型当 embedding 了

---

### 6. 建议的后续整理动作（可选）

- 将 worker 处理成功/失败的关键指标做成更明确的统计输出（例如每分钟 done/failed 数量）
- 将 “failed 任务重放” 做成一个后台管理接口或脚本（避免手动 SQL）
- 明确区分：
  - **结构化画像**（权威、立即生效）
  - **语义记忆条目**（Mem0、可选增强）

