# Chat NLU Eval Harness

This directory contains the offline smoke/full harness for the conversation-mode entity, route, and rewrite contracts.

Smoke:

```bash
pytest tests/evals -m eval_smoke
```

Full placeholders:

```bash
python -m tests.evals.runner --target entity --mode full
python -m tests.evals.runner --target route --mode full
python -m tests.evals.runner --target rewrite --mode full
```

The metrics are offline regression evidence, not online SLA claims.
