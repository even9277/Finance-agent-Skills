# Phase A / Phase B 无逻辑变更重构清单

> **范围**：仅做代码**搬家与边界收口**（目录重排、门面保留、适配层集中 import），**不修改**业务逻辑、算法、API 契约、环境变量默认值、Feature Flag 语义。  
> **验收标准**：重启前后端后，报告模式与对话模式行为与改前一致；`pytest` 相关用例不退化；手工冒烟 8 条全绿。  
> **真源对齐**：`docs/项目描述.md`（报告模式、对话模式、STM/LTM 章节）；结构参考 Google eng-practices、FastAPI Bigger Applications、12-Factor、Vue Style Guide。  
> **输出路径**：本文件。

---

## 1. 背景与目标

### 1.1 背景

当前主栈已具备产业级雏形（前后端分离、Agent 独立、MCP 工具独立、Trace/测试覆盖），但存在三类**结构债**：

| 问题 | 现状 | 风险 |
|------|------|------|
| 超大服务文件 | `backend/services/chat_service.py` 约 3800 行 | 改一处牵全局，难 review |
| 报告入口耦合 | `backend/services/agent_service.py` 与 `Financial-MCP-Agent/src/main.py` 工作流同构 | 双份逻辑易漂移 |
| 跨仓直连 Agent | `backend` 多处 `sys.path.insert` + `from src.*` | 边界被打穿，难测试与替换 |

本计划只做 **Phase A（拆大文件 + 门面）** 与 **Phase B（integrations 收口 import）**，为后续按「报告 / 对话 / 记忆」域持续演进打地基。

### 1.2 目标

1. **对话域**：将 `chat_service.py` 拆为 `backend/services/chat/` 子包，旧路径 `chat_service.py` 保留为**门面（Facade）**，对外符号不变。
2. **报告域**：将 `agent_service.py` 拆为 `backend/services/report/` 子包，门面保留；`routers/report.py` 仍 `from backend.services.agent_service import run_report_task`。
3. **边界**：新建 `backend/integrations/agent_runtime/`，集中 `sys.path` 与 `from src.*`；业务层只依赖 integrations。
4. **可理解性**：目录命名与 `docs/项目描述.md` 中「报告模式 / 对话模式」一一对应，便于他人阅读。

### 1.3 非目标（本计划不做）

- 修改 `backend/schemas/*` 字段名、HTTP path、WebSocket 帧 `type` 枚举。
- 修改 Feature Flag 默认值（`backend/config.py`）。
- 合并或删除 `skills/` 与 `skills_v2/` 实现（仅可在文档中标注主路径）。
- 抽取 `main.py` 与 `agent_service.py` 的**公共工作流库**（避免行为变化，留待后续独立任务）。
- 前端 `api/index.ts` 拆分（可选附录，不阻塞 Phase A/B 后端验收）。
- 引入 Redis / Kafka / 新中间件。

### 1.4 必须保持不变的行为

| 类别 | 必须不变 |
|------|----------|
| 对外 HTTP/WS | `/api/chat/*`、`/api/report/*` 路径、请求/响应 JSON 结构 |
| 门面符号 | `chat_service.chat_single_turn`、`stream_chat_single_turn`、`confirm_skill_route`、`InvalidSopSkillError`、`list_discoverable_sop_skills` 等 |
| 报告任务 | `run_report_task(task_id, report_id, command, user_id)` 签名与进度字段语义 |
| 环境 | `.env` 含义不变；`ENABLE_STM` / `ENABLE_MEMORY` / `enable_chat_skills` 等开关行为不变 |
| Agent 运行时 | `Financial-MCP-Agent` 内算法与 Skill 执行顺序不变（本计划不移动 Agent 内文件，仅搬 backend 调用侧） |
| 数据库 | 不删列、不改迁移；仅允许新增 `__init__.py` 与空包 |

### 1.5 顶层验收标准

1. **自动化**：`cd /root/Finance && python -m pytest tests/ -q` 与改前通过集合一致（允许仅新增 import 路径的测试，不得改断言预期）。
2. **边界检查**：`backend/` 下除 `integrations/agent_runtime/` 外，无 `from src.`、`sys.path.insert`（见 §7.3）。
3. **手工冒烟**：§6 八条场景全部与基线一致。
4. **启动**：`backend/main.py` + `frontend` dev server 无 ImportError；报告任务能 `pending → running → completed`。

---

## 2. 目标目录结构（完成后形态）

### 2.1 Backend 服务层（按产品域）

```text
backend/
  routers/                    # 薄：HTTP + 鉴权，不写业务
    chat.py                   # 对话模式 API
    report.py                 # 报告模式 API
    memory.py
    ...
  schemas/                    # 契约层（本阶段不拆文件，仅引用路径不变）
    chat.py
    report.py
    memory.py
    ...
  services/
    chat/                     # 【对话模式】产品域
      __init__.py             # 再导出门面所需符号（可选）
      constants.py            # 常量、同义词表、overflow 模式
      session.py              # 会话/消息 CRUD、compress_if_needed、summaries
      preflight.py            # _prepare_chat_preflight_inputs、_run_chat_preflight_compaction
      route_bridge.py         # 路由、HITL、skill 确认、rewrite 编排入口
      skill_pipeline.py       # _run_skill_chat_if_enabled 及 summarize_* 委托
      stream.py               # stream_chat_single_turn、_chunk_text
      memory_bridge.py        # LTM 注入、profile action、maybe_update_ltm_from_chat
      artifacts.py            # route_summary、trace 持久化、plan/skill artifact
      orchestrator.py         # chat_single_turn、confirm_skill_route（编排入口）
    report/                   # 【报告模式】产品域
      __init__.py
      workflow_runner.py      # run_report_task、进度更新、astream_events
      state_builder.py        # _build_initial_state、股票解析委托
      workflow_factory.py     # _get_workflow（LangGraph 编译，从 agent_service 迁入）
      legacy_extract.py       # extract_stock_info（已废弃，保持兼容）
    memory/                   # 【可选 Phase A 末】LTM 门面，或暂保留 memory_service.py
    shared/                   # 跨域共用（本阶段可仅 re-export，不强制搬迁）
      entity_resolver.py      # 仍放原路径亦可，通过 shared 再导出
      stock_resolver.py
      stm_context_service.py    # 暂保留顶层文件名，chat 包内 memory_bridge 引用
      stm_summary_runtime.py
      chat_route_runtime.py
      chat_hitl_pending.py
      token_counter.py
      auth_service.py
    chat_service.py           # 【门面】仅 import + 转调，目标 <200 行
    agent_service.py          # 【门面】仅 import + 转调
  integrations/
    agent_runtime/
      __init__.py
      env.py                  # 唯一 sys.path.insert + load_dotenv(agent)
      chat_runtime.py         # 原 chat_service 内所有 from src.agents.* / src.tools.*
      report_runtime.py       # 原 agent_service 内所有 from src.agents.* / src.utils.*
      contracts.py            # 仅类型别名/文档，无逻辑
  db/
  middleware/
  config.py
  main.py
```

### 2.2 与两套产品功能的映射表

| 产品功能 | 用户可见 | 路由层 | 服务层（改后） | Agent / 工具 |
|----------|----------|--------|----------------|--------------|
| **对话模式** | 聊天页、流式、SOP 选择、skill_confirm | `routers/chat.py` | `services/chat/*` + 门面 `chat_service.py` | `skill_router_node`、`skill_runner_v2`、`synthesis/*`、`query_rewriter` |
| **报告模式** | 报告页、进度条、下载 Markdown | `routers/report.py` | `services/report/*` + 门面 `agent_service.py` | `fundamental/technical/value/news` + `summary_agent`；CLI：`Financial-MCP-Agent/src/main.py` |
| **短期记忆 STM** | 上下文占用、压缩提示、running_summary | chat 接口返回 `context_window` | `chat/preflight.py`、`chat/memory_bridge.py` + `stm_*` | 报告图可选 `stm_nodes`（flag 控制） |
| **长期记忆 LTM** | 记忆侧栏、画像卡片 | `routers/memory.py` | `memory_service.py`（可后续迁入 `services/memory/`） | `ltm_worker`、`mem0_client`（`main.py` lifespan 启动） |

### 2.3 Financial-MCP-Agent（本计划不搬文件，仅文档约定）

建议在 `Financial-MCP-Agent/README.md` 或 `AGENTS.md` 中补充（**不写代码也可**）：

```text
对话模式主路径（backend 调用）:
  skill_router_node → skill_runner_v2 / tushare_plan_executor → synthesis/*

报告模式主路径（backend 调用 + CLI）:
  fundamental_analyst ∥ technical_analyst ∥ value_analyst ∥ news_analyst → summarizer
```

`skills/` 与 `skills_v2/`：在文档中标明**生产默认**（以 `settings.enable_sop_v2` / `enable_skill_loader_v2` 为准），本计划不删除任一套。

---

## 3. 重构原则（执行时必须遵守）

### 3.1 绞杀者门面（Strangler Facade）

```python
# backend/services/chat_service.py（完成后示意）
from backend.services.chat.orchestrator import chat_single_turn as _chat_single_turn
from backend.services.chat.orchestrator import stream_chat_single_turn as _stream_chat_single_turn
# ... 其它公开符号同理 ...

async def chat_single_turn(*args, **kwargs):
    return await _chat_single_turn(*args, **kwargs)
```

- **禁止**：在门面层写新业务逻辑。
- **禁止**：删除测试中引用的模块级符号（如 `chat_service.InvalidSopSkillError`）。

### 3.2 剪切粘贴，禁止顺手优化

- 使用 `git mv` 或 IDE 移动后 `git diff` 应为**纯位置变化**（允许调整相对 import）。
- 不合并 if 分支、不改默认值、不改异常类型、不改日志文案（除非日志 import 路径变化）。

### 3.3 依赖方向（Phase B 后）

```text
routers  →  services/*  →  integrations/agent_runtime  →  Financial-MCP-Agent/src
                ↓
              db / schemas
```

- `services/chat` **不得** import `routers`。
- `integrations` **不得** import `services/chat`（避免环）。

### 3.4 每步可回滚

- 每个子任务单独 commit；消息格式见 §8。
- 失败时 `git revert HEAD`，重新跑 §6 基线。

---

## 4. Phase A：拆大文件（详细任务）

### 4.0 任务 A0：建立基线（0.5 天）

| 项 | 内容 |
|----|------|
| 操作 | 记录当前 commit SHA；执行 §6.1 自动化 + §6.2 手工，截图或保存 JSON 样例 |
| 产出 | `docs/开发计划/Phase-A-B-基线记录.md`（可选，自建） |
| 禁止改代码 | 是 |

**建议保存的 API 样例（改后 diff 用）：**

```bash
# 登录后替换 TOKEN
curl -s -H "Authorization: Bearer $TOKEN" -X POST http://127.0.0.1:8000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"user_id":"YOUR_USER_ID","message":"分析一下贵州茅台"}' | jq . > /tmp/baseline_chat.json
```

---

### 4.1 任务 A1：创建 `services/chat/` 包骨架

| 项 | 内容 |
|----|------|
| 新建 | `backend/services/chat/__init__.py` 及空模块：`constants.py`、`session.py`、`preflight.py`、`route_bridge.py`、`skill_pipeline.py`、`stream.py`、`memory_bridge.py`、`artifacts.py`、`orchestrator.py` |
| 修改 | 无逻辑 |
| 验收 | `python -c "from backend.services import chat_service"` 成功 |

---

### 4.2 任务 A2：搬迁「常量与纯函数」（低风险）

**迁入 `chat/constants.py`（建议清单）：**

| 原符号 | 说明 |
|--------|------|
| `_RISK_LEVEL_*`、`_SECTOR_*`、`_HORIZON_*`、`_RESPONSE_PREF_*` 等表 | 纯数据 |
| `_CHAT_STREAM_CHUNK_SIZE`、`_STM_*`、`_ROUTE_SNAPSHOT_*` | 常量 |
| `_normalize_sectors`、`_normalize_profile_action` | 无副作用 |
| `_chunk_text`、`_context_window_to_payload`、`_unique_strings` | 工具函数 |
| `_is_context_overflow_error` | 纯判断 |
| `InvalidSopSkillError` | **必须在门面 re-export** |

**门面保留：**

```python
from backend.services.chat.constants import InvalidSopSkillError
# 以及 tests 可能引用的 normalize_* 若直接测私有函数，则 constants 再 export
```

| 验收 | `pytest tests/test_chat_service_skill_processing.py tests/test_chat_service_overflow_fallback.py -q` |
| 回滚 | 单 commit revert |

---

### 4.3 任务 A3：搬迁「会话与 STM 压缩」（低风险）

**迁入 `chat/session.py`：**

| 原符号 |
|--------|
| `get_or_create_session` |
| `get_sessions` |
| `get_session_messages` |
| `delete_session` |
| `rename_session` |
| `compress_if_needed` |
| `get_session_summaries` |
| `_build_fallback_chat_messages` |
| `_force_overflow_recovery_compaction` |

**注意：** 仍 import `backend.services.stm_summary_runtime` 等顶层模块，**不要**在本任务改 stm 逻辑。

| 验收 | 会话列表/删除/重命名 API；`tests/test_chat_service_overflow_fallback.py` |
| 手工 | 新建会话、历史消息拉取 |

---

### 4.4 任务 A4：搬迁「Preflight / LLM 小工具」（中风险）

**迁入 `chat/preflight.py`：**

| 原符号 |
|--------|
| `_prepare_chat_preflight_inputs` |
| `_run_chat_preflight_compaction` |
| `_get_llm` |
| `_serialize_prompt_payload` |
| `_extract_model_text` |

**迁入 `chat/constants.py` 或 `artifacts.py`（二选一，避免循环）：**

| 原符号 |
|--------|
| `_profile_to_summary`、`_profile_to_route_summary`、`_trace_query_summary` |
| `_trace_root_metrics`、`_trace_root_payload`、`_trace_root_refs` |

| 验收 | 长对话触发 pre_compaction 时行为与基线一致（提示文案、context_window） |

---

### 4.5 任务 A5：搬迁「路由与 Skill 管线」（高风险，拆 2 个子 commit）

**子任务 A5a → `chat/route_bridge.py`：**

| 原符号 |
|--------|
| `normalize_requested_sop_skill_id`、`validate_requested_sop_skill_id`、`list_discoverable_sop_skills` |
| `_ensure_skill_runtime_ready` |
| `_load_memory_context_for_chat`、`_build_skill_route_context` |
| `_resolve_entity_hint_for_route`、`_resolver_hint_*` |
| `_should_offer_skill_hitl`、`_build_skill_confirm_*`、`_apply_hitl_choice_to_route_dict` |
| `confirm_skill_route`（也可放 orchestrator，但须保持门面导出） |

**子任务 A5b → `chat/skill_pipeline.py`：**

| 原符号 |
|--------|
| `_apply_skill_query_rewrite` |
| `_run_post_rewrite_extractors_if_enabled` |
| `_run_skill_chat_if_enabled` |
| `summarize_sop_reply`、`summarize_tushare_reply`、`summarize_fallback_reply` |
| `_trace_plan_artifacts`、`_executor_qualifies_for_evidence_retry` |

**子任务 A5c → `chat/artifacts.py`：**

| 原符号 |
|--------|
| `_build_route_summary`、`_persistable_route_summary`、`_record_route_runtime_with_log` |
| `_route_trace_to_summary_entities`、`_apply_route_entities_to_stm_with_log` |
| `_strip_profile_actions_from_reply`、`_prepare_reply_for_user` |
| `_route_summary_skill_label` |

| 验收 | `tests/test_chat_service_skill_processing.py` 全过；手工：SOP 技能、Tushare 路由、fallback、skill_confirm |
| 禁止 | 在本任务移动 `from src.*`（留给 Phase B 原样剪切到 integrations） |

---

### 4.6 任务 A6：搬迁「编排入口」（最高风险）

**迁入 `chat/orchestrator.py`：**

| 原符号 | 门面是否必须保留 |
|--------|------------------|
| `chat_single_turn` | 是 |
| `stream_chat_single_turn` | 是 |
| `confirm_skill_route` | 是（若未在 route_bridge） |

**迁入 `chat/stream.py`（可选，与 orchestrator 二选一）：**

| 原符号 |
|--------|
| `stream_chat_single_turn` 中与 WS 帧拼装相关的私有函数 |

**迁入 `chat/memory_bridge.py`：**

| 原符号 |
|--------|
| `_build_memory_system_prompt` |
| `maybe_update_ltm_from_chat` |
| `_extract_from_summary` |
| `_handle_profile_action_in_reply` |
| `_handle_profile_action_in_user_message` |

**完成后 `chat_service.py` 形态：**

- 顶部：logger、settings、门面 re-export 列表。
- 中部：可选保留尚未迁出的 `from src.*`（Phase B 前）。
- 底部：对各公开函数的 `from backend.services.chat.xxx import ...` 转调。

| 验收 | §6 全部；`chat_service.py` 行数应显著下降 |
| 通过标准 | `routers/chat.py` **无需修改 import** |

---

### 4.7 任务 A7：拆分 `agent_service.py` → `services/report/`

| 迁入模块 | 原符号 |
|----------|--------|
| `report/workflow_factory.py` | `_get_workflow` |
| `report/state_builder.py` | `_build_initial_state`、`extract_stock_info`（废弃） |
| `report/workflow_runner.py` | `run_report_task` |

**门面 `agent_service.py`：**

```python
from backend.services.report.workflow_runner import run_report_task
__all__ = ["run_report_task", "extract_stock_info"]  # 若外部有引用
```

| 验收 | 触发报告生成；进度 10→35→…→100；`tests/` 中报告相关用例 |
| 注意 | `_get_workflow` 内 `from src.agents.memory_nodes import ...` 本阶段仍保留在 report 包内，Phase B 再迁入 `integrations/report_runtime.py` |

---

### 4.8 任务 A8（可选）：`services/memory/` 仅文档 + `__init__.py`

本阶段**不强制**搬迁 `memory_service.py`（避免与 `routers/memory.py`、LTM worker 交叉影响）。仅新增：

```text
backend/services/memory/__init__.py   # from backend.services.memory_service import *
```

供后续迭代；**不纳入 Phase A/B 硬性验收**。

---

## 5. Phase B：边界收口（详细任务）

> **前置条件**：Phase A 全部验收通过后再开始 Phase B。

### 5.1 任务 B1：创建 `integrations/agent_runtime/`

| 新建文件 | 职责 |
|----------|------|
| `env.py` | 唯一 `_AGENT_ROOT` 定义；`ensure_agent_path()`：`sys.path.insert` + 可选 `load_dotenv` |
| `chat_runtime.py` | 从 `chat_service.py` **原样剪切**所有 `from src.agents...`、`from src.tools...`、`from src.skills...` |
| `report_runtime.py` | 从 `agent_service` / `report/workflow_factory.py` **原样剪切**所有 `from src.agents...`、`from src.utils...` |
| `contracts.py` | 文档化：输入输出 dict 结构，无运行逻辑 |

**修改清单（剪切后改 import）：**

| 原位置 | 新 import |
|--------|-----------|
| `chat_service.py` 顶部 `from src.*` | `from backend.integrations.agent_runtime import chat_runtime as _agent_rt` 再在具体函数内使用 `_agent_rt.execute_skill` 等 **或** `from backend.integrations.agent_runtime.chat_runtime import execute_skill` |
| `agent_service.py` / `report/workflow_factory.py` | `from backend.integrations.agent_runtime import report_runtime` |
| `entity_resolver.py`、`memory_service.py` | 暂可保留直引 `src.tools.*`；Phase B **最低要求**是 chat + report 主链路 |

| 验收 | 同 Phase A 全套；额外跑 §7.3 grep |

---

### 5.2 任务 B2：收紧 `main.py` lifespan 中的 Agent import

| 项 | 内容 |
|----|------|
| 现状 | `main.py` 内 `from src.memory.mem0_client`、`from src.memory.ltm_worker` |
| 目标 | 改为 `from backend.integrations.agent_runtime.env import ensure_agent_path` 后 `from src.memory...` **仅**在 `integrations` 子模块内出现，或增加 `integrations/memory_runtime.py` 薄封装 |

| 验收 | `ENABLE_MEMORY=true` 时启动无报错；`ltm_worker` 日志与改前一致 |

---

### 5.3 任务 B3：文档与 AGENTS 约定（无代码逻辑）

新增或更新（**本计划允许只写文档**）：

| 文件 | 内容 |
|------|------|
| `backend/AGENTS.md` | 分层规则、禁止 routers 写业务、禁止 services 直引 `src` |
| `docs/项目代码架构说明.md` | 增补 §「Phase A/B 后目录」指向本文件 |
| `Financial-MCP-Agent/AGENTS.md` | 报告/对话主路径、skills 版本说明 |

---

## 6. 验收清单（每步必做）

### 6.1 自动化

```bash
cd /root/Finance

# 主测试集（对话/路由/STM/实体等）
python -m pytest tests/ -q --tb=short

# Agent 包内测试（若环境齐全）
cd Financial-MCP-Agent && python -m pytest test_skill_router.py test_query_rewriter.py -q --tb=short
```

**通过标准：** 与基线相比，失败集合不扩大；允许跳过项一致。

**编译检查：**

```bash
python -m compileall backend/services backend/integrations -q
```

### 6.2 手工冒烟（8 条）

| # | 场景 | 操作 | 通过标准 |
|---|------|------|----------|
| 1 | 登录 | 注册/登录 | token 有效，`/api/auth/me` 正常 |
| 2 | 对话首句 | 新会话发送「分析贵州茅台」 | 有回复，`session_id` 非空 |
| 3 | 对话续句 | 同会话追问 | 无 500，上下文连贯 |
| 4 | 流式 | 聊天页发送（WS） | 有 token 流，收到 `done` |
| 5 | SOP 技能 | 选择可发现 SOP（若 `ENABLE_CHAT_SKILLS`） | 列表与执行正常 |
| 6 | skill_confirm | 低置信场景或测试触发 | 确认后能继续出答 |
| 7 | 报告 | 提交报告指令 | `pending→running→completed`，有 Markdown |
| 8 | 记忆 | 打开记忆侧栏，改风险偏好 | 保存成功，下轮对话可见 |

### 6.3 Phase B 专项：依赖边界 grep

```bash
cd /root/Finance
rg "from src\.|sys\.path\.insert" backend \
  --glob '!**/integrations/agent_runtime/**' \
  --glob '!**/__pycache__/**'
```

**期望：** 无输出（或仅 `integrations/__init__.py` 文档注释中的示例）。

---

## 7. 风险与规避

| 风险 | 规避 |
|------|------|
| 循环 import | 先 constants/session，再 route，再 orchestrator；`TYPE_CHECKING` 仅用于类型 |
| 测试引用私有函数 | 门面 `chat_service` 继续 export `_normalize_*`、`_run_skill_chat_if_enabled` 等测试用到的符号 |
| 隐式副作用 | 不调整 `settings` 加载顺序；`env.py` 仅在 integrations 首次 import 时执行 path |
| Phase A/B 同 PR 过大 | **禁止**；必须分 commit，每 commit 跑 §6 |
| 报告与对话误拆 | `report/` 只含 `run_report_task` 链；凡 `chat_single_turn` 一律 `chat/` |

---

## 8. 建议 Commit 顺序与消息模板

```text
chore(refactor): record Phase A-B baseline acceptance

refactor(chat): add services/chat package skeleton (no behavior change)

refactor(chat): move constants and pure helpers to chat/constants

refactor(chat): move session APIs to chat/session

refactor(chat): move preflight helpers to chat/preflight

refactor(chat): move route and skill pipeline to chat/route_bridge and skill_pipeline

refactor(chat): move orchestrator entrypoints; thin chat_service facade

refactor(report): split agent_service into services/report package

refactor(integrations): add agent_runtime and centralize src imports

docs: add backend AGENTS and report/chat path map
```

---

## 9. Codex 执行任务拆分（可直接派单）

| 任务 ID | 目标 | 允许修改 | 禁止修改 | 验证命令 |
|---------|------|----------|----------|----------|
| CAB-A0 | 基线记录 | 仅 `docs/开发计划/Phase-A-B-基线记录.md` | 任何 `.py` | 人工 |
| CAB-A1 | chat 包骨架 | `backend/services/chat/__init__.py` 等空文件 | 业务逻辑 | `python -c "import backend.services.chat_service"` |
| CAB-A2 | constants 搬迁 | `chat/constants.py`、`chat_service.py` | `routers/*`、`schemas/*` | `pytest tests/test_chat_service_*.py -q` |
| CAB-A3 | session 搬迁 | `chat/session.py`、`chat_service.py` | 同上 | 同上 + 会话 API 冒烟 |
| CAB-A4 | preflight 搬迁 | `chat/preflight.py`、`chat_service.py` | 同上 | 长对话压缩冒烟 |
| CAB-A5a | route_bridge 搬迁 | `chat/route_bridge.py`、`chat_service.py` | `integrations/*` | `pytest tests/test_chat_service_skill_processing.py -q` |
| CAB-A5b | skill_pipeline 搬迁 | `chat/skill_pipeline.py`、`chat_service.py` | 同上 | 同上 + SOP/Tushare 冒烟 |
| CAB-A6 | orchestrator + memory_bridge + stream | `chat/orchestrator.py` 等、`chat_service.py` | 同上 | §6 全套 |
| CAB-A7 | report 包拆分 | `services/report/*`、`agent_service.py` | `chat/*` | 报告全流程冒烟 |
| CAB-B1 | agent_runtime | `integrations/agent_runtime/*`、改 chat/report import | 改算法 | §6 + §7.3 grep |
| CAB-B2 | main lifespan | `main.py`、`integrations/*` | Feature flags | `ENABLE_MEMORY` 启动 |
| CAB-B3 | AGENTS 文档 | `backend/AGENTS.md`、`docs/*` | 业务代码 | 评审 |

**停止条件（必须询问用户）：**

- 剪切后出现循环依赖无法在不改逻辑下解决；
- 测试失败且失败并非 import 路径问题；
- 需要修改 `schemas` 或 API 契约才能通过测试。

---

## 10. 与现有开发计划的关系

| 文档 | 关系 |
|------|------|
| `docs/开发计划/对话模式-实体解析-路由-改写-优化开发计划.md` | **功能开发**；本计划完成后，新功能应写入 `services/chat/` 子模块，而非堆入门面 |
| `docs/开发计划/对话模式-Plan-Execute-证据-总结-优化开发计划.md` | 同上，优先落 `chat/skill_pipeline.py` |
| `docs/开发计划/对话模式-Skills集成与开发-优化开发计划.md` | 同上 |
| `docs/项目代码架构说明.md` | Phase B3 后更新「二、Web 应用主栈」目录表 |

---

## 11. 附录：当前必须保持的门面符号清单

以下符号**必须**仍可通过 `backend.services.chat_service` 访问（`grep` 验证）：

| 符号 | 引用方示例 |
|------|------------|
| `chat_single_turn` | `routers/chat.py` |
| `stream_chat_single_turn` | `routers/chat.py` |
| `confirm_skill_route` | `routers/chat.py` |
| `get_or_create_session` | 内部/未来 router 可能用 |
| `get_sessions` | `routers/chat.py` |
| `get_session_messages` | `routers/chat.py` |
| `delete_session` | `routers/chat.py` |
| `rename_session` | `routers/chat.py` |
| `get_session_summaries` | `routers/chat.py` |
| `normalize_requested_sop_skill_id` | `routers/chat.py` |
| `validate_requested_sop_skill_id` | `routers/chat.py` |
| `list_discoverable_sop_skills` | `routers/chat.py` |
| `InvalidSopSkillError` | `routers/chat.py` |
| `settings` | `routers/chat.py`（模块级引用） |
| `_run_skill_chat_if_enabled` | `tests/test_chat_service_skill_processing.py` |
| `_prepare_reply_for_user` | 同上 |
| `_build_fallback_chat_messages` | `tests/test_chat_service_overflow_fallback.py` |
| `compress_if_needed` | 同上 |
| `maybe_update_ltm_from_chat` | 内部 |

报告侧：

| 符号 | 引用方 |
|------|--------|
| `run_report_task` | `routers/report.py` |

---

## 12. 执行时间估算（单人）

| 阶段 | 预估 |
|------|------|
| A0–A4 | 1–2 天 |
| A5–A6 | 2–3 天 |
| A7 | 0.5–1 天 |
| B1–B3 | 1–2 天 |
| **合计** | **约 5–8 个工作日**（含回归与修 import） |

---

**最后更新**：与仓库当前 `chat_service.py` / `agent_service.py` 结构对齐；执行时若函数名有增减，以 `rg "^async def |^def "` 实时更新 §4 搬迁表，但**不得**借此改名或合并逻辑。
