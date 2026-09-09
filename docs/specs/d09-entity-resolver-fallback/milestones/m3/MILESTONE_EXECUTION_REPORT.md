# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: 3 — Controlled Model Adapter, Repair, Settings, Prompt, and Trace
- Status: Complete
- Date: 2026-09-09

## 2. Development Standards Read

- `PLAN.md`: 已读取 M3 目标、允许文件、检查与停止条件。
- `AGENTS.md` 与 Python/Agent engineering standard: 已应用集中 Settings、Prompt 版本化、typed Port/Adapter、有界重试、低敏 Trace 和 tests-first。
- README / contribution / test docs: 沿用前序里程碑已读取规则。

## 3. Files Inspected

- `backend/infrastructure/chat/providers.py`: 对齐现有 OpenAI-compatible 客户端配置。
- `backend/application/chat/factory.py`: 确认生产依赖装配点。
- `Financial-MCP-Agent/src/prompts/chat/registry.py`: 对齐版本化 Prompt 读取方式。
- workflow/trace/tests/config/.env.example: 确认外部合同、可观测字段和安全配置边界。

## 4. Files Modified

- `backend/infrastructure/chat/entity_resolution.py`: strict model Adapter、一次 syntax repair、Tushare Catalog、stable errors 和 symbol normalization。
- `Financial-MCP-Agent/src/prompts/chat/{entity_resolution_v1,entity_resolution_repair_v1}.md` 及 registry: 版本化候选与修复 Prompt。
- `backend/config.py`、`backend/.env.example`: timeout、repair、catalog TTL、fuzzy 门禁配置。
- `backend/application/chat/factory.py`: 注入模型、Catalog 和确定性阈值。
- conversation contracts/errors/workflow 与 trace test: 记录 path、model calls、repair count、catalog status。
- D09 adapter/live/factory tests 与本计划报告。

## 5. Implementation Summary

模型只在确定性链路未命中时提出最多三个候选。输出必须满足 `entity-resolution-v1` 严格 envelope，额外字段、类型或版本错误立即失败；只有 JSON tokenizer/parser 语法错误允许一次格式修复。模型 SDK 自动重试关闭，单次调用有 timeout，整轮调用预算最大为 2。候选仍必须由领域 Resolver 经过本地/外部 Catalog 验证代码、名称和类型后才能确认。

Trace 只记录低敏枚举和计数：`resolver_path`、`model_calls`、`repair_count`、`catalog_status`、候选数和置信度，不记录查询原文、模型原始响应、Token 或 Authorization。生产配置统一从 typed Settings 读取。

## 6. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| D09 model/catalog/domain/trace focused suites | strict schema、repair、timeout、grounding、trace | 27 passed |
| `tests/unit/conversation tests/evals -m "not live"` | 对话与评测广回归 | 154 passed, 1 deselected |
| `uv run --locked ruff check ...` | 变更文件 lint | Passed |
| `uv run --locked pyright ...` | Adapter/Protocol/配置类型 | 0 errors |
| `git diff --check` | 补丁空白检查 | Passed（仅 CRLF 提示） |
| source/secret logging scan | 自动重试与敏感输出检查 | `max_retries=0`；无 query/response/secret 日志 |

## 7. Failures and Fixes

- Pyright initially rejected the provider client protocol and broad test imports. The Adapter now casts the SDK to a minimal async protocol and tests import typed implementations directly; rerun produced 0 errors.
- Initial symbol normalization uppercased `sector:`. A canonical normalization helper now preserves the lowercase domain prefix; the new sector regression passes.

## 8. Scope Compliance

- Allowed files only: Yes。
- Interview documents changed: No。
- User D01 file touched/staged: No。
- Dependencies, database, auth, frontend, memory or Skill behavior changed: No。

## 9. Risks Remaining

- 报告和 CLI 仍调用旧解析实现；M4 必须整体迁移并删除旧路径，不能形成双轨。
- Tushare 和真实模型兼容性尚需 M6 protected live 证明，skip 不算验收。
- 当前 factory 每请求构建 Catalog，M4 迁移时需把共享 Resolver 装配收敛到进程级入口，才能让 TTL 缓存跨请求生效。

## 10. PLAN.md Updates

- Progress: M3 complete。
- Decision Log: strict schema、syntax-only repair、zero SDK retry。
- Discoveries: 修复板块 canonical prefix；记录进程级装配待 M4 收敛。

## 11. Handoff

M3 is complete. M4 will migrate report/tools/CLI to one process-level shared Resolver, fail closed before report fan-out, and delete the old Prompt/regex paths.
