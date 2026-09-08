# D06 报告任务治理 M6 执行报告

## 1. Milestone Executed

- Milestone: 6 — Protected Live, Documentation, Independent Review and GitHub Delivery
- Status: Complete
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

发现并修复四个可操作问题：

1. `restoreActiveTask()` 在异步 Web Crypto/Storage lookup 期间可能与用户新建报告竞争，旧恢复随后接管新 observation epoch。修复在 await 前后校验 epoch、`isGenerating` 和用户，新增“delayed refresh recovery cannot replace newly created task”测试。
2. 既有 CI 的 Ruff/Pyright 白名单未覆盖新增报告 application/infrastructure、router/schema/service。现已纳入相同质量门禁，并让 Compose 回滚检查同时验证 `ENABLE_REPORT_TASK_REDIS=false` 且 Redis 不成为 backend 启动依赖。
3. PR 的第二轮 Offline Compose E2E 暴露出历史缓存命中断言的多实例波动：聊天请求命中某一后端，但代理 `/api/health` 可能落到另一个后端，而计数器本身是进程内指标。测试现改为直读两个已知后端健康端点、逐实例验证 `UP` 并聚合命中/事件计数；不改变生产指标语义。独立 Compose 项目完整复核通过 `335 passed, 4 skipped, 48 deselected, 3 xfailed`。
4. PR 的下一轮 Offline Compose E2E 在更快的 GitHub Runner 上暴露迁移隔离缺口：测试曾在两个后端健康检查和后台 worker 仍访问应用数据库时执行全量 downgrade，触发多表 DDL/读事务锁顺序反转。迁移 upgrade/pgvector/downgrade/历史数据保留/re-upgrade 现迁至独立 tmpfs pgvector 数据库，运行中应用不连接该库；不修改生产迁移语义。

修复后专项测试 10/10；D06 CI 静态边界 Ruff/Pyright 通过，Compose 回滚断言和 workflow YAML 解析通过。其余审查项没有发现阻断交付的问题。

## 6. Final Local Gates

| Gate | Result |
| --- | --- |
| Backend default full suite | `441 passed, 14 skipped, 9 deselected, 3 xfailed` |
| Frontend full suite | 16 files / 54 tests passed |
| Frontend lint / type / build | passed / passed / passed；仅既有大 chunk warning |
| D06 CI Ruff / Pyright boundary | passed / 0 errors |
| Workflow YAML / Compose rollback override | passed / passed |
| True two-backend Offline Compose after metrics fix | `335 passed, 4 skipped, 48 deselected, 3 xfailed` |
| Dedicated migration database | Ruff/Pyright/Compose config passed；最终容器结果以 PR checks 为准 |
| Protected Live | 1 passed；未重跑 |

## 7. Known Boundaries

- `BackgroundTasks` 不提供 Web 进程崩溃续跑。
- Redis Pub/Sub 只提供最新版本唤醒，不是完整事件日志。
- 两个 ASGI 应用的 Live 不等于两个 OS 进程；真双后端证据来自 M5 Compose。
- 仓库全量 Pyright 的 4 个 provider 历史错误未触达，D06 范围为 0 error。
- Live 观察到既有 Starlette TestClient、naive UTC 与 LangGraph legacy factory 弃用 warning。

## 8. GitHub Delivery

- Issue: [#52](https://github.com/even9277/Finance-agent-Skills/issues/52)
- Implementation commit: `0a03b42482800a09eef0020d7f15e1b8aede5c90`
- PR: [#53](https://github.com/even9277/Finance-agent-Skills/pull/53)
- Independent review evidence: [PR comment](https://github.com/even9277/Finance-agent-Skills/pull/53#issuecomment-5573416228)
- Required checks: 实现提交的 Python quality/offline tests、Frontend lint/type/build、Docker packaging/Compose config、Offline Compose E2E 全部通过；后续 Compose runs 暴露并修复上述进程内指标聚合与迁移数据库隔离问题，最终检查状态以 GitHub PR 记录为准。
- Merge policy: 用户已授权 squash merge；修复推送后等待同一组检查全绿，最终 merge/Issue 状态由 GitHub 记录。分支保留可审查的小步提交，squash 后 `main` 只保留一个 D06 提交。

保护文件 `docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` 的 Git blob hash 仍为 `cc21919a88d19453f47f58d895ff2759462f5425`，保持 untracked、unstaged。
