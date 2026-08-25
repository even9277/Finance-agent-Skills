# M7 Milestone 4 Execution Report

## Result

`COMPLETED`.

## Verification

The rebuilt Docker Compose offline stack was executed with:

```powershell
docker compose -f docker/docker-compose.offline.yml up --build --abort-on-container-exit --exit-code-from offline-e2e
```

The run started the real PostgreSQL, Redis, backend, Nginx, and frontend containers. The offline deterministic provider remained in use; no paid model, production service, real Tushare, or network Mem0 call was made.

| Evidence | Result |
| --- | --- |
| Full Compose offline suite | `144 passed, 1 skipped, 39 deselected, 4 xfailed` |
| M7 HTTP journey through frontend proxy | synthetic memory write, forget preview, confirmation, authoritative inactive status, replay rejection passed |
| Focused post-fix tests | `15 passed` |
| Compose configuration | passed |
| PostgreSQL authority ordering | fixed by flushing the authority row before the audit row in the same transaction |

## Narrow Fix

`SqlAlchemyAuthoritativeMemoryRepository` now flushes newly created or updated authority records before inserting audit events. This preserves the existing caller-owned transaction and satisfies the PostgreSQL composite foreign-key contract without changing the authority model or deleting audit evidence.

## E2E Safety Assertions

- “忘掉我的文本记忆” returns `CONFIRMATION_REQUIRED` and a pending confirmation reference.
- “确认” executes the frozen scope once and leaves the synthetic authority record `INACTIVE`.
- A repeated “确认” returns `REJECTED` with `CONFIRMATION_NOT_FOUND` and does not repeat the mutation.
- The command branch is exercised through the frontend reverse proxy and backend HTTP API, not only an in-process test client.

## Residual Risk

Playwright browser coverage is not installed. Existing frontend dependency audit findings remain documented and were not expanded into this migration. Live providers and production deployment remain deferred by the frozen plan.
