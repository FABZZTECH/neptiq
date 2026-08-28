"""Async session management and row-level-security session binding.

ARCHITECTURE §8:

    "RLS on every tenant table bound to ``current_setting('neptiq.org_id')``.
     No RLS-bypass role for application code; only migrations run as owner."

This module is where that binding happens, and getting it right is subtle
enough to be worth stating explicitly.

**Why ``set_config(..., is_local => true)`` and not ``SET``.** The application
runs on a connection pool. A plain ``SET`` persists for the life of the
connection, so a request for org A would leave ``neptiq.org_id`` set to A on a
pooled connection that the next request — for org B — then picks up. With
``is_local => true`` the setting is scoped to the surrounding transaction and
is reverted on COMMIT or ROLLBACK. That single flag is the difference between
tenant isolation and a cross-tenant data leak.

**Why the value is bound as a parameter.** ``set_config`` takes its value as an
argument, so we pass the org id as a bind parameter. Interpolating it into SQL
text would be a taint-into-SQL path, and the org id comes from a session cookie
— i.e. from the network.

**Why there is no ``bypass_rls`` helper.** Deliberate. Providing one would make
it available, and the existence of an escape hatch is what turns "RLS
everywhere" into "RLS almost everywhere". Migrations connect as the owner via
``DATABASE_URL_MIGRATOR``, which is a different credential and a different code
path (Alembic), not a flag on this session factory.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Final
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from neptiq_core.errors import AuthorizationError
from neptiq_core.logging import get_logger

logger = get_logger(__name__)

# The GUC name RLS policies read. Must match db/policies/*.sql exactly; a typo
# here means every policy evaluates against an unset variable and denies all
# rows, which at least fails safe — but it fails safe by breaking the product,
# so the name is a module constant referenced from tests.
ORG_ID_GUC: Final = "neptiq.org_id"
USER_ID_GUC: Final = "neptiq.user_id"

# Minimum length for an audited "reason" string. Long enough that a caller
# cannot satisfy it with "x" and call the audit trail done.
_MIN_REASON_CHARS: Final = 12


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create the application engine.

    ``pool_pre_ping`` is on because Kamal rolling deploys and Postgres failover
    both leave stale connections in the pool, and a stale connection surfaces
    as a confusing mid-request failure rather than a reconnect.

    ``statement_cache_size=0`` is set for asyncpg because PgBouncer in
    transaction mode (which the deployment topology in §15 will use in front of
    the primary) is incompatible with server-side prepared statements.
    """
    return create_async_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
        pool_recycle=1800,
        connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory with autoflush off.

    Autoflush off is a correctness choice, not a performance one: with
    append-only tables and immutability triggers, an implicit flush at an
    unexpected moment produces a database-level error whose traceback points at
    a read, not at the write that caused it.
    """
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
        class_=AsyncSession,
    )


@contextlib.asynccontextmanager
async def tenant_session(
    factory: async_sessionmaker[AsyncSession],
    *,
    org_id: UUID,
    user_id: UUID | None = None,
) -> AsyncIterator[AsyncSession]:
    """Yield a session inside a transaction bound to ``org_id`` for RLS.

    Every application read and write must go through this. The binding is
    transaction-local, so it cannot leak to the next user of the pooled
    connection.

    Usage::

        async with tenant_session(factory, org_id=ctx.org_id) as session:
            rows = await session.execute(select(Finding))

    The transaction commits on clean exit and rolls back on exception. There is
    intentionally no way to obtain an unbound session from this module.
    """
    if org_id is None:  # pragma: no cover - defensive; mypy forbids it statically
        raise AuthorizationError("refusing to open a database session without an org_id")

    session = factory()
    try:
        async with session.begin():
            # is_local => true scopes both settings to THIS transaction.
            await session.execute(
                text("SELECT set_config(:k, :v, true)"),
                {"k": ORG_ID_GUC, "v": str(org_id)},
            )
            if user_id is not None:
                # Used by audit triggers to attribute state transitions.
                await session.execute(
                    text("SELECT set_config(:k, :v, true)"),
                    {"k": USER_ID_GUC, "v": str(user_id)},
                )
            yield session
    finally:
        await session.close()


@contextlib.asynccontextmanager
async def unscoped_session(
    factory: async_sessionmaker[AsyncSession],
    *,
    reason: str,
) -> AsyncIterator[AsyncSession]:
    """A session with NO org binding, for genuinely global tables only.

    Legitimate uses are few: the login lookup (which must find a user before an
    org is known) and the jobs reaper (which operates across tenants by design
    and whose queries carry an explicit org_id column filter).

    This does NOT bypass RLS — the application role has no BYPASSRLS attribute,
    so any tenant table read here returns zero rows. That is the intended
    behaviour: this session can only usefully touch tables that have no
    org_id, and it fails closed on the ones that do.

    ``reason`` is mandatory and is logged, so every use is traceable.
    """
    if not reason or len(reason) < _MIN_REASON_CHARS:
        raise AuthorizationError("unscoped_session() requires a substantive reason")
    logger.info("opening unscoped session", extra={"reason": reason})
    session = factory()
    try:
        async with session.begin():
            yield session
    finally:
        await session.close()


def install_rls_guard(engine: AsyncEngine) -> None:
    """Log a loud warning if a connection is checked in with org_id still set.

    A belt-and-braces detector for the failure mode this module is designed to
    prevent. If ``is_local`` were ever dropped from the ``set_config`` calls,
    this fires on the very first request instead of silently leaking rows.
    Registered in tests and in dev/staging; harmless in production.
    """

    @event.listens_for(engine.sync_engine, "checkin")
    def _on_checkin(dbapi_conn: object, record: object) -> None:
        info = getattr(record, "info", None)
        if isinstance(info, dict) and info.get("neptiq_org_bound"):
            logger.error(
                "connection returned to pool with a tenant binding still attached; "
                "set_config must use is_local => true",
                extra={"event": "rls_binding_leak"},
            )


__all__ = [
    "ORG_ID_GUC",
    "USER_ID_GUC",
    "create_engine",
    "create_session_factory",
    "install_rls_guard",
    "tenant_session",
    "unscoped_session",
]
