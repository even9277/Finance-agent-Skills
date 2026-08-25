# Memory Migration Module Evidence Map

本文档把面试口径（短期记忆、长期记忆、自然语言记忆命令、可观测性）映射到可复现的代码、测试和合并 PR。所有链接均为仓库内路径；证据可在 `main` 上复现。

## 1. 短期记忆（STM）

| 面试口径要点 | 代码/模块 | 测试证据 | 合并 PR |
| --- | --- | --- | --- |
| Preflight 预算筛查与阈值压缩，不阻塞主链 | `backend/application/chat/use_case.py`；`backend/services/stm_compaction_worker.py` | `tests/integration/test_memory_summary_worker.py`；`tests/integration/test_controlled_chat_cutover_persistence.py` | #29 |
| Working State（active_entity / constraints / reply_preference_hint）结构化维护 | `Financial-MCP-Agent/src/memory/contracts.py`；`backend/application/memory/ports.py` | `tests/unit/memory/test_working_state_policy.py`；`tests/unit/conversation/test_controlled_trace_adapter.py` | #29 |
| rolling summary 质量门控与 last-good 保护 | `backend/application/memory/summary.py`；`backend/services/stm_compaction_worker.py` | `tests/integration/test_memory_summary_worker.py`（provider failure / dead-letter / stale lease / fencing） | #29 |
| Redis 仅作为可重建热缓存，PostgreSQL 是权威 | `backend/infrastructure/memory/redis_cache.py`；`backend/infrastructure/memory/runtime.py` | `tests/integration/test_memory_redis_cache.py`；`tests/unit/memory/test_redis_cache_contract.py` | #31 |
| 失败降级：cache/provider 不可用时前台不中断 | `backend/application/chat/use_case.py`（retrieval DEGRADED）；`backend/infrastructure/memory/redis_cache.py` | `tests/integration/test_memory_redis_cache.py`；`tests/unit/memory/test_observability_contract.py` | #31/#41 |

## 2. 长期记忆（LTM）

| 面试口径要点 | 代码/模块 | 测试证据 | 合并 PR |
| --- | --- | --- | --- |
| 候选抽取与证据边界（只引用用户消息、query hash） | `backend/application/memory/candidates.py`；`backend/services/ltm_governance_worker.py` | `tests/unit/memory/test_candidate_governance.py`；`tests/integration/test_memory_candidate_governance.py` | #33 |
| 确定性治理评分：重复/多样性/活跃天数/矛盾/过期 | `Financial-MCP-Agent/src/memory/policy.py` | `tests/evals/memory/test_ltm_eval.py`（`memory-ltm-v1`） | #41 |
| 高影响画像候选必须用户确认 | `Financial-MCP-Agent/src/memory/policy.py` | `tests/unit/memory/test_candidate_governance.py` | #33 |
| 混合召回：PostgreSQL 词法 + pgvector 语义 + 权威后过滤 | `backend/application/memory/retrieval.py`；`backend/infrastructure/memory/retrieval_repository.py`；`backend/infrastructure/memory/semantic_provider.py` | `tests/unit/memory/test_m6_semantic_retrieval.py`；`tests/integration/test_postgres_isolation.py` | #36 |
| Mem0 仅作为派生语义层，不允许成为权威 | `backend/infrastructure/memory/semantic_provider.py`；`backend/services/semantic_index_worker.py` | `tests/unit/memory/test_m6_semantic_retrieval.py`（worker/lease/failure） | #36 |
| 删除/遗忘一致性：权威软删除、派生索引重建/删除 | `backend/infrastructure/memory/authority_repository.py`；`backend/services/semantic_index_worker.py` | `tests/integration/test_memory_command_lifecycle.py`；`tests/e2e/test_offline_compose_stack.py` | #39/#41 |

## 3. 自然语言记忆命令（M7）

| 面试口径要点 | 代码/模块 | 测试证据 | 合并 PR |
| --- | --- | --- | --- |
| 确定性中文解析：查看/更新/删除/忘记/确认/取消 | `backend/application/memory/commands.py` | `tests/unit/memory/test_m7_command_contract.py` | #39 |
| 高影响删除必须预览 + 一次性确认，防重放/跨用户/跨会话/过期/版本冲突 | `backend/application/memory/commands.py`；`backend/db/models.py`（`MemoryPendingCommandRow`）；迁移 `20260825_04` | `tests/integration/test_memory_command_lifecycle.py` | #39 |
| REST/WS/前端共享同一 `memory_command` 结果合同 | `backend/routers/chat.py`；`backend/schemas/chat.py`；`frontend/src/api/index.ts`；`frontend/src/composables/useChat.ts` | `tests/contract/test_api_contract.py`；`frontend/src/stores/__tests__/memoryStore.spec.ts` | #39 |
| 命令分支在金融主链前终止，普通金融问题不受影响 | `backend/application/chat/use_case.py` | `tests/contract/test_memory_characterization_contract.py`；离线 Compose E2E 负例 | #39 |

## 4. 可观测性与失败治理（M8）

| 面试口径要点 | 代码/模块 | 测试证据 | 合并 PR |
| --- | --- | --- | --- |
| 稳定低基数记忆阶段与显式状态 | `backend/application/memory/observability.py` | `tests/contract/test_memory_characterization_contract.py`（正式合同） | #41 |
| 日志/Trace 脱敏，不记录命令正文、记忆正文、用户 ID、凭据 | `backend/infrastructure/memory/observability.py`；`Financial-MCP-Agent/src/tools/skill_trace.py` | `tests/unit/memory/test_observability_contract.py`；`tests/e2e/test_live_controlled_chat_chain.py`（redaction 断言） | #41 |
| 指标快照与健康接口 | `backend/application/memory/observability.py`；`backend/main.py` | `tests/contract/test_api_contract.py`；`tests/e2e/test_offline_compose_stack.py` | #41 |
| 失败语义：RETRY/DEAD_LETTER/DEGRADED/SKIPPED，worker 租约与 fencing | `backend/services/stm_compaction_worker.py`；`backend/services/ltm_governance_worker.py`；`backend/services/semantic_index_worker.py` | `tests/integration/test_memory_summary_worker.py`；`tests/integration/test_memory_ltm_worker.py` | #29/#33/#36/#41 |

## 5. 端到端与真实验收

| 验收项 | 命令/证据 | 结果 |
| --- | --- | --- |
| 离线 Compose 全链路 | `docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e` | `148 passed, 1 skipped, 39 deselected, 3 xfailed`（M8 后最终值；M7 为 `144 passed`） |
| 受保护真实 LLM + 只读 Tushare | `RUN_PROTECTED_LIVE_E2E=true uv run --locked pytest tests/e2e/test_live_controlled_chat_chain.py -q -m live` | `1 passed`：1 次真实合成调用、`600519.SH` 只读证据、12 阶段 Trace、隔离 SQLite、脱敏断言 |
| 根回归 | `uv run --locked pytest -q` | `249 passed, 6 skipped, 5 deselected, 3 xfailed` |
| Agent 项目 | `uv run --locked pytest Financial-MCP-Agent -q -m "not live"` | `33 passed, 4 deselected` |
| 离线评测 | `uv run --locked pytest tests/evals -q -m "eval_smoke and not live"` | `24 passed` |

## 6. 剩余风险与后续建议

- Playwright 浏览器级 E2E 未安装；后续可作为独立改进项。
- 进程内指标尚未接入聚合后端；生产部署时接入 Prometheus/OpenTelemetry。
- npm audit 存在 1 个 critical 通告，未在本次范围内升级。
- 受保护 live 工作流依赖 GitHub `protected-live-e2e` 环境 secrets；本地运行需要显式开关与真实凭证。