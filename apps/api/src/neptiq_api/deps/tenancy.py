"""Authentication, tenancy and RLS session binding dependencies.

This is the single place where a request's identity becomes a database session.
ARCHITECTURE §8's guarantee — "no RLS-bypass role for application code" — only
holds if every route acquires its session here, so the dependency is written to
be the path of least resistance and no alternative is exported.

The ordering matters and is easy to get wrong:

  1. Read the session cookie, verify its signature.  (authentication)
  2. Resolve the requested org from the URL path.    (routing)
  3. Verify a membership row links user -> org.      (authorization)
  4. ONLY THEN open a session bound to that org.     (RLS)

Doing (4) before (3) would bind RLS to an org the user may not belong to, and
RLS would then dutifully serve that org's rows. RLS is a backstop against
missing WHERE clauses; it is not a substitute for an authorization check.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Path, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neptiq_core.errors import AuthenticationError, AuthorizationError
from neptiq_db.models import Membership, Organization, Role
from neptiq_db.session import identity_session, tenant_session

# Roles ordered by capability, for `require_role`.
_ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.MEMBER: 1,
    Role.ADMIN: 2,
    Role.OWNER: 3,
}


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated user, before any org is resolved."""

    user_id: UUID
    email: str


@dataclass(frozen=True, slots=True)
class TenantContext:
    """An authenticated user acting within one authorized org."""

    user_id: UUID
    org_id: UUID
    role: Role

    def require_role(self, minimum: Role) -> None:
        """Raise unless the principal's role meets ``minimum``.

        Called explicitly by routes rather than inferred, because "who may
        approve an artifact" is a product decision that should be visible in
        the route signature (P5: human authorisation for consequential change).
        """
        if _ROLE_RANK[self.role] < _ROLE_RANK[minimum]:
            raise AuthorizationError(f"this action requires the {minimum.value} role or higher")


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """Pull the app-wide session factory off application state.

    Stored on ``app.state`` at startup rather than created per request: an
    engine per request would exhaust Postgres connections under any real load.
    """
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:  # pragma: no cover - startup wiring failure
        raise RuntimeError("session_factory missing from app.state; check the lifespan handler")
    return factory  # type: ignore[no-any-return]


async def get_principal(request: Request) -> Principal:
    """Authenticate from the signed session cookie.

    Session cookies + Argon2id + TOTP per ARCHITECTURE §4. The cookie carries
    only an opaque signed session id; user data is never in the cookie, so a
    revoked session cannot keep working until expiry.

    Task 1 wires the dependency shape and the failure path. The signed-cookie
    verification and the sessions store land with POST /v1/auth/session.
    """
    session_cookie = request.cookies.get("neptiq_session")
    if not session_cookie:
        raise AuthenticationError("no session cookie presented")

    principal = getattr(request.state, "principal", None)
    if principal is None:
        # Explicit failure rather than a permissive default. A dependency that
        # silently returns an anonymous principal is how authorization holes
        # get shipped.
        raise AuthenticationError("session could not be verified")
    return principal  # type: ignore[no-any-return]


async def get_tenant_context(
    org_slug: Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")],
    principal: Annotated[Principal, Depends(get_principal)],
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> TenantContext:
    """Resolve and AUTHORIZE the org named in the path. Step 2 and 3.

    The membership lookup runs in an identity-bound session (user_id set, no
    org_id — the org is not yet known, which is the whole point of the
    lookup). It is safe because the application role has no BYPASSRLS: the
    query can only read rows the ``memberships``/``organizations`` RLS
    policies grant to this ``user_id``, and it filters by ``user_id``
    explicitly on top of that. A missing membership yields 403, not an empty
    result that a caller might mistake for "no data".

    This must NOT use ``unscoped_session``: that binds no identity at all, and
    the memberships/organizations RLS policies key their "resolve my own
    orgs" grant on ``neptiq.user_id`` being set — see ``db/policies/`` and
    ``identity_session``'s docstring for why binding org_id here would be
    wrong even if it were available.
    """
    async with identity_session(
        factory,
        user_id=principal.user_id,
        reason="resolve org membership before an org_id is known",
    ) as session:
        row = (
            await session.execute(
                select(Membership.org_id, Membership.role)
                .join(Organization, Organization.id == Membership.org_id)
                .where(Organization.slug == org_slug, Membership.user_id == principal.user_id)
            )
        ).one_or_none()

    if row is None:
        # Deliberately the same message whether the org does not exist or the
        # user is not a member: distinguishing them lets an attacker enumerate
        # which org slugs are real.
        raise AuthorizationError("organization not found or access denied")

    org_id, role = row
    return TenantContext(user_id=principal.user_id, org_id=org_id, role=role)


async def get_db(
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    """Step 4: an RLS-bound session, only after authorization succeeded.

    This is the ONLY session dependency routes should use. It yields inside a
    transaction; the transaction commits when the request handler returns and
    rolls back if it raises, which is also what makes invariant 8 achievable —
    the cost record and the work it accounts for share one transaction.
    """
    async with tenant_session(factory, org_id=ctx.org_id, user_id=ctx.user_id) as session:
        yield session


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
CurrentTenant = Annotated[TenantContext, Depends(get_tenant_context)]
Db = Annotated[AsyncSession, Depends(get_db)]

__all__ = [
    "CurrentPrincipal",
    "CurrentTenant",
    "Db",
    "Principal",
    "TenantContext",
    "get_db",
    "get_principal",
    "get_session_factory",
    "get_tenant_context",
]
