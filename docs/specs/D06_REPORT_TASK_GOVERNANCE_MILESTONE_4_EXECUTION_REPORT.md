# D06 报告任务治理 M4 执行报告

## 1. Milestone Executed

- Milestone: 4 — Frontend Recovery and Deployment Topology
- Status: Complete with browser-smoke environment limitation
- Date: 2026-09-07

## 2. Development Standards Read

- `docs/specs/D06_REPORT_TASK_GOVERNANCE_PLAN.md`: 已读取；M4 只允许浏览器显式幂等键、刷新恢复、双后端代理拓扑及其测试。
- 根 `AGENTS.md`: 已读取；最小改动、应用/基础设施边界、配置/隐私、真实基础设施和 diff 审核规则适用。
- `C:/Users/27411/.codex/skills/small-step-implementation/SKILL.md` 及全部直接引用协议：按单里程碑、先红后绿、同一失败两次修复上限、报告后停止执行。
- `C:/Users/27411/.codex/PYTHON_AGENT_ENGINEERING_STANDARD.md`: 已读取并应用到测试辅助边界、类型、注释和失败语义。
- `computer-use` skill、核心 guidance 与 confirmations：仅用于不提交报告、不发送敏感数据的本地浏览器烟测。

Applicable rules:

- 每次用户主动生成创建一个 Web Crypto UUID；同一次响应丢失重试必须复用同一 key，确定性 4xx 不重试。
- 浏览器只在当前用户摘要命名空间保存 task/report/key/fingerprint 四字段，不保存原始 user、command、token、正文或错误。
- 刷新先调用状态接口验证所有权，再恢复 SSE/轮询；不得通过 POST 恢复。
- Redis 仍是可选派生层，生产后端启动不得依赖 Redis healthy；双实例测试必须使用真实 Nginx、PostgreSQL 和 Redis。
- 不修改 auth/JWT、Prompt、Agent、工具、Skills、Memory 或生产依赖。

## 3. Files Inspected

- `frontend/src/api/index.ts`, `frontend/src/api/reportProgress.ts`: 报告 API、错误适配和 SSE 合同。
- `frontend/src/composables/useReport.ts`, report store/view/tests: 创建、观察、轮询、清理和页面挂载链路。
- `docker/docker-compose.yml`, `docker/docker-compose.offline.yml`, existing Nginx/Dockerfiles: 生产和隔离拓扑。
- `tests/e2e/offline_app.py`, offline stack/report tests: 假外部端口、真实应用链路和共享 artifact。
- M1 D06-T07 红测、M3 后端持久版本与跨实例接口，以及 M0-M3 执行报告。

## 4. Files Modified

- `frontend/src/api/index.ts`: typed `ApiRequestError`；创建响应可选治理字段；显式 `Idempotency-Key` header。
- `frontend/src/composables/reportTaskRecovery.ts`: Web Crypto 用户摘要、请求指纹、UUID 和严格四字段 `sessionStorage` 管理。
- `frontend/src/composables/useReport.ts`: 一次同键安全重试、创建后最小引用、刷新无 POST 恢复、所有权/终态/logout 定向清理。
- `frontend/src/views/ReportView.vue`: 页面挂载时先恢复活动任务，再加载历史。
- `frontend/src/api/reportProgress.ts`: 注释对齐 PostgreSQL 持久版本语义。
- `frontend/src/api/__tests__/reportTaskGovernanceContract.spec.ts`, `frontend/src/composables/__tests__/useReport.governance.spec.ts`: D06-T07 API/恢复/隔离/清理/重试合同。
- `docker/docker-compose.yml`: 启用报告治理 Redis 配置，但不增加 Redis 启动依赖。
- `docker/docker-compose.offline.yml`, `docker/nginx/offline.conf`: 两个后端、真实 `least_conn` 代理、SSE、隔离命名空间和 runner gate。
- `tests/e2e/offline_app.py`: test-only 实例响应头和只含固定计数行的 workflow artifact。
- `tests/e2e/test_report_task_governance_offline.py`: 20 路同键、双实例 SSE、Redis 报告 namespace 定向删除和数据库重建验收。
- `tests/e2e/test_report_task_governance_offline_contract.py`: 静态拓扑/环境/Nginx 合同。
- `tests/e2e/test_report_progress_offline_contract.py`: D05 版本合同改为严格递增且唯一，不虚构跨实例完整回放。
- `docs/specs/D06_REPORT_TASK_GOVERNANCE_PLAN.md` 与本执行报告。

`frontend/tsconfig.node.tsbuildinfo` 在本机 build 后只发生 TypeScript 工具版本漂移，已恢复仓库内容，未纳入 D06 diff。

## 5. Implementation Summary

前端现在为每次主动生成创建一个安全 UUID，并通过 header 发送。网络、408/425/429/5xx 只允许一次同键重试；409 和其他确定性 4xx 直接返回。后端返回 task/report 后，前端在当前用户 SHA-256 摘要命名空间保存严格四字段引用。刷新只读取当前用户记录并先 GET 状态校验所有权；运行中恢复原任务 SSE/轮询，终态拉取报告并清理，401/404/损坏记录只删除当前精确 key，网络瞬断保留引用供下次恢复。

离线验收拓扑新增第二个真实 FastAPI 实例，Nginx 对普通 API 和 SSE 使用同一 `least_conn` upstream。测试先按真实前端顺序初始化用户，再通过代理并发 20 个同 key 创建请求；随后找到非创建实例直接连接 SSE，等待数据库持久版本，定向删除隔离 Redis 的报告 namespace，并验证同一任务从 PostgreSQL 恢复到唯一终态和一条 workflow invocation artifact。

## 6. Diff Summary

- Added: browser recovery helper/API contract, two-backend Nginx configuration, deterministic D06 full-stack acceptance.
- Changed: report API/composable/view, production/offline Compose, test-only offline app, one D05 monotonic assertion.
- Unchanged: auth/JWT、Prompt、Agent 图、工具/Skills、Memory 业务/namespace、生产依赖、报告正文和数据库 Schema。
- Protected `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` remains untouched, untracked and unstaged.

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| initial M4 `useReport.governance` Vitest | 证明显式 key、刷新恢复和清理的红基线 | 3 failed，均对应缺失的 M4 行为 |
| focused report frontend tests | API/header、SSE/轮询和恢复回归 | 19 passed |
| final `npm run test` | 前端全量 | 16 files / 53 tests passed |
| `npm run lint -- --no-cache` | frontend lint | pass |
| `npm run type-check` | Vue/TypeScript contracts | pass |
| `npm run build` | production frontend artifact | pass；仅既有 dynamic-import/chunk-size warnings |
| Ruff + Pyright on M4 Python/E2E | syntax/import/type | pass；Pyright 0 errors/warnings |
| default focused E2E pytest | 无隔离资源时的 gate | 1 passed, 2 expected skips |
| both Compose `config --quiet` | production/offline topology syntax | pass |
| real isolated Compose full runner | 双后端、PostgreSQL、Redis、Nginx、全量离线回归 | 334 passed, 4 skipped, 48 deselected, 3 xfailed |
| `git diff --check`, status and staged inspection | whitespace/scope/D01 | pass；staged set empty |
| storage/privacy/secret scan | browser payload/header/config | 四字段 payload；无 raw command/user/token/body；无真实 secret |
| in-app browser navigation to `/report` | 可见页面烟测 | not run：宿主 `127.0.0.1:5173` dev server 已停止，导航前 `ERR_CONNECTION_REFUSED` |

## 8. Test Results

- Browser lifecycle: 主动新生成换 key；同一请求生命周期重试不换 key；刷新恢复不 POST；终态、logout、非法 owner 和损坏当前记录定向清理；其他 sessionStorage 不受影响。
- Privacy: storage key 使用用户 SHA-256 摘要；value 只含 `task_id/report_id/idempotency_key/request_fingerprint`；Web Crypto 不可用时不降级保存原始用户。
- Multi-instance: 20 个代理请求由 primary/secondary 都服务，返回一个 task/report，`CREATED=1`、`REPLAYED=19`，invocation 增量为 1。
- Recovery: 非创建实例可观察持久版本；报告 Redis namespace 删除后由 PostgreSQL 重建并到达 completed/100；Report 和治理行各 1。
- Deployment: 生产 Compose 配置报告 Redis，但后端没有 Redis healthy 前置依赖；离线 secondary 在 primary 迁移完成后启动，避免并发 Alembic。
- Cleanup: 每轮使用唯一 Compose project；最终 `down -v` 后 `ps -a` 为空，没有触碰宿主既有容器或卷。

## 9. Failures and Fixes

1. 初始前端红测 3 项失败，分别证明 API 未发送 key、刷新会丢任务、终态未清引用；实现冻结生命周期后转绿。
2. M1 fixture 使用任意 owner 字符串作 storage key，正式实现按用户摘要寻址；测试改为调用正式派生函数，不放宽隔离策略。
3. 第一轮真实 Compose 全量只有旧 D05 序列断言失败：跨实例数据库版本可在客户端观察前合并，合法序列可能跳号；将契约修为正整数、严格递增且唯一，保持“latest snapshot”而非完整回放口径。
4. 第二轮真实 Compose 只有 D06 E2E 失败：测试未初始化用户便并发 20 路请求，两个实例同时补建用户触发 `users_pkey`；按真实前端顺序先调用一次 `/api/user/init`，再并发报告请求。第三轮全量 334 passed。
5. 首轮停止 secondary 时日志出现一个 `ReportProgressSubscription.receive()` pending-task 提示；业务断言和最终清理均成功。因后端复合订阅不属于 M4 允许修改面，未越界修复，转交 M5 做资源清理专项复核。
6. 浏览器页仍指向本地 5173，但对应 dev server 已停止；未把连接拒绝解释为 UI 缺陷，也未为了重复证据重新执行整套 runner。

每个具体失败只做了一次聚焦修复，没有同一失败连续两次未解决。

## 10. Scope Compliance

- Current milestone only: Yes.
- Allowed files only: Yes.
- Forbidden changes: None.
- Dependencies added: None.
- Public API compatibility: 新 header 可选，响应新增字段可选，旧客户端和历史/detail UI 保持兼容。
- Storage safety: 只定向删除当前用户摘要 key；无 `sessionStorage.clear()`；无 raw user/command/token/body。
- Database/Redis safety: M4 未改 Schema；仅删除唯一隔离 namespace 的派生报告键；Memory Redis 未触碰。
- Production startup: Redis 不参与后端 Compose `depends_on`，继续 fail-open。
- D01 protection: Untouched, untracked and unstaged.

## 11. Engineering Implementation Contract

| Category | Status | Evidence |
|---|---|---|
| Architecture substrata and ownership | Satisfied | Vue composable owns UI lifecycle；API adapter owns protocol；backend remains application/infrastructure layered |
| Comments, docstrings, types | Satisfied | public recovery helper/error/test app boundaries typed and documented |
| Configuration, secrets, constants, prompts | Satisfied | existing config reused；isolated namespace/instance labels；Prompt untouched；no dependency/secret change |
| Output, logs, traces, artifacts | Satisfied | test-only instance header and fixed `invoked` line；no report body/key/user in logs/artifact |
| Validation, retry/fallback, compatibility | Satisfied | bounded same-key retry, owner validation, same-task SSE→poll, DB recovery, optional API additions |
| Tests and handoff evidence | Satisfied with environment note | frontend/full Compose passed；only visible browser smoke unavailable because dev server was offline |

## 12. Risks Remaining

- BackgroundTasks remains same-process and cannot resume workflow execution after process death.
- Browser state is session- and tab-scoped；cross-device/multi-tab coordination remains deferred.
- Redis/PubSub provides latest-state wake-up, not complete event history；version gaps are legal and state cannot regress.
- M5 must audit the observed pending receive task, run the frozen complete offline/migration/Python 3.11 matrix and review the full diff.
- Existing Starlette/httpx、naive-UTC and frontend bundle-size warnings remain unrelated debt.

## 13. PLAN.md Updates

- Progress: M4 marked complete with frontend and real two-backend evidence.
- Decision Log: recorded minimal browser record、one same-key retry and production Redis fail-open topology.
- Surprises & Discoveries: recorded hashed fixture、D05 version gap、user initialization、pending receive task and offline dev server.
- Outcomes & Retrospective: recorded M4 implementation/evidence and narrowed M5 resource audit.

## 14. Suggested Commit Message

```text
feat(report): recover idempotent tasks across instances

- persist minimal browser task references for refresh recovery
- reuse explicit keys for bounded response-loss retries
- verify one workflow through a two-backend proxy topology
```

No milestone commit was created; the frozen plan keeps D06 as one coherent commit in M6 after M5 verification and independent review.

## 15. Handoff to User

Milestone 4 is complete with the local dev-server browser limitation documented above. Per the one-milestone execution contract, the complete offline verification and narrow-fix gate begins only in Milestone 5 after explicit continuation.
