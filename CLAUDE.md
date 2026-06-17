# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Commands

### Backend (FastAPI)
```bash
# Start backend (must run from /root/Finance root — agent paths depend on it)
cd /root/Finance && source .venv/bin/activate && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Run specific backend tests
PYTHONPATH=/root/Finance pytest tests/test_chat_service_skill_processing.py -q

# Run tests under backend/tests/
cd /root/Finance && PYTHONPATH=/root/Finance pytest backend/tests/test_redis_cache_service.py -q

# Run eval smoke tests
PYTHONPATH=/root/Finance pytest tests/evals -m 'eval_smoke or not eval_smoke' -q

# Run working state test
PYTHONPATH=/root/Finance .venv/bin/python backend/test_working_state_store.py
```

### Frontend (Vue 3 + Vite)
```bash
cd /root/Finance/frontend && npm run dev           # dev server (port 5173, proxies /api → :8000)
cd /root/Finance/frontend && npm run build          # production build (runs vue-tsc type-check first)
cd /root/Finance/frontend && npm run preview        # preview production build
```

### Docker
```bash
# Quick full-stack startup (PostgreSQL + Redis + backend + frontend + pgAdmin)
cd /root/Finance/docker && docker compose up -d --build

# Health check
curl -fsS http://localhost:8000/api/health

# Rebuild specific services
cd /root/Finance/docker && docker compose build --no-cache backend frontend

# Run with explicit env files
docker compose -f docker/docker-compose.yml --env-file ../backend/.env up -d
```

### Useful search/explore commands
```bash
rg "keyword" --type py                          # search Python files
rg "keyword" --type ts                          # search TypeScript files
rg --files -g '*.py' | head -20                 # list Python files
```

### Redis verification (quality gates — run after any Redis code change)
```bash
# Full Redis test suite
cd /root/Finance && PYTHONPATH=/root/Finance pytest backend/tests/test_redis_*.py -q

# Single-chain compliance check (ensures no direct redis imports outside integrations/redis/)
python /root/Finance/scripts/check_redis_single_chain.py

# Health check — redis_status must be one of: ok / disabled / degraded
curl -fsS http://localhost:8000/api/health | python -m json.tool | grep -A5 redis

# Redis metrics endpoint
curl -fsS http://localhost:8000/api/redis/metrics
```

## Architecture Overview

### Three-system design

The project spans three interconnected codebases that share a single process at runtime:

1. **`backend/`** — FastAPI application. The entry point. Owns HTTP routing, JWT auth, DB access, and the lifespan that bootstraps everything.
2. **`Financial-MCP-Agent/src/`** — The agent runtime. Lives outside backend/ but is directly imported by it (via `PYTHONPATH` injection and `backend/integrations/agent_runtime/`). Contains all agent logic: routing, planning, execution, skills, memory, tools, trace.
3. **`frontend/`** — Vue 3 SPA. Independent Vite dev server in dev; served via Nginx in Docker.

The key architectural insight: the backend and agent runtime share a Python process. There is no IPC or separate service boundary. `backend/integrations/agent_runtime/app_runtime.py` does `from src.tools.skill_trace import ...` — it imports directly from the agent package.

### Startup sequence (lifespan in `backend/main.py`)

```
init_db() → initialize_trace_runtime() → ensure_seed_accounts() →
(if ENABLE_MEMORY) init_mem0_client() + start ltm_worker background task →
(if ENABLE_STM) verify STM config →
(if REDIS_ENABLED) init_redis_runtime() → yield → on shutdown: stop worker, close redis, flush traces
```

`.env` files are loaded in a specific order: `Financial-MCP-Agent/.env` first, then `backend/.env` overrides. `backend/config.py` uses `pydantic-settings` with `env_file` list. However, `_load_project_env_files()` in `main.py` ALSO runs `load_dotenv()` to push values into `os.environ`, because many downstream libraries (Mem0, Langfuse) read directly from `os.getenv`.

### Feature flags: the central control plane

Nearly every major behavior is gated behind a boolean in `backend/config.py` → `Settings`. There is NO separate feature flag service. All flags are env vars read on startup. Key flags (all default `False`):

| Flag | Controls |
|------|----------|
| `ENABLE_STM` | Short-term memory / context window compression |
| `ENABLE_MEMORY` | Mem0 + pgvector + LTM worker |
| `ENABLE_CHAT_SKILLS` | Skill-first chat routing (Router → Planner → Executor) |
| `ENABLE_TUSHARE_SKILLS` | Tushare data skill bundle |
| `ENABLE_DETERMINISTIC_SKILL_EXECUTION` | Fast pre-planned tool execution vs. agentic path |
| `ENABLE_TRACE` | Local structured trace (JSONL + log) |
| `ENABLE_LANGFUSE` | Langfuse cloud export (requires trace enabled) |
| `AUTH_ENABLED` | JWT auth middleware enforcement |
| `REDIS_ENABLED` | Redis caching infrastructure |

When debugging "why didn't skill X activate", check these flags first.

### Chat request flow (the main hot path)

```
POST /api/chat/message
  → AuthMiddleware (attach auth_ctx to request.state; public paths bypass)
  → chat_service.handle_chat_message()
    → build_context_window_payload() (STM: gather recent messages + summary)
    → route_v2() (stage1 confidence → stage2 → final route: financial-sop / tushare-data / fallback)
    → If skill route: planner → executor (deterministic or agentic) → evidence verification
    → synthesis (LLM generates final answer from data + context)
    → save message + trigger LTM enqueue (if ENABLE_MEMORY)
    → return ChatMessageResponse
```

WebSocket streaming (`/api/chat/stream`) follows the same internal path but yields SSE events per stage. Auth for WS is via `?token=` query param or `Authorization` header.

### Redis integration (on `feature/redis-integration-phase1`)

**Positioning**: Redis is the **runtime state layer** — not the primary database. PostgreSQL remains the authoritative source of truth (messages, reports, profiles, audit). Redis stores only short-lived, expirable, rebuildable data. Never put complete messages, final reports, long-term profiles, or sensitive information (tokens, keys, PII) into Redis. Redis failure must never break the main request path.

**Current phase scope** (Phase 1 — infrastructure only, no business caching yet):
- ✅ Done: Docker deployment + connection config, unified client with connection pool/timeout/health, KeyBuilder, CacheEnvelope, TTL+jitter strategy, degradation fallback, metrics+trace integration, single-chain enforcement
- ❌ Not yet: frontend Redis dashboard, AOF/RDB persistence, business-layer Redis access (STM/report/summary actual read/write — these come in later phases)

**Module layout** (`backend/integrations/redis/`):
- **`client.py`**: async Redis client wrapper with connect/ping/health_snapshot
- **`cache_service.py`**: get/set/delete with TTL jitter, JSON envelope — this is the **single entry point** for all Redis access
- **`runtime.py`**: singleton lifecycle (init on startup, close on shutdown, health dict for `/api/health`)
- **`key_builder.py`**: all keys must use this; format: `finagent:{env}:{module}:{resource}:{...}` — no hand-crafted keys in business code
- **`envelope.py`**: all values must be wrapped in `CacheEnvelope` (JSON + version + updated_at + source)
- **`lock.py`**: distributed lock helper
- **`metrics.py`**: metrics collection with `/api/redis/metrics` endpoint
- **`routers/redis_admin.py`**: admin debug endpoints (gated by `REDIS_DEBUG_ENDPOINTS_ENABLED`)

**Hard design rules** (from `docs/开发计划/Redis集成/AGENTS.md`):
1. **Single entry point**: business code must go through `CacheService` — never `import redis` directly
2. **KeyBuilder mandatory**: all keys via KeyBuilder, format `finagent:{env}:{module}:{resource}:{...}`
3. **CacheEnvelope mandatory**: all values wrapped in CacheEnvelope (JSON + version + updated_at + source)
4. **TTL required**: `set()` must receive a TTL; TTL ≤ 0 raises an error — no permanent keys
5. **Degradation first**: Redis exceptions return fallback metadata, never interrupt the main flow
6. **No sensitive values in logs**: log only key prefix, latency, hit/miss, error type — never the full key or value
7. **Trace fields (minimum set)**: `redis_enabled`, `redis_status` (ok/disabled/degraded), `cache_hit`, `cache_key_family`, `redis_latency_ms`, `fallback_reason` (when degraded), `redis_error_type` (when error)

When Redis is unavailable, the system degrades gracefully — no requests fail, caching is simply skipped.

### Database: dual-mode SQLite / PostgreSQL

- Default local dev: SQLite via `aiosqlite` (`sqlite+aiosqlite:///...backend/finance.db`)
- Docker or production: PostgreSQL via `asyncpg` (`postgresql+asyncpg://...`)
- The switch is purely a `DATABASE_URL` env var change — all code uses SQLAlchemy async APIs
- `init_db()` does `create_all` (auto-DDL) + incremental field migration via try/catch ALTER TABLE
- Alembic files exist in `backend/db/migrations/` but aren't hooked into auto-migration yet
- Models in `backend/db/models.py` include: User, Account, Session, Message, Report, ReportTask, UserProfile, PortfolioHolding, and STM summary tables

### Auth model

`AuthMiddleware` (starlette BaseHTTPMiddleware) runs on every request. It does NOT reject unauthenticated requests — it only parses and attaches `AuthContext` to `request.state`. Public paths (`/api/health`, `/api/auth/login`, `/api/docs`, `/api/openapi.json`, `/api/redis/health`, `/api/redis/metrics`) skip parsing entirely. Individual routers use `Depends(require_auth)` to enforce login. The `ensure_user_access()` helper enforces that users can only access their own data.

Test accounts (`test1/test1`, `test2/test2`) are seed-created idempotently on startup via `ensure_seed_accounts()`.

### Frontend conventions

- `@/` alias maps to `frontend/src/`
- API calls through `frontend/src/api/index.ts` (axios instance with interceptor for auth token)
- State management: Pinia stores (`authStore`, `chatStore`, `memoryStore`, `portfolioStore`, `userStore`)
- Reusable logic: composables (`useChat.ts`, `useReport.ts`, `useMemory.ts`, `usePortfolio.ts`)
- Backend sends `snake_case`, axios interceptor transforms to `camelCase` for TS consumption
- Vite dev server proxies `/api` (REST + WebSocket) to `http://localhost:8000`

### Agent runtime key modules

- **`agents/router.py`**: Two-stage skill routing. Stage 1 (high-confidence keyword/pattern match) → Stage 2 (LLM classification). Outputs `RouteDecisionV2` with final route, skill_id, execution_policy.
- **`agents/planner/`**: Generates tool execution plans from skill specs. `tushare_planner.py` is the primary planner for data skills.
- **`agents/executor/`**: Runs tool plans. `execution_scheduler.py` handles concurrency (max 6, per-API-family limit of 2, min interval 150ms).
- **`agents/verifier/`**: Post-execution evidence verification and scoring.
- **`agents/synthesis/`**: Generates the final user-facing answer from verified evidence + context.
- **`skills/`**: Workspace financial skills (stock-first-pass, etf-screen, fund-compare, etc.) + skill registry + metadata index.
- **`memory/`**: Mem0 client wrapper, LTM worker loop, memory service.
- **`tools/`**: Tushare SDK wrapper, skill trace (structured event logging), trace exporters (Langfuse).

### Testing conventions

- Tests live in both `tests/` (project root, mostly agent/unit tests) and `backend/tests/` (backend-specific, mostly Redis tests)
- All tests require `PYTHONPATH=/root/Finance` to resolve both backend and agent imports
- Test fixtures in `tests/conftest.py` and `backend/tests/conftest.py`
- Eval tests in `tests/evals/` use `pytest` markers for smoke vs full runs
- Redis tests use `_redis_enabled_override` in `backend/integrations/redis/runtime.py` to avoid depending on a real Redis instance

## Key Gotchas

1. **Must start from `/root/Finance`** — agent code resolves paths relative to CWD (logs, reports, vendor skills). Starting from elsewhere causes import and path errors.

2. **Two .env files, two loading mechanisms** — `pydantic-settings` reads env files for config model, but `main.py` also runs `load_dotenv()` for libraries that use `os.getenv` directly. Both must be kept in sync.

3. **Feature flag defaults are all `False`** — a fresh `.env` gives you auth + basic chat only. No skills, no memory, no Tushare, no Redis. Enable flags explicitly.

4. **`PYTHONPATH` is required for tests** — the agent package (`Financial-MCP-Agent/src/`) is NOT installed as a package. It works at runtime because `uvicorn` inherits the CWD, but `pytest` needs explicit `PYTHONPATH`.

5. **SQLite concurrent access** — SQLite in WAL mode with `check_same_thread=False`. Concurrent writers will still serialize. For parallel test runs, each test should use its own DB file.

6. **Auth is soft by default** — middleware only parses tokens on protected paths. The `require_auth` dependency actually enforces. Public paths are whitelisted at the middleware level.

7. **Redis is strictly optional** — all Redis operations have degradation paths. If Redis is down, the system functions normally without caching. The health endpoint reports Redis status as `ok`, `disabled`, or `degraded`.

8. **Redis KeyBuilder is mandatory** — all Redis keys must be generated through `KeyBuilder` with format `finagent:{env}:{module}:{resource}:{...}`. Never hand-craft key strings in business code. Never `import redis` directly — always go through `CacheService`.

9. **Redis TTL is mandatory** — `CacheService.set()` requires a TTL parameter. TTL ≤ 0 raises an error. No permanent keys allowed. TTL jitter (±15%) is applied automatically to prevent thundering herd expirations.

10. **Redis stores no sensitive data** — never put complete messages, final reports, long-term profiles, tokens, keys, or PII into Redis. It's a runtime state layer, not a data store.

11. **Agent code changes need end-to-end verification** — unit tests aren't enough. The AGENTS.md prescribes a full startup + login + chat + report verification path.

## Project Rules Reference

The file `AGENTS.md` at the repo root contains comprehensive development rules covering:
- Directory boundaries (what's modifiable, read-only, and forbidden to touch)
- Backend/frontend/agent layering rules
- Database change requirements
- Reference repository reuse rules
- E2E startup and verification procedures
- Debug and security rules

For Redis-specific development rules, see `docs/开发计划/Redis集成/AGENTS.md` — it defines positioning, phase scope, directory constraints, hard code rules, quality gates, and delivery format requirements.

This CLAUDE.md supplements AGENTS.md with architecture overview and quick commands. When in doubt about process, consult AGENTS.md first.
