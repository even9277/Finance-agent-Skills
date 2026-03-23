---
name: finance-incremental-dev
description: >-
  Enforces incremental development, contract alignment, PostgreSQL migrations, Linux/Docker/venv+uv
  workflows, external best-practice research, up-to-date dependencies, and production-grade logging
  for the Finance 智能投研助手 repo (FastAPI + Vue + LangGraph + Mem0/pgvector). Use when adding
  features, fixing bugs, touching DB schema, deploying on Linux cloud hosts, or when the user asks
  for project development standards or skill-style guidance for this codebase.
---

# Finance 项目增量开发规范（Skill）

面向本仓库：**FastAPI 后端 + Vue3/TS 前端 + Financial-MCP-Agent（LangGraph）+ PostgreSQL/pgvector + Docker + Mem0**。所有改动默认 **增量、可回滚、不破坏已有行为**。

## 1. 代码审核与适配（契约一致）

- **改前**：用搜索/阅读确认调用链（router → service → Agent/memory → 前端 `api/` 与 store）。
- **改后自检**：
  - 函数签名、Pydantic schema、TS 接口、`snake_case`/`camelCase` 映射是否与现有约定一致。
  - 枚举/字段名与 UI、DB 列名一致；禁止“半套新命名”导致运行时 `KeyError` / 422。
- **禁止**：在未核对全链路的情况下重命名公共字段或删改已有 API 行为。

## 2. 增量开发（不破坏现有功能）

- 新能力用 **feature flag / 分支逻辑** 包裹（如 `ENABLE_MEMORY`、`ENABLE_STM`），默认关闭时行为与旧版一致。
- **禁止**删除或削弱用户已依赖的路径；需要替换时保留兼容层或明确迁移步骤。
- 大改拆步：**先可观测（日志）→ 再行为 → 再优化**。

## 3. 数据库（PostgreSQL）

- 新增/变更列：**必须**与 `backend/db/models.py`、迁移脚本或 `_migrate_add_columns` 等机制对齐。
- 交付物二选一（或两者都给）：
  1. 可执行的 `ALTER TABLE ...`（`IF NOT EXISTS`），附在 `migrations/` 或文档。
  2. 在回复中给出 **可复制的一整段 Linux/psql 指令**（含连接示例），说明执行一次即可。
- 代码侧对缺列要有 **降级或明确报错**（避免 silent failure），并在日志中写明“缺哪一列”。

## 4. 环境与依赖（Linux 云主机 + Docker + venv + uv）

- **后端 / Agent**：优先在项目根或模块目录使用 **Python 虚拟环境**；Python 包可用 **`uv pip install`**（与团队约定一致时）或 `pip`，并在文档中写清路径。
- **Docker**：数据库、pgAdmin 等用 Compose；应用是否容器化以仓库 `docker/` 为准，不要假设 Windows 路径。
- **配置**：`.env` 不提交密钥；区分开发/生产；Mem0/LLM 等读 `os.environ` 的路径要 **显式 load_dotenv**（本仓库已有模式需延续）。

## 5. 不确定时：先查权威实践再实现

- **禁止闭门造车**：对架构模式、Mem0/LangGraph、FastAPI 异步、pgvector 等拿不准时，应 **web 检索**：
  - 高星、维护活跃的开源仓库；或
  - 官方文档 / 大厂工程博客（Google/Microsoft/Cloudflare 等）的架构与降级文章。
- **落地**：说明参考来源（文档/仓库名），再映射到本仓库目录与命名，避免照搬无关栈。

## 6. 依赖与版本（保持前沿、可验证）

- 新增依赖前：**查官网或 PyPI/npm 当前主版本**与 breaking changes。
- 若版本不确定：**打开官方安装/迁移页**再写 `requirements`/`package.json`。
- 锁文件或约束版本要有简短注释（为何钉版本，例如兼容 OpenAI-compatible API）。

## 7. 产业级与可上线思维

- **并发**：异步 DB session 不跨任务共享；后台任务与 worker 避免全局可变状态污染。
- **稳定性**：外部服务（Mem0、LLM、MCP）失败时 **降级**（Noop、跳过、回退 SQL），主链路不崩。
- **可观测性**：
  - **结构化日志** + `exc_info=True` 记录异常链；
  - **终端/print** 关键阶段一行摘要（便于云主机 `journal`/`docker logs` 肉眼排查）。
- **上线前预判**：超时、重试、幂等（如 outbox `ltm_write_tasks`）、敏感信息不落日志。

## 8. 补充要点（建议默认遵守）

- **安全**：鉴权边界、SQL 注入（用参数绑定）、CORS、密钥仅环境变量。
- **API 契约**：改 DTO 时同步 OpenAPI、前端 `api/index.ts`、相关组件 props。
- **测试与验证**：至少说明如何手动验证；能加则加最小自动化（单测或脚本）。
- **文档**：复杂流程写入 `docs/`，含故障排查与一键命令。
- **国际化/文案**：用户可见中文；代码注释中英均可，关键架构建议中文简述。

## 9. 交付前自检清单（可复制）

```
[ ] 全链路参数名与类型与现有代码一致
[ ] 默认路径下旧功能行为不变（flag 关闭时）
[ ] PostgreSQL 列与 ORM/迁移/文档一致；给出 psql 指令或迁移文件
[ ] Linux + venv/uv + Docker 步骤可复现
[ ] 关键路径有 logger + 必要终端输出；失败可降级
[ ] 不确定点已对照官网或高星/权威开源实践
[ ] 依赖版本可查官网，无已知过期安全洞（力所能及范围内）
```

## 10. 与本仓库的锚点（快速定位）

| 区域 | 典型路径 |
|------|-----------|
| 后端入口 | `backend/main.py`, `backend/config.py` |
| 报告任务 | `backend/services/agent_service.py`, `backend/routers/report.py` |
| 对话/STM/LTM | `backend/services/chat_service.py`, `Financial-MCP-Agent/src/memory/` |
| 前端 API | `frontend/src/api/index.ts` |
| 画像状态 | `frontend/src/stores/memoryStore.ts`, `frontend/src/composables/useMemory.ts` |
| 文档 | `docs/` |

更细的命令模板（psql、Compose、uv）可逐步扩写到同目录 `reference-commands.md`（可选）。
