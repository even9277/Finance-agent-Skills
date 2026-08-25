# M9 PLAN: Full Compose, Protected Live Acceptance, and Delivery Closure

## Goal

Prove the complete memory migration in the real deployment topology and one protected live LLM + read-only Tushare journey, then close delivery with documentation and an interview evidence map.

## Scope

- Rebuilt offline Compose E2E across PostgreSQL/pgvector, Redis, backend workers, Nginx, and the production frontend bundle.
- Protected live E2E (	ests/e2e/test_live_controlled_chat_chain.py) with real OpenAI-compatible model and read-only Tushare on an isolated SQLite identity and isolated trace path.
- README/CONTRIBUTING updates for memory commands, observability, and the full test matrix.
- MODULE_EVIDENCE_MAP.md reconciling interview modules (STM/LTM/commands/observability) with code, tests, and merged PRs.
- M9 milestone report and top-level plan closure.

## Acceptance

1. Rebuilt offline Compose E2E passes with the final main code.
2. Protected live E2E passes with RUN_PROTECTED_LIVE_E2E=true and real credentials; it must not touch production databases, must use one isolated user identity, and must pass redaction assertions.
3. Default CI remains offline; live-e2e.yml stays workflow_dispatch and environment-gated.
4. Documentation is accurate and contains no credentials, memory content, command text, or user IDs.
5. Issue to PR to CI to review to squash merge to Issue closure to branch deletion completes on main.

## Constraints

- Never weaken an existing test or remove failure handling to make CI green.
- Do not change financial planner/tool behavior.
- PostgreSQL remains the only durable authority.
- Local SOCKS-only proxy environments may require removing ALL_PROXY for the live run; HTTP proxy remains usable and no dependency change is required.

## Rollback

Revert the M9 PR; documentation-only changes carry no runtime risk. The protected live test is a gate, not a service.
## Progress

- [x] Rebuilt offline Compose E2E and final local gates
- [x] Protected live LLM + read-only Tushare acceptance (isolated identity/trace, redaction assertions)
- [x] README/CONTRIBUTING updates
- [x] Module evidence map and milestone report
- [x] PR, CI, review, merge, Issue closure, branch cleanup, clean main