"""neptiq_db — models, async session, RLS binding helpers, repositories.

MUST NOT be importable from Zone U (ARCHITECTURE invariant 1). Enforced by
tools/check_zone_imports.py.
"""

from __future__ import annotations

from neptiq_db.models import (
    IMMUTABLE_TABLES,
    TENANT_TABLES,
    AuditEvent,
    Base,
    CostRecord,
    Embedding,
    Evidence,
    Finding,
    FindingState,
    Membership,
    Organization,
    PageSnapshot,
    Project,
    Role,
    Severity,
    Site,
    User,
    VerificationMethod,
)
from neptiq_db.session import (
    ORG_ID_GUC,
    USER_ID_GUC,
    create_engine,
    create_session_factory,
    install_rls_guard,
    tenant_session,
    unscoped_session,
)

__all__ = [
    "IMMUTABLE_TABLES",
    "ORG_ID_GUC",
    "TENANT_TABLES",
    "USER_ID_GUC",
    "AuditEvent",
    "Base",
    "CostRecord",
    "Embedding",
    "Evidence",
    "Finding",
    "FindingState",
    "Membership",
    "Organization",
    "PageSnapshot",
    "Project",
    "Role",
    "Severity",
    "Site",
    "User",
    "VerificationMethod",
    "create_engine",
    "create_session_factory",
    "install_rls_guard",
    "tenant_session",
    "unscoped_session",
]
