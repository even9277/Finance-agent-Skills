# Milestone 8 Execution Report

## 1. Milestone Identity

- Milestone: 8 — Observability and Reproducible Evaluation
- Branch: `feature/skills-sop-migration`
- Completed: 2026-08-30
- Execution policy: exactly one frozen milestone；未 commit、push、PR，未进入 Milestone 9。
- Previous report: `MILESTONE_7_EXECUTION_REPORT.md`

## 2. Frozen Contract

从 route 到 synthesis 记录可定位到具体 Skill 资产版本的低基数 trace；Reference 只记录独立 path/hash，Web Search 只记录 query hash 与来源计数，不记录原始 query、用户消息、证据正文、模型回答或 secret。新增真实离线 `skills_sop` runner，通过生产 `ControlledChatUseCase → ControlledConversationWorkflow → SkillRegistry/Loader → 唯一 Planner/Executor/Verifier/Synthesis` 链路执行 15-case 数据集并重复三次，固化 dataset/runner/Registry/tool/provider/repeat 元数据，生成 activation、plan、evidence、clarification、claim 与 overclaim 指标。历史 75×3 指标必须单列为未复现。禁止接入真实 Langfuse、真实模型、生产流量、新依赖或第二执行器。

## 3. Implementation Outcome

### 3.1 Route-to-synthesis version chain

- Workflow 复用既有 `EventAttribute`、`SkillTraceSink` 与递归脱敏器，没有新增 exporter 或第二 trace 通道。
- Route 事件记录 route family/confidence/band/source、selected Skill/version、Registry snapshot hash，以及有界候选数量/名称。
- Permission 事件继续记录工具数量和权限 hash，并补充 selected Skill/version/spec hash/Registry hash；Planner Reference 使用独立 `planner_reference_N_path/hash` 字段。
- Plan 事件记录 plan/spec hash、Web Search 是否触发、步骤数以及规范化 query 的 SHA-256；不写 raw query。
- Verify 事件记录 accepted evidence、claim level、score，以及 Web 来源、accepted/rejected Web evidence 计数。
- Synthesis 事件记录 selected Skill/version/spec/Registry hash、claim/degrade，以及独立 synthesis Reference path/hash。
- 非法显式 Skill 的 route 事件也保留安全的 route source 与 Registry 身份，便于证明失败发生在权限/工具之前。

### 3.2 Real reproducible evaluator

- `tests/evals/runner.py` 注册 `skills_sop` target，并新增范围为 1–10 的 `--repeat`；其他既有 eval target 的行为不变。
- `tests/evals/skills_sop/runner.py` 使用真实应用/Workflow/Registry/Loader 和确定性 FakeModel/FakeTool，逐 case 计算路由、选择、状态、澄清、计划工具、accepted evidence、claim level 及 gold 对比。
- records artifact 不包含 user message、模型答案、证据事实、session/trace id；动态时间戳和运行期标识不参与可复现 hash。
- runner 原子写入 `skills_sop_records.jsonl` 和 `skills_sop_metrics.json`；metadata 固化 dataset/version/hash、runner version、Registry snapshot hash、tool schema、provider/model/tool、repeat、Git commit、records hash 与 reproducibility hash。
- CI 现有 Ruff/Pyright 命令均显式纳入 `Financial-MCP-Agent/src/skills`，没有改变 job 语义或依赖。

### 3.3 Documentation alignment

- eval README 增加可复制的 `skills_sop --repeat 3` 命令、artifact 说明与历史指标限制。
- 实现矩阵同步实际低基数字段、Reference/Web 安全边界、15×3 新基线、Langfuse/live 限制，以及 M5–M7 已落地事实。

## 4. Concrete Trace Evidence

### Stock first-pass sample

| Stage | Safe observed attributes |
| --- | --- |
| route | `financial-sop / confidence=1 / band=high / source=explicit / stock-first-pass@1.0.0 / registry hash / bounded candidate` |
| permission | 6 tools；permission/spec/registry hash；Planner Reference `references/财务与风险口径.md` + `658d…225f` |
| plan | 6 steps；spec hash；`web_search_triggered=false` |
| verify | 6 accepted；`claim_level=ANALYTICAL`；score 100；Web counts 0 |
| synthesis | Skill/version/spec/registry；`claim_level=ANALYTICAL`；`degrade=primary`；同一 Reference path/hash |

### Web News sample

- Plan: `web_search_triggered=true`、1 个 Web step、`web_search_query_hash=7a726f5dc1f550eb2c5522992c65271fb9ad5425fbf15849c1a4da3f98167ab8`。
- Verify: `web_source_count=1`、`accepted_web_evidence_count=1`、`rejected_web_evidence_count=0`。
- Redaction assertions: 原始 query 不在 trace；Web title 不在 trace；测试 secret 不在 trace。

实际 JSONL 样本位于忽略目录：

- `tests/evals/_runs/m8-trace-sample-20260830/test_skill_trace_links_route_a0/skill-version-chain.jsonl`
- `tests/evals/_runs/m8-trace-sample-20260830/test_web_news_trace_records_qu0/web-search-summary.jsonl`

## 5. Reproducible Baseline

执行 15 个 smoke case，每个重复 3 次，共 45 条 prediction：

| Metadata | Value |
| --- | --- |
| dataset | `skills-sop-smoke-v1` |
| dataset hash | `a6d0fece133349b113a1c73f5ff7d3c80ac9e56f1bcc736758773dc48c223786` |
| runner | `skills-sop-eval-v1` |
| Registry snapshot hash | `e58213b8651c7b26758f63d6d41d2711f9c42a67d835e4ba7f6e9b9481891165` |
| tool schema | `controlled-read-tools-v2` |
| provider | deterministic `FakeModelProvider` / `FakeToolProvider` |
| logical records hash | `7685930f8f0b9bc493f6a3cee9d8327cfa916488c3ef29184c9d60ceba1d242b` |
| reproducibility hash | `de4dc5540277c865024183e22e1b550383d14ee045206d004822f36df1455bf6` |

| Metric | Actual result |
| --- | ---: |
| Skill activation accuracy | 0.666667 |
| Activation precision | 0.875 |
| Activation recall | 0.7 |
| Plan compliance rate | 0.866667 |
| Evidence coverage rate | 1.0 |
| Clarification accuracy | 0.866667 |
| Claim-level accuracy | 0.733333 |
| Overclaim rate | 0.0 |
| Deterministic stability rate | 1.0 |

第二个独立输出目录再次实际执行后，logical records hash 与 reproducibility hash 均相同。历史 75×3 因原始数据集和 artifact 不存在，metrics 中明确记录为 `not_reproduced`，没有与当前新基线混算。

Artifacts（均由 `.gitignore` 排除）：

- `tests/evals/_runs/m8-skills-sop/skills_sop_metrics.json`
- `tests/evals/_runs/m8-skills-sop/skills_sop_records.jsonl`
- `tests/evals/_runs/m8-skills-sop-replay/skills_sop_metrics.json`
- `tests/evals/_runs/m8-skills-sop-replay/skills_sop_records.jsonl`

## 6. Changed Surface

- Workflow trace: `Financial-MCP-Agent/src/conversation/workflow.py`
- Eval runtime/docs: `tests/evals/runner.py`、`tests/evals/skills_sop/runner.py`、`tests/evals/README.md`
- Tests: `tests/unit/conversation/test_controlled_trace_adapter.py`、`tests/evals/skills_sop/test_skills_sop_eval.py`
- CI/docs: `.github/workflows/ci.yml`、`docs/specs/controlled-conversation-mainline/INTERVIEW_NARRATIVE_IMPLEMENTATION_MATRIX.md`

没有修改公开 API、数据库、鉴权、部署、生产依赖、工具权限、Planner/Executor 所有权或真实 `.env`。

## 7. Verification Evidence

| Command / check | Result |
| --- | --- |
| focused M8 trace + eval | `8 passed` |
| all offline eval smoke | `29 passed` |
| trace/redaction/Skills/routing/spec regression | `64 passed` |
| contracts + controlled chat E2E | `45 passed, 3 xfailed`；1 条既有 TestClient deprecation warning |
| target matrix | `8 passed`；全部冻结红灯已转绿 |
| backend tests | `11 passed`；56 条既有 datetime warning |
| Agent tests, non-live | `33 passed, 4 deselected` |
| concrete trace sample tests | `2 passed, 3 deselected` |
| CI exact Ruff command, including `src/skills` | `All checks passed` |
| CI exact Pyright command, including `src/skills` | `0 errors, 0 warnings` |
| CI YAML parse | pass；jobs 为 `compose-config/frontend-quality/offline-compose-e2e/python-quality` |
| independent 15×3 replay | records/reproducibility hashes both equal |
| `git diff --check` | pass；仅 Windows LF→CRLF working-copy warnings |
| dependency/migration diff | empty |
| historical `Finance` runtime import scan | empty |
| generated artifact ignore check | pass |

全仓 Python、frontend 与 Compose 的最终顺序门禁属于冻结 Milestone 9，本里程碑没有越界执行或声称已经完成最终验收。

## 8. Failures and Repairs

### Tests-first red phase

首轮新增合同产生 3 个预期失败：route-to-synthesis trace 缺少版本/Reference/Web 安全字段，runner 尚未注册 `skills_sop`。另有 1 个测试自身错误把 plan 从 `ChatOutcome` 读取；按真实合同改为 `outcome.workflow_result.plan` 后，生产实现继续按红灯开发。

### Intentional test import order

新增 eval runner 测试使用仓库既有显式 `sys.path` 启动模式，focused Ruff 初次报 8 个 `E402`。只对这 8 个有意延迟导入增加 `# noqa: E402`，未扩大全局 ignore；重跑 Ruff 与 Pyright 均为 0。

## 9. Honest Gaps and Remaining Risk

- 新基线真实暴露：缺槽位的股票/板块问题会在 Skill 激活前落为 no-skill；多任务 case 选择 `fund-compare` 后正确澄清；market-move 计划比当前 gold allowlist 多 sector constituents，且 claim 为 `ANALYTICAL` 而 gold 为 descriptive。
- 这些偏差未被隐藏、放宽断言或伪造阈值；Milestone 9 应结合完整验收判断是窄修实现、修正 gold，还是作为明确延期。
- 未调用真实 Langfuse、真实模型、Tavily、行情或生产流量；本里程碑证明的是默认离线、可复现、可脱敏链路。
- records JSONL 的 metrics 内 hash 是规范化逻辑记录 hash；实际文件包含换行/序列化格式，磁盘文件 SHA-256 不作为跨平台可复现合同。

## 10. Compatibility and Rollback

- trace 字段为增量低基数属性；既有 JSONL consumer 可继续忽略未知字段。
- eval target 与 `--repeat` 为增量 CLI；既有 target 默认 repeat=1 且未改变计算路径。
- 可独立移除 M8 的 trace helper、`skills_sop` runner、CI include 和测试，不影响 public confirmation、Registry、Planner 或唯一 Executor。

## 11. Handoff

Milestone 8 complete. The next frozen step is Milestone 9 only: review the final diff, execute the complete CI-ordered Python/frontend/Compose/end-to-end matrix, make only evidence-driven narrow repairs, synchronize final documentation, and produce the final handoff report. Suggested commit if later authorized: `feat(observability): add reproducible skills SOP evidence`.
