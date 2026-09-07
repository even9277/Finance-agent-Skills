# D06 报告任务治理 M5 执行报告

## 1. Milestone Executed

- Milestone: 5 — Full Offline Verification and Narrow Fixes
- Status: Complete
- Date: 2026-09-07

## 2. Frozen Contract

- Goal: 执行 D06-T01..T09 的完整离线、静态、迁移、Redis、双实例和资源释放门禁；只修复证据明确的 D06 回归。
- Allowed: M0-M4 已允许的 D06 文件与测试、本报告和计划治理记录。
- Forbidden: 受保护真实 API、依赖/Auth/Prompt/Skills/Memory 语义、生产数据、削弱测试、暂存或提交。
- Stop condition: 同一失败经两次聚焦修复仍存在、需要越界/破坏性操作、基础设施持续不可用，或隐私/安全不变量失败。

## 3. Files Inspected

- 根与个人工程规范、Small-step Implementation skill 及其全部直接引用协议。
- `docs/specs/D06_REPORT_TASK_GOVERNANCE_PLAN.md`、M0-M4 执行报告、README、CONTRIBUTING 和测试策略。
- 完整 D06 diff、报告路由/任务应用层/Redis 与 PostgreSQL 适配器、前端恢复链路、迁移、Compose/Nginx 和所有相关测试。

## 4. Files Modified

- `backend/routers/report.py`: 将复合订阅的 `asyncio.wait` 纳入无条件清理边界；外层超时/取消时 cancel 并 gather 所有 receive 子任务。
- `tests/unit/report/test_report_update_subscription.py`: 新增外层取消专项回归测试，并保证测试失败路径自身不遗留 pending task。
- `docs/specs/D06_REPORT_TASK_GOVERNANCE_PLAN.md`: 更新 M5 Progress、Decision Log、Surprises 和 Outcomes。
- 本执行报告。

没有修改新功能面、依赖、Schema、Auth、Prompt、Skills、Memory 或生产数据。

## 5. Evidence-backed Fix

M4 双实例关闭日志中的 `Task was destroyed but it is pending! ReportProgressSubscription.receive()` 被专项红测稳定复现。根因是 `_ReportUpdateSubscription.receive()` 在进入 `try/finally` 前调用 `await asyncio.wait()`；SSE 的 `asyncio.wait_for()` 若在 FIRST_COMPLETED 前取消外层协程，本地和 Redis 两个子 receive 不会被清理。

修复只调整资源生命周期：把 wait 放入 `try`，在 `finally` 中取消所有未完成子任务，并始终 `gather(..., return_exceptions=True)` 观察结果。业务协议、选择优先级和状态语义不变。

## 6. Tests and Checks

| Command / Gate | Result |
| --- | --- |
| 专项红测 `test_report_update_subscription.py` | 修复前 1 failed，明确显示 local child 未取消 |
| 专项 + progress contract 回归 | `11 passed`；仅既有 Starlette warning |
| `uv lock --check` | pass |
| changed/untracked Python Ruff | pass |
| changed/untracked Python Pyright | `0 errors, 0 warnings` |
| repository-wide `uv run --locked pyright backend tests` | 4 个历史错误：`profile_extractor.py:233,239`、`stock_resolver.py:78,82`；均未触达且与 D06 无调用关系 |
| local full `uv run --locked python -m pytest -q` | `441 passed, 14 skipped, 9 deselected, 3 xfailed`，87.87s |
| frontend lint / type-check | pass / pass |
| frontend Vitest / build | `16 files, 53 tests passed` / pass；仅既有 chunk warnings |
| production + offline Compose `config --quiet` | pass / pass |
| read-only Python 3.11 `compileall` | pass；pycache 定向到容器 `/tmp` |
| true Compose full runner | `335 passed, 4 skipped, 48 deselected, 3 xfailed`，73.16s；重复验收同样通过 |
| D06 PostgreSQL/Redis/双实例定向子矩阵 | `27 passed, 0 skipped`，20.18s |
| shutdown warning scan | 无 `Task was destroyed`、`pending!`、`ReportProgressSubscription.receive`、`Exception ignored` 或 `RuntimeWarning` |
| `git diff --check` / staged set | pass / empty |
| secret/privacy/generated scan | 无真实密钥；无 raw command/user/token/report body 进入 Redis/日志；无 lock/build artifact 变更 |

4 个 Compose skip 均为冻结的受保护 Live 门禁：controlled-chat 2 个参数用例缺少 `RUN_PROTECTED_LIVE_E2E=true`，report-progress 1 个缺少 `RUN_PROTECTED_LIVE_REPORT_E2E=true`，report-governance 1 个缺少 `RUN_PROTECTED_LIVE_REPORT_GOVERNANCE_E2E=true`。它们属于 M6，不是 D06 离线验收缺口。

## 7. Failures, Diagnosis and Repair Budget

1. 首次真实 Compose build 在读取 Docker Hub metadata 时，本机 `127.0.0.1:7890` 代理连接被强制关闭；确认项目没有容器后，同一命令重试一次恢复并全绿。未改网络或镜像配置。
2. 首次定向 `docker compose run` 覆盖镜像命令时遗漏 `PYTHONPATH=/workspace`，在收集阶段报 `No module named backend`；校正验证命令后 `27 passed`，未改代码。
3. 为提取 skip 原因第一次错误地把全部无 marker 单测放入注入 `ENABLE_REDIS_CACHE=true` 的 Compose 环境，导致历史默认配置断言 1 failed；恢复镜像原始 marker 选择后结果与正式 runner 完全一致。未修改或弱化单测。
4. 唯一产品缺陷只修复一次即由红转绿；没有触发“两次修复失败”停止条件。

## 8. Static, Privacy and Scope Review

- Redis key/channel 使用摘要；value 是严格 `extra=forbid` 的 task/report/version/status/progress/stages/time/error-code/message 白名单，不含原始 user、command、幂等键、Prompt、token 或报告正文。
- 浏览器仅 `sessionStorage.setItem/removeItem` 当前用户摘要命名空间的 task/report/key/fingerprint；生产代码无 `sessionStorage.clear()`，Auth token 仍沿用既有 store。
- 扫描命中的 secret/token 文本只来自 `.env.example` 安全占位、固定 fixture、泄漏哨兵和设计文档，不是可用凭据。
- 没有 package/lock、`dist`、pycache 或 `tsbuildinfo` 漂移进入 diff。
- 保护文件 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` hash 仍为 `cc21919a88d19453f47f58d895ff2759462f5425`，保持 untracked、unstaged。

## 9. Resource and Rollback Status

- 所有真实基础设施都使用唯一 Compose project、tmpfs PostgreSQL 和隔离 Redis namespace。
- 每次测试后执行精确 `down -v`；最终 `ps -a` 为空，没有操作宿主既有容器、卷或生产数据。
- M5 未执行数据库迁移以外的持久写入，未创建 commit，回滚边界仍是显式 D06 diff。

## 10. Engineering Contract

| Category | Status | Evidence |
| --- | --- | --- |
| Architecture ownership | Satisfied | 资源修复留在路由复合观察器；未搬移应用/基础设施边界 |
| Comments/docstrings/types | Satisfied | 取消语义有意图注释和 typed 专项测试；触达范围 Pyright 0 error |
| Config/secrets/prompts | Satisfied | 无新设置/依赖/凭据；Prompt 未触达 |
| Logs/traces/artifacts | Satisfied | 关闭日志无 pending warning；敏感字段扫描通过 |
| Failure/fallback/compatibility | Satisfied | 外层取消完全清理；SSE/Redis/DB 协议不变 |
| Tests/handoff | Satisfied with unrelated baseline note | D06 required infra 27/27；仓库全量 Pyright 4 个未触达历史错误单列 |

## 11. Risks Remaining

- `BackgroundTasks` 仍存在进程崩溃后无法恢复执行的已知边界。
- Redis/PubSub 仍只提供 latest-state wake-up，不是完整事件回放。
- 仓库全量 Pyright 的 4 个 provider 历史错误仍需独立任务治理。
- 真实模型/只读金融数据、Claim 文档对齐、独立 review、commit/PR/CI/merge 属于 M6，尚未执行。

## 12. Commit Status and Handoff

本里程碑没有暂存或提交。冻结计划要求 D06 在 M6 完成受保护 Live、Claim 对齐和独立 review 后形成一个 coherent commit。下一步只能执行 Milestone 6。
