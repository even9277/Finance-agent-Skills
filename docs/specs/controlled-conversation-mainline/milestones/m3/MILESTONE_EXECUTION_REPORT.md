# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 3 — Entity, Routing, Rewrite, and Skill Discovery Migration
- Status: Complete, pending GitHub PR delivery at report creation time
- Date: 2026-08-24
- GitHub tracking: [Issue #9 — feat: migrate controlled-chat understanding stages](https://github.com/even9277/Finance-agent-Skills/issues/9)
- Local branch: `feat/9-controlled-chat-understanding`

## 2. Scope and Standards

- 只迁移工具调用前的理解链，不切换公开 REST/WebSocket，不迁移 Planner、Executor、Evidence、Controller 或 Synthesis。
- 完整遵循 `PLAN.md`、仓库 `AGENTS.md`、`CONTRIBUTING.md`、工程结构/测试/观测文档、个人 Python Agent 工程标准和 small-step 执行协议。
- 未新增依赖、数据库 Schema、环境变量、历史 Runtime Adapter、双写或 `Finance` 运行时引用。
- 默认测试只使用确定性实现或 Fake 外部 Port，没有调用真实 LLM、Tushare 或生产服务。

## 3. Files and Modules Changed

- `Financial-MCP-Agent/src/conversation/contracts.py`: 扩展实体、两阶段路由、三路 Rewrite、约束、回答偏好、Skill 快照与阶段终止合同。
- `Financial-MCP-Agent/src/conversation/entity.py`: 新增权威实体解析、代码归一化、多实体、歧义和安全追问继承。
- `Financial-MCP-Agent/src/conversation/skill_discovery.py`: 新增仅基于 Skill 元数据的 Stage1 SOP Discovery。
- `Financial-MCP-Agent/src/conversation/routing.py`: 新增 Stage1 SOP 优先、Stage2 当前事实/静态知识路由。
- `Financial-MCP-Agent/src/conversation/constraints.py`、`preferences.py`: 新增有限集合约束和回答偏好抽取。
- `Financial-MCP-Agent/src/conversation/rewriting.py`: 新增 SOP、Tushare、Fallback 三路强类型 Rewrite 和主语校验。
- `Financial-MCP-Agent/src/conversation/workflow.py`: 将上述阶段接入 M2 单一 Orchestrator，并在未迁移执行边界诚实结束。
- `Financial-MCP-Agent/src/skills/skill_registry.py`: 从真实 workspace Skill 元数据构建请求级不可变快照。
- `tests/unit/conversation/`、`tests/contract/test_skill_catalog_contract.py`: 增加模块合同、不变量和状态机测试。
- `tests/evals/{entity,route,rewrite,skill_activation}`: 将原数据加载冒烟改为真正执行实现的版本化离线评测。
- `tests/e2e/test_controlled_chat_chain.py`: 增加低置信澄清、高置信 SOP 边界和非法主语纵向案例。

## 4. Migrated Behavior Matrix

| Module | Migrated contract and behavior | Verification |
|---|---|---|
| Entity | 股票/基金/板块/指数；名称和代码归一化；多基金；“平安”歧义；仅单一历史实体可安全继承 | 7 个版本化 entity cases + unit/E2E |
| Stage1 route | 只看冻结 Skill 名称、描述、版本和执行模式；支持 fund compare、ETF screen、market move、sector hotspot、stock first pass | 8 个 route cases + metadata isolation contract |
| Stage2 route | Stage1 miss 后区分当前事实数据与静态解释；不修改实体结果 | route unit/eval |
| Rewrite | SOP/Tushare/Fallback 判别 union；主语数量、数据维度、时间范围和澄清合同 | 4 个 rewrite cases + unit/E2E |
| Constraints | A 股、排除项等有限、可审计更新语义 | unit/eval |
| Reply preference | 简洁/详细等只影响表达、不提升事实权限 | unit/eval |
| Skill snapshot | Registry 冻结、排序、去重、内容 hash；routing/execution/reference 渐进视图互不越权 | 5 个 activation cases + contract |
| Workflow boundary | 低置信和非法主语在工具前澄清；执行能力未迁移时不伪造成功、不调用模型/工具 | direct workflow E2E |

## 5. Test and Check Evidence

| Check | Result |
|---|---|
| M3 scoped Ruff | `All checks passed` |
| M3 scoped Pyright | `0 errors, 0 warnings` |
| M3 focused unit/contract/eval/E2E | `35 passed` |
| `pytest backend -q` | `12 passed` |
| `pytest Financial-MCP-Agent -q -m "not live"` | `33 passed, 4 deselected` |
| `pytest tests/unit tests/contract -q` | `34 passed, 1 xfailed` |
| `pytest tests/integration -q -m integration` | `3 passed, 1 skipped` |
| `pytest tests/evals -q -m "eval_smoke and not live"` | `6 passed, 4 skipped` |
| `pytest tests/e2e -q -m e2e` | `12 passed, 1 skipped` |
| `pytest -q` | `100 passed, 6 skipped, 4 deselected, 1 xfailed` |
| `uv lock --check`、`git diff --check` | 通过 |
| Offline Compose build/run | 前端、后端镜像构建成功；Nginx/FastAPI/PostgreSQL 健康；HTTP chat 200；容器测试 `51 passed, 1 xfailed`；退出码 0 |
| Compose cleanup | 容器、网络、数据卷删除；`ps --all` 为空 |

固定离线评测中本里程碑新增的 entity 7 条、route 8 条、rewrite 4 条和 skill activation 5 条均通过。该结果只说明固定案例符合合同，不代表真实流量或生产模型准确率。

## 6. Failure and Recovery Record

首次测试先行按预期因新合同不存在而失败。实现后，窄修复解决了澄清语义断言和带空格 A 股约束归一化；随后新增 Workflow 边界测试发现 M2 状态机缺少 `REWRITTEN -> SYNTHESIZING`，按“两次修复即停止”规则暂停并生成 blocked 报告。

恢复执行后，只扩展这一条显式转换并增加状态机测试。定点 E2E 与 unit 均通过，随后所有分层回归和 Compose 门禁通过。转换仍必须经过 `SYNTHESIZING` 才能到 `UNSUPPORTED`，没有允许 Rewrite 绕过 Planner 直接执行工具。

首轮 GitHub CI 的 Python 任务发现 Linux 下 `pytest` 控制台入口没有自动把仓库根目录放入 `sys.path`，四个新 eval 文件因此无法导入 `tests.evals.runner`；同轮前端、Compose 配置和 Offline Compose E2E 均通过。修复仅为在 eval 测试启动段显式注入 `PROJECT_ROOT`，随后使用与 CI 完全相同的 `uv run --locked pytest tests/evals ...` 和 `uv run --locked pytest -q` 本地复验通过，未改变生产代码或降低门禁。

## 7. Trace and Failure Semantics

- 所有 M3 路径沿用 M2 的同一 trace/run 标识、连续阶段事件和唯一终态。
- 低置信 Skill 命中返回 `ROUTE_CONFIRMATION_REQUIRED`，非法 Rewrite 主语返回 `REWRITE_CLARIFICATION_REQUIRED`。
- 高置信 SOP 在 M4/M5 未迁移期间返回 `UNSUPPORTED`，并断言 model/tool call count 均为 0。
- Registry 快照只保存安全元数据和 hash，不在日志或报告中写入秘密、Prompt 正文或 Provider 载荷。

## 8. Remaining Risks and Honest Limitations

- 公开 REST/WS 仍走旧 `backend/services/chat_service.py`；M3 新链通过直接 Application/Workflow E2E 和同一 Compose 容器测试验证，公开入口切换属于 M6。
- Planner/Validator/Executor/Tool Governance 属于 M4，Evidence/Controller/Replanner/Synthesis 属于 M5，因此当前高置信 SOP 尚不会执行真实工具。
- 真实 LLM/Tushare 受保护只读 E2E 尚未执行，不能据此宣称真实模型质量或真实行情正确性。
- 全仓旧代码仍有静态债务；M3 触及范围 Ruff/Pyright 为零问题。
- Compose 暴露既有 PostgreSQL 初始化重复 `ALTER TABLE` 和事务中止日志；应用、HTTP 和测试均成功，但数据库迁移幂等性仍需后续独立治理。
- 既有 WS 内部异常泄露 strict xfail、Starlette TestClient 与 `datetime.utcnow()` 弃用警告仍保留，未在 M3 越界修复。

## 9. Rollback

M3 没有切生产入口、改 Schema、改依赖或访问真实外部服务。合并后可通过 revert 本里程碑 squash commit，恢复 M2 的确定性理解基线；不需要数据回滚或配置恢复。

## 10. Suggested Commit Message

```text
feat(controlled-chat): migrate understanding stages

- migrate authoritative entity resolution and two-stage routing
- add typed rewrites, constraints, preferences, and frozen skill snapshots
- verify understanding boundaries with offline evals and Compose E2E

Closes #9
```

## 11. Handoff

下一个且唯一执行单元是 M4：让计划、校验、权限快照和工具执行形成受控 DAG，并覆盖越权、预算、去重、超时、重试和失败分类。M4 不得提前切换 REST/WS，也不得把真实模型或生产数据源放进默认测试。
