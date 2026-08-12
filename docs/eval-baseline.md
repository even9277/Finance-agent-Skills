# 离线评测基线（M1 基础设施验收）

## 基线信息

- 生成时间：2026-08-12
- 仓库：Finance-agent-Skills（远端 even9277/Finance-agent-Skills）
- 本地 commit：8ec4761（main）
- 数据来源：从 Finance 仓库迁移的 `tests/evals/` 固定 smoke 数据集
- 运行方式：完全离线，不调用模型与外部服务

## 指标口径

- `schema_pass_rate`：记录结构符合 schema 的比例。
- `planned_evidence_coverage`：计划步骤覆盖所需证据类型的比例。
- `false_reject_rate`：不应拒绝但被拒绝的比例。
- `allowed_claim_level_match`：允许的结论等级与目标一致的比例。
- `overclaim_rate`：结论超出证据支持程度的比例。
- `latency p50/p95`：当前 smoke 数据不含耗时字段，全部为 0；真实链路延迟在 M2 受控主链落地后记录。

## 当前基线

| target | count | schema_pass_rate | planned_evidence_coverage | false_reject_rate | allowed_claim_level_match | overclaim_rate |
| --- | --- | --- | --- | --- | --- | --- |
| entity | 2 | 1.0 | - | - | - | - |
| route | 2 | 1.0 | - | - | - | - |
| rewrite | 1 | 1.0 | - | - | - | - |
| planner | 2 | 1.0 | 1.0 | 0.0 | - | - |
| executor | 2 | 1.0 | 1.0 | - | - | - |
| verifier | 2 | 1.0 | 0.75 | 0.0 | 1.0 | - |
| synthesis | 2 | 1.0 | 1.0 | - | - | 0.0 |
| skill_activation | 2 | 1.0 | 1.0 | - | - | - |
| web_search | 2 | 1.0 | 1.0 | - | - | - |

## 与受控主链迁移（M2）的关系

- entity / route / rewrite：当前仓库已有对应入口，基线可直接用于迁移前后对比。
- planner / executor / verifier / synthesis / web_search / skill_activation：真实链路模块将在 M2 分阶段迁移；对应评测测试内置 `find_spec` 守卫，模块落地后自动从 skip 变为运行。
- 每个 M2 里程碑合并后，按下方命令重新生成指标并更新本文件。

## 复现命令

```bash
python -m pytest tests/evals -m eval_smoke -q
python -m tests.evals.runner --target entity --mode smoke
python -m tests.evals.runner --target verifier --mode smoke
```

## M1 基础设施验收状态

- backend 离线测试：12 passed。
- Financial-MCP-Agent 离线测试：33 passed，4 个 `live` 标记测试默认跳过。
- 离线评测 smoke：6 passed，4 skipped（executor / planner / verifier 依赖 M2 模块）。
- frontend `type-check` 与生产 `build`：通过（存在原有大包体告警，非本次引入）。
- CI：`.github/workflows/ci.yml` 包含 backend-tests / eval-smoke / frontend 三个 job。
- 待外部操作：推送后首次 GitHub Actions 运行，以及 main 分支保护配置。

