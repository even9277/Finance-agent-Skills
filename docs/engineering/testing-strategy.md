# 测试策略

## 1. 测试分层

| 层级 | 目的 | 外部付费/生产服务 | 典型位置 |
| --- | --- | --- | --- |
| unit | 纯函数、错误码、Settings、redaction、retry | 禁止 | `tests/unit` |
| contract | API、事件、Agent State、工具 Schema | 默认 Fake | `tests/contract` |
| integration | FastAPI + PostgreSQL + Provider fake | 禁止真实生产 | `tests/integration` |
| offline eval | 固定 Agent 样例、指标和 bad cases | 禁止 | `tests/evals` |
| Compose offline E2E | 前端/后端/数据库/fake 完整链路 | 禁止 | `tests/e2e` |
| live E2E | 真实模型/只读服务验收 | 显式允许 | `tests/e2e` + `live` |

默认 `pytest` 必须跳过 `live`；marker 必须注册并启用 strict markers。Live 只能由本地显式命令或受保护的 GitHub Environment 触发。

## 2. Agent 测试最小集合

每个受控模块至少覆盖：正常样例、空/非法输入、歧义、下游超时、下游无效响应、无证据、无权限、工具副作用和终止条件。测试期望应写成结构化字段，不依赖模型自由文本的偶然措辞。

## 3. 完整 E2E 验收

使用 `docker/docker-compose.offline.yml` 启动临时 PostgreSQL、真实 FastAPI、生产构建的 Vue/Nginx 和测试执行器，检查健康接口，从前端代理入口发送固定虚拟请求，并验证最终响应、数据库隔离、Trace 脱敏和错误路径。`tests/e2e/offline_app.py` 只注入 Fake Model/Tool Ports，真实 Application、Orchestrator、Trace Adapter 和 Repository 均不替换；该装配不是生产兼容 Adapter。

Live E2E 使用独立测试账号、固定少量只读问题和预算上限。真实写只允许测试租户；生产写、下单、持仓修改、报告发布永远禁止。

当前受控对话与报告主链的本地 Live 入口各只运行一个固定案例。报告案例使用隔离 SQLite、临时执行目录和只读 Tushare toolkit，断言真实阶段、单调进度、数据库/SSE 终态、正文 hash 与脱敏 artifact；不会发布报告或修改外部数据。Windows 本机使用 SOCKS 代理时，必须通过 Python 模块入口让 uv 的临时依赖生效：

```powershell
$env:RUN_PROTECTED_LIVE_E2E="true"
uv run --with socksio -- python -m pytest tests/e2e/test_live_controlled_chat_chain.py -q -m live

$env:RUN_PROTECTED_LIVE_REPORT_E2E="true"
uv run --locked --with socksio python -m pytest tests/e2e/test_live_report_progress.py -q -m live
```

GitHub 端只允许手工触发 `.github/workflows/live-e2e.yml`，并由 `protected-live-e2e` Environment 提供 secrets。显式触发但配置缺失时测试必须失败，不能以 skip 伪装通过。

## 4. 验证顺序

```text
format/lint/type -> unit -> contract -> integration
-> offline eval -> frontend checks -> Compose offline E2E -> protected live E2E
```

本仓库当前可复现命令见 `CONTRIBUTING.md`。完整离线链路命令为：

```powershell
docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e
docker compose -f docker/docker-compose.offline.yml down -v --remove-orphans
```

失败时先跑最窄命令、查看日志和 Trace，再做最小修复。连续两次失败就停止，保存报告和复现输入。

## 5. 测试数据和产物

测试数据固定日期、来源和时区；不把“今天的实时值”作为稳定断言。产物只保存脱敏摘要、版本、trace_id、耗时、断言和错误诊断；禁止提交数据库转储、真实 `.env` 或大段原始模型内容。
