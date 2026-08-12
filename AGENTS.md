# Finance Agent 开发流程规约（个人项目轻量版）

## 1. 这个文件是干什么的

本文件定义本仓库从需求、开发、测试、合并到上线的轻量流程，目标是让每次改动都可验证、可回滚、可追踪，同时避免个人项目被团队级重型流程拖垮。

- 主仓库：`Finance-agent-Skills`。`main` 是唯一主线，不在 `main` 上直接开发、提交或强推。
- 更近目录的 `AGENTS.md` / `AGENTS.override.md` 可以补充细节，但不能降低本文件的安全底线。
- 未获用户明确授权，不执行 `commit`、`push`、创建/合并 PR、部署或破坏性操作。

## 2. 两条流程，够用就行

**普通改动**（大多数新功能、Bug、UI、文档）：走第 3 节轻量链路。

**高风险改动**（鉴权/权限、安全、数据库迁移、破坏性操作、生产部署、新增生产依赖、跨模块重构）：在轻量链路前先写一页以内的设计说明，包含影响面、方案选择、测试与回滚；只有设计确实复杂时才启用完整 Spec Coding 链（`requirement-definition` → `codebase-reconnaissance` → `clarification` → `solution-tradeoff` → `plan-freezing` → `small-step-implementation`）。

不确定时按高风险处理；在实施中发现隐藏风险，立即停下升级流程，不要闷头写完。

## 3. 一次功能从 0 到 merge 的轻量链路

1. **记需求**：在 Issue 或 PR 描述里写清目标、非目标、验收标准（验收标准必须能通过真实请求或测试判断）。
2. **看调用链**：确认改动应放哪一层（API/服务/领域/集成适配器，前端 `api`/`stores`/`components`）；能复用就复用。从 `Finance` 迁移时只提炼已验证的逻辑，不整目录复制历史代码。
3. **建短分支**：从最新 `origin/main` 创建，命名如 `feat/xxx`、`fix/xxx`、`docs/xxx`、`refactor/xxx`。
4. **测试先行**：新功能先写最小测试或契约测试；修 Bug 先写能稳定复现且修复前失败的测试。
5. **小步实现**：一次只做一件事，保持 diff 小；不顺手重构、不格式化无关文件、不引入无关依赖。
6. **本地检查**：运行与改动相关的 `pytest` 和前端 `type-check`/`build`；合入前至少完整跑一遍相关目录。
7. **端到端验收（必做）**：见第 4 节。这是判断功能“真完成了”的硬标准。
8. **开 PR**：写清改动内容、测试证据、E2E 结果、风险与回滚方式。
9. **自审 diff**：检查密钥、日志、无关改动、接口兼容性；有同伴就让同伴审一眼，没有就留下自审记录。
10. **合并**：使用 Squash Merge 进入 `main`，删除功能分支，让每个 PR 对应一个可回滚提交。

## 4. 端到端验收：判断功能“真完成了”的硬标准

单测全绿不等于功能完成。**每个功能验收时，必须启动完整链路，构造虚拟请求真实跑一遍**；本规约明确授权：验收 E2E 可以调用真实模型和生产服务（如 OpenAI、Tushare、MCP），并按实际需要修复、迭代。

步骤：

1. 启动完整链路：优先 `docker compose -f docker/docker-compose.yml up -d --build`（包含 PostgreSQL、后端、前端）。本机没有 Docker 时，按 README 手动启动后端与前端也算完整链路，但要在 PR 中注明环境差异。
2. 健康检查：后端 `/api/health` 正常、数据库连接正常、前端页面可访问。
3. 构造虚拟请求：用 `curl`、脚本或前端页面真实调用，至少覆盖主路径和一个错误/边界路径（空输入、超时、无权限、模型失败等）。
4. 真实依赖：在本地 `.env` 配好密钥后，按需求调用真实模型与生产服务；这是验收环节的明确授权，不属于默认 CI。
5. 记录证据：保存请求、响应、日志、Trace、耗时和是否报错，作为 PR 的验收依据。
6. 有报错就修复并重新跑，直到关键链路通过；前端问题用页面/浏览器复现，后端问题看日志和 Trace。

注意：真实调用会产生费用并受外部波动影响，因此验收 E2E 只在本地/发布前手动执行，不放进每次 push 的默认 CI；CI 只跑快、稳、不花钱的检查。

## 5. 测试做什么（最低成本版）

- **单元测试**：只测业务函数、服务、工具解析等，不打真实网络；行为一改就同步更新。
- **接口/契约测试**：用 `TestClient` 和固定 fixture 覆盖 API 契约、错误码和边界。
- **验收 E2E**：第 4 节，每个功能验收必做，用真实模型/服务验证前后端完整链路。
- **Agent 改动**（Prompt、工具、工作流、Memory）：除单测外，至少用固定案例跑一遍真实链路，记录成功率、报错和耗时；暂不引入完整 Eval 平台。
- **测试数据**：固定日期、来源和容差，不用“今天的实时值”当稳定期望。
- **覆盖率**：不为追百分比堆测试，核心路径和错误路径优先。

默认 `pytest` 已通过根目录 `pyproject.toml` 配置为跳过带 `live` 标记的测试；需要真实模型/外部服务的验收测试必须加 `@pytest.mark.live`。离线评测冒烟命令：`python -m pytest tests/evals -m eval_smoke`。CI 使用与本地一致的命令。

## 6. 当前可用命令

```bash
# Python（在装好依赖的虚拟环境中；默认跳过 live 测试）
python -m pytest backend -q
python -m pytest Financial-MCP-Agent -q
python -m pytest tests/evals -m eval_smoke -q

# 只跑相关文件，加速迭代
python -m pytest backend/test_xxx.py -q

# 生成/查看某模块离线评测基线
python -m tests.evals.runner --target entity --mode smoke

# 前端（在 frontend 目录；Windows PowerShell 请用 npm.cmd）
npm ci
npm run type-check
npm run build

# 完整链路验收（含真实模型调用，见第 4 节）
docker compose -f docker/docker-compose.yml up -d --build

# Compose 静态校验（需要本机有 Docker CLI）
docker compose -f docker/docker-compose.yml config
```

没跑的命令必须在 PR 中写明“命令、原因、剩余风险”，不允许假装通过。

## 7. 个人项目版 CI/CD（先最小，后按需加）

- **CI 最小集**（GitHub Actions）：一个 job 跑离线 `pytest`，一个 job 跑前端 `type-check` + `build`；容器改动再加 `docker compose config`。之后按需补充 lint、覆盖率、依赖漏洞扫描。
- **现阶段不做**：merge queue、CODEOWNERS、多人强制审批、Staging/Production 环境审批矩阵。
- **main 保护**：在 GitHub 开启至少“需要 PR 后才能合并”和“禁止绕过保护”。个人项目允许自审，但 PR 中必须留下自审记录；CI 稳定后把必需检查设为 required status check。
- **CD 简化**：不搭建自动 Staging/Production 多环境。验收和发布都走本地完整链路（第 4 节）；`main` 合并后按 README 部署。
- **版本与回滚**：部署前保留上一个可用镜像 tag（不使用漂移的 `latest`）；出问题优先关 feature flag，其次 revert PR 或切回旧镜像。
- **数据库**：迁移前备份，破坏性操作先在副本或本地验证；禁止把不可逆删除和功能发布绑在同一步。

## 8. 安全底线（不能省的部分）

- 真实 `.env`、Token、Cookie、账号、持仓和私有连接串一律不入库，只提交 `.env.example`；发现密钥入库要轮换密钥，只删文件不够。
- 日志、Trace、截图、fixture 和 CI 产物不得输出敏感信息。
- 金融输出注明数据时间和来源，禁止把估算、过期或空数据伪装成实时确定结论。
- 输入边界校验、参数化查询；鉴权与授权改动单独测试。

## 9. Definition of Done（功能真正完成的条件）

- 验收标准有证据（测试结果或 E2E 记录）。
- 相关单测通过；关键链路 E2E 跑通，真实模型/服务按需已调用并记录结果。
- 没有无关改动、调试代码、密钥或大文件。
- PR 写清：改了哪些文件、如何验证、风险是什么、如何回滚。
- 已 Squash Merge 进 `main`，功能分支已删除。

## 10. 紧急修复

生产或演示环境出问题时：从最新 `main` 创建 `hotfix/xxx` 分支，只做最小修复，先写复现测试，跑相关测试和关键链路 E2E，再合并部署。恢复后 1～2 个工作日内补一条根因记录：为什么没被测试发现、如何防止再次发生。

## 11. Agent 每次接到功能任务时的响应协议

1. 复述目标并说明走轻量流程还是高风险流程。
2. 先读取本文件、README、相关调用链和 Git 状态，保护用户已有改动。
3. 编辑前给出执行契约：目标、范围、不做什么、如何验证。
4. 小步实现，超过 60 秒的工作持续提供简短进度。
5. 编辑后先审 diff，再运行相关检查；跑不了的检查必须如实报告原因。
6. 最终回答先说结果，再列改动文件、测试证据、未验证项和风险。
7. 未获授权不 `commit`、不 `push`、不开/合 PR、不部署。

## 12. 什么时候升级流程

出现多人协作、正式产品部署、审计或合规要求时，再逐步补充：完整 Spec Coding、强制评审、Staging 环境、完整 CI 矩阵、merge queue。个人项目阶段不提前上重型流程。
