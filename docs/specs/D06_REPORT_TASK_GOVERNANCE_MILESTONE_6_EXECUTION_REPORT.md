# D06 报告任务治理 M6 执行报告

## 1. Milestone Executed

- Milestone: 6 — Protected Live, Documentation, Independent Review and GitHub Delivery
- Status: In progress（本地验收/文档/review 完成，GitHub delivery 待完成）
- Date: 2026-09-08

## 2. Frozen Contract

- Goal: 只运行一份受保护真实报告，证明 20 次同键并发重试只执行一个 workflow；对齐 README/测试/面试 Claim；独立审查完整 diff；完成 Issue #52、commit、PR、checks 和授权 squash merge。
- Allowed: protected Live harness/安全摘要、D06 验收与执行文档、README/测试策略/两份相关项目描述文档、review 发现的窄修、GitHub metadata。
- Forbidden: 第二次整报告 Live、生产写、凭据/正文 artifact、Auth/Prompt/Skills/Memory 扩面、新依赖和持久任务队列。

## 3. Protected Live Evidence

唯一一次真实报告执行通过，且没有自动重跑：

| Signal | Result |
| --- | --- |
| 请求/应用分布 | 20；两个独立 ASGI 应用各 10 |
| API 幂等结果 | 1 `CREATED` + 19 `REPLAYED` |
| 唯一性 | 1 task + 1 report + 1 background dispatch |
| 真实工作流 | 1 stream invocation；0 fallback invocation |
| 外部只读调用 | 17 model runs；46 Tushare calls |
| 终态 | `completed` / progress 100 / snapshot version 15 |
| 耗时 | 167660.48 ms |
| 正文 hash | `dbaabb0715bb0fcfea59d93a9683149a5b740359cf467d322b80b4c948de80e1` |
| 临时摘要 artifact hash | `2432c5083326937777549c2048a9f0163b7479a28311bf4106bf57ceda513f1a` |
| 脱敏 | passed |

测试使用精确确认的本机一次性 `d06_live` pgvector/PostgreSQL，完成后停止并由 `--rm` 删除。测试摘要没有请求正文、原始用户、原始 key、Token、API key 或报告正文。Tushare `sw_daily` 的账号权限错误由既有工具容错处理，其他只读接口与最终报告成功；没有为此重跑。

## 4. Documentation and Claim Alignment

- README/测试策略补齐 PostgreSQL 唯一权威、Redis 派生快照、显式 key、latest-snapshot、Live 门禁和 BackgroundTasks 边界。
- 仓库新增 `docs/interview/D06_REPORT_TASK_GOVERNANCE_CLAIM_ALIGNMENT.md`，让远端代码、口述和测试互相导航。
- 项目描述源文档 `成果点-前后端与工程体系搭建-完整阐述.md` 与 `报告模式.md` 的 D06 段落已最小校正：废止 Redis-only `SET NX EX`、Redis-first 状态和 query token 说法；保留用户 + 规范化命令 hash + 10 分钟兼容口径。
- 所有数字明确标为固定验收样本，不包装为 SLA、线上收益或统计结论。

## 5. Independent Review

审查覆盖架构所有权、PostgreSQL 竞争/换代、迁移 up/down、Redis 污染/失联、鉴权隔离、SSE 竞态/取消、前端恢复/重试、隐私/日志/Live 资源清理和 Claim 准确性。

发现并修复两个可操作问题：

1. `restoreActiveTask()` 在异步 Web Crypto/Storage lookup 期间可能与用户新建报告竞争，旧恢复随后接管新 observation epoch。修复在 await 前后校验 epoch、`isGenerating` 和用户，新增“delayed refresh recovery cannot replace newly created task”测试。
2. 既有 CI 的 Ruff/Pyright 白名单未覆盖新增报告 application/infrastructure、router/schema/service。现已纳入相同质量门禁，并让 Compose 回滚检查同时验证 `ENABLE_REPORT_TASK_REDIS=false` 且 Redis 不成为 backend 启动依赖。

修复后专项测试 10/10；D06 CI 静态边界 Ruff/Pyright 通过，Compose 回滚断言和 workflow YAML 解析通过。其余审查项没有发现阻断交付的问题。

## 6. Final Local Gates

| Gate | Result |
| --- | --- |
| Backend default full suite | `441 passed, 14 skipped, 9 deselected, 3 xfailed` |
| Frontend full suite | 16 files / 54 tests passed |
| Frontend lint / type / build | passed / passed / passed；仅既有大 chunk warning |
| D06 CI Ruff / Pyright boundary | passed / 0 errors |
| Workflow YAML / Compose rollback override | passed / passed |
| Protected Live | 1 passed；未重跑 |

## 7. Known Boundaries

- `BackgroundTasks` 不提供 Web 进程崩溃续跑。
- Redis Pub/Sub 只提供最新版本唤醒，不是完整事件日志。
- 两个 ASGI 应用的 Live 不等于两个 OS 进程；真双后端证据来自 M5 Compose。
- 仓库全量 Pyright 的 4 个 provider 历史错误未触达，D06 范围为 0 error。
- Live 观察到既有 Starlette TestClient、naive UTC 与 LangGraph legacy factory 弃用 warning。

## 8. GitHub Delivery

Issue #52 已存在。commit、PR、checks、review 和 squash merge 将在最终门禁后补充；完成前本报告保持 `In progress`，不得宣称 M6 完成。

保护文件 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` 的 Git blob hash 仍为 `cc21919a88d19453f47f58d895ff2759462f5425`，保持 untracked、unstaged。
