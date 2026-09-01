"""Alembic environment — async, migrator-role only.

Two things make this file non-boilerplate and worth commenting:

1. **The engine is async** (asyncpg, per ARCHITECTURE §4 "Async I/O"), so this
   follows Alembic's documented async recipe: build an `AsyncEngine`, then run
   the actual migration inside `connection.run_sync(...)`. There is no sync
   driver in this codebase (no psycopg2/psycopg dependency) to fall back to.

2. **The connection URL comes from DATABASE_URL_MIGRATOR, not DATABASE_URL.**
   ARCHITECTURE §8: "No RLS-bypass role for application code; only migrations
   run as owner." `neptiq_app` (DATABASE_URL) is NOBYPASSRLS and owns nothing;
   `neptiq_migrator` (DATABASE_URL_MIGRATOR) owns the schema. Falling back to
   DATABASE_URL when the migrator URL is unset is deliberately NOT done here —
   a migration that silently ran as the app role would either fail on
   permissions (safe) or, worse, succeed and leave the schema owned by a role
   the application also uses, which is the same shape of bug ADR 0001 entry 6
   was written about: an artefact whose existence was assumed rather than
   checked. Missing means fail loudly, immediately.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from neptiq_db.models import Base

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate diffs against the ORM metadata. `alembic revision --autogenerate`
# is a drafting aid only — every generated migration in this repo is reviewed
# and hand-annotated (see 0001_initial_schema.py) rather than committed as-is,
# because autogenerate cannot know about RLS, triggers, or CHECK constraints
# expressed outside the column definition.
target_metadata = Base.metadata

_MIGRATOR_URL_VAR = "DATABASE_URL_MIGRATOR"
_APP_URL_VAR = "DATABASE_URL"


def _migrator_url() -> str:
    url = os.environ.get(_MIGRATOR_URL_VAR)
    if url:
        return url
    # No silent fallback to DATABASE_URL: see module docstring point 2.
    if os.environ.get(_APP_URL_VAR):
        msg = (
            f"{_MIGRATOR_URL_VAR} is not set, but {_APP_URL_VAR} is. Migrations must "
            f"run as the owner role via {_MIGRATOR_URL_VAR}; refusing to fall back to "
            f"the application role, which is NOBYPASSRLS and would either fail on "
            "permissions or leave the schema owned by the wrong role (ARCHITECTURE §8)."
        )
        raise RuntimeError(msg)
    msg = f"{_MIGRATOR_URL_VAR} (or {_APP_URL_VAR}) must be set to run migrations."
    raise RuntimeError(msg)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection (``--sql``)."""
    context.configure(
        url=_migrator_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live database using the async engine."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _migrator_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
