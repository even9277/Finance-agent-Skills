# M7 Milestone 2 Execution Report

## Result

`COMPLETED` for the frozen core-change scope.

## Implemented Files

- `backend/application/memory/commands.py`: deterministic parser, typed intent/result, inspect/update/delete/forget/confirm/cancel orchestration, owner/session/version/TTL/replay checks.
- `backend/db/models.py`: `MemoryPendingCommandRow` and Alembic-managed table registration.
- `backend/migrations/versions/20260825_04_memory_pending_commands.py`: reversible pending-command schema migration.
- `Financial-MCP-Agent/src/memory/contracts.py`: shared `ProfileField.RESPONSE_PREF` enum member.
- `backend/infrastructure/memory/authority_repository.py`: response preference mapped to existing PostgreSQL authority write path.
- `backend/application/chat/{contracts.py,use_case.py,factory.py}`: preflight command branch and `ChatOutcome.memory_command`.
- `backend/schemas/chat.py`, `backend/routers/chat.py`: additive REST result and WebSocket `memory_command` control frame.
- `frontend/src/api/index.ts`: matching TypeScript result and WebSocket frame contracts.
- M7 contract test xfail removed for the implemented application owner.

## Checks

| Command | Result |
| --- | --- |
| `uv run --locked pytest tests/unit/memory/test_m7_command_contract.py tests/contract/test_memory_characterization_contract.py -q` | `10 passed, 4 xfailed` |
| `uv run --locked pytest tests/contract/test_controlled_chat_contract.py -q` | `6 passed` |
| `uv run --locked pytest tests/integration/test_memory_migrations.py -q` | `4 passed` |
| `uv run --locked alembic heads` | `20260825_04 (head)` |
| `uv run --locked ruff check <changed Python scope>` | passed |
| `uv run --locked pyright <changed Python scope>` | `0 errors, 0 warnings, 0 informations` |
| `git diff --check` | passed |

## Safety and Compatibility

- Explicit command handling occurs after the existing session preparation and before retrieval/financial workflow execution.
- PostgreSQL remains the authority; text deletion reuses audit/outbox/index invalidation.
- Broad forget freezes IDs/versions and requires a session-bound, one-time 600-second confirmation.
- REST/WS fields are additive; ordinary chat contract tests remain green.
- No paid model, production service, real Tushare, network Mem0, or real user data was used.

## Known Follow-up

- Legacy memory routes still need write-path delegation and removal of direct `confirm=true` broad deletion.
- Structured integration tests for cross-user/session/replay/expiry/version conflicts and derived-provider degradation belong to Milestone 3.
- Frontend pending state, Vitest/Playwright decision, logs/traces, and full Compose E2E remain for Milestones 3-4.

Suggested commit: `feat(memory): add controlled memory command core`
