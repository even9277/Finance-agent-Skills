# M6 执行报告：Mem0/pgvector 派生索引、混合召回与受控注入

## 状态

- 状态：实现、CI、代码审查与合并闭环完成
- Issue：#35
- PR：#36（已合并，merge commit `2d1d09b`）
- 实现分支：`feat/35-memory-hybrid-retrieval`（已删除）
- 权威源：PostgreSQL `memory_records`
- 派生层：pgvector/Mem0 索引、`memory_provider_references`、INDEX Outbox

## 已实现

1. 增加 `IndexUpsertPayload`、`IndexDeletePayload` 及 Outbox 幂等合同。
2. 增加 `memory_semantic_index` Alembic 表；PostgreSQL 使用 pgvector，SQLite 测试使用 JSON 向量。
3. 增加确定性 hash embedding 和 pgvector Provider；Mem0 使用惰性导入、`infer=False`、用户过滤及权威 `record_id/version` 元数据。
4. 权威文本新增、更新、删除和治理自动晋升均在同一事务中创建索引 Outbox；权威接口返回 `PENDING` 派生一致性状态。
5. 增加带租约 fencing、重试、死信、过期/版本跳过、旧引用 stale 和删除状态机的语义索引 Worker。
6. 增加 PostgreSQL 词法召回、语义召回、融合排序、权威后过滤和 token budget packing。
7. 将召回结果接入 `ContextPacket -> AnswerContextPack`，仅供 Context/Rewrite/Synthesis 使用；不进入 Planner、Permission 或 Evidence。
8. 在已有 context trace 事件中记录 `memory_hit_count`、`memory_token_count`、`memory_context_status`，不记录正文、用户 ID 或查询原文。
9. Offline Compose 切换到 `pgvector/pgvector:0.8.0-pg16`，显式启用 deterministic memory/embedding，仍关闭所有真实外部服务。

## 验收命令与结果

```text
uv run --locked ruff check [维护范围] tests
All checks passed!

uv run --locked pyright [维护范围] tests
0 errors, 0 warnings, 0 informations

uv run pytest -q tests/unit/memory/test_m6_semantic_retrieval.py
7 passed

uv run --locked pytest -q tests/contract/test_controlled_chat_contract.py \
  tests/unit/conversation/test_evidence_control_synthesis.py \
  tests/e2e/test_controlled_chat_chain.py \
  tests/integration/test_memory_transactional_outbox.py
30 passed

uv run --locked pytest -q tests/integration/test_memory_migrations.py
4 passed

uv run --locked python -m compileall -q backend Financial-MCP-Agent/src
success

聚焦回归合计：`30 + 4 + 7 = 41 passed`。
```

Docker Compose 离线验收已在隔离的 PostgreSQL/pgvector、Redis、FastAPI、Nginx、Vue 环境完成；执行命令为：

```text
docker compose -f docker/docker-compose.offline.yml \
  up --build --abort-on-container-exit --exit-code-from offline-e2e
docker compose -f docker/docker-compose.offline.yml down -v --remove-orphans
```

结果：`136 passed, 1 skipped, 39 deselected, 5 xfailed`，耗时 `50.16s`，退出码 `0`。验收覆盖数据库迁移与 ORM parity、pgvector 扩展/HNSW 索引、真实 pgvector CRUD/用户隔离/权威删除过滤/派生删除、真实 HTTP 前后端代理、两轮受控对话、并发与 STM 摘要、Redis 缓存、Trace 脱敏和受控主链路阶段顺序。全程使用 deterministic provider，未调用付费模型、生产服务、真实 Tushare 或 Mem0 网络服务。

## 失败与修复记录

- 首轮真实 pgvector 生命周期验收暴露距离表达式被 SQLAlchemy 错误按 `Vector` 解析；查询层通过显式 `CAST(... AS FLOAT)` 固定返回类型，完整 Compose 重建后通过。
- 补充 PostgreSQL 外键、pgvector/HNSW schema parity、Provider 进程级复用、运行时超时与召回预算接线、Worker 调用后租约 fencing，以及 Mem0 用户作用域和 Provider ID 的 fail-closed 校验。

## 安全与回滚

- 默认 `MEMORY_SEMANTIC_PROVIDER=disabled`，不会隐式导入 Mem0 或调用外部模型。
- Offline Compose 使用空模型/Tushare/Langfuse 凭据和 deterministic Provider。
- pgvector/Mem0 行可删除并从 PostgreSQL 权威记录重建；不允许反向覆盖权威记录。
- 回滚时先停止 semantic Worker、关闭语义召回，再保留 PostgreSQL 词法/画像路径；不要回滚权威记忆数据。

## 未纳入 M6

- M7 自然语言记忆命令和前端控制。
- M8 完整指标/故障矩阵与离线评测门禁。
- M9 受保护真实模型、真实 Tushare 和最终生产拓扑验收。

## 交付闭环

- Commit：`e6df305 feat(memory): add governed hybrid retrieval (#35)`
- Pull Request：`#36`，GitHub Actions 四项门禁全部通过，完成代码审查后 squash merge 到 `main`。
- Issue：`#35` 已关闭。
