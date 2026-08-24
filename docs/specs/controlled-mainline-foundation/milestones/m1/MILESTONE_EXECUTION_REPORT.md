# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 1 — Lock or Add Tests / Reproduction
- Status: Complete
- Date: 2026-08-20
- Branch: `docs/1-engineering-contract`

## 2. Development Standards Read

- `PLAN.md`: 已读取，严格限制本里程碑只改规则、文档和模板。
- `AGENTS.md`: 已重写并作为本仓库工程合同。
- `DEV_STANDARDS.md`、`CLAUDE.md`、`.cursor/rules`、`.github/copilot-instructions.md`: 均不存在。
- `README.md`、现有 pytest/CI 配置：已在 M0 勘察和本轮验证中使用。
- `C:/Users/27411/.codex/PYTHON_AGENT_ENGINEERING_STANDARD.md`: 已读取；本轮无 Python 代码改动。

## 3. Files Inspected

- `docs/specs/controlled-mainline-foundation/PLAN.md`: 当前里程碑范围和验收标准。
- `AGENTS.md`: 原规则作为重写前基线。
- `.github/workflows/ci.yml`、`pyproject.toml`、`frontend/package.json`: 命令和现有 CI 口径。
- `docs/specs/controlled-mainline-foundation/*`: 需求、勘察、决策和方案证据。

## 4. Files Modified

- `AGENTS.md`: 升级为完整工程协作合同。
- `CONTRIBUTING.md`: 增加面向小白的 Issue 到 merge SOP、测试、E2E、Review 和回滚说明。
- `docs/architecture/README.md`: 定义当前入口、目标依赖方向和受控主链模块边界。
- `docs/engineering/development-sop.md`: 固化 Spec、分支、测试先行、直接重构、E2E、Review 和回滚阶段。
- `docs/engineering/code-structure.md`: 固化目录职责、命名、分层和注释边界。
- `docs/engineering/testing-strategy.md`: 固化 unit/contract/integration/eval/E2E/live 测试层级和安全边界。
- `docs/engineering/observability.md`: 固化日志、Trace、Langfuse、字段和脱敏规范。
- `.github/ISSUE_TEMPLATE/feature.yml`: 新能力 Issue Form。
- `.github/ISSUE_TEMPLATE/bug.yml`: 缺陷 Issue Form。
- `.github/ISSUE_TEMPLATE/config.yml`: 禁用空白 Issue 并链接贡献指南。
- `.github/pull_request_template.md`: PR 变更、测试、E2E、观测、安全、Review 和回滚清单。
- `docs/specs/controlled-mainline-foundation/PLAN.md`: 更新 M1 进度、决策、发现和结果。
- `docs/specs/controlled-mainline-foundation/milestones/m1/MILESTONE_EXECUTION_REPORT.md`: 本报告。

## 5. Implementation Summary

本里程碑建立了后续直接模块重构的唯一工程口径：Finance 只作证据源，不做运行时依赖；每个模块先锁契约、再唯一位置直接替换，同 PR 修改调用方并删除旧实现；默认 CI 离线，完整链路 E2E 必须执行，Live 真实读取与隔离写受保护，生产写永久禁止。文档同时明确了目录所有权、接口类型、中文注释、日志/Trace 字段、脱敏、Issue/PR、Review、Squash Merge 和回滚。

## 6. Diff Summary

- `AGENTS.md`: 97 行工程合同，覆盖边界、SOP、架构、测试、安全、观测、交付和 DoD。
- `CONTRIBUTING.md`: 小白可执行的从 0 到 merge 指南。
- `docs/architecture/*`、`docs/engineering/*`: 结构、开发、测试和观测规范。
- `.github/ISSUE_TEMPLATE/*`、`.github/pull_request_template.md`: 结构化协作入口。
- `docs/specs/.../PLAN.md`: 仅更新治理区块。
- No business runtime, API, database, dependency, secret, or deployment file was modified.

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| `.venv/Scripts/python.exe -c "import yaml; ..."` | 解析所有 GitHub YAML | `yaml ok` |
| `.venv/Scripts/python.exe -c "...template assertions..."` | 检查 Feature/Bug/PR 必填字段、安全与回滚口径 | `template fields ok` |
| `.venv/Scripts/python.exe -c "...local link check..."` | 检查本地 Markdown 目标 | `local link missing: []` |
| `git diff --check` | 检查空白和 patch 错误 | 通过 |
| `.venv/Scripts/python.exe -m pytest -q` | 确认文档/模板变更不影响根回归 | 51 passed，4 skipped，4 deselected，56 warnings |
| `git status --short` / `git diff --stat` | 检查范围 | 仅规则、文档、模板和 specs；无业务 Runtime diff |

## 8. Test Results

- Passed: YAML、模板字段、本地链接、diff check、根级 pytest。
- Failed: 无。
- Not run: Ruff/Pyright/前端 lint/Compose E2E/Live E2E 属于后续里程碑；本里程碑未新增运行依赖。
- Limitations: YAML 检查使用当前 `.venv` 的 PyYAML；后续应把检查固化为 CI 命令而非一次性脚本。

## 9. Failures and Fixes

- Failure: 初次批量 patch 尝试同时删除并新增同一文件，apply_patch 拒绝该 patch。
- Root cause: 补丁操作类型冲突，不是项目代码问题。
- Fix attempt: 分两次完成 AGENTS.md 的删除与新增，再继续添加文档和模板。
- Rerun result: 文件存在、内容检查通过，根回归通过。

## 10. Scope Compliance

- Allowed files only: Yes
- Forbidden changes avoided: Yes
- User changes preserved: Yes
- Dependencies changed: No
- API/database/config changed: No

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
|---|---|---|
| Architecture and dependency direction | Satisfied | `docs/architecture/README.md`、`docs/engineering/code-structure.md` |
| Docstrings, types, field meaning, section navigation | Satisfied | `AGENTS.md` 和 code-structure 规范已冻结 |
| Configuration, secrets, constants, prompts | Satisfied | `AGENTS.md`、CONTRIBUTING 和 observability 脱敏规则 |
| Terminal output, logs, traces, artifacts | Satisfied | `docs/engineering/observability.md` |
| Validation, errors, retry/fallback, state, compatibility | Satisfied | `AGENTS.md`、testing strategy、PR 模板 |
| Tests, evaluation, and handoff evidence | Satisfied | 测试分层文档、Issue/PR 模板和本报告 |

## 12. Risks Remaining

- Risk: 文档规则尚未自动成为 CI required check。
- Mitigation or follow-up: M2 增加稳定的 lint/type/marker/文档检查入口并接入 CI。
- Risk: 目标 `finance_agent` 包尚未建立，当前文档是目标边界而非已完成迁移。
- Mitigation or follow-up: 后续每个业务模块单独走 Spec 和 PLAN，不在 M1 伪造目录或 Adapter。
- Risk: GitHub Issue/PR 模板已在本地，尚未推送到远程主线。
- Mitigation or follow-up: 经过后续 CI 和用户确认后再执行授权的 commit/push/PR。

## 13. PLAN.md Updates

- Progress: M1 标记完成。
- Decision Log: 记录 M1 只做工程规则、文档和模板。
- Surprises & Discoveries: 记录文档检查应固化进 CI。
- Outcomes & Retrospective: 记录规则和模板交付结果。

## 14. Suggested Commit Message

docs(governance): establish engineering contract and contribution templates

- document direct controlled-mainline refactoring rules
- add testing, observability, architecture and beginner SOP docs
- add GitHub issue and pull request templates

## 15. Handoff to User

Milestone 1 is complete. The next approved unit is Milestone 2: reproducible Python/frontend quality tooling and CI hardening. No business runtime was changed.
