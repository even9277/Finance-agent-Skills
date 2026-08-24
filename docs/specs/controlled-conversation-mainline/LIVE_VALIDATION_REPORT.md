# 真实模型与 Tushare Live 验收报告

## 1. 验收边界

- 日期：2026-08-24
- 授权来源：用户显式要求迁移历史测试凭证，并真实调用 LLM 与 Tushare。
- 验收对象：当前 `Finance-agent-Skills` 已存在的 Router、Tushare 工具和公开 HTTP `chat_service` 主链。
- 安全边界：只读金融查询；临时 SQLite；关闭 Memory 写回和 Langfuse；不执行交易、生产写、commit、push、PR、merge 或部署。
- 结论边界：本报告证明当前旧主链可真实运行，不代表计划中的新受控主链已经实现。

## 2. 本地测试配置迁移

历史来源仅用于本地测试，未成为运行时依赖：

- `D:\FinanceProject\Finance\backend\.env` → `D:\FinanceProject\Finance-agent-Skills\backend\.env`
  - `TUSHARE_TOKEN`
  - `CHAT_ROUTER_MODEL`
  - `CHAT_RESOLVER_MODEL`
  - `CHAT_REWRITER_MODEL`
  - `CHAT_SKILL_SYNTHESIS_MODEL`
  - `STM_COMPACTION_MODEL`
- `D:\FinanceProject\Finance\Financial-MCP-Agent\.env` → `D:\FinanceProject\Finance-agent-Skills\Financial-MCP-Agent\.env`
  - `OPENAI_COMPATIBLE_API_KEY`
  - `OPENAI_COMPATIBLE_BASE_URL`
  - `OPENAI_COMPATIBLE_MODEL`
  - `USE_LOCAL_MODEL`

两个目标 `.env` 均由仓库 `.gitignore` 的 `.env` 规则忽略；Git 状态没有出现环境文件。迁移过程只输出变量名及非空状态，没有输出任何 Token、API Key 或完整连接地址。数据库、JWT、Tavily、Redis、Langfuse 和生产设置没有迁移。

## 3. 真实模型验证

### 3.1 迁移前目标配置的提供商 HTTP 诊断探针

- 方法：使用已配置 OpenAI-compatible endpoint 发出一个最多 24 tokens 的真实请求。
- 结果：HTTP `200`，配置模型和提供商返回模型均为 `gpt-5.5`。
- 响应：非空，15 个字符。
- 耗时：约 3,088 ms。
- 说明：该探针发生在历史配置迁移动作之前，用于证明目标仓库当时的凭证、网络代理和模型服务可用；迁移后的真实模型证据以 3.3 和第 5 节为准。

### 3.2 迁移前项目 Router 诊断调用

- 输入：`查询贵州茅台 600519.SH 的基础信息和近期行情`。
- 临时依赖：`uv run --with socksio --locked ...`，只用于适配本机 SOCKS5 代理，未修改 `pyproject.toml` 或 `uv.lock`。
- 结果：Router 成功返回 `tushare-data`、`single_stock_data`，Trace 中记录真实模型标记。该项用于定位 SOCKS 依赖问题，不作为迁移后配置的最终证据。

### 3.3 仓库 Live Router 测试

```powershell
uv run --with socksio --locked python -m pytest -q -m live
```

结果：`4 passed, 66 deselected, 1 warning in 19.28s`。

注意：`uv run --with socksio --locked pytest ...` 会调用 `.venv` 中独立的 `pytest.exe`，绕过临时依赖并导致 4 项在请求前失败；改用 `python -m pytest` 后通过。

## 4. 真实 Tushare 验证

### 4.1 官方客户端读取

- 标的：`600519.SH`。
- `stock_basic`：成功，1 行，代码匹配 `600519.SH`。
- `daily`：查询 `20260801`–`20260824` 成功，16 行。
- 返回的最新交易日：`20260824`。
- 返回的最新收盘价：`1304.66`。
- 总耗时：约 6,033 ms。

以上数值是本次真实调用返回的测试证据，不作为投资建议或长期固定 fixture。

### 4.2 项目工具封装读取

- `get_stock_basic_info`：`ok=true`，`source_api=stock_basic`，1 行。
- `get_daily_bars`：`ok=true`，`source_api=daily`，5 行。
- 两个工具均产生 `chat.tool.start`、`chat.tool.end` 和 `tool_call` Trace。
- 工具封装阶段耗时约 411 ms；命中同进程客户端缓存的部分不用于推断生产延迟。

## 5. 当前公开 HTTP 主链 Live E2E

### 5.1 测试链路

```text
POST /api/chat/message
→ FastAPI Router
→ chat_service.chat_single_turn
→ 真实 Router 模型
→ fallback planner
→ 真实 Tushare pro_bar + stock_basic
→ Evidence 验收
→ 真实 Synthesis 模型
→ 临时 SQLite 持久化
→ GET /api/chat/sessions/{id}/messages
```

### 5.2 隔离设置

- 使用自动生成的临时 SQLite 数据库，不连接主仓库现有 PostgreSQL。
- `AUTH_ENABLED=false`，仅用于本地测试用户。
- `ENABLE_MEMORY=false`、`ENABLE_STM=false`，不写入 Mem0/LTM。
- `ENABLE_LANGFUSE=false`，不向外部观测平台发送数据。
- Tushare 只调用只读接口；不存在交易或持仓写操作。
- 测试结束后两个 `finance-live-e2e-*` 临时目录均已核验删除。

### 5.3 结果

- 健康接口：HTTP `200`。
- 聊天接口：HTTP `200`。
- 总耗时：约 31,723 ms。
- Router：`tushare-data`，置信度 `0.9`，真实模型 `tongyi-xiaomi-analysis-pro`。
- Planner：`fallback_planner`，计划 `get_market_bars` + `get_stock_basic_info`。
- 工具：真实 `pro_bar` 和 `stock_basic` 均成功，失败率 `0.0`。
- Synthesis：真实模型 `glm-5.1`，约 19,729 ms。
- Evidence：`evidence_ok=true`，生成 3 条 claim lineage。
- 回复：810 字符，包含 `600519` 和行情/交易日类证据表述。
- 持久化：成功创建 session，读取到 2 条消息，顺序为 `user → assistant`。
- Trace：最终 `status=ok`、`final_status=ok`、`degrade_stage=primary`。

## 6. 失败与真实缺口

| 现象 | 根因 | 当前处理 | 后续工程动作 |
|---|---|---|---|
| 默认 Python 模型客户端初始化失败 | 本机 `ALL_PROXY` 为 SOCKS5，锁定依赖缺少 `socksio` | Live 时用 uv 临时附加依赖 | 单独评审是否把 `httpx[socks]`/`socksio` 纳入开发或 Live 依赖 |
| `uv run ... pytest` 仍找不到临时依赖 | Windows `pytest.exe` 使用 `.venv` 解释器 | 改用 `python -m pytest` | 将受保护 Live 命令固化为唯一文档入口 |
| FastAPI 首次启动在 GBK 下失败 | 入口使用包含 `✓` 的 `print` | UTF-8 进程重跑 | 按日志规范删除入口 `print`，使用参数化 logger |
| 现有 committed Live 测试只覆盖 Router | 没有真实 Tushare/HTTP Live 测试文件 | 本次用受控脚本手工验收 | 后续建立显式 marker、预算、隔离 DB 和只读工具的自动 Live E2E |
| 当前 E2E 仍经过巨型 `chat_service` | 新受控 Orchestrator 尚未迁移 | 作为迁移前基线保存 | Milestone 1–7 逐步建立并切换新主链 |

## 7. 最终结论

当前仓库的真实 LLM、真实 Tushare 和旧公开聊天主链可以跑通；之前只做测试收集的结果不能代表这一点。本次已经获得真实调用证据，但也确认默认 Live 环境仍存在 SOCKS 依赖、Windows 终端编码和自动化覆盖缺口。这些缺口必须进入后续里程碑，不能用本次临时运行方式掩盖。
