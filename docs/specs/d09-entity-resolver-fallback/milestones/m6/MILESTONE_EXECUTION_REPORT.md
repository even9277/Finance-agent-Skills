# MILESTONE_EXECUTION_REPORT.md

## 1. Milestone Executed

- Milestone: 6 — Protected Real API Acceptance
- Status: Complete
- Date: 2026-09-09

## 2. Protected Case

- Case id: `d09-live-01`
- Product entry: `/api/chat/stream` WebSocket through the real FastAPI router/application/workflow/repository/Trace chain。
- Input class: natural-language A-share company name absent from the frozen local catalog。
- Entity provider/model: OpenAI-compatible / `tongyi-xiaomi-analysis-pro`。
- Synthesis provider/model: OpenAI-compatible / `glm-5.1`。
- Catalog/tool: real read-only Tushare。
- Secrets and original model responses were not printed or persisted。

## 3. Command and Result

```text
RUN_PROTECTED_LIVE_E2E=true
uv run --locked --with socksio -- python -m pytest \
  tests/e2e/test_live_controlled_chat_chain.py -q -m live -k d09-live-01
```

Result: `1 passed, 2 deselected, 0 skipped` in 64.24 seconds。

## 4. Assertions Proven

- Resolver path was exactly `model_fallback`, not exact/alias/fuzzy/static code。
- Model call count was within the frozen 1–2 total-call budget。
- Catalog status was `verified` and the canonical stock was `601012.SH`。
- All downstream observations used the same symbol and a `tushare:` source。
- Real streaming synthesis produced at least two chunks with ordered protocol frames and matching persisted answer hash。
- Trace and low-sensitive acceptance artifact contained neither the original question nor model/Tushare credentials。
- Follow-up offline D09 suite: 22 passed。

## 5. Scope and Side Effects

- External operations: paid model calls and read-only Tushare queries explicitly authorized by the user。
- No external write, database production write, brokerage action or document change。
- Test database and trace artifact lived in pytest temporary storage。

## 6. Handoff

M6 hard acceptance is complete. M7 will perform final diff/security/duplicate-path review, commit only D09 files (excluding user D01), push, open the PR linked to #56, inspect CI, fix in-scope findings, and squash merge when green.
