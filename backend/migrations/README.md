# Database migrations

`backend/migrations` owns versioned schema changes introduced by the maintained memory
subsystem. The application still bootstraps pre-existing legacy tables for backward
compatibility, but every table listed in `ALEMBIC_MANAGED_TABLE_NAMES` is created and
removed only by Alembic.

The initial revision references legacy `users`, `sessions`, and `messages` tables.
Therefore, use the application `init_db()` path for a completely blank database; it
creates those legacy tables first and then upgrades Alembic-managed tables. Run Alembic
directly only after that bootstrap step, or in a test fixture that creates the legacy
baseline explicitly.

Direct Alembic commands fail closed unless the dedicated migration target is supplied.
Do not reuse the application's broad `.env` implicitly:

```powershell
$env:MIGRATION_DATABASE_URL = "sqlite+aiosqlite:///./memory-migration-test.db"
uv run --locked alembic upgrade head
```

The preferred downgrade entry is
`backend.db.migration_runner.downgrade_database(..., allow_isolated=True)`. The revision
also guards itself, so a direct CLI downgrade fails closed unless the operator explicitly
marks the target as disposable:

```powershell
$env:MIGRATION_DATABASE_URL = "sqlite+aiosqlite:///./memory-migration-test.db"
$env:ALLOW_ISOLATED_MEMORY_DOWNGRADE = "true"
uv run --locked alembic downgrade base
Remove-Item Env:ALLOW_ISOLATED_MEMORY_DOWNGRADE
```

Never set this flag for production or user data, and remove it immediately after the
isolated operation.
