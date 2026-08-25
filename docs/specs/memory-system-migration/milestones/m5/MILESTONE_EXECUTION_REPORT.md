# M5 执行报告：长期记忆候选抽取与治理

## 1. 范围

本里程碑只完成“用户证据 -> 候选 -> 确定性治理 -> PostgreSQL 权威记录”的受控链路，保留高影响画像的确认门槛；不安装或启动 Mem0、pgvector，不改变历史 `Finance` 仓库。

## 2. 已交付

- 领域合同：候选草稿、证据、统计信号、晋升决策、候选 Outbox payload 和稳定版本号。
- 抽取边界：默认 deterministic extractor；OpenAI-compatible 适配器仅在显式配置时启用；Provider 输出必须通过 Pydantic schema、版本和用户消息来源校验。
- 治理仓储：候选创建/证据去重/统计聚合/冲突隔离/状态转换/自动晋升/确认隔离/审计事件同事务提交；同用户指纹使用数据库锁避免并发重复。
- Worker：候选任务领取、租约 fencing、摘要/Working State/会话所有权复核、用户消息证据边界、有限重试和 dead-letter。
- 权威写入：显式画像/文本写入、更新、软删除和候选确认均走 PostgreSQL 权威记录；模型推断不能直写高影响画像。
- 数据库：新增候选统计字段和 `memory_candidate_evidence` expand-first Alembic revision `20260825_02`。

## 3. 验收结果

执行目录：`D:\FinanceProject\Finance-agent-Skills`

```text
uv run --locked python -m pytest \
  tests/unit/memory/test_candidate_governance.py \
  tests/unit/memory/test_contracts.py \
  tests/contract/test_memory_characterization_contract.py \
  tests/integration/test_memory_candidate_governance.py \
  tests/integration/test_memory_ltm_worker.py \
  tests/integration/test_memory_migrations.py \
  tests/evals/memory/test_memory_eval.py -q
28 passed, 5 xfailed
```

新增 Worker 与迁移专项：`8 passed`。

```text
ruff (maintained M5 paths): All checks passed
pyright (new/maintained M5 paths): 0 errors, 0 warnings
git diff --check: passed
```

迁移测试验证 upgrade -> downgrade(显式隔离授权) -> re-upgrade，并确认历史用户/会话/消息仍可读。测试只使用隔离 SQLite、确定性 Provider 和固定夹具，不调用付费模型、生产服务或真实 Tushare。

## 4. 已知风险与未完成交付

- 全仓 Pyright 仍有 86 个历史错误，集中在旧 Agent、工具和 Langfuse 适配器；本里程碑未扩大范围修复。
- 测试存在 Python 运行时 `datetime.utcnow()` 弃用警告及 Starlette/httpx 警告；不影响本次行为结果，后续单独治理。
- 已执行完整 Docker Compose E2E：真实隔离 PostgreSQL、Redis、FastAPI、Nginx/Vue 链路通过 `136 passed, 1 skipped, 32 deselected, 5 xfailed`，退出码为 0。
- 交付闭环已完成：commit `e308477` 已推送，PR #33 已通过四项 CI 门禁并合并为 `0ea2aa0`；Issue #32 已关闭。GitHub 不允许 PR 作者批准自己的 PR，因此未产生作者自审批准记录；合并前已完成本地只读 diff 审查和全部自动化门禁。
- M6 的 Mem0/pgvector 检索、索引同步和自然语言记忆命令仍未实现。

## 5. 回滚与交接

回滚时停止候选治理 Worker，并按 `policy_version` 与 `activation_source` 隔离本版本自动晋升记录；不删除或自动回滚用户确认写入，不执行生产批量删除。迁移降级只能针对显式隔离数据库授权执行。M5 完成交接前不得开始 M6。
