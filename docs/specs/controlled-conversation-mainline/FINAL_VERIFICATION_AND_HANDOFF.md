# 受控对话主链最终验证与交接

> 日期：2026-08-24
> 范围：Milestone 0-8
> GitHub 跟踪：Issue #19；全仓静态债务另见 Issue #20

## 1. 最终结论

受控对话主链已经完整迁移到 `Finance-agent-Skills` 的唯一生产调用路径，并完成公开
REST/WS、事务持久化、真实离线 Compose、脱敏 Trace 和受保护 Live 验收。旧
`backend/services/chat_service.py` 已删除，生产装配不依赖 `Finance` 历史 Runtime，也没有
兼容 Adapter 或长期双轨。

“完整迁移”在这里指主链阶段和工程合同完整，不代表两份面试材料中的全部增强能力和历史
质量数字都已复现。逐模块的精确状态以
`INTERVIEW_NARRATIVE_IMPLEMENTATION_MATRIX.md` 为准。

## 2. 当前验收调用链

```text
Nginx / Vue
→ FastAPI REST 或 WebSocket
→ ControlledChatUseCase
→ ControlledConversationWorkflow
→ Context / Entity / Route / Rewrite / Permission
→ Planner / Validator / Executor
→ Verifier / Controller / bounded Replan / Synthesis
→ SQLAlchemy Repository commit or rollback
→ root Trace + ordered stage spans
```

生产端口实现为 `OpenAICompatibleModelProvider`、`TushareToolProvider`、
`SqlAlchemyConversationRepository` 和 `SkillTraceSink`。默认/Compose E2E 只替换外部
Model 与 Tool Provider，不替换 Workflow、Repository、PostgreSQL 或生产 Trace Adapter；
单元测试会按被测边界使用 Repository/Trace Fake。

## 3. M8 测试矩阵

| 层级 | 命令 | M8 结果 |
| --- | --- | --- |
| 依赖锁 | `uv lock --check` | 通过 |
| Backend | `uv run --locked pytest backend -q` | 11 passed |
| Agent offline | `uv run --locked pytest Financial-MCP-Agent -q -m "not live"` | 33 passed，4 deselected |
| Unit + Contract | `uv run --locked pytest tests/unit tests/contract -q` | 52 passed |
| Integration | `uv run --locked pytest tests/integration -q -m integration` | 5 passed，1 skipped |
| Offline eval | `uv run --locked pytest tests/evals -q -m "eval_smoke and not live"` | 11 passed |
| E2E marker | `uv run --locked pytest tests/e2e -q -m e2e` | 14 passed，2 skipped |
| Default full | `uv run --locked pytest -q` | 126 passed，2 skipped，5 deselected |
| Ruff CI scope | 与 `.github/workflows/ci.yml` 相同 | All checks passed |
| Pyright CI scope | 与 `.github/workflows/ci.yml` 相同 | 0 errors，0 warnings |
| Frontend | `npm ci`、lint、type-check、build | 全部通过；保留 chunk warning |
| Compose config | production + offline 两份配置 | 通过 |
| Offline Compose | `docker compose ... up --build ...` | 73 passed，1 skipped |
| Compose cleanup | `docker compose ... down -v --remove-orphans` | 容器、网络、Trace 卷均删除 |
| Diff | `git diff --check` | 通过 |

M8 没有修改业务行为，因此没有再次调用付费模型或真实 Tushare。真实证据复用 M7 的显式
Live E2E：真实 LLM 恰好一次、真实只读 Tushare、公开 HTTP、临时 SQLite、12 个阶段
Span，结果 `1 passed`。该证据不等于全场景质量评测。

## 4. 仓库级静态扫描的诚实结论

冻结 PLAN 还要求执行比 CI 更宽的两条历史仓库扫描：

- `uv run --locked ruff check backend Financial-MCP-Agent/src tests`：81 errors。
- `uv run --locked pyright backend Financial-MCP-Agent/src tests`：80 errors、6 warnings。

问题集中在未迁移的报告 Agents、Memory、旧 Router/Executor、旧 Langfuse SDK 接口和
`sys.path` 导入；不是 M8 文档变更引入。M8 禁止跨模块新增功能或批量修复历史代码，因此
没有使用 ignore、降低规则或 unsafe fix 掩盖问题。Issue #20 已登记分批治理，当前 CI 对
M0-M7 实际维护边界仍保持 Ruff/Pyright 零问题。

因此最终结论是：**默认交付门禁和受控主链维护边界全绿；整个历史仓库尚未达到全量静态
零债务。** 两者必须同时说明。

## 5. Compose 与 Trace 证据

M8 Compose 从生产构建的 Vue/Nginx 发出虚拟请求，真实经过 FastAPI、Application、
Workflow、Repository 和 PostgreSQL。成功案例产生 12 个有序 Span：

```text
context → entity_resolution → route → rewrite → permission → plan
→ validate → execute → verify → controller → synthesis → termination
```

该轮 `route_family=tushare-data`、计划 2 步、校验问题数 0、工具调用 2 次、证据验收
`accepted=2/rejected=0`、Controller `STOP`、终态 `SUCCEEDED`。Compose 外部模型和数据
端口为确定性 Fake，因此零费用且不访问生产服务。测试后已确认 `docker compose ps -a`
为空，`docker_trace-e2e` 卷不存在。

## 6. 面试口径核对结论

可以作为当前项目成果讲述的核心能力：

- 唯一 workflow-style 受控对话主链和 Typed State。
- route 前权威实体阶段、两阶段路由、三路 Rewrite 和当前轮窄约束。
- 请求级只读工具权限快照、确定性 Planner、Validator 和有界 DAG Executor。
- Evidence 五维验收、规则 Controller、最多一次补证和 accepted-only Synthesis。
- REST/WS 共用用例、事务回滚、用户隔离、PostgreSQL 和 12 阶段 Trace。
- 默认零费用 CI、真实 Workflow Compose 和显式保护 Live E2E。

必须作为限制或后续规划讲述的能力：

- LLM route rerank、模型 rewrite/extractor、模型 Planner。
- 前端 `skill_confirm/plan_preview/step_status/verification_summary`。
- `search_web_news`、来源分层和新闻弱证据。
- Redis 共享熔断、限流、分布式幂等和断线恢复。
- Provider 逐 token streaming、完整在线 Langfuse score/dataset 回流。
- 150×3、90×3、75×3 黄金集和 70.2%→88.4%、93.8%、95%+ 等历史数字。

## 7. 回滚与剩余风险

- M8 只修改文档，无 Schema、依赖、API、鉴权或生产配置变化。
- M8 合并后可 revert 单个 squash commit；M7 受控主链代码和数据不受影响。
- M0-M7 每个里程碑均为独立 squash commit，可按反向顺序逐个 revert；M6 是入口切换与旧
  实现删除边界，不能通过长期 Feature Flag 恢复双轨。
- GitHub protected Live Environment 的 secrets/审批和可选 branch protection 仍需管理员配置。
- 数据库历史增量初始化噪声、前端大 chunk、弃用 warning 和 Issue #20 全仓静态债务仍需后续规格治理。
- 未经新的用户授权，不执行部署、release、生产写或交易能力。

## 8. 后续唯一真相源

- 研发规则：`AGENTS.md`、`CONTRIBUTING.md`、`docs/engineering/`。
- 受控主链规格和历史决策：本目录 `REQUIREMENT_SPEC.md` 至 `PLAN.md`。
- 当前实现与面试口径映射：`INTERVIEW_NARRATIVE_IMPLEMENTATION_MATRIX.md`。
- 真实调用证据：`LIVE_VALIDATION_REPORT.md` 第 8 节和 M7 Trace index。
- 后续新增模块：重新走 Spec Coding 和独立 Issue/PR，不在历史面试材料里直接改代码事实。
