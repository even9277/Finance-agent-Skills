# Finance Agent 贡献指南

这份指南把工程流程翻译成可以照着做的步骤。你不需要先理解所有术语；每一步都有目的、命令和完成标准。

## 1. 开始前

1. 确认仓库根目录是 `Finance-agent-Skills`。
2. 确认虚拟环境 `.venv` 存在。Windows 使用 `.venv\Scripts\python.exe`，Unix 使用 `.venv/bin/python`。
3. 运行 `git status --short`。如果目标文件有别人的未提交改动，先停止并确认。
4. 从最新 `origin/main` 创建短分支，不在 `main` 直接开发。

## 2. 先写 Issue

Feature、Bug 和 Refactor 都必须先有 Issue。Issue 要用可观察的语言写清楚：

- 用户遇到什么问题，谁能观察到；
- 这次要做什么、不做什么；
- API、数据库、Agent State、Prompt、工具和前端是否受影响；
- 通过什么测试或真实请求验收；
- 失败时如何降级、如何回滚；
- 是否调用真实模型或外部服务，以及费用和副作用边界。

跨模块、Agent 主链、依赖、安全、API、数据库和部署变更，还要在 `docs/specs/<name>/` 形成 Requirement、Recon、Tradeoff 和 PLAN。

## 3. 创建分支和测试

```powershell
git fetch origin
git switch -c refactor/123-route-contract origin/main
.\.venv\Scripts\python.exe -m pytest -q
```

先写能描述当前行为的 characterization/contract test。测试应包含正常路径、边界输入、下游失败、超时、无权限和副作用规则。若无法自动化，必须在 PR 写清楚手工步骤和限制。

## 4. 实现规则

- 一个 PR 只解决一个 Issue/里程碑。
- `Finance` 只能提供历史证据，不能被 import 或复制成运行时依赖。
- 直接在唯一目标模块实现；同一个 PR 同步更新内部调用方并删除旧实现，不做兼容 Adapter。
- Router 只做协议适配，application service 负责用例和事务，Agent 模块负责决策，Provider 负责外部系统。
- 新增/修改 Python 必须有中文 docstring、类型、错误码和必要意图注释。
- 不要顺手格式化无关文件、升级无关依赖、修改 Schema 或改动生产配置。

## 5. 本地验证顺序

从窄到宽运行：

```powershell
uv lock --check
uv run --locked ruff check tests Financial-MCP-Agent/src/tools/skill_trace.py
uv run --locked pyright tests Financial-MCP-Agent/src/tools/skill_trace.py
uv run --locked pytest tests/unit tests/contract tests/integration tests/e2e -q
uv run --locked pytest backend -q
uv run --locked pytest Financial-MCP-Agent -q -m "not live"
uv run --locked pytest tests/evals -q -m "eval_smoke and not live"
uv run --locked pytest -q
Set-Location frontend
npm.cmd ci
npm.cmd run lint -- --quiet
npm.cmd run type-check
npm.cmd run build
Set-Location ..
docker compose -f docker/docker-compose.yml config --quiet
docker compose -f docker/docker-compose.offline.yml config --quiet
docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e
docker compose -f docker/docker-compose.offline.yml down -v --remove-orphans
```

当前静态检查只覆盖本次已冻结的维护范围，避免把历史未迁移模块通过全局 ignore 或大规模格式化“伪装”成零债务。每次触达新模块时，必须把该模块加入同一质量命令和对应计划。

具体模块的计划可能增加 integration、Compose E2E 或浏览器测试。测试失败时先检查最窄命令；同一里程碑连续两次修复失败就停止。

## 6. 完整链路验收

功能不能只靠单元测试验收。使用测试 Compose 启动 PostgreSQL、后端、前端和 fake Provider，检查健康接口，发送固定虚拟金融请求，验证前端事件、数据库状态、Trace 和错误路径。需要真实服务时，手动启用 `live`：真实读可以，写只能使用隔离环境，生产写永久禁止。

Live 测试报告只保存脱敏的版本、trace_id、数据日期、耗时、断言和错误摘要，不保存真实 Token、原始敏感 Prompt/响应或用户数据。

当前仓库的离线 Compose 会启动临时 PostgreSQL、真实 FastAPI、生产构建的 Vue/Nginx 和测试执行器；`tests/e2e/offline_app.py` 只替换外部 Model/Tool Ports，公开入口、Application、受控 Orchestrator、Trace Adapter 与 PostgreSQL Repository 都是真实实现。真实 Live E2E 使用单独的 `workflow_dispatch`、受保护 Environment、固定只读案例、预算、超时、临时 SQLite 和脱敏证据。

本地显式 Live 命令如下；它会产生真实模型费用并读取 Tushare，默认 CI 绝不运行。若 Windows 使用 SOCKS 代理，必须保留 `python -m pytest` 入口，不能直接调用虚拟环境中的 `pytest.exe`：

```powershell
$env:RUN_PROTECTED_LIVE_E2E="true"
uv run --with socksio -- python -m pytest tests/e2e/test_live_controlled_chat_chain.py -q -m live
```

## 7. 提交 PR

提交前：

1. 阅读 `git diff` 和 `git diff --check`。
2. 检查是否误改生成物、秘密、无关文件、公共 Schema 或数据库。
3. 在 PR 模板中填写测试命令和结果、E2E 证据、风险、回滚、未运行检查和费用边界。
4. 完成自审；再进行独立 Agent Review。
5. 解决所有 Review conversation 后等待 CI。

默认使用 Squash Merge，使一个 PR 对应一个可回滚的主线提交。没有明确授权时，Agent 不执行 commit、push、merge、分支保护或部署。

## 8. 出问题时回滚

- 未合并：停止并保留报告，放弃分支即可。
- 已合并：创建 revert PR，不改写 `main` 历史。
- 已部署：切回上一个已验证的提交/不可变镜像。
- 数据库 Schema 迁移必须独立规划，包含备份、升级、降级和恢复演练。

## 9. 给新手的术语

- Issue：描述一个问题或功能的任务卡。
- Branch：不会影响主线的独立开发副本。
- Contract test：验证模块输入、输出、错误和事件格式的测试。
- E2E：从前端/HTTP 入口经过后端、Agent、工具、数据库再返回的完整链路测试。
- CI：每次 PR 自动运行的离线质量检查。
- Live E2E：显式调用真实模型/服务的验收，不是默认 CI。
- Squash Merge：把一个 PR 压缩为一个主线提交，方便审查和回滚。
