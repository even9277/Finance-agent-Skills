# MILESTONE_2_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 2 — Skill Assets, Typed Schema Gate, and Version Contract
- Status: Complete
- Date: 2026-08-26
- Branch: `feature/skills-sop-migration`

## 2. Development Standards Read

- `PLAN.md`: 已读取当前里程碑、允许路径、禁区、工程合同、检查和停止条件。
- `DEV_STANDARDS.md`: Not found。
- `AGENTS.md`: 已读取根规则；唯一主仓库、历史仓库只读、单执行器、typed contract、中文 Google-style docstring、测试先行、默认离线、无授权不 commit/push。
- nested `AGENTS.md` / `AGENTS.override.md`: Not found。
- `CLAUDE.md`: Not found。
- `.cursor/rules/*.mdc`: Not found。
- `.github/copilot-instructions.md`: Not found。
- README / contribution / test docs: 已读取 `README.md`、`CONTRIBUTING.md` 的架构、测试入口、Compose/live 和回滚规则。
- Personal Python/Agent standard: 已读取并应用类型、文档、分层、错误、日志、秘密和测试要求。

## 3. Files Inspected

- `Financial-MCP-Agent/src/skills/skill_registry.py`: 确认当前薄 Registry、asset 发现与兼容读取方式；本轮不接入新 gate。
- 五类现有 `SKILL.md` / `skill_spec.yaml` / references / cases: 确认四层资产缺口。
- `Financial-MCP-Agent/src/conversation/tool_governance.py`: 以当前 15 个只读工具作为权限上界。
- `Financial-MCP-Agent/src/conversation/contracts.py`: 确认证据维度和本轮不修改对话合同。
- `tests/contract/test_skill_assets_v2_contract.py`、`tests/unit/skills/test_skill_runtime_contract.py`: 读取冻结验收合同。
- 历史 `D:/FinanceProject/Finance/Financial-MCP-Agent/src/skills/**`: 只读提取五类 SOP 内容、references 和 cases。
- 历史 `src/skills_v2/{schema_gate,version,lifecycle}.py`: 只读评估可复用边界；未建立 runtime import。

## 4. Files Modified

- `Financial-MCP-Agent/src/skills/{contracts,schema_gate,version,lifecycle}.py`: 新增 typed spec、fail-closed gate、稳定哈希/SemVer 和生命周期状态机。
- `Financial-MCP-Agent/src/skills/__init__.py`: 只导出本轮治理合同。
- 五类 Skill 的 `SKILL.md` / `skill_spec.yaml`: 补齐统一十章节、路由/input/工具/步骤/证据/output/degrade/version 合同。
- 五类 Skill 的 `references/*.md`: 补齐可分阶段读取的 frontmatter、来源说明、tags 和 evidence types。
- 五类 Skill 的 `tests/cases.md`: 补齐正例、反例、缺槽位、降级和安全边界样例。
- `tests/unit/skills/test_schema_gate.py`: 新增五类目录通过及未知工具/证据、名称/章节、坏 reference 的 fail-closed 测试。
- `tests/unit/skills/test_skill_version.py`: 新增换行、mapping 顺序、SemVer 与历史标签测试。
- `tests/unit/skills/test_skill_lifecycle.py`: 新增激活、回滚、弃用复活和未知状态测试。
- `docs/specs/skills-sop-migration/PLAN.md`: 更新进度、决策、发现和结果。
- `docs/specs/skills-sop-migration/MILESTONE_1_EXECUTION_REPORT.md`: 归档上一里程碑报告。
- `docs/specs/skills-sop-migration/MILESTONE_EXECUTION_REPORT.md`: 当前报告。

未修改 Registry snapshot/Loader、conversation 主链、API、前端、配置、依赖或数据库。

## 5. Implementation Summary

五类金融 SOP 现在都具备完整四层资产：人类说明、机器 spec、分阶段 references 和回归 cases。机器合同使用冻结 Pydantic model，拒绝未知字段并验证 SemVer、章节映射、工具依赖、计划步骤、证据、输出、降级链、并发边界和 Web News 权限一致性。

`validate_skill_directory` 会读取未信任 YAML/frontmatter，做目录身份、权限交集、证据类型、reference metadata 和 resolved-path containment 校验；任一问题返回 `disabled` 报告而不是部分启用。报告只包含低敏错误码和内容哈希，不保存资产正文。

历史资产只作为内容证据使用。旧 `skills_v2` 松散字典 gate 和旧 Runtime 没有被 import；reference 的旧 Skill 名阶段已改为 `rewrite/planner/synthesis`，为下一里程碑最小权限 Loader 建立边界。

## 6. Diff Summary

- Architecture: 新治理职责只位于 `src.skills`，当前生产 Registry 尚未切换。
- Assets: 五个 Skill 的工具、证据、reference、输出与降级声明闭合。
- Tests: 新增 11 项 schema/version/lifecycle unit case；上一里程碑 10 项资产合同全部转绿。
- No files outside the current milestone scope were modified。

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
| --- | --- | --- |
| `uv run --locked pytest tests/contract/test_skill_assets_v2_contract.py tests/unit/skills/test_schema_gate.py tests/unit/skills/test_skill_version.py tests/unit/skills/test_skill_lifecycle.py Financial-MCP-Agent/src/skills/fund-compare/tests/test_fund_compare_p1.py -q` | 资产/gate/version/lifecycle/P1 focused | `27 passed, 2 deselected` |
| `uv run --locked ruff check <changed modules/tests>` | 新维护范围 lint | `All checks passed` |
| `uv run --locked pyright <changed modules/tests>` | typed contract/type check | `0 errors, 0 warnings` |
| `uv run --locked pytest tests/contract/test_skill_catalog_contract.py ... tests/e2e/test_controlled_chat_chain.py -q` | 既有 catalog/理解/治理/唯一主链回归 | `21 passed` |
| `uv run --locked pytest tests/evals/skill_activation tests/evals/route tests/evals/rewrite tests/evals/planner -q -m "eval_smoke and not live"` | 既有离线 eval | `5 passed` |
| `uv lock --check` | 确认无依赖变化 | passed |
| `uv run --locked python -m pytest <Milestone 1 target matrix> -q` | 检查红灯只剩后续里程碑 | `16 passed, 10 expected failed` |
| `rg` history-runtime/secret scan | 禁止历史依赖和敏感值 | no matches |
| `validate_skill_directory` hash smoke | 五 Skill 状态和版本指纹 | 5 active |

## 8. Test Results

- Passed: 27 focused；21 existing mainline；5 existing eval；Ruff、Pyright、lock 和安全扫描。
- Expected failed: 10 个冻结目标测试，分别属于 Milestone 3 的 snapshot/reference/loader（5）、Milestones 4/7 的 public confirm/multi-task（4）和 Milestone 8 的 eval runner（1）。
- Not run: 全量 root、frontend、Compose 和 live；本轮没有触及对应运行面，最终 Milestone 9 统一执行。
- Limitations: `search_web_news` 本轮只是已批准资产权限和弱证据声明，尚未进入治理目录或真实 Provider。

## 9. Failures and Fixes

- Failure: 首次 Pyright 报告降级目标可能含 `None`，Pydantic error location 为通用 `object`。
- Root cause: 静态类型收窄不足，运行逻辑未失败。
- Fix attempt: 用显式循环构造 `set[str]`，并对 error location 做 tuple/list type guard。
- Rerun result: Pyright `0 errors`，focused tests 仍为 `27 passed`。

- Failure: 直接 `uv run --locked pytest <target matrix>` collection 时找不到 `backend`。
- Root cause: Windows/uv script 入口没有把仓库根加入 `sys.path`。
- Fix attempt: 按仓库规范改用 `uv run --locked python -m pytest`，不修改代码或测试。
- Rerun result: 正常收集，`16 passed, 10 expected failed`。

## 10. Scope Compliance

- Allowed files only: Yes。
- Forbidden changes avoided: Yes。
- User changes preserved: Yes。
- Dependencies changed: No。
- API/database/config changed: No。
- Commit/push/PR: No。

## 11. Engineering Contract Compliance

| Category | Result | Evidence |
| --- | --- | --- |
| Architecture and dependency direction | Satisfied | 新合同位于 `src.skills`；无旧 Runtime import；未改唯一 Executor |
| Docstrings, types, field meaning, section navigation | Satisfied | Pydantic/frozen dataclass/Enum；公共接口中文 docstring；十章节资产 |
| Configuration, secrets, constants, prompts | Satisfied | 无配置/依赖/Prompt 变化；治理常量留在代码；secret scan 无命中 |
| Terminal output, logs, traces, artifacts | Satisfied | gate 不写日志或正文，只返回 status/error code/hash；hash smoke 脱敏 |
| Validation, errors, retry/fallback, state, compatibility | Satisfied | unknown tool/evidence/frontmatter/path fail closed；生命周期有限状态机；旧 Registry 未切换 |
| Tests, evaluation, and handoff evidence | Satisfied | focused/static/existing regression/target matrix 均记录实际结果 |

## 12. Hash Samples

```text
stock-first-pass       active spec=42beafad16ba doc=905079278df0 refs=377b6fd7aab1
fund-compare           active spec=1d71755b4519 doc=427b51ccb102 refs=2ebc7a0317e4
etf-screen             active spec=37dfd88f9d14 doc=18a08e50875d refs=ba36239358af
sector-hotspot-brief   active spec=bef9617ce4fe doc=7f8624355455 refs=59bac3a9638d
market-move-explain    active spec=3ef5d7ed1c9b doc=be2398feba66 refs=d92cece4475a
```

## 13. Risks Remaining

- 新 gate 尚未由生产 Registry 调用；Milestone 3 完成前，旧 Registry 仍可读取松散 YAML。
- reference resolved-path containment 已实现并对格式错误 fail closed；真实分阶段索引与 token budget 尚待 Milestone 3。
- Web News 只存在资产合同，执行、超时、限流、内容安全和弱证据流仍待 Milestone 6。

## 14. PLAN.md Updates

- Progress: Milestone 2 marked complete with exact evidence。
- Decision Log: 记录 typed gate 重写、reference 阶段统一和 Web News 资产边界。
- Surprises & Discoveries: 记录历史 gate 覆盖不足及 Windows pytest 入口差异。
- Outcomes & Retrospective: 更新为 5 active、16 green/10 future red 的当前状态。

## 15. Suggested Commit Message

```text
feat(skills): add typed SOP asset governance

- complete five financial Skill asset layers
- add schema, version and lifecycle contracts
- verify focused tests and existing mainline regressions
```

## 16. Handoff to User

Milestone 2 is complete. I will not proceed to the next milestone unless you explicitly ask me to continue.
