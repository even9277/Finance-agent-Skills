# D04 Milestone 4 Execution Report

## 1. Milestone Executed

- Milestone: Full Verification, Live E2E, Browser and Narrow Fixes
- Status: `SUCCEEDED_WITH_LOCAL_DOCKER_LIMITATION`
- Date: 2026-09-04
- Branch: `feat/d04-controlled-interaction-ui`
- Base: `eb0549bccb4e6ae9c14f18dc49168bae6a3b6676`
- Issue: [#48 Add controlled plan, step, tool, and evidence interaction UI](https://github.com/even9277/Finance-agent-Skills/issues/48)

M4 已证明 D04 在本机隔离前后端、真实浏览器、真实模型和真实 Tushare 链路中运行。两份 Compose 配置可以解析，但 Docker Desktop 4.86.0 因其本地损坏的 `dockerInference` 运行节点在启动阶段崩溃，因此本机容器 `up` 未通过；该环境门禁必须由 M5 GitHub Actions Compose job 补齐，不能记作本机通过。

## 2. Scope and Standards

- 仅执行冻结计划的 M4；未更新 README、提交、推送、创建 PR 或进入 M5。
- 允许修改 D04 的窄屏布局、确定性浏览器测试支持和 protected Live 断言。
- 未修改数据库 Schema、迁移、Redis、认证、Prompt、Skills、Memory、工具治理或生产依赖。
- 保留且未触碰用户的 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md`。
- 使用 small-step implementation 约束单里程碑边界；使用 in-app Browser 对真实本地页面进行桌面、窄屏、停止和 Skill 确认验收。

## 3. Narrow Repairs

### 3.1 Narrow viewport usability

浏览器在 `390x844` 下发现左右两个固定 `w-64` 侧栏把中间输入框挤压为 `0px`。`ChatView.vue` 现在在小于 `1024px` 时隐藏该页面的两个辅助侧栏，只保留受控对话主链；复验输入框宽度为 `248px`，document width 与 viewport 均为 `390px`。

### 3.2 Deterministic browser stop window

`FakeModelProvider` 增加默认关闭的 `chunk_delay_seconds`，`tests/e2e/offline_app.py` 仅通过 `OFFLINE_E2E_MODEL_CHUNK_DELAY_SECONDS` 为浏览器验收注入延迟。默认测试和 Compose 行为仍为零延迟；未增加生产配置或依赖。

### 3.3 Real-provider D04 assertions

protected Live 用例现在验证真实控制帧顺序：`plan_preview` 先于 step/tool lifecycle，`verification_summary` 先于 `content_delta`；并验证 validated plan、step/tool 终态、Trace 摘要以及禁止公开 `arguments`、`facts`、`permission_hash`、`idempotency_key`。真实数据缺失时允许且要求终态与 `PARTIAL`/limitations 一致，不把正确降级误判为失败。

## 4. Verification Evidence

| Gate | Result |
|---|---|
| `uv lock --check` | Passed; 114 packages resolved |
| D04 scoped Ruff | Passed |
| D04 scoped Pyright | `0 errors, 0 warnings` |
| D04 Python unit/contract/WS E2E | `15 passed` |
| Unit + contract + integration + E2E | `304 passed, 6 skipped, 3 deselected, 3 xfailed` |
| Backend suite | `11 passed` |
| Financial-MCP-Agent non-live | `33 passed, 4 deselected` |
| Eval smoke | `29 passed` |
| Root offline regression after repairs | `377 passed, 6 skipped, 7 deselected, 3 xfailed` |
| `npm ci` | Passed; lock-consistent install |
| Frontend ESLint | Passed |
| Frontend Vue/TypeScript check | Passed |
| Frontend Vitest | `10 files / 27 tests passed` |
| Frontend production build | Passed; 404 modules transformed |
| Compose production config | Passed |
| Compose offline config | Passed |
| Protected Live baseline | `2 passed`; real model for both, real Tushare for one |
| Protected Live with D04 control assertions | Final focused real-model + real-Tushare case `1 passed, 1 deselected` |
| `git diff --check` | Passed; line-ending warnings only |

The full-repository Ruff and Pyright gates remain red on the unchanged baseline: Ruff reports 65 findings and Pyright reports 70 errors/6 warnings, all outside the D04 changed surface. D04 scoped checks are clean. This historical debt was not mass-fixed in M4.

## 5. Browser Acceptance

### Desktop (`1440x900`)

- Initial page had no fabricated execution panel before any authority event.
- A real local WebSocket turn displayed the validated plan, six step states, six tool calls, evidence sufficiency/claim level and final text.
- The layout had no horizontal overflow (`scrollWidth == viewport width`).

### Narrow (`390x844`)

- Before repair, input width was `0px`; after repair it was `248px`.
- Validated execution state remained visible and the page had no horizontal overflow.
- After waiting for the authority-backed plan, clicking `停止生成` removed the active stop action, showed cancellation, did not show `SUCCEEDED`, and did not add `请求失败`.
- A mid-confidence request displayed three Skill candidates; choosing `stock-first-pass` removed the confirmation card and completed the continuation without request error.

The browser viewport override was reset and the agent-created tab was closed. Local frontend/backend listeners were stopped. The isolated browser database was moved out of the repository to the system temporary directory after the host blocked direct deletion; no production or user data was used.

## 6. Protected Live Failure and Repair

The first enhanced Live assertion failed after a fully successful external call because the test referenced a nonexistent `sufficient` field and assumed every real run must be evidence-complete. The actual public field is `sufficiency`; Tushare returned no `financial_indicator`, and the application correctly emitted `PARTIAL / EVIDENCE_MISSING` with a limitation.

The assertion was corrected to require consistency between `SUFFICIENT`/`PARTIAL`/`INSUFFICIENT`, missing dimensions, limitation text and terminal status. The same fully real path then passed. No production behavior was weakened or changed.

## 7. Docker Desktop Limitation

- Docker client: available, context `desktop-linux`.
- Docker daemon: unavailable at `npipe:////./pipe/dockerDesktopLinuxEngine`.
- Both Compose files pass `config --quiet`.
- Isolated project `d04m4` fails before image access because the daemon is absent; no container or volume was created.
- Docker logs identify the external root cause: Desktop 4.86.0 crashes while initializing its Inference manager because `C:/Users/27411/AppData/Local/Docker/run/dockerInference` is a damaged inaccessible reparse point.
- With all Docker processes stopped, the exact node remained inaccessible to `Rename-Item`, `fsutil reparsepoint delete` and `.NET File.Delete`. No factory reset, recursive delete, WSL cross-shell deletion, image removal or user-data mutation was attempted.

M5 must treat the repository Compose job in GitHub Actions as the authoritative container runtime gate. If CI also fails for a repository reason, D04 cannot merge until fixed; if CI passes, the remaining local failure is host-specific Docker Desktop debt.

## 8. Additional Risks Observed

- `npm ci` reports three existing dependency advisories (two low, one critical). No automatic audit fix was run because dependency upgrades are outside D04 and may be breaking.
- Uvicorn may include the WebSocket query token in connection logs. The token transport/auth redesign is explicitly deferred by the D04 plan; production logging and WebSocket ticket/cookie design need a dedicated security task.
- Existing Starlette/httpx and naive `datetime.utcnow()` deprecation warnings remain unchanged.
- Existing Vite chunk-size and mixed dynamic/static import warnings remain unchanged.

## 9. Scope Compliance

- Allowed files only: Yes.
- User work preserved: Yes.
- Generated `frontend/tsconfig.node.tsbuildinfo` restored and excluded: Yes.
- New production dependency/config/database/auth changes: No.
- D05/D06 work started: No.
- M5 work started: No.

## 10. Handoff

M4 is complete with a transparent local Docker limitation. The next permitted work is D04 M5 only: update repository truth, conduct final review, stage only D04 files, commit/push/open PR linked to #48, use CI (including Compose) to close the container runtime gate, resolve findings, squash merge and verify `origin/main`.
