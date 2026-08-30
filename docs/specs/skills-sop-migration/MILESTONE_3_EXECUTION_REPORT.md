# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 3 — Registry Snapshot, LKG, Reference Index, and Stage Loader
- Status: Complete
- Date: 2026-08-26
- Branch: `feature/skills-sop-migration`

## 2. Development Standards Read

- `PLAN.md`: 已读取当前里程碑、允许范围、禁区、接口、工程合同、验证与回滚要求。
- `DEV_STANDARDS.md`: Not found。
- `AGENTS.md`: 已读取；唯一主仓库、历史仓库只读、单执行器、typed interface、中文 Google-style docstring、测试先行、默认离线、无授权不 commit/push。
- nested `AGENTS.md` / `AGENTS.override.md`: Not found。
- `CLAUDE.md`: Not found。
- `.cursor/rules/*.mdc`: Not found。
- `.github/copilot-instructions.md`: Not found。
- README / contribution / test docs: 已读取现有架构、`python -m pytest`、Compose/live、交付与回滚规则。
- Personal Python/Agent standard: 已读取并应用模块边界、类型、文档、错误、日志、秘密、状态与测试要求。

## 3. Files Inspected

- `Financial-MCP-Agent/src/skills/{contracts,schema_gate,version,lifecycle,skill_registry}.py`: 当前 typed Gate 和薄 Registry。
- `Financial-MCP-Agent/src/conversation/contracts.py`: 现有 `SkillCatalogSnapshot` 四类渐进视图和兼容要求。
- `backend/application/chat/factory.py`: 确认当前只向 Workflow 注入 conversation facade，暂不越界装配 Loader。
- `tests/contract/test_skill_catalog_contract.py`、`Financial-MCP-Agent/test_skill_registry.py`: 旧 catalog/vendor 兼容合同。
- `tests/unit/skills/test_skill_runtime_contract.py`: 冻结 snapshot/reference/loader 目标接口。
- 历史只读 `D:/FinanceProject/Finance/Financial-MCP-Agent/src/skills_v2/{snapshot,reference_index,loader}.py`: 对照职责边界；未复制旧 Runtime 或建立 import。

## 4. Files Modified

- `Financial-MCP-Agent/src/skills/snapshot.py`: 新增自包含不可变 entry、稳定 snapshot hash、pending/active/LKG 原子管理。
- `Financial-MCP-Agent/src/skills/reference_index.py`: 新增 typed reference item、realpath/identity containment、stage hard filter、词法排序和 token budget。
- `Financial-MCP-Agent/src/skills/loader.py`: 新增请求固定 Loader、rewrite/planner/synthesis typed views、章节投影和脱敏 artifact。
- `Financial-MCP-Agent/src/skills/skill_registry.py`: 组合 Gate/Index/Snapshot/Loader；五类 SOP all-or-nothing 发布；刷新失败保留 active；vendor facade 兼容。
- `Financial-MCP-Agent/src/skills/contracts.py`: 集中金融 SOP 支持的 evidence type 集合。
- `Financial-MCP-Agent/src/skills/__init__.py`: 导出本里程碑治理边界。
- `Financial-MCP-Agent/src/conversation/contracts.py`: 保持旧 facade 版本，增量携带 Registry/spec/document/reference hashes。
- `tests/unit/skills/test_snapshot_lifecycle.py`: 首次 fail closed、请求固定、并发原子读、刷新失败 LKG。
- `tests/unit/skills/test_reference_index.py`: 阶段/身份/path containment、词法、预算、hash。
- `tests/unit/skills/test_loader.py`: 三视图隔离、redacted artifact、刷新前后请求固定、预算失败。
- `docs/specs/skills-sop-migration/PLAN.md`: 更新进度、决策、发现和结果。
- `docs/specs/skills-sop-migration/MILESTONE_2_EXECUTION_REPORT.md`: 归档上一里程碑报告。
- `docs/specs/skills-sop-migration/MILESTONE_EXECUTION_REPORT.md`: 当前报告。

未修改路由、Rewrite、Planner、Executor、API、Frontend、配置、依赖或数据库。

## 5. Implementation Summary

Registry 现在先扫描保持原有 vendor→workspace precedence，再把五类 workspace SOP 逐个 join 到 typed Gate 与 ReferenceIndex。只有所有资产都通过时，才生成自包含 `RegistrySnapshot` 并在锁内一次性从 pending 切换为 active/LKG；任一 Skill 失败都拒绝整批候选，旧 active 对象和请求已固定对象保持不变。

每个快照 entry 固定 typed spec、SKILL Markdown、reference 内容索引、工具白名单和三类内容 hash，因此刷新成功后旧请求不会回读新磁盘内容。`conversation_snapshot()` 保留 `workspace-skills-v1` 兼容版本，同时携带内部 Registry version/hash 和每个 Skill 的 spec/document/reference hash。

ReferenceIndex 先验证 resolved path 仍位于当前 Skill 的 `references` 目录，再执行 `skill_id + stage` 强过滤。词法匹配只决定同阶段文档的顺序，不能改变身份、阶段或权限；总正文使用保守字符预算。Loader 的 artifact 只保存路径、内容 hash、阶段、section hash 和预算，不保存正文或用户 query。

## 6. Diff Summary

- Snapshot: 自包含、不可变、稳定哈希、原子 pending/active/LKG。
- Registry: 完整候选发布，失败保留旧状态，默认无 watcher/DB/分布式锁。
- Reference: resolved containment、跨 Skill/跨阶段拒绝、词法与预算。
- Loader: rewrite 无工具；planner 有已校验工具/步骤/证据；synthesis 有输出/降级且无工具计划。
- Compatibility: 旧 `conversation_snapshot()`、vendor metadata/reference API 继续可用。
- No files outside the current milestone scope were modified。

## 7. Tests / Checks Run

| Command / Method | Purpose | Result |
| --- | --- | --- |
| `uv run --locked python -m pytest tests/unit/skills/test_snapshot_lifecycle.py tests/unit/skills/test_reference_index.py tests/unit/skills/test_loader.py tests/unit/skills/test_skill_runtime_contract.py tests/contract/test_skill_catalog_contract.py Financial-MCP-Agent/test_skill_registry.py -q` | Snapshot/LKG/reference/loader/concurrency/catalog/vendor | `24 passed` |
| `uv run --locked ruff check <changed modules/tests>` | 新维护范围 lint | `All checks passed` |
| `uv run --locked pyright <changed modules/tests>` | typed boundary check | `0 errors, 0 warnings` |
| `uv run --locked python -m pytest <Milestone 2 focused> -q` | Gate/asset/version/lifecycle regression | `27 passed, 2 deselected` |
| `uv run --locked python -m pytest <catalog/understanding/governance/E2E> -q` | 既有唯一主链回归 | `21 passed` |
| `uv run --locked python -m pytest tests/evals/{skill_activation,route,rewrite,planner} ...` | 既有离线 eval | `5 passed` |
| `uv lock --check` | 确认无依赖变化 | passed |
| `uv run --locked python -m pytest <Milestone 1 target matrix> -q` | 检查 M3 红灯转绿范围 | `21 passed, 5 expected failed` |
| Registry + `load_for_rewrite/planner/synthesis` Python smoke | 具体加载调用与安全摘要 | passed |
| `git diff --check`、history import/secret/trailing-space scans | scope/安全/格式 | passed / no matches |

## 8. Test Results

- Passed: 24 focused；27 previous focused；21 existing mainline；5 existing eval；Ruff、Pyright、lock、安全扫描和具体 Loader smoke。
- Expected failed: 5 个冻结目标测试——public explicit skill、typed confirmation、Web News governance、多任务 Rewrite 和 `skills_sop` eval runner，均属于 Milestones 4/6/7/8。
- Not run: root full、frontend、Compose、protected live；本轮未触及相应运行面，Milestone 9 统一执行。
- Limitations: 当前 factory 仍只传 conversation facade；Workflow 消费 Loader 属于 Milestones 4-5。

## 9. Failures and Fixes

- Failure: 首次 Ruff/Pyright 报告 Loader 未使用 import，且完整性检查没有把 `reference_index` 收窄为非空。
- Root cause: 静态类型信息未从防御性检查传回调用点。
- Fix attempt: `_require_complete_entry` 返回 `(SkillSpec, ReferenceIndex)` 并删除未使用 import。
- Rerun result: Ruff passed，Pyright `0 errors`，focused `24 passed`。

- Failure: 第一次具体 Loader smoke 的内嵌 f-string 在 PowerShell/Python 引号边界产生 SyntaxError。
- Root cause: 命令行转义错误，业务代码未执行。
- Fix attempt: 改用 `.format()` 且不修改代码。
- Rerun result: 成功输出 Registry 和三阶段安全摘要。

## 10. Concrete Loader Smoke

```text
registry=registry-v2-e58213b8651c hash=e58213b8651c7b26
active=('etf-screen', 'fund-compare', 'market-move-explain', 'sector-hotspot-brief', 'stock-first-pass')
rewrite   spec_keys=(input_contract, route_metadata)                         tokens=806/4096
planner   spec_keys=(allowed_tools, tool_plan_steps, required_evidence, ...) tokens=881/4096
synthesis spec_keys=(output_template, degrade_policy, required_evidence)     tokens=1005/4096
```

三个阶段分别加载 4/3/3 个允许章节；reference artifact 均包含相对路径与 `content_hash`，不含正文。Windows 终端中文路径显示乱码只是 code page 展示，UTF-8 读取、hash 和测试正常。

## 11. Scope Compliance

- Allowed files only: Yes。
- Forbidden changes avoided: Yes。
- User changes preserved: Yes；上一里程碑资产作为当前明确输入继续组合。
- Dependencies changed: No。
- API/database/config changed: No。
- Commit/push/PR: No。

## 12. Engineering Contract Compliance

| Category | Result | Evidence |
| --- | --- | --- |
| Architecture and dependency direction | Satisfied | Registry 组合 Gate/Index/Snapshot/Loader；无第二 Executor、无历史 Runtime import |
| Docstrings, types, field meaning, section navigation | Satisfied | frozen dataclass/Pydantic/Literal；公共接口中文 docstring；Pyright 通过 |
| Configuration, secrets, constants, prompts | Satisfied | 无配置/依赖/Prompt 改动；稳定阶段/预算规则留在代码 |
| Terminal output, logs, traces, artifacts | Satisfied | Registry 参数化低基数日志；Loader artifact 无正文/query；hash/version 可定位 |
| Validation, errors, retry/fallback, state, compatibility | Satisfied | 首启 fail closed、all-or-nothing、LKG、请求固定、containment、stage/budget、旧 facade |
| Tests, evaluation, and handoff evidence | Satisfied | focused/static/regression/target matrix/concrete smoke 全部记录实际结果 |

## 13. Risks Remaining

- 受控 Workflow 尚未持有 Registry/Loader；后续必须在唯一主链装配，不能重新读磁盘或创建第二 Runtime。
- `search_web_news` 仍只是资产声明；治理 policy、Provider、失败分类与弱证据流待 Milestone 6。
- 当前字符预算是默认离线、偏保守估算，不等于特定模型 tokenizer；已保证不超内部预算，但后续可通过配置化模型预算优化。

## 14. PLAN.md Updates

- Progress: Milestone 3 marked complete with exact evidence。
- Decision Log: 记录自包含快照、all-or-nothing、stage-first reference 和兼容 hash facade。
- Surprises & Discoveries: 记录 factory 装配缺口、历史 section-map 不兼容和终端 code page。
- Outcomes & Retrospective: 更新为 21 green/5 future red 和具体 Loader smoke。

## 15. Suggested Commit Message

```text
feat(skills): add atomic registry and stage loader

- publish validated snapshots with last-known-good fallback
- isolate reference retrieval by skill, stage and budget
- preserve catalog and vendor compatibility
```

## 16. Handoff to User

Milestone 3 is complete. I will not proceed to the next milestone unless you explicitly ask me to continue.
