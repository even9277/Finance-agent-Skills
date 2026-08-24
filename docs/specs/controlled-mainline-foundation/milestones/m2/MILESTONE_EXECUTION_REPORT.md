# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 2 — Implement Core Change
- Status: Complete with limitations
- Date: 2026-08-20
- Branch: `docs/1-engineering-contract`

## 2. Development Standards Read

- `PLAN.md`: 已读取，M2 允许修改 pyproject、uv lock、前端 package/lint、CI。
- `AGENTS.md`、`CONTRIBUTING.md`: 已读取并遵守依赖、渐进收紧、默认离线和 diff 规则。
- `DEV_STANDARDS.md`、`CLAUDE.md`、`.cursor/rules`、`.github/copilot-instructions.md`: 不存在。
- `C:/Users/27411/.codex/PYTHON_AGENT_ENGINEERING_STANDARD.md`: 已读取；新工具配置采用 typed/可复现方向，未修改 Python 业务代码。

## 3. Files Inspected

- `pyproject.toml`、`backend/requirements.txt`: 对比现有依赖与 pytest 配置。
- `frontend/package.json`、`frontend/package-lock.json`: 确认前端脚本和锁定依赖。
- `.github/workflows/ci.yml`: 重写前的 CI job 和默认外部服务边界。
- `tests`、`backend`、`Financial-MCP-Agent/src`: 确定 Ruff/Pyright 渐进检查范围。

## 4. Files Modified

- `pyproject.toml`: 增加根项目元数据、backend 依赖、dev dependency group、Ruff/Pyright、严格测试 markers。
- `uv.lock`: 锁定 99 个 Python 包及开发工具。
- `frontend/package.json`: 增加 ESLint 脚本和 ESLint/Vue/TypeScript lint 依赖。
- `frontend/package-lock.json`: 与 package.json 同步。
- `frontend/eslint.config.mjs`: ESLint flat config；历史规则非阻断，新门禁保留错误检查。
- `.github/workflows/ci.yml`: 增加 uv locked 安装、Ruff/Pyright/pytest、前端 lint、最小权限、缓存、超时和 Compose config job。
- `docs/specs/controlled-mainline-foundation/PLAN.md`: 更新 M2 进度、决策、发现和结果。
- `docs/specs/controlled-mainline-foundation/milestones/m2/MILESTONE_EXECUTION_REPORT.md`: 本报告。

## 5. Implementation Summary

M2 将 Python 依赖从“backend requirements + 机器当前环境”收敛为根 `pyproject.toml` 与 `uv.lock`；开发工具由锁定环境提供；pytest marker 现在显式包含 unit/contract/integration/e2e/slow；前端新增 ESLint 入口；CI 默认只执行离线测试，采用最小 `contents: read` 权限、缓存、超时和并发取消。

由于历史 Vue 组件存在大量格式警告，lint 使用 `--quiet`，并关闭已知的 DOM 全局和遗留未使用变量错误；这避免一次性修改历史代码，不代表历史债务已经消失。Pyright 以 basic 模式运行，0 errors、9 个未迁移模块 import warnings。

## 6. Diff Summary

- `pyproject.toml` / `uv.lock`: 可复现 Python 环境和质量工具。
- `frontend/package*.json` / `eslint.config.mjs`: 前端 lint 入口。
- `.github/workflows/ci.yml`: 质量门禁和离线 CI。
- No business runtime, API schema, database schema, secret, or production deployment file was modified.

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| `.venv/Scripts/uv.exe lock` | 解析依赖 | Resolved 99 packages |
| `.venv/Scripts/uv.exe sync --locked --no-install-project --group dev` | 冷安装锁定环境 | Installed 18 packages/tools |
| `.venv/Scripts/uv.exe lock --check` | 锁文件一致性 | 通过 |
| `.venv/Scripts/uv.exe run --locked ruff check tests` | Python lint | All checks passed |
| `.venv/Scripts/uv.exe run --locked pyright tests` | Python 类型检查 | 0 errors，9 warnings |
| `.venv/Scripts/uv.exe run --locked pytest -q` | 根回归 | 51 passed，4 skipped，4 deselected，56 warnings |
| `npm.cmd ci` | 前端冷安装 | 278 packages；2 low severity audit warnings |
| `npm.cmd run lint` | ESLint | 通过 |
| `npm.cmd run type-check` | Vue 类型 | 通过 |
| `npm.cmd run build` | 生产构建 | 通过；原有大 chunk/dynamic import warning |
| `docker compose -f docker/docker-compose.yml config --quiet` | Compose 配置 | 通过 |
| Python YAML parse of `.github/workflows/ci.yml` | CI YAML 语法 | 通过 |
| `git diff --check` | diff 健康 | 通过 |

## 8. Test Results

- Passed: lock、Ruff、Pyright exit code、pytest、前端 lint/type-check/build、Compose config、CI YAML。
- Failed: 无阻断失败。
- Not run: GitHub Actions 新 workflow 尚未 push 到远程；Compose 服务、集成数据库和 Live E2E 属于 M3/M4。
- Limitations: Pyright 的 9 个 warning 对应尚未迁移的历史 Planner/Executor/Verifier 模块；前端有 2 个低严重度 npm audit warning；构建有大 chunk warning。

## 9. Failures and Fixes

- Failure: 首次 ESLint 运行发现 13 errors、454 warnings，主要来自旧 Vue 模板、DOM globals 和未使用参数。
- Root cause: 仓库此前没有 ESLint 配置，历史代码未按新规则维护。
- Fix attempt: 调整 flat config 的渐进策略：关闭已知历史错误规则，使用 `--quiet` 让真正阻断错误保持门禁；不修改旧组件。
- Rerun result: `npm run lint` 通过，type-check/build 继续通过。

## 10. Scope Compliance

- Allowed files only: Yes
- Forbidden changes avoided: Yes
- User changes preserved: Yes；构建生成的 `frontend/tsconfig.node.tsbuildinfo` 已恢复且未纳入 diff。
- Dependencies changed: Yes，限 M2 明确批准的锁定工具/前端 lint 依赖。
- API/database/config changed: API/数据库/生产配置 No；仅修改本地质量和 CI 配置。

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
|---|---|---|
| Architecture and dependency direction | Satisfied | 无业务模块移动；质量工具不依赖 Runtime 适配层 |
| Docstrings, types, field meaning, section navigation | Satisfied | Pyright 配置与渐进范围已冻结 |
| Configuration, secrets, constants, prompts | Satisfied | CI 无 Secret；uv/Node lockfile；无 `.env` 变更 |
| Terminal output, logs, traces, artifacts | Not applicable | M2 未改变运行时日志/Trace |
| Validation, errors, retry/fallback, state, compatibility | Satisfied | pytest marker、默认 not live、公共 Runtime 未变 |
| Tests, evaluation, and handoff evidence | Satisfied with limitations | 本报告命令结果、根回归和前端检查完整 |

## 12. Risks Remaining

- Risk: 新 CI workflow 尚未在 GitHub 远程运行。
- Mitigation or follow-up: M4 在授权 push/PR 后观察 Actions job；若 CI 环境差异导致失败，只修同一配置范围。
- Risk: 9 个 Pyright import warnings 反映未迁移主链模块。
- Mitigation or follow-up: 模块迁移时建立可安装 `finance_agent` 包和边界类型，逐个消除 warning。
- Risk: npm audit 报 2 个低严重度问题。
- Mitigation or follow-up: 不使用 `--force` 自动升级；单独审查依赖树后处理。
- Risk: Frontend lint 仍有被 quiet 隐藏的历史 warning。
- Mitigation or follow-up: 新增/触达文件逐步收紧，不一次格式化全仓。

## 13. PLAN.md Updates

- Progress: M2 标记完成。
- Decision Log: 记录 uv 锁定和历史 lint 渐进策略。
- Surprises & Discoveries: 记录依赖重解析、Pyright warning 和前端遗留 lint。
- Outcomes & Retrospective: 记录 M2 质量工具和 CI 配置结果。

## 14. Suggested Commit Message

chore(tooling): lock Python environment and harden offline CI

- add uv lock, Ruff, Pyright and pytest marker configuration
- add frontend ESLint entrypoint and locked dependencies
- enforce offline quality jobs with minimal CI permissions

## 15. Handoff to User

Milestone 2 is complete with documented limitations. The next approved unit is Milestone 3: layered contract/integration tests, fake providers, isolated PostgreSQL and offline Compose E2E, followed by the observability slice.
