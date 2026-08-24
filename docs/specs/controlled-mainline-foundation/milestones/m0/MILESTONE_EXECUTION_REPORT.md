# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 0 — Safety and Baseline Check
- Status: Complete
- Date: 2026-08-20

## 2. Development Standards Read

- PLAN.md: 已完整读取并按 Milestone 0 的只读范围执行。
- DEV_STANDARDS.md: 不存在。
- AGENTS.md: 已读取仓库根 AGENTS.md。
- nested AGENTS.md / AGENTS.override.md: 未发现。
- CLAUDE.md: 不存在。
- .cursor/rules/*.mdc: 未发现。
- .github/copilot-instructions.md: 不存在。
- README / contribution / test docs: 已读取规划阶段的仓库勘察与当前命令；CONTRIBUTING.md 尚不存在，属于 Milestone 1。
- Personal Python / Agent Engineering Standard: 已读取 C:/Users/27411/.codex/PYTHON_AGENT_ENGINEERING_STANDARD.md。

## 3. Files Inspected

- AGENTS.md: 确认当前轻量开发规则与权限边界。
- docs/specs/controlled-mainline-foundation/PLAN.md: 提取当前里程碑、允许范围、测试与停止条件。
- pyproject.toml: 确认 pytest 默认跳过 live 和当前测试路径。
- frontend/package.json: 确认 type-check/build 命令。
- docker/docker-compose.yml: 通过 Compose 解析确认当前服务配置有效。
- .github/workflows/ci.yml: 确认当前离线 CI job。

## 4. Files Modified

- docs/specs/controlled-mainline-foundation/PLAN.md: 更新 M0 Progress、Decision Log、Surprises & Discoveries 和 Outcomes。
- docs/specs/controlled-mainline-foundation/milestones/m0/MILESTONE_EXECUTION_REPORT.md: 新增本里程碑证据报告。

## 5. Implementation Summary

本里程碑没有修改业务代码、依赖、配置、API 或数据库。完成了仓库状态、远程主线、开发工具、现有测试、前端构建、Docker Compose 和 GitHub CI 的基线确认，并记录两个非阻断技术债。

## 6. Diff Summary

- docs/specs/controlled-mainline-foundation/PLAN.md: 记录 M0 实际结果。
- docs/specs/controlled-mainline-foundation/milestones/m0/MILESTONE_EXECUTION_REPORT.md: 固化可审计的命令与结果。
- No files outside the current milestone scope were modified.

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| git status --short / git branch --show-current | 检查用户改动与分支 | main；仅 docs/specs 为本任务新增未跟踪文件 |
| git fetch origin --prune / git rev-list --left-right --count HEAD...origin/main | 比较远程主线 | 0 0；HEAD 与 origin/main 均为 4570ee9 |
| gh auth status | 检查后续 GitHub 闭环能力 | even9277 已登录，具有 repo/workflow scope |
| .venv/Scripts/python.exe --version | 确认 Python | Python 3.12.13 |
| .venv/Scripts/python.exe -m pytest backend -q | 后端基线 | 12 passed，56 warnings |
| .venv/Scripts/python.exe -m pytest Financial-MCP-Agent -q -m "not live" | Agent 离线基线 | 33 passed，4 deselected |
| .venv/Scripts/python.exe -m pytest tests/evals -q -m "eval_smoke and not live" | 离线评测基线 | 6 passed，4 skipped |
| .venv/Scripts/python.exe -m pytest -q | 根回归 | 51 passed，4 skipped，4 deselected，56 warnings |
| npm.cmd ci | 前端锁定安装 | 178 packages；0 vulnerabilities |
| npm.cmd run type-check | 前端类型 | 通过 |
| npm.cmd run build | 前端生产构建 | 通过；存在既有拆包/大 chunk 警告 |
| docker compose -f docker/docker-compose.yml config --quiet | Compose 静态验证 | 通过 |
| gh run list --branch main | 主线 CI | run 31602724590，success |

## 8. Test Results

- Passed: 所有 Milestone 0 必需基线检查均通过。
- Failed: 无。
- Not run: 未启动完整 Compose 服务、未执行 Live E2E；两者属于后续测试基础设施与验收里程碑。
- Limitations: 系统 PATH 的 python 是 Windows Store 占位符，必须使用仓库 .venv；Docker 本轮只做静态 config。

## 9. Failures and Fixes

- Failure: 前端构建更新了已跟踪的 frontend/tsconfig.node.tsbuildinfo 中 TypeScript 版本元数据。
- Root cause: 本地 npm 安装使用 package.json 约束解析 TypeScript 5.7.3，而仓库生成文件记录 5.9.3。
- Fix attempt: 将该纯生成变动恢复到 HEAD，未修改 package/lockfile。
- Rerun result: git status 只剩本任务 docs/specs；构建本身已成功。

## 10. Scope Compliance

- Allowed files only: Yes
- Forbidden changes avoided: Yes
- User changes preserved: Yes
- Dependencies changed: No
- API/database/config changed: No

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
|---|---|---|
| Architecture and dependency direction | Not applicable | M0 只读，不修改架构 |
| Docstrings, types, field meaning, section navigation | Not applicable | 无代码修改 |
| Configuration, secrets, constants, prompts | Satisfied | 未读取或修改真实 .env；确认 .env 未被 Git 跟踪 |
| Terminal output, logs, traces, artifacts | Satisfied | 仅记录脱敏命令摘要，gh token 输出已遮蔽 |
| Validation, errors, retry/fallback, state, compatibility | Not applicable | 无运行时行为变更 |
| Tests, evaluation, and handoff evidence | Satisfied | 已运行完整现有离线回归、前端构建与 Compose 配置检查 |

## 12. Risks Remaining

- Risk: datetime.utcnow 产生 56 个弃用警告。
- Mitigation or follow-up: 作为独立技术债在后续允许范围内修复，不阻断本基线。
- Risk: 前端存在混合动态导入和大 chunk 警告。
- Mitigation or follow-up: 后续用真实构建/性能数据单独治理，不在基础设施里程碑顺手重构。
- Risk: 完整 Compose 和真实服务 E2E 尚未执行。
- Mitigation or follow-up: 在 Milestone 3/4 建立隔离、可重复的执行入口后运行。

## 13. PLAN.md Updates

- Progress: M0 标记完成并附证据。
- Decision Log: 记录本地 Python 必须使用仓库 .venv。
- Surprises & Discoveries: 记录 UTC 弃用和前端构建警告。
- Outcomes & Retrospective: 记录只读基线结果。

## 14. Suggested Commit Message

docs(plan): record controlled-mainline baseline

- add frozen requirement, reconnaissance, tradeoff, and execution artifacts
- record local and CI baseline evidence
- preserve runtime behavior

## 15. Handoff to User

Milestone 0 is complete. The next approved unit is Milestone 1, which may only change the engineering constitution, contribution guide, architecture/testing/observability documentation, and GitHub Issue/PR templates.
