# D05 Report SSE Progress — Milestone 4 Execution Blocked Report

> Resolution (2026-09-05): 此文件保留首次主机阻塞的审计证据。经用户授权升级 Docker Desktop 4.86.0→4.89.0，并可恢复地重建损坏的 runtime socket 目录后，Linux engine 已恢复；完整 Compose 复跑以 `288 passed`、退出码 0 通过。最终结论见 `D05_REPORT_SSE_PROGRESS_MILESTONE_4_EXECUTION_REPORT.md`。

## 1. Milestone Status

- Milestone: Milestone 4 — Offline Full Verification and Narrow Fixes
- Status: Blocked at the Docker Compose runtime gate
- Date: 2026-09-04
- Branch: `feat/50-report-sse-progress`
- Issue: #50
- Completed scope: deterministic report fixture、真实 LangGraph/本机 HTTP-SSE E2E、D05 focused、Python/frontend full regression、build/config/static/redaction/diff checks
- Missing gate: 真 PostgreSQL/FastAPI/Vue-Nginx offline Compose runtime 与 Nginx flush timing

M4 不标记完成，也不进入 M5。阻塞来自本机 Docker Desktop 在创建 Windows AF_UNIX runtime endpoint 时反复生成不可访问的重解析点，并非 Compose 配置或 D05 代码失败。

## 2. Frozen Contract Followed

- 只执行 M4；未运行 protected Live、未提交、未推送、未创建 PR。
- 允许范围仅为失败证据触发的报告实现、offline fixture、测试和治理文档窄改。
- 未修改数据库 schema、Redis/D06、Skills、Memory、Prompt、认证或生产依赖。
- 用户未跟踪的 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` 未编辑、未删除、未 stage。
- Docker 修复未执行 factory reset、clean/purge、prune、卸载或卷/镜像删除。

## 3. Implemented in M4

- `tests/e2e/offline_app.py`
  - 只替换报告股票解析和外部工作流端口。
  - 使用真实 `StateGraph` 编译与生产阶段同名的确定性节点，由 LangGraph 真实产生 `astream_events`。
  - 保留真实 FastAPI BackgroundTask、报告服务、Tracker/Hub、数据库提交、SSE 路由和报告详情查询。
- `tests/e2e/test_report_progress_offline_contract.py`
  - 移除严格 `xfail`。
  - 验证首帧预算、连续 sequence、单调 progress、六类真实阶段、completed 终态、报告持久化和 wire redaction。
  - 允许已经在订阅前完成的阶段从 `stream_ready.stages` 权威快照恢复，避免把正常竞态误判为缺帧。
- `backend/services/agent_service.py`
  - 将 LangGraph event protocol 从 v1 升级为 v2。
  - 股票解析成功/降级日志不再记录原始指令、公司名或股票代码。
- `tests/unit/report/test_report_service_progress.py`
  - 冻结 v2 调用合同。
  - 增加成功和降级日志的用户输入脱敏断言。

## 4. Evidence-Driven Fixes

### 4.1 LangGraph v1 root output incorrectly failed a successful report

- Failure: 首次本机 HTTP/SSE E2E 收到 `task_terminal.status=failed`。
- Evidence: 真实编译 LangGraph 的 v1 根结束事件输出为 `{"summarizer": <state>}`，而 `ainvoke` 与 v2 根事件返回完整 `<state>`；服务随后找不到顶层 `data.final_report`。
- Root cause: 生产服务使用已弃用的 `astream_events(version="v1")`，并按完整状态解释其分块输出。
- Fix: 改为 `version="v2"`，不增加 fallback 重跑，因此不会重复整份模型调用。
- Verification: service unit `3 passed`；本机真实 HTTP/SSE E2E `1 passed in 1.08s`，终态 completed 且报告非空。

### 4.2 Report preparation logs exposed user input

- Failure: 静态脱敏审查发现 stock resolver 降级日志包含完整 `command`，成功日志包含 company/stock。
- Root cause: 旧调试日志直接插值业务输入。
- Fix: 改为稳定字段 `stage/task_id/status/error_code`，终端仅保留通用降级提示。
- Verification: unit test 使用 `PRIVATE_COMMAND` / `PRIVATE_COMPANY` 哨兵，日志和终端均不包含；敏感 literal scan 为 0。

### 4.3 Offline report path was not wired

- Failure: D05-T08 原为严格 `xfail`，offline app 只替换 chat ports。
- Fix: 增加真实编译 deterministic LangGraph report fixture，并解除 `xfail`。
- Verification: 本机 FastAPI/SQLite external-port E2E `1 passed`；Compose 镜像的默认命令会收集该 e2e，但 daemon 阻塞了容器执行。

## 5. Validation Matrix

| Command / Method | Result | Evidence |
| --- | --- | --- |
| `uv run --locked python -m pytest -q tests/contract/test_report_progress_contract.py tests/unit/report backend/test_report_download.py backend/test_agent_service.py` | Passed | 20 passed, 1 known Starlette warning |
| final `uv run --locked python -m pytest -q` | Passed | 393 passed, 7 skipped, 8 deselected, 3 pre-existing xfailed, 868 warnings, 74.30s |
| `uv run --locked ruff check` on D05 changed Python files | Passed | 0 errors |
| `uv run --locked pyright` on D05 changed Python files | Passed | 0 errors, 0 warnings |
| repository `uv run --locked ruff check .` | Baseline failed | 94 existing findings, mainly `Financial-MCP-Agent` and `a-share-mcp-is-just-i-need`; no D05 changed-file finding |
| focused report Vitest | Passed | 4 files, 14 tests |
| frontend `npm test` | Passed | 14 files, 41 tests |
| frontend `npm run lint` | Passed | ESLint exit 0 |
| frontend `npm run type-check` | Passed | Vue/TS exit 0；tracked build info restored byte-for-byte |
| frontend `npm run build` | Passed | 406 modules；only existing dynamic-import/chunk-size warnings |
| two `docker compose ... config --quiet` commands | Passed | production and offline Compose both valid |
| PowerShell Nginx static contract | Passed | exact events location disables buffering/cache and clears Connection；normal `/api/` unchanged |
| FastAPI SSE import smoke | Passed | native `EventSourceResponse` and `ServerSentEvent` import |
| local SQLite FastAPI + D05-T08 | Passed | 1 passed in 1.08s；real HTTP/SSE/persistence chain, no external Provider |
| CRLF-aware `git diff --check` | Passed | no whitespace error |
| changed/untracked D05 secret literal scan | Passed | 38 files, 0 OpenAI/Langfuse/GitHub/JWT/Bearer/Tushare literal matches |
| `docker compose ... ps -a` | Blocked | Linux engine named pipe missing before any project container could start |
| offline Compose `up --build ...` | Not run | daemon unavailable；不得用 config/local E2E 冒充真代理验收 |

## 6. Docker Blocker Diagnosis and Safe Recovery Attempts

Environment evidence:

- Docker Desktop: 4.86.0；Docker CLI: 29.7.2；context: `desktop-linux`。
- WSL distributions use version 2 and were stopped before repair。
- `%APPDATA%\Docker\settings-store.json` already had `EnableDockerAI=false`。
- Backend log failed before the Linux engine pipe existed。

Attempt 1:

- Confirmed `%LOCALAPPDATA%\Docker\run` contained only three zero-length temporary reparse endpoints, including inaccessible `dockerInference`。
- Preserved the whole directory as `%LOCALAPPDATA%\Docker\run.corrupt-d05-m4-20260904` and created a fresh empty `run` directory。
- Docker progressed past that point, then failed on the same inaccessible-endpoint error at `%LOCALAPPDATA%\docker-secrets-engine\engine.sock`。

Attempt 2:

- Stopped all Docker Desktop/backend processes。
- Confirmed the secrets-engine directory contained only `engine.sock`；preserved it as `%LOCALAPPDATA%\docker-secrets-engine.corrupt-d05-m4-20260904` and recreated an empty directory。
- Docker immediately recreated an inaccessible `dockerInference` in the newly created `run` directory and failed again。

Conclusion:

- The same failure recurred after two recoverable, exact-directory repairs. This proves the active blocker is Windows/Docker Desktop runtime socket creation, not stale Compose resources or D05 application code。
- Docker Desktop was stopped after reproduction。No D05 Compose container, network, volume or image was created by this M4 attempt, so there was nothing project-scoped to tear down。
- The preserved directories are recoverable diagnostic backups；they contain only the inspected temporary endpoints。

## 7. Blocked Gate and Resume Condition

M4 can resume when `docker info` returns a server version and `docker compose -f docker/docker-compose.offline.yml ps -a` can contact the Linux engine. Likely external recovery paths are a Windows restart and/or Docker Desktop upgrade/official fix; those host-level actions are intentionally not performed automatically in this milestone。

On resume, run exactly:

1. `docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e`
2. Regardless of result, `docker compose -f docker/docker-compose.offline.yml down -v --remove-orphans`
3. `docker compose -f docker/docker-compose.offline.yml ps -a`
4. Inspect timing/log redaction, rerun only evidence-driven narrow fixes, then update this report and mark M4 complete。

## 8. Scope and Delivery State

- M4 code changes are locally implemented and default regressions are green。
- The required real Nginx/PostgreSQL Compose runtime proof is missing, so M4 remains incomplete。
- M5 protected Live、commit、push、PR、CI/review and merge have not started。
- No commit was created in this milestone。

## 9. Resume Audit — 2026-09-05

- Authoritative pre-start state: Docker Desktop/backend process count `0`；Linux engine 与 backend API named pipe 均不存在。
- Started the installed Docker Desktop 4.86 executable once without changing any runtime directory or setting。
- Result: all Docker processes exited；latest backend log again reported the same `dockerInference` remove/access/syntax failure before the Linux engine pipe was created。
- Conclusion: M4 remains blocked on the same host-runtime defect。The next in-scope application check still cannot run until Docker Desktop is upgraded/repaired or the host state changes。
