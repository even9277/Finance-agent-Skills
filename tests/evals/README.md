# Chat NLU Eval Harness

This directory contains the offline smoke/full harness for the conversation-mode modules and complete controlled mainline.

Smoke:

```bash
pytest tests/evals -m eval_smoke
```

Full placeholders:

```bash
python -m tests.evals.runner --target entity --mode full
python -m tests.evals.runner --target route --mode full
python -m tests.evals.runner --target rewrite --mode full
python -m tests.evals.runner --target mainline --mode full
```

`mainline` executes the real Orchestrator with Fake external Ports and reports terminal-status accuracy plus required-stage coverage. The metrics are offline regression evidence, not online SLA claims.

Skills SOP reproducible baseline:

```bash
python -m tests.evals.runner --target skills_sop --mode smoke --repeat 3 --output-dir tests/evals/_runs/latest
```

该目标通过真实 `ControlledConversationWorkflow` 与确定性 Fake Ports 执行 15 条版本化案例，生成 `skills_sop_metrics.json` 和不含用户原文/模型回答/证据事实的 `skills_sop_records.jsonl`。报告固定 dataset、runner、Registry、tool schema、provider、repeat 与内容 hash；历史 75×3 指标因缺少原始数据和 artifact 单列为未复现，不与当前基线混写。
