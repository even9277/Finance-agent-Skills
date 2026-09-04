# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 2 — Implement Backend Truth, Snapshot, and SSE
- Status: Complete
- Date: 2026-09-04

## 2. Development Standards Read

- `PLAN.md`: 已读取 M2 goal/allowed files/tests/stop/rollback，只实现后端。
- `DEV_STANDARDS.md`: 未发现。
- `AGENTS.md`: 应用 Router/Application/service 分层、typed contract、中文 Google-style docstring、错误码/脱敏、测试先行和无 schema/新依赖规则。
- nested `AGENTS.md` / `AGENTS.override.md`: 未发现。
- `CLAUDE.md`: 未发现。
- `.cursor/rules/*.mdc`: 未发现。
- `.github/copilot-instructions.md`: 未发现。
- README / contribution / test docs: 沿用 M0/M1 已读取的贡献、SOP、代码结构、测试和 observability 文档。

## 3. Files Inspected

- `docs/specs/D05_REPORT_SSE_PROGRESS_PLAN.md`: M2 工程合同与测试门禁。
- `backend/db/{database.py,models.py}`: 确认 request/short-session factory 与 Report 无 schema 变化。
- `backend/middleware/auth.py`: header Bearer、query token 和 owner 语义。
- `backend/services/agent_service.py`: 现有数据库更新、LangGraph events、final state 与异常路径。
- 本机 FastAPI 0.141.1 `fastapi.sse`/routing source: 确认 native SSE 是 generator route marker，不是普通 StreamingResponse wrapper。
- 本机锁定 LangGraph：运行无外部依赖小图，确认顶层与内部 Runnable 的 name/metadata 传播形状。
- M1 Python contracts/unit tests 与既有 backend/API tests。

## 4. Files Modified

- `backend/application/report_progress/__init__.py`: 导出 D05 应用边界。
- `backend/application/report_progress/contracts.py`: 协议版本、stage/status、typed stage/terminal notification 和 publisher port。
- `backend/application/report_progress/tracker.py`: 顶层节点过滤、并行完成计数、optional personalization、失败闭合和单调进度。
- `backend/application/report_progress/hub.py`: bounded multi-subscriber latest-event Hub、阶段快照、cleanup/drop metric；全局容量 32。
- `backend/application/report_progress/snapshot.py`: 显式 primitive 输入的 DB 安全快照和稳定失败码/提示。
- `backend/schemas/report.py`: 三类 strict Pydantic SSE frame 与 REST `error_code`。
- `backend/routers/report.py`: status safe projection、pre-stream 401/404、function-scope DB preflight、native SSE、reconcile 和终态关闭。
- `backend/services/agent_service.py`: 真实 stage 接入、commit-before-publish、单调 DB progress、publisher isolation、安全 failure terminal。
- `pyproject.toml`、`backend/requirements.txt`、`uv.lock`: FastAPI 最低版本 0.115→0.135；锁定版本/包集合不变。
- `tests/contract/test_report_progress_contract.py`: 移除 backend target xfail，补活动 stream Hub/终态测试与 optional REST 字段兼容。
- `tests/unit/report/{test_report_task_progress,test_progress_hub}.py`: 移除 xfail并收紧 nested/personalization/preparing failure。
- `tests/unit/report/test_report_service_progress.py`: 新增成功乱序与敏感失败的 service 集成测试。
- `docs/specs/D05_REPORT_SSE_PROGRESS_PLAN.md`: M2 governance。
- `docs/specs/D05_REPORT_SSE_PROGRESS_MILESTONE_2_EXECUTION_REPORT.md`: 本报告。

## 5. Implementation Summary

后端现在由真实 `run_report_task` 产生进度事实。PREPARING 在初始状态构建前后闭合；四个 analyst 的完成百分比按完成数量计算为 35/50/65/80，与节点身份和乱序无关；optional personalization 根据 STM/LTM 拓扑在真实终止节点闭合或显式 SKIPPED；summarizer 为 90/95。每次百分比先以短事务和 `max(old,new)` 写数据库，再通知 Hub；任务终态必须在 DB commit 后通知。失败保留最后进度，只保存稳定 `REPORT_GENERATION_FAILED` 和安全提示。

`ReportProgressHub` 是协议无关、非阻塞、有界的当前单进程加速层。正常容量 32 可容纳完整报告生命周期，异常慢消费者才替换最旧通知；数据库仍是恢复/终态权威。SSE endpoint 用普通 dependency 在响应启动前完成 Bearer 和统一 404 owner 检查，dependency session 在 producer 前关闭；route 直接 yield FastAPI `ServerSentEvent`，由框架负责编码、15 秒 ping、取消与防缓冲 header。连接先发 DB + hub 安全快照，消费低延迟通知，idle 时短会话 reconcile，唯一终态后关闭。

## 6. Diff Summary

- 新增明确的 report progress application package；未引入 Redis/HTTP/ORM 到 contracts/tracker/hub。
- Router/API 只新增 versioned SSE 和向后兼容 `error_code`；现有 report path/fields 保留。
- Service 移除固定 node→progress 和 progress=0 failure，换成真实 tracker/单调 commit/安全 terminal。
- FastAPI dependency minimum 窄幅对齐原生 SSE；`uv.lock` 只改一行 specifier，无新包/版本漂移。
- Backend D05 xfail 全部移除；frontend/T08/T09 target failures 保留给后续里程碑。
- No frontend, Nginx, Compose, database model/migration, Redis, prompt, Skill, tool, memory policy or chat protocol files were modified.
- 用户 D01 文件未编辑、未 stage。

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| `uv lock` + `uv lock --check` + lock diff | dependency minimum/reproducibility | Pass；114 packages，lock 仅 specifier 1 行 |
| focused Ruff | Python production/tests | Pass |
| focused Pyright | contracts/Router/service/tests typing | Pass；0 errors/warnings |
| D05 backend focused + old report tests | T01～T04/T07、service、root/download regression | Pass；最终 19 passed |
| `pytest backend tests/contract/test_api_contract.py -q` | backend/auth/OpenAPI/API regression | Pass；13 passed |
| real local LangGraph mini-graph | 顶层/内部 event shape | Pass；内部 name 不同但继承 node metadata，过滤规则据此修正 |
| `git diff --check`、status/xfail/forbidden scans | scope/whitespace/remaining gates | Pass；无生成物/secret，backend target xfail 为 0 |

## 8. Test Results

- Passed: 最终 focused 19；backend/API 13；Ruff；Pyright；lock check。
- Failed: None at completion。
- Not run: Python full repo、frontend tests/build、offline Compose、protected Live；分别属于 M3～M5。
- Remaining expected failures: frontend 6 `it.fails`、offline Compose 1 strict xfail、Live 1 strict xfail。
- Warnings: FastAPI TestClient 的既有 httpx deprecation；backend 历史 `datetime.utcnow` warnings；LangGraph v1 characterization 的弃用警告。均非本轮新增行为失败。
- Limitations: Hub 仅保证仓库当前单 worker 的低延迟事件；多 worker/replay 明确留 D06。

## 9. Failures and Fixes

- Failure: 首次 Ruff 报 `agent_service.py` 3 个既有 unused imports。
- Root cause: 文件进入本次维护范围后启用 focused lint。
- Fix attempt: 只删除 `os/uuid/AsyncSession` 未使用导入。
- Rerun result: Ruff pass。
- Failure: 首次 SSE test 报 `ServerSentEvent` 无 `.encode`；普通 `EventSourceResponse(iterator)` 未进入 FastAPI native encoder。
- Root cause: 0.141.1 的 response class 是 route marker，必须由 path operation 直接 yield。
- Fix attempt: endpoint 改为 `response_class=EventSourceResponse` + async yield。
- Rerun result: completed SSE framing/header test pass。
- Failure: 404 在 async generator 函数体内抛出，已在响应 producer 启动后，TestClient 收到 ExceptionGroup。
- Root cause: generator body 延迟执行，无法承担 pre-stream auth/ownership。
- Fix attempt: `_require_sse_snapshot` 普通 dependency 提前校验，endpoint 只消费已授权 snapshot。
- Rerun result: 401/query-token/cross-user/nonexistent 统一语义通过。
- Failure: 首次 Pyright 14 errors，主要为 ORM Protocol 不变性、Literal 常量、terminal enum 和 object→int。
- Root cause: 静态合同表达不准确，不是运行行为错误。
- Fix attempt 1: snapshot 改 explicit primitive args；terminal 加 runtime validator；Mapping/类型收窄。
- Rerun result: 剩 3 个 nullable `user_id`。
- Fix attempt 2: snapshot 准确表达历史 `str | None`，owner 仍在投影前拒绝。
- Rerun result: Pyright 0 errors；全部测试重过。

## 10. Scope Compliance

- Allowed files only: Yes
- Forbidden changes avoided: Yes
- User changes preserved: Yes
- Dependencies changed: No new dependency；仅已批准 FastAPI minimum alignment
- API/database/config changed: 新增 versioned SSE 和 optional REST field；无破坏性 API、schema、env 或 secret；Nginx 尚未改

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
|---|---|---|
| Architecture and dependency direction | Satisfied | service→publisher port；application contracts 无 FastAPI/ORM；Router only protocol/auth；DB authority |
| Docstrings, types, field meaning, section navigation | Satisfied | 新公共类/函数中文 Google-style docs、enum/dataclass/Pydantic、Pyright 0 |
| Configuration, secrets, constants, prompts | Satisfied | protocol/reconcile/capacity constants in code；FastAPI minimum aligned；无 env/Prompt/secret |
| Terminal output, logs, traces, artifacts | Satisfied | stable stage/task/report/status/error_type；无 raw exception/正文/token；drop count 可读 |
| Validation, errors, retry/fallback, state, compatibility | Satisfied | pre-stream 401/404、terminal validator、progress max、bounded queue、DB reconcile/status compatibility |
| Tests, evaluation, and handoff evidence | Satisfied | 19 focused + 13 backend/API、真实 LangGraph characterization、exact outputs 和本报告 |

## 12. Risks Remaining

- Risk: frontend 尚未消费协议，当前用户页面仍使用旧 polling/阈值 UI。
- Mitigation or follow-up: M3 实现 strict parser、AbortController、serial fallback、cleanup 和真实 stage component。
- Risk: Nginx 仍可能缓冲 SSE，offline report fixture 尚未装配。
- Mitigation or follow-up: M3 专用 location + deterministic offline service；M4 Compose timing。
- Risk: Hub 不跨 worker/重启，DB 无完整阶段历史。
- Mitigation or follow-up: 能力声明限单 worker；DB 负责 status/terminal；D06 实现 Redis snapshot/pub-sub/recovery。
- Risk: LangGraph `astream_events(v1)` 已弃用且无 root output 时旧 fallback 会再次执行图。
- Mitigation or follow-up: 当前 root regression/锁定版本通过；版本迁移与重复执行风险单独进入后续治理，不在 D05 静默扩改。

## 13. PLAN.md Updates

- Progress: M2 complete；M3～M5 保持未开始。
- Decision Log: native SSE generator/preflight dependency、Hub 32、top-level event filter、安全失败状态。
- Surprises & Discoveries: native SSE marker、generator preflight、LangGraph metadata propagation、ORM typing、v1 deprecation。
- Outcomes & Retrospective: 回填后端已实现/验证，明确 frontend/Compose/Live 未完成。

## 14. Suggested Commit Message

```text
feat(report): stream authoritative report progress over SSE

- Publish true monotonic stages after database commits
- Add protected native SSE with bounded in-process delivery
- Preserve REST compatibility and redact terminal failures
```

## 15. Handoff to User

Milestone 2 is complete. I will not proceed to the next milestone unless you explicitly ask me to continue.
