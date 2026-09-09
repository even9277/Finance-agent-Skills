# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: 1 — Lock Tests and Reproduction
- Status: Complete（tests-first 红测已按预期建立）
- Date: 2026-09-08

## 2. Development Standards Read

- `PLAN.md`: 已按 M1 允许范围仅修改 tests/eval/live harness 与本报告。
- `DEV_STANDARDS.md`: 未提供独立文件。
- `AGENTS.md`: 已读取；本里程碑遵循 tests-first、默认无外呼和单主线要求。
- nested `AGENTS.md` / `AGENTS.override.md`: 未发现。
- `CLAUDE.md`: 未发现。
- `.cursor/rules/*.mdc`: 未发现。
- `.github/copilot-instructions.md`: 未发现。
- README / contribution / test docs: 已读取 `README.md`、`CONTRIBUTING.md`、`tests/evals/README.md`。

## 3. Files Inspected

- `Financial-MCP-Agent/src/conversation/entity.py`: 对齐当前同步静态实现与红测缺口。
- `Financial-MCP-Agent/src/conversation/contracts.py`: 冻结现有 Entity/Result 外部消费字段。
- `Financial-MCP-Agent/src/conversation/ports.py`: 确认模型/Catalog ports 尚不存在。
- `Financial-MCP-Agent/src/conversation/workflow.py`: 确认实体阶段当前同步调用且 Trace 字段不足。
- `backend/services/stock_resolver.py`: 确认 inline Prompt、宽松 JSON、散落 getenv 和 LLM-only 路径。
- `backend/services/agent_service.py`: 确认未识别实体仍继续 fan-out，且保留 deprecated regex。
- `tests/evals/entity/**`: 确认原 7 条 case 仅覆盖静态行为。
- `tests/e2e/test_live_controlled_chat_chain.py`: 确认原 live 只覆盖显式代码，不触发 fallback。
- `tests/unit/report/test_report_service_progress.py`: 复用报告任务 failure/persistence harness。

## 4. Files Modified

- `tests/unit/conversation/test_entity_resolution_d09.py`: 新增 8 个领域红测。
- `tests/unit/conversation/test_entity_resolution_adapters_d09.py`: 新增 6 个模型/Catalog Adapter 红测。
- `tests/contract/test_entity_resolution_single_path_contract.py`: 新增旧路径删除静态合同。
- `tests/unit/report/test_report_entity_resolution_d09.py`: 新增报告未确认实体拒绝合同。
- `tests/unit/report/test_report_service_progress.py`: 增加 workflow-start 审计与解析异常不 fan-out 用例。
- `tests/evals/entity/test_entity_eval.py`: 改为 async、可注入 fake model/catalog，并断言路径/预算/错误码。
- `tests/evals/entity/data/smoke.jsonl`: 从 7 条扩为 12 条，加入 typo、非法代码、长尾、幻觉和名称代码冲突。
- `tests/e2e/test_live_controlled_chat_chain.py`: 增加 D09 真实长尾 case 与 resolver path/catalog 断言。
- `docs/specs/d09-entity-resolver-fallback/PLAN.md`: 更新 M1 进度、决策和发现。
- `docs/specs/d09-entity-resolver-fallback/milestones/m1/MILESTONE_EXECUTION_REPORT.md`: 本报告。

## 5. Implementation Summary

本里程碑没有修改生产代码。测试已把 D09 的核心工程合同变成可执行断言：唯一 async Resolver；确定性 exact/fuzzy 不调用模型；长尾模型候选必须目录确认；幻觉、显式非法代码和名称—代码冲突 fail closed；模型 Adapter 仅对 JSON syntax 做一次 repair；Tushare Catalog canonicalize + TTL cache；报告解析失败不启动工作流；生产调用方最终不能保留私有 Resolver；live 从真实 WebSocket 产品入口用“隆基绿能”触发 model fallback + Tushare。

## 6. Diff Summary

- 所有行为变更均位于 M1 允许的测试、eval 和 live harness。
- 既有报告测试 helper 只增加 `started` 审计和可注入初始状态异常，不改变被测生产行为。
- 未修改生产实现、依赖、数据库、API、`.env`、面试文档或用户 D01 文件。

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
|---|---|---|
| `python -m py_compile`（4 个新增测试文件） | 语法检查 | Passed |
| D09 focused tests + report progress | 红测与既有 safety harness | 16 expected failed, 5 passed |
| `uv run --locked pytest tests/evals/entity -q` | 新 eval 红测 | 1 expected failed：Resolver 不支持 model/catalog 注入 |
| `uv run --locked python -m pytest tests/unit/report/test_report_service_progress.py -q` | 报告既有行为保护 | 5 passed |
| `uv run --locked python -m pytest tests/e2e/test_live_controlled_chat_chain.py --collect-only -q -m live` | live case 可收集 | 3 collected |
| `uv run --locked ruff check <M1 changed tests>` | 测试代码质量 | All checks passed |
| `git diff --check` | 空白/补丁检查 | Passed（仅 CRLF 提示） |

## 8. Test Results

- Passed: 既有报告 safety 5 项；M1 Ruff；Python syntax；3 个 live cases 收集。
- Failed: 16 个 D09 focused 行为断言和 1 个 entity eval 均按预期在旧实现上失败。
- Not run: 真实 live（M6 执行）；全量回归（生产实现前继续以 M0 为 baseline）。
- Limitations: 红测阶段不要求 suite green；失败必须在 M2-M4 按职责逐步收敛。

## 9. Failures and Fixes

- Failure: 单独用 `uv run pytest tests/unit/report/...` 出现 `ModuleNotFoundError: backend`。
- Root cause: Windows 控制台 `pytest.exe` 的 sys.path 与仓库贡献指南要求的 module invocation 不一致；并非生产或测试代码缺陷。
- Fix attempt: 改用 `uv run --locked python -m pytest`。
- Rerun result: 5 passed。

## 10. Scope Compliance

- Allowed files only: Yes。
- Forbidden changes avoided: Yes。
- User changes preserved: Yes。
- Dependencies changed: No。
- API/database/config changed: No。

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
|---|---|---|
| Architecture and dependency direction | Satisfied | tests 明确 domain ports、infra adapters、thin report adapter 和 single-path |
| Docstrings, types, field meaning, section navigation | Satisfied | 新测试 helper/contract 均有类型与中文责任说明 |
| Configuration, secrets, constants, prompts | Satisfied | live 复用既有门禁；未读取或记录 secrets |
| Terminal output, logs, traces, artifacts | Satisfied | live 只断言低敏 path/calls/catalog；无新原文 artifact |
| Validation, errors, retry/fallback, state, compatibility | Satisfied | syntax/semantic、预算、grounding、fan-out、冲突均有测试 |
| Tests, evaluation, and handoff evidence | Satisfied | 12-case eval 与真实产品入口 case 已落盘 |

## 12. Risks Remaining

- Risk: M2 async 迁移会使旧同步单测需要机械更新。
- Mitigation or follow-up: 只改直接调用 Resolver 的测试；workflow 消费者由 await 统一处理。
- Risk: live 断言目前与旧 trace schema 不兼容。
- Mitigation or follow-up: M3 增加低敏字段，M6 实际验证非 skip。

## 13. PLAN.md Updates

- Progress: M1 已完成。
- Decision Log: 冻结 async constructor/ports 与 `entity-resolution-v1` envelope。
- Surprises & Discoveries: 记录 Windows pytest invocation 差异。
- Outcomes & Retrospective: 仍待实现/验收。

## 14. Suggested Commit Message

```text
test(entity): lock d09 resolver fallback contracts

- Add deterministic, model grounding and failure cases
- Add report fan-out and single-path guards
- Add protected long-tail live scenario
```

## 15. Handoff to User

Milestone 1 is complete. The active goal authorizes continued execution; the next isolated milestone is M2 shared async deterministic Resolver and Catalog contract.
