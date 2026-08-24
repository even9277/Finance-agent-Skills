# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 0 — Safety and Baseline Check
- Status: Complete with limitations
- Date: 2026-08-24

## 2. Development Standards Read

- `PLAN.md`: 已完整读取，按冻结的 Milestone 0 只读边界执行。
- `DEV_STANDARDS.md`: 仓库未发现。
- `AGENTS.md`: 已读取个人规则和仓库根 `AGENTS.md`。
- nested `AGENTS.md` / `AGENTS.override.md`: 未发现。
- `CLAUDE.md`: 未发现。
- `.cursor/rules/*.mdc`: 未发现。
- `.github/copilot-instructions.md`: 未发现。
- README / contribution / test docs: 已读取根 README、`backend/README.md`、`frontend/README.md`、`CONTRIBUTING.md`、`docs/architecture/README.md` 和 `tests/evals/README.md`。
- Small-step references: 已读取开发规范、执行协议、测试失败处理、diff/commit 规则和报告模板。

## 3. Files Inspected

- `docs/specs/controlled-conversation-mainline/PLAN.md`: 提取当前里程碑、允许范围、检查、停止条件和治理要求。
- `AGENTS.md`、`CONTRIBUTING.md`: 确认分层、默认离线测试、用户改动保护和 GitHub 权限边界。
- `.github/workflows/ci.yml`: 核对现有离线 Python、前端、Compose 配置和 Compose E2E 命令。
- `pyproject.toml`: 核对 Python 版本、锁定依赖、pytest 路径/markers 和默认 `not live` 规则。
- `frontend/package.json`: 核对 lint、type-check 和 build 脚本。
- `docker/docker-compose.offline.yml`: 核对空凭证、内部网络、隔离 PostgreSQL 和离线服务装配。
- README/架构/评测说明: 核对本地运行入口和测试命令说明。
- Git 状态与 tracked/untracked 清单: 审计上一轮基础设施改动及其与后续里程碑的重叠。

## 4. Files Modified

- `docs/specs/controlled-conversation-mainline/PLAN.md`: 更新 M0 Progress、Decision Log、Surprises & Discoveries 和 Outcomes & Retrospective。
- `docs/specs/controlled-conversation-mainline/milestones/m0/MILESTONE_EXECUTION_REPORT.md`: 新增本里程碑证据报告。

## 5. Implementation Summary

本里程碑没有实现或修改任何运行时代码。它确认当前仓库仍位于 `docs/1-engineering-contract`，HEAD 与 `main`、`origin/main` 同为 `4570ee9`；本地 Python、Node 和 Docker 工具链可用；uv 锁文件、两份 Compose 配置和 pytest 测试收集有效。

工作区中的 CI、AGENTS、Trace、frontend、pyproject、Docker、tests、docs 和锁文件改动来自上一轮基础设施工作，归属已知，但必须作为受保护改动保留。由于它们与后续测试和观测范围重叠，下一里程碑编辑前必须逐文件避让；分支创建或切换仍需用户明确授权。

## 6. Diff Summary

- `docs/specs/controlled-conversation-mainline/PLAN.md`: 仅补充 M0 的实际状态和证据。
- `docs/specs/controlled-conversation-mainline/milestones/m0/MILESTONE_EXECUTION_REPORT.md`: 固化只读检查、限制和交接结论。
- 本里程碑没有修改业务代码、测试实现、依赖、配置、API、数据库或历史 `Finance` 仓库。

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| `git status --short --untracked-files=all` | 获取完整未提交改动清单 | 通过；确认 6 个 tracked 修改及上一轮基础设施 untracked 文件 |
| `git branch --show-current` | 核对当前分支 | `docs/1-engineering-contract` |
| `git rev-parse --show-toplevel` | 核对唯一主仓库根目录 | `D:/FinanceProject/Finance-agent-Skills` |
| `git log -1 --oneline --decorate` | 核对 HEAD 与主线关系 | `4570ee9`，同时指向当前分支、`main`、`origin/main` |
| `uv --version` | 核对 uv | `0.12.3` |
| `.venv\Scripts\python.exe --version` | 核对仓库 Python | `3.12.13` |
| `node --version` / `npm.cmd --version` | 核对前端工具链 | Node `v24.18.0`；npm `11.16.0` |
| `docker --version` / `docker compose version` | 核对容器工具链 | Docker `29.7.2`；Compose `v5.3.1` |
| `docker version --format ...` | 核对 Docker 守护进程 | Client/Server 均为 `29.7.2` |
| `uv lock --check` | 核对锁文件一致性 | 通过；解析 99 packages |
| `docker compose -f docker/docker-compose.yml config --quiet` | 核对常规 Compose 语法 | 通过 |
| `docker compose -f docker/docker-compose.offline.yml config --quiet` | 核对离线 Compose 语法 | 通过 |
| `uv run --locked pytest --collect-only -q` | 只收集测试，不执行测试或外部调用 | 通过；66/70 collected，4 项 `live` deselected，1 条弃用警告 |
| `git diff --check` | 检查已有 tracked diff 的空白错误 | 通过；仅有 Windows LF→CRLF 提示 |

## 8. Test Results

- Passed: 所有 Milestone 0 要求的状态、版本、锁文件、Compose 配置和测试收集检查均通过。
- Failed: 无。
- Not run at M0 completion time: 未运行 pytest 测试正文、服务、Live E2E、真实模型或生产服务调用。
- Subsequent evidence: 用户在 M0 报告后显式授权真实只读调用；真实模型、Tushare、Live Router 和当前公开 HTTP 主链的结果另见 `../../LIVE_VALIDATION_REPORT.md`，不改变 M0 原本的只读范围。
- Limitations: M0 本身只证明测试可收集和配置可解析；后续 Live 只证明当前旧 `chat_service` 链路，不证明待重构的新受控主链。

## 9. Failures and Fixes

- Failure: None。
- Root cause: Not applicable。
- Fix attempt: Not applicable。
- Rerun result: Not applicable。

## 10. Scope Compliance

- Allowed files only: Yes
- Forbidden changes avoided: Yes
- User changes preserved: Yes
- Dependencies changed: No
- API/database/config changed: No

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
|---|---|---|
| Architecture and dependency direction | Not applicable | M0 没有运行时代码或架构改动 |
| Docstrings, types, field meaning, section navigation | Not applicable | M0 没有 Python 接口改动 |
| Configuration, secrets, constants, prompts | Satisfied | 仅静态解析安全配置；未读取/修改真实 `.env` 或凭证 |
| Terminal output, logs, traces, artifacts | Satisfied | 报告只保存版本、计数和脱敏状态，不保存 Prompt、Token 或用户数据 |
| Validation, errors, retry/fallback, state, compatibility | Not applicable | M0 没有运行时行为变更 |
| Tests, evaluation, and handoff evidence | Satisfied with limitation | 测试收集、marker、锁文件和 Compose 配置已验证；测试正文属于后续里程碑 |

## 12. Risks Remaining

- Risk: 当前分支包含上一轮跨 tests/CI/Trace/frontend 的未提交基础设施改动，无法把下一业务里程碑作为干净独立 diff 直接交付。
- Mitigation or follow-up: 继续保护这些改动；用户授权后创建/切换符合 SOP 的独立交付边界，或先将基础设施作为独立 Review/PR 固化。
- Risk: `pytest --collect-only` 出现 Starlette `TestClient` 弃用警告。
- Mitigation or follow-up: 记录为技术债，不在 M0 升级依赖；后续在独立依赖/测试基础设施任务中处理。
- Risk: 现有离线 Compose E2E 替换整个 Chat Service，仍不能证明真实受控 Orchestrator。
- Mitigation or follow-up: 按冻结计划在 Milestone 7 只替换外部 Ports，而不是替换业务服务。

## 13. PLAN.md Updates

- Progress: M0 标记为完成并附真实命令证据与分支限制。
- Decision Log: 记录现有脏工作区的保护策略，以及 M0 不运行测试正文的边界。
- Surprises & Discoveries: 记录测试收集数量、弃用警告和当前分支/主线关系。
- Outcomes & Retrospective: 记录本里程碑实际核验结果和下一阶段治理前提。

## 14. Suggested Commit Message

```text
docs(controlled-chat): record milestone zero baseline

- audit the protected infrastructure worktree
- verify toolchain, lockfile, compose config, and test collection
- document the branch gate and remaining risks
```

## 15. Handoff to User

Milestone 0 is complete with limitations. The next approved unit is Milestone 1, which may only add characterization/contract tests and fixed fixtures without changing production behavior. Branch creation, commit, push, PR, merge, release, and deployment remain unauthorized.
