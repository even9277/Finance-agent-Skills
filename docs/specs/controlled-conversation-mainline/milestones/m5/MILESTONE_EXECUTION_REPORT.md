# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 5 — Evidence, Controller, Replanner, and Synthesis Migration
- Status: Complete, pending GitHub PR delivery at report creation time
- Date: 2026-08-24
- GitHub tracking: [Issue #13 — feat: migrate controlled evidence verification and synthesis](https://github.com/even9277/Finance-agent-Skills/issues/13)
- Local branch: `feat/13-controlled-evidence-synthesis`

## 2. Scope and Standards

- 只迁移 Evidence、Verifier、Controller、有界 Replanner 和 Synthesis，不切换公开 REST/WebSocket，不修改持久化事务。
- 完整遵循 `PLAN.md`、仓库 `AGENTS.md`、`CONTRIBUTING.md`、工程结构/测试/观测文档、个人 Python Agent 工程标准和 small-step 执行协议。
- 以两份面试口径文档的“主语/时间/维度/角色/质量验收、有限补证、accepted-only 总结”为设计映射，但没有把未复测指标写成代码事实。
- 未新增依赖、数据库 Schema、环境变量、历史 Runtime Adapter、双写或 `Finance` 运行时引用；默认测试未调用真实 LLM、Tushare 或生产服务。

## 3. Files and Modules Changed

- `Financial-MCP-Agent/src/conversation/contracts.py`: 扩展 Evidence role/rejection/score、逐实体 requirement、Controller runtime、Replan 和 AnswerContextPack 合同。
- `Financial-MCP-Agent/src/conversation/verification.py`: 统一主语、合同、时效、空值、来源、冲突、覆盖和质量验收，并产生可解释五维分数与 claim level。
- `Financial-MCP-Agent/src/conversation/control.py`: 根据验证结果和冻结预算裁定 REPLAN、SUCCEEDED、PARTIAL 或 FAILED。
- `Financial-MCP-Agent/src/conversation/replanning.py`: 只在原权限快照内为 missing requirement 选择未尝试备用动作。
- `Financial-MCP-Agent/src/conversation/permissions.py`: 股票行情请求级权限增加治理内备用 `get_daily_bars`，首轮计划仍保持最小工具集。
- `Financial-MCP-Agent/src/conversation/planning.py`、`validation.py`: requirement 绑定实体；暴露统一参数与 action fingerprint 构造；按实体校验 coverage。
- `Financial-MCP-Agent/src/conversation/workflow.py`: 接入唯一的执行后有界补证环、重复 verify/controller、REPLAN Trace 和 accepted-only Synthesis。
- `Financial-MCP-Agent/src/conversation/synthesis.py`、`src/prompts/chat/{registry.py,synthesis_v2.md}`: 升级 Prompt 合同，拒绝 REFUSE/rejected payload 进入模型。
- `backend/infrastructure/chat/testing.py`: 增加“首选行情无证据、备用工具恢复”的确定性 Fake 行为。
- `tests/unit/conversation/`、`tests/evals/{verifier,synthesis}`、`tests/e2e/test_controlled_chat_chain.py` 和纵向 fixture：新增合同、评测和纵向证据。

## 4. Interview Narrative Mapping

| 面试设计口径 | M5 实现映射 | 验收证据 |
|---|---|---|
| Evidence Envelope | 每条观察归一化为带 plan/step/tool/entity/dimension/role/source/date/quality/status 的强类型信封 | unit + verifier eval |
| 主语验收 | observation symbol 必须与已校验计划 step 一致 | wrong-entity case |
| 时间验收 | analysis date 与各维度 freshness policy 比较，未来或 stale 拒绝 | stale/future contract |
| 维度与角色 | requirement 按 `dimension + entity_symbol` 检查，required 与 optional 明示 | planner/validator/verifier tests |
| 数据质量 | 空 facts、空 key/value、空 source 均有稳定拒绝码 | unit cases |
| 证据冲突 | 同主语/维度/日期/key 的不同值整体拒绝，不由模型挑选 | conflict case |
| Controller | ANALYTICAL 成功；DESCRIPTIVE 降级；REFUSE 失败；缺口且有预算才 REPLAN | controller unit/E2E |
| 有界 Replanner | 仅补 missing requirement、复用权限快照、跳过已尝试 fingerprint、最多一次 | alternative/no-progress E2E |
| AnswerContextPack | accepted facts + executed plan summary + missing dimensions + 无事实 rejection summary | isolation unit/synthesis eval |
| Synthesis | `chat-synthesis-v2` 只消费 AnswerContextPack；DESCRIPTIVE 强制显示缺口；REFUSE 不调用模型 | synthesis unit/eval |

Redis 熔断、网页新闻证据分级、用户画像/LTM 深度注入和前端 plan preview 不属于本里程碑；不得把面试文档中的这些规划表述成当前 M5 已实现。

## 5. Test and Check Evidence

| Check | Result |
|---|---|
| M5 scoped Ruff | `All checks passed` |
| M5 scoped Pyright | `0 errors, 0 warnings` |
| M5 focused unit/eval/E2E | `26 passed` |
| `pytest backend -q` | `12 passed` |
| `pytest Financial-MCP-Agent -q -m "not live"` | `33 passed, 4 deselected` |
| `pytest tests/unit tests/contract -q` | `44 passed, 1 xfailed` |
| `pytest tests/integration -q -m integration` | `3 passed, 1 skipped` |
| `pytest tests/evals -q -m "eval_smoke and not live"` | `10 passed` |
| `pytest tests/e2e -q -m e2e` | `14 passed, 1 skipped` |
| `pytest -q` | `116 passed, 2 skipped, 4 deselected, 1 xfailed` |
| `uv lock --check`、`git diff --check` | 通过 |
| Offline Compose build/run | 前端、后端镜像构建成功；Nginx/FastAPI/PostgreSQL 健康；HTTP chat 200；容器测试 `63 passed, 1 xfailed`；E2E 容器退出码 0 |
| Compose cleanup | 容器、网络、数据卷删除；`ps --all` 为空 |

## 6. Failure and Recovery Record

测试先行阶段按预期因 M5 合同尚不存在而 collection 失败，不计入修复次数。实现后的第一次窄修复把旧 E2E 对 M2 `PARTIAL` claim 名称的断言更新为 M5 `DESCRIPTIVE`；第二次窄修复移除测试未使用导入，并让 Pyright 明确收窄可空 rejection code。之后 scoped static、focused、分层全量和 Compose 均通过，没有第三次实现修复。

## 7. Trace, Failure, and Termination Semantics

- 一轮仍使用同一 `trace_id/run_id/session_id`；补证通过稳定 `replan` stage 和 `attempt/reason/added_step_count` 可见。
- Verify 事件记录 accepted/rejected/missing 数、claim level 和 evidence score，不记录 facts 或原始 Provider payload。
- Controller 每轮记录 action/reason/replans_remaining；默认 `max_replans=1`，状态机只允许 `VERIFIED -> REPLANNING -> VALIDATED -> EXECUTING -> VERIFIED`。
- Executor 已用完的 action fingerprint 不能由 Replanner 重复；无备用动作或无新增证据时立即 PARTIAL/FAILED。
- Synthesis 输入中的 `rejected_evidence` 永远为空，只有不含事实值的 rejection summary；REFUSE 不允许调用模型。

## 8. Remaining Risks and Honest Limitations

- 公开 REST/WS 仍走旧 `backend/services/chat_service.py`；新链通过 Application/Workflow E2E 和 Compose 容器测试验证，入口切换属于 M6。
- 真实 Model/Tushare adapter 尚未接入新 Tool/Model Port；M5 结果不能证明实时数据或模型质量。
- `financial-sop` 当前使用统一 requirement/claim-level 门控；Skill spec 中更细的每 Skill degrade policy、output template 和 required/optional 规则仍需后续按实际合同演进。
- 网页新闻弱证据、来源优先级、注入检测、Redis 三态熔断、缓存和用户可见 plan preview 不在本次范围。
- 历史 `src/agents` verifier/controller/synthesis 仍存在但新 Workflow 不引用；M6 切换时删除被替代旧编排，不建立 Adapter。
- Compose 继续暴露既有 PostgreSQL 重复 `ALTER TABLE` 事务噪声；应用与测试成功，但数据库迁移幂等性仍是独立技术债。
- 既有 WS 内部异常泄露 strict xfail、Starlette TestClient 与 `datetime.utcnow()` 弃用警告仍保留，等待 M6 或独立治理。

## 9. Rollback

M5 没有切生产入口、改 Schema、改依赖或访问真实外部服务。合并后可 revert 本里程碑 squash commit，恢复 M4 的受控工具执行与 M2 Evidence 基线；不需要数据或配置回滚。

## 10. Suggested Commit Message

```text
feat(controlled-chat): enforce evidence-bounded answers

- verify typed evidence across entity, freshness, coverage, role, quality, and conflict gates
- add one bounded permission-preserving supplemental replan
- isolate rejected facts from versioned controlled synthesis

Closes #13
```

## 11. Handoff

下一个且唯一执行单元是 M6：把 REST/WebSocket 同时切到单一 Chat Use Case，收拢事务与事件映射，并删除被替代的旧 Chat Service 编排。M6 不得保留转发壳、永久 feature flag 或双写。
