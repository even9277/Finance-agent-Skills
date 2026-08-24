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
