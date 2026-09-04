# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 1 — Lock Tests and Public Contracts
- Status: Complete
- Date: 2026-09-04

## 2. Development Standards Read

- `PLAN.md`: 已读取并严格限定为测试/fixture/治理文档；业务实现属于 M2/M3。
- `DEV_STANDARDS.md`: 未发现。
- `AGENTS.md`: 已读取；应用完整 SOP、测试先行、typed contract、脱敏和一里程碑规则。
- nested `AGENTS.md` / `AGENTS.override.md`: 未发现。
- `CLAUDE.md`: 未发现。
- `.cursor/rules/*.mdc`: 未发现。
- `.github/copilot-instructions.md`: 未发现。
- README / contribution / test docs: 沿用 M0 已完整读取的 `CONTRIBUTING.md` 与 `docs/engineering/{development-sop,code-structure,testing-strategy,observability}.md`。

适用规则：测试先锁正常、边界、安全、失败和终止；Python/TS 显式类型；不导入历史 Finance runtime；默认离线；Live 显式 gate；不记录 secret/正文；不得通过弱化测试换绿；同一失败最多两次窄修复。

## 3. Files Inspected

- `backend/schemas/report.py`: 当前 REST schema 和新增三类 frame 的目标相邻位置。
- `backend/routers/report.py`: generate/status/ownership/BackgroundTasks 当前行为与 SSE 路由缺口。
- `backend/services/agent_service.py`: 真实 `astream_events`、固定 node progress、root state fallback 和 DB 更新顺序。
- `backend/middleware/auth.py`: Bearer header、query-token 差异、`require_auth`/`ensure_user_access`。
- `backend/main.py`: Router/middleware 注册和 app lifespan。
- `backend/test_agent_service.py`、`test_report_download.py`、`test_auth_service.py`: 当前报告/auth 回归模式。
- `tests/contract/test_memory_characterization_contract.py`: 仓库 strict xfail characterization 模式。
- `tests/e2e/offline_app.py`、`test_offline_compose_stack.py`、`test_live_controlled_chat_chain.py`: deterministic Compose 和 protected Live 模式。
- `frontend/src/{api/index.ts,composables/useReport.ts,views/ReportView.vue,components/report/ReportProgress.vue}`: 当前轮询、认证来源、阈值推断和生命周期缺口。
- D03/D04 frontend specs、`frontend/package.json`/Vitest config: strict parser、mock、fake timers、component/test 命令模式。

## 4. Files Modified

- `tests/contract/test_report_progress_contract.py`: D05-T01/T04/T07 协议、SSE、auth/ownership、REST compatibility/safe error。
- `tests/unit/report/test_report_task_progress.py`: D05-T02 并行乱序、metadata 优先、重复/未知节点、可选 personalization。
- `tests/unit/report/test_progress_hub.py`: D05-T03 bounded latest event、多订阅和 cleanup。
- `frontend/src/api/__tests__/reportProgressContract.spec.ts`: D05-T05 strict frame/SSE chunk parser。
- `frontend/src/composables/__tests__/useReport.progress.spec.ts`: D05-T06 Bearer fetch、transport、串行 polling、统一 cleanup。
- `frontend/src/components/report/__tests__/ReportProgress.spec.ts`: D05-T06 真实阶段和 fallback UI。
- `tests/e2e/test_report_progress_offline_contract.py`: D05-T08 Nginx/FastAPI/PostgreSQL/fake report 完整链骨架。
- `tests/e2e/test_live_report_progress.py`: D05-T09 默认关闭的单例真实报告入口。
- `docs/specs/D05_REPORT_SSE_PROGRESS_PLAN.md`: 标记 M1 并记录接口/测试决策和发现。
- `docs/specs/D05_REPORT_SSE_PROGRESS_MILESTONE_1_EXECUTION_REPORT.md`: 本报告。

## 5. Implementation Summary

本里程碑没有实现 SSE。它把 D05 的九类验收责任固化成行为测试：公共协议和脱敏、真实并行阶段、非阻塞 hub、pre-stream auth/ownership、浏览器 parser/reducer、fallback/cleanup、REST 兼容、Compose 真代理链和 protected Live。Python 使用仓库已有 strict xfail，前端使用 Vitest `it.fails`；因此缺口当前是可审计目标失败，未来实现一旦满足会 XPASS 并要求移除标记，而不是永久跳过。

测试同时冻结了最小接口方向：后端协议无关模块为 `backend.application.report_progress.{contracts,tracker,hub}`；公共 Pydantic frame 与已有 report schema 相邻；前端 parser 从 `@/api` 导出，网络生命周期由 `useReport` 所有，组件只消费 typed stage/transport props。

## 6. Diff Summary

- 5 个 Python test files：覆盖 D05-T01～T04、T07～T09。
- 3 个 frontend spec files：覆盖 D05-T05/T06。
- PLAN/report：记录受控失败基线和后续移除规则。
- No production source, dependency, database, Nginx, environment, CI or generated files were modified.
- 用户 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` 保持未编辑、未 stage。

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| `git status --short --branch`、`git diff --check` | scope/user-file/whitespace | Pass；仅 D05 docs/tests + untouched D01 |
| `uv run --locked ruff check <5 new Python test files>` | Python test 静态质量 | Pass |
| `uv run --locked python -m pytest <D05 Python test files> -q` | D05 target baseline | Pass；1 passed, 10 xfailed, 1 skipped, 1 deselected |
| `npm.cmd test -- reportProgressContract useReport.progress ReportProgress.spec` | 新 frontend target baseline | Pass；3 files, 6 expected-failure tests |
| `npm.cmd run lint -- --quiet` | frontend lint | Pass |
| `npm.cmd run type-check` | 新 tests TypeScript/Vue contract | Pass |
| `npm.cmd test` | frontend complete regression | Pass；13 files, 33 tests |

## 8. Test Results

- Passed: Python REST completed-status compatibility 1；frontend 全套 33；ruff/lint/type-check。
- Failed: None after one test-only repair。
- Expected failures: Python 10 strict xfail；frontend 6 `it.fails`（计入 Vitest pass）；它们精确对应尚未实现的 D05 功能。
- Skipped/deselected: offline Compose contract 在非 Compose 环境 skip 1；protected live 被默认 `-m not live` deselect 1。
- Not run: Python full suite、offline Compose runtime、protected Live；按 M4/M5 执行，不属于 M1。
- Limitations: frontend `it.fails` 的摘要不单独显示 xfail 数，源文件的 `.fails` 标记和实现后 unexpected-pass 共同形成门禁。

## 9. Failures and Fixes

- Failure: 首次 Python target run 为 `1 failed, 9 xfailed`；safe status 用 `payload["error_code"]`，旧实现缺字段时抛 `KeyError`，未匹配 strict xfail 的 `AssertionError`。
- Root cause: 测试写法在表达目标断言前访问不存在字段。
- Fix attempt: 改为 `payload.get("error_code") == ...`，让缺口成为明确 assertion。
- Rerun result: `1 passed, 10 xfailed, 1 skipped, 1 deselected`；ruff 通过。未修改业务实现。
- Failure: `vue-tsc -b` 把已跟踪 `frontend/tsconfig.node.tsbuildinfo` 的缓存版本从 5.9.3 改为本机 5.7.3。
- Root cause: TypeScript build-info 是增量构建产物，不是 D05 源码变化。
- Fix attempt: 对比 numstat/diff/hash 确认只有版本缓存后，精确恢复该单文件到 HEAD。
- Rerun result: `git status` 不再包含 build artifact；D01 和其他用户文件未触碰。

## 10. Scope Compliance

- Allowed files only: Yes
- Forbidden changes avoided: Yes
- User changes preserved: Yes
- Dependencies changed: No
- API/database/config changed: No

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
|---|---|---|
| Architecture and dependency direction | Satisfied | tests 冻结 protocol/application/router/composable/component 所有权，不导入历史 runtime |
| Docstrings, types, field meaning, section navigation | Satisfied | Python 测试中文 docstring/typing；TS 无 `any`；stage/progress/sequence 语义明确 |
| Configuration, secrets, constants, prompts | Satisfied | Live 仅新显式 gate 名；不改 Settings/env/Prompt，不输出值 |
| Terminal output, logs, traces, artifacts | Satisfied | forbidden Authorization/API key/report content 负向断言；无运行 artifact |
| Validation, errors, retry/fallback, state, compatibility | Satisfied | 401/404、strict parser、单调、bounded queue、serial poll、status compatibility 全有合同 |
| Tests, evaluation, and handoff evidence | Satisfied | D05-T01～T09 一一映射，exact commands/results 与本报告齐全 |

## 12. Risks Remaining

- Risk: 所有 expected-failure 仍代表真实未实现功能，不能当成最终通过。
- Mitigation or follow-up: M2 只实现 Python T01～T04/T07 并移除对应 xfail；M3 实现 frontend/T08 并移除 `.fails`/xfail；M5 才移除 Live xfail。
- Risk: offline report fixture 尚未装配，若现在直接触发 generate 可能进入旧真实 workflow。
- Mitigation or follow-up: T08 在 endpoint 探针通过前不创建报告；M3 先装配 deterministic report，再运行 Compose。

## 13. PLAN.md Updates

- Progress: M1 complete；M2～M5 未开始。
- Decision Log: 记录 strict expected-failure 门禁、后端目标模块路径和前端 owner/export。
- Surprises & Discoveries: 记录 strict xfail `KeyError` 表达问题，以及 `vue-tsc` 更新已跟踪 build-info 后的精确清理。
- Outcomes & Retrospective: 更新已锁定测试数量和仍未实施的真实边界。

## 14. Suggested Commit Message

```text
test(report): lock D05 SSE progress contracts

- Cover typed progress, auth, fallback, cleanup, and proxy behavior
- Add guarded offline and live end-to-end acceptance entries
- Keep production behavior unchanged until implementation
```

## 15. Handoff to User

Milestone 1 is complete. I will not proceed to the next milestone unless you explicitly ask me to continue.
