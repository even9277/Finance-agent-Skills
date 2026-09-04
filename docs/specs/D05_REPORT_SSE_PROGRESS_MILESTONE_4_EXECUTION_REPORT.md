# D05 Report SSE Progress — Milestone 4 Execution Report

## 1. Milestone Status

- Milestone: Milestone 4 — Offline Full Verification and Narrow Fixes
- Status: Completed
- Completed: 2026-09-05
- Branch: `feat/50-report-sse-progress`
- Issue: #50
- Next milestone: M5 protected Live、文档收口、独立 review 与 GitHub 交付

本里程碑完成了 D05 的完整离线自动化和真 Compose 代理链验收。未运行 protected Live，未提交、推送或创建 PR，也未进入 D06。

## 2. Frozen Contract Followed

- 只执行 M4；修改仅来自失败证据，并限制在报告实现、测试、离线 fixture 与治理文档。
- 未修改数据库 schema、Redis/D06、Skills、Memory、Prompt、工具权限或报告正文合同。
- 未新增生产依赖；FastAPI 仅对齐已锁定原生 SSE 能力。
- 用户未跟踪的 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` 未编辑、删除或 stage。
- Docker 恢复未执行 factory reset、prune、purge 或删除镜像/数据卷。

## 3. Completed Implementation and Fixes

### 3.1 Deterministic real-LangGraph report fixture

- `tests/e2e/offline_app.py` 仅替换外部股票解析、模型和行情端口。
- 保留 FastAPI BackgroundTask、生产报告 service、真实编译 LangGraph、Tracker/Hub、PostgreSQL 提交、SSE endpoint、Nginx 代理和报告详情读取。
- `tests/e2e/test_report_progress_offline_contract.py` 验证首帧、连续 sequence、单调 progress、阶段快照/更新、completed 终态、持久化报告与 wire redaction。

### 3.2 LangGraph v1 root-output compatibility bug

- Evidence: 真实小图的 `astream_events(version="v1")` 根结束事件返回按节点嵌套的输出，服务误判 `final_report` 缺失。
- Fix: `backend/services/agent_service.py` 使用 v2 event protocol；不增加会重复模型调用的整图 fallback。
- Verification: service unit 3 passed；本机 FastAPI/SQLite HTTP-SSE E2E completed。

### 3.3 Report preparation log privacy

- Evidence: 旧日志包含原始 command、company 和 stock code。
- Fix: 日志仅保留 `stage/task_id/status/error_code` 等稳定字段。
- Verification: `PRIVATE_COMMAND`、`PRIVATE_COMPANY` 哨兵与敏感 literal scan 均无泄露。

### 3.4 Compose-only authentication test isolation

- Evidence: 首次 Compose 为 `1 failed, 287 passed`；`test_report_sse_rejects_query_token_and_hides_task_existence` 在 `AUTH_ENABLED=false` 环境把非所有者样例当成免鉴权请求并返回 SSE 200。
- Root cause: 测试前半段隐式依赖本机默认 `AUTH_ENABLED=true`，不是生产路由绕过鉴权。
- Fix: helper 内显式冻结 `settings.auth_enabled=True`，使存在性隐藏合同独立于宿主环境。
- Verification: focused contract `6 passed`，Ruff/Pyright 通过；完整 Compose 复跑 `288 passed`。

## 4. Docker Host Recovery

- 原环境 Docker Desktop 4.86.0 在 Windows AF_UNIX `dockerInference` endpoint 上失败，历史诊断见 blocked report。
- 经用户明确授权，使用 SHA256 校验通过的官方安装包按 per-user 模式原地升级至 4.89.0，安装退出码 0。
- 完整停止 Docker 后，把精确的 `%LOCALAPPDATA%\Docker\run` 目录移动为可恢复备份，再创建空 runtime 目录；未触碰 `%LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx`。
- 新版本完成 WSL 数据盘重新挂载/组件迁移，最终 `docker version` 返回 Client/Server 29.7.2，backend state 为 running。

## 5. Validation Matrix

| Check | Result |
| --- | --- |
| D05 focused backend | 20 passed |
| Final Python regression | 393 passed, 7 skipped, 8 deselected, 3 xfailed |
| Changed-surface Ruff / Pyright | Passed / 0 errors |
| Repository-wide Ruff | 94 pre-existing findings outside D05 changed surface |
| Focused frontend | 14 passed |
| Frontend full | 41 passed |
| Frontend lint / type-check / build | Passed；406 modules，既有 chunk warnings only |
| Production + offline Compose config | Passed |
| Nginx static SSE contract | Passed |
| Local FastAPI/SQLite real-LangGraph report E2E | 1 passed |
| First real Compose run | 1 failed, 287 passed；定位为测试环境隔离缺陷 |
| Focused repair verification | 6 passed；Ruff/Pyright passed |
| Final real Compose run | 288 passed, 3 skipped, 40 deselected, 3 xfailed；exit 0 |
| D05 report runtime chain | POST generate→BackgroundTask→LangGraph→DB→SSE→Nginx→GET report passed |
| Secret/redaction scan | 0 usable credential matches；仅命中预期的 `Bearer MUST_NOT_LEAK` 脱敏测试哨兵 |
| CRLF-aware diff check | Passed |
| Compose cleanup | `down -v --remove-orphans` completed；`ps -a` empty |

## 6. Cleanup Note

冻结的 cleanup 命令使用默认 Compose project 名 `docker` 和 `--remove-orphans`。首次清理因此同时移除了同名项目下四个旧 `dash-*` orphan 容器。输出未显示删除其镜像或数据卷；这些容器可由原 Compose 定义重建。D05 创建的临时 PostgreSQL、Redis、backend、frontend、offline-e2e 容器、网络和 `trace-e2e` 卷均已清理。

## 7. Remaining Risk and Deferred Scope

- 当前 hub 是单进程低延迟 accelerator；不承诺 multi-worker、durable replay 或跨刷新恢复。
- 一条受保护真实模型/Tushare 报告、最终 acceptance artifact、独立 diff review、GitHub PR/CI/merge 留给 M5。
- Redis snapshot/pub-sub、TTL、幂等提交、duplicate task 和 reconnect/replay 留给 D06。
- 全仓 Ruff 的 94 个既有问题不属于 D05，不在本里程碑越界修复。

## 8. Delivery State

- M4 完成，所有必需离线和 Compose runtime gate 有真实运行证据。
- 当前改动仍只在本地工作树；没有 commit、push 或 PR。
- 按一里程碑治理，本轮在 M4 停止，不自动开始 M5。
