# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: 2 — Shared Async Deterministic Resolver and Catalog Contract
- Status: Complete
- Date: 2026-09-09

## 2. Development Standards Read

- `PLAN.md`: 已读取 M2 目标、允许文件、tests/checks、停止与回滚条件。
- `DEV_STANDARDS.md`: 未提供独立文件。
- `AGENTS.md`: 已遵循领域/port/adapter 依赖方向、async I/O、类型/docstring/tests-first。
- nested rules / CLAUDE / Cursor / Copilot: 未发现。
- README / contribution / test docs: 沿用 M0/M1 已读取规则。
- Python/Agent standard: 已应用所需的接口类型、中文 Google-style docstring、稳定错误和低敏边界。

## 3. Files Inspected

- `Financial-MCP-Agent/src/conversation/{entity,contracts,ports,errors,workflow}.py`: 领域合同与调用点。
- `Financial-MCP-Agent/src/tools/tushare_client.py`: 复用现有 async、timeout、retry 和缓存客户端。
- `backend/infrastructure/chat/providers.py`: 对齐基础设施 Adapter 风格。
- `backend/application/chat/factory.py`: 确认 M3 的生产注入位置。
- 所有 `AuthoritativeEntityResolver.resolve()` 直接调用测试：确认 async 迁移范围。

## 4. Files Modified

- `Financial-MCP-Agent/src/conversation/contracts.py`: 新增 path/catalog status、模型请求/结果、稳定错误码与结果元数据。
- `Financial-MCP-Agent/src/conversation/errors.py`: 新增模型/目录 typed errors。
- `Financial-MCP-Agent/src/conversation/ports.py`: 新增模型和 Catalog Protocol。
- `Financial-MCP-Agent/src/conversation/entity.py`: 唯一 async deterministic-first Resolver、fuzzy、冲突/非法代码门禁、模型候选 grounding 编排。
- `Financial-MCP-Agent/src/conversation/workflow.py`: entity stage 改为 await，并支持唯一 Resolver 注入。
- `backend/infrastructure/chat/entity_resolution.py`: 新增 Tushare A 股 Catalog Adapter 和 TTL 正/负缓存。
- 9 处 unit/eval 直接调用：改用 async contract。
- `tests/unit/conversation/test_entity_resolution_d09.py`、entity eval：改用正式 typed model result。
- `PLAN.md` 与本报告：更新治理证据。

## 5. Implementation Summary

实体解析现在拥有唯一异步合同。当前轮优先级为显式代码、canonical name、alias、实体歧义/无实体任务、受门控继承、确定性 fuzzy、模型兜底。显式未知代码会先查本地目录，再查注入 Catalog；名称与代码冲突直接澄清且不调用模型。模型候选编排已在领域内就位，但 M2 不装配真实模型：非本地候选必须由 Catalog 回查，名称/代码/类型一致才返回 canonical entity；无结果或目录不可用均 fail closed。

Tushare Adapter 只调用 `stock_basic`，支持 DataFrame/Mapping/list 响应并在 TTL 内缓存；不读取 query、Prompt 或 token。公开 workflow 已 await Resolver，旧直接测试调用均已迁移，没有同步兼容实现。

## 6. Diff Summary

- 领域层：新增 typed 状态/端口并替换同步静态 Resolver。
- 基础设施层：新增只读 Tushare Catalog Adapter。
- 工作流/测试：只迁移 async 调用，不改外部 REST/WS/schema。
- No database, dependency, authentication, frontend, memory, Skill or interview-document changes.

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| D09 domain + entity/route/rewrite eval | 核心解析行为与下游合同 | 11 passed |
| Catalog test + affected understanding/Skill/Web News | 目录缓存和 async 迁移回归 | 43 passed, 1 deselected |
| broader conversation + contract + mainline eval | 工作流广回归 | 125 passed, 1 deselected |
| `uv run --locked ruff check ...` | 领域/Adapter/测试 lint | Passed |
| `uv run --locked pyright ...` | 跨层类型与 Protocol | 0 errors |
| `git diff --check` | 补丁空白检查 | Passed（仅 CRLF 提示） |
| dependency-direction `rg` | domain 禁止导入 backend/LangChain/Tushare | 0 matches |

## 8. Test Results

- Passed: 179 个本里程碑相关/广回归测试，Ruff/Pyright。
- Failed: 0 个 M2 门禁。
- Not run: M3 的 5 个模型 Adapter 红测、M4 的旧路径/报告红测、真实 live、完整 450 回归/Compose。
- Limitations: 生产 factory 尚未注入模型和 Tushare Catalog；这是 M3 的明确边界，不是完成状态。

## 9. Failures and Fixes

- Failure: 首次 Pyright 报 fake model 返回 `SimpleNamespace/object` 不满足 Protocol，test helper 返回类型过宽。
- Root cause: tests-first fake 尚未随正式 `EntityModelResolution` 合同收窄。
- Fix attempt: fake 改为接收 `EntityModelRequest` 并返回正式 `EntityModelResolution`；helper 返回 `EntityResolutionResult`。
- Rerun result: Pyright 0 errors，相关测试 11 passed。

## 10. Scope Compliance

- Allowed files only: Yes。
- Forbidden changes avoided: Yes。
- User changes preserved: Yes；D01 未触碰。
- Dependencies changed: No。
- API/database/config changed: No。

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
|---|---|---|
| Architecture and dependency direction | Satisfied | domain→ports；infra 实现 Catalog；依赖扫描为零 |
| Docstrings, types, field meaning, section navigation | Satisfied | 公共 Resolver/ports/contracts/Adapter 有类型与中文职责/失败说明 |
| Configuration, secrets, constants, prompts | Satisfied | M2 无新配置/Prompt；Catalog 不读取 token |
| Terminal output, logs, traces, artifacts | Satisfied | 无新增原文日志/artifact；Trace 留 M3 |
| Validation, errors, retry/fallback, state, compatibility | Satisfied | explicit invalid/conflict/grounding/ambiguity/async 均测试 |
| Tests, evaluation, and handoff evidence | Satisfied | 12-case entity eval 与 179 项结果 |

## 12. Risks Remaining

- Risk: fuzzy threshold 仅由当前小型固定集校准。
- Mitigation or follow-up: 阈值集中在 Resolver 构造参数；M5 扩大 eval/回归，未来用真实 bad cases 校准。
- Risk: Tushare 权限/真实 DataFrame 字段尚未 live 验证。
- Mitigation or follow-up: M6 protected live 必须实际执行。
- Risk: 模型异常路径尚未接入。
- Mitigation or follow-up: M3 严格 Adapter、一次 repair、Settings、Prompt 与 Trace。

## 13. PLAN.md Updates

- Progress: M2 已完成。
- Decision Log: 记录本地/动态目录分层和 fuzzy 门禁。
- Surprises & Discoveries: async 直接调用面小于预估。
- Outcomes & Retrospective: 核心领域与 Catalog 局部结果已知，整体仍待 M3-M7。

## 14. Suggested Commit Message

```text
feat(entity): add async grounded resolver core

- Add deterministic paths and typed model/catalog ports
- Validate explicit codes and model candidates against catalogs
- Migrate controlled workflow to the async contract
```

## 15. Handoff to User

Milestone 2 is complete. The active goal authorizes continued execution; M3 will add the real controlled model Adapter, Settings, versioned Prompt and resolver Trace.
