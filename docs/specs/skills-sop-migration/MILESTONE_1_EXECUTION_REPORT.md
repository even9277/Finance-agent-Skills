# MILESTONE_1_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: Milestone 1 — Freeze Behavioral Contracts and Failing Reproductions
- Status: Complete
- Date: 2026-08-26
- Branch: `feature/skills-sop-migration`

## 2. Contract Restatement

- Goal: 在生产实现前冻结五类投研 Skill 的资产、运行时、对话接入和评测合同。
- Expected behavior: 新测试能够收集，既有行为保持全绿，尚未实现的目标能力以稳定、可归因的红灯呈现。
- Allowed area: `tests/**` 与 `docs/specs/skills-sop-migration/**`。
- Exclusions: 不修改 `src/**`、前端、依赖、配置、数据库、真实环境变量或远端 Git 状态。
- Owning layer: 本里程碑仅由测试与评测层拥有；生产模块归后续 Milestones 2-8。
- Interface/config/observability impact: 仅冻结未来接口，不改变当前运行时。
- Escalation condition: 若红灯来自语法、导入、类型或既有回归，而非未实现目标能力，则必须先修正测试合同。

## 3. Files Added

- `tests/contract/test_skill_assets_v2_contract.py`
  - 冻结五类 Skill 的四层资产、统一章节、spec 字段、路由元数据、引用 frontmatter、工具和证据维度。
- `tests/unit/skills/test_skill_runtime_contract.py`
  - 冻结 schema gate、SemVer、生命周期、Registry snapshot/LKG、引用索引、阶段加载器与 loader 缓存合同。
- `tests/unit/conversation/test_skill_sop_migration_contract.py`
  - 冻结公开 `explicit_skill`、类型化确认、Web News 治理和多任务澄清合同。
- `tests/evals/skills_sop/data/smoke.jsonl`
  - 新增 15 条高信息量 smoke case，覆盖五 Skill、正反例、缺槽位、显式选择、多任务、确认、降级和 Web News。
- `tests/evals/skills_sop/test_skills_sop_eval.py`
  - 冻结 `tests.evals.runner --target skills_sop --repeat 1`、artifact 元数据和指标合同。

## 4. Files Modified

- `docs/specs/skills-sop-migration/PLAN.md`
  - 标记 Milestone 1 完成并记录测试证据、决策与发现。
- `docs/specs/skills-sop-migration/MILESTONE_0_EXECUTION_REPORT.md`
  - 由原通用报告归档，保留 Milestone 0 基线证据。
- `docs/specs/skills-sop-migration/MILESTONE_EXECUTION_REPORT.md`
  - 记录当前 Milestone 1 的唯一执行报告。

没有修改生产源码、前端、配置、依赖、数据库或真实环境变量。

## 5. Verification Results

### New contract collection

```text
26 tests collected
```

### New target contract run

```text
1 passed, 25 failed
```

这 25 项失败均为计划内目标红灯：

| Area | Expected red | Missing capability |
| --- | ---: | --- |
| Asset contract | 10 | cases/references、统一 SKILL 章节、typed spec/frontmatter |
| Runtime contract | 10 | schema/version/lifecycle/snapshot/reference/loader modules 与 Registry loader |
| Conversation contract | 4 | public explicit skill、typed confirmation、Web News、multi-task guard |
| Eval runner contract | 1 | `skills_sop` runner target 与 artifact metrics |
| Dataset coverage | 0 | 15 条 smoke case 已通过覆盖合同 |

### Existing regression characterization

```text
21 passed
```

覆盖既有 Skill catalog、理解阶段、工具治理和 controlled chat chain。

```text
5 passed
```

覆盖既有 skill activation、route、rewrite 和 planner eval。

### Static quality gates for new tests

```text
ruff: All checks passed
pyright: 0 errors
```

初次 Pyright 暴露了测试直接访问未来接口的问题；已改为 `getattr`/`cast` 的存在性合同，避免目标红灯被静态类型错误污染。没有放宽项目类型规则。

## 6. Scope and Safety Review

- `git status --short` 仅包含本专题 docs/tests。
- 未触及鉴权、安全边界、持久化模型、数据库 migration、依赖锁或公开运行时行为。
- 未记录或输出密钥、Authorization header、Cookie、私有 prompt 或敏感 payload。
- 未 commit、push、创建 PR 或删除/关闭任何分支。
- 历史仓库仅作为只读证据；当前主仓库没有新增运行时依赖。

## 7. Outcome

Milestone 1 已把“Skills 发现、注册、澄清、路由、执行、证据、降级、确认、评测”的目标拆成可独立转绿的合同。当前红灯是后续实现的验收清单，不是仓库回归。下一里程碑为 Milestone 2：只实现 Skill 四层资产、typed schema gate、SemVer 与生命周期合同。

## 8. Deferred Work

- Milestone 2: Skill 资产、schema、version、lifecycle。
- Milestone 3: Registry snapshot、LKG、reference index、stage loader。
- Milestones 4-8: 路由/确认/改写、规划/证据/降级/总结、Web News、公开 API/UI、可观测与评测。
- Milestone 9: 全量回归、E2E、真实调用检查、文档与交付。
