"""SQLAlchemy models.

ARCHITECTURE §8 classifies every table into one of three lifecycles, and the
classification is not decorative — it determines what DDL the migration emits
and what CI asserts:

  * **Immutable**  — UPDATE and DELETE raise at the database level (invariant
    7). Enforced by a trigger, not by the ORM, because "at the database level"
    means a psql session and a buggy worker are both stopped.
  * **Versioned**  — correction by superseding: a new row plus ``supersedes_id``,
    with a partial unique index keeping exactly one current row per identity.
  * **Mutable state machines** — every transition written to ``audit_events``.

Each model declares its lifecycle via ``__neptiq_lifecycle__`` and its tenancy
via the presence of an ``org_id`` column. tools/check_rls_coverage.py reads
these declarations and cross-references them against db/policies/, so a new
tenant table without a policy fails the build (invariant 3).

Task 1 defines the tenancy spine (organizations, users, memberships, projects,
sites) plus one exemplar of each lifecycle class so the invariant checks,
migrations and RLS tests are exercised against real DDL rather than against an
empty schema. The remaining tables from the §8 list land with the features that
use them; each will carry the same declarations.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import (
    Enum as SaEnum,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Lifecycle = Literal["immutable", "versioned", "mutable"]


class Base(DeclarativeBase):
    """Declarative base carrying NEPTIQ's lifecycle metadata.

    ``__neptiq_lifecycle__`` and ``__neptiq_tenant__`` are read by CI tooling.
    Defaults are deliberately the strict-but-wrong choices ("mutable", not
    tenant) so that a model author who forgets to declare them gets a CI
    failure rather than an accidental exemption from RLS.
    """

    __neptiq_lifecycle__: ClassVar[Lifecycle] = "mutable"
    __neptiq_tenant__: ClassVar[bool] = False

    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
    }


def _uuid7_pk() -> Mapped[UUID]:
    """Primary key column using Postgres 18's native ``uuidv7()``.

    Server-side generation, not client-side: it means a row's id is assigned at
    INSERT time in commit order, which is what makes the id useful as a
    chronological cursor for append-only tables.
    """
    return mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# Tenancy spine
# ---------------------------------------------------------------------------


class Organization(Base):
    """The tenant boundary.

    Not itself RLS-scoped by ``org_id`` — it IS the org. Access is mediated by
    ``memberships``; the policy on this table is an EXISTS against membership
    rather than a column comparison.
    """

    __tablename__ = "organizations"
    __neptiq_lifecycle__ = "mutable"
    __neptiq_tenant__ = False

    id: Mapped[UUID] = _uuid7_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint("length(name) between 1 and 200", name="ck_org_name_len"),
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'", name="ck_org_slug_shape"),
    )


class User(Base):
    """A person. Global, not tenant-scoped — one user may join many orgs.

    ``email`` is CITEXT: case-insensitive uniqueness at the database level.
    Doing this in application code invites two accounts differing only by case,
    which then both look plausible at a login prompt.
    """

    __tablename__ = "users"
    __neptiq_lifecycle__ = "mutable"
    __neptiq_tenant__ = False

    id: Mapped[UUID] = _uuid7_pk()
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    # Argon2id (ARCHITECTURE §4). Stored as the full PHC string so the
    # parameters travel with the hash and can be upgraded per-user.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Role(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Membership(Base):
    """Join table carrying RBAC role. The basis of every RLS policy.

    RLS on tenant tables asks "does a membership row exist linking the session
    org to this row's org?" — which is why this table's own policy must be
    written carefully: it is the one table whose policy cannot itself depend on
    a membership lookup without recursing.
    """

    __tablename__ = "memberships"
    __neptiq_lifecycle__ = "mutable"
    __neptiq_tenant__ = True

    id: Mapped[UUID] = _uuid7_pk()
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[Role] = mapped_column(
        SaEnum(Role, name="membership_role", native_enum=True), nullable=False
    )
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),
        Index("ix_membership_user", "user_id"),
    )


class Project(Base):
    __tablename__ = "projects"
    __neptiq_lifecycle__ = "mutable"
    __neptiq_tenant__ = True

    id: Mapped[UUID] = _uuid7_pk()
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_projects_org", "org_id"),)


class VerificationMethod(str, enum.Enum):
    DNS_TXT = "dns_txt"
    HTML_FILE = "html_file"
    META_TAG = "meta_tag"
    GSC_OAUTH = "gsc_oauth"


class Site(Base):
    """A registered site. Mutable state machine.

    ``verified_methods`` is an array-ish JSONB rather than a separate table
    because §16 requires "verifies ownership by at least two methods" — we need
    to count them, not query across them.

    ``origin`` holds scheme+host+port, never a full URL, and never a hardcoded
    default: invariant 6.
    """

    __tablename__ = "sites"
    __neptiq_lifecycle__ = "mutable"
    __neptiq_tenant__ = True

    id: Mapped[UUID] = _uuid7_pk()
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    verified_methods: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # §10: "Unverified domains hard-capped at 50 URLs." Stored per-site so the
    # cap is data, not a constant buried in the fetcher.
    crawl_url_cap: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("50"))
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        UniqueConstraint("project_id", "origin", name="uq_site_project_origin"),
        Index("ix_sites_org", "org_id"),
        CheckConstraint("crawl_url_cap > 0", name="ck_site_cap_positive"),
    )

    @property
    def verified_method_count(self) -> int:
        return len(self.verified_methods or {})


# ---------------------------------------------------------------------------
# Immutable exemplars — UPDATE/DELETE rejected by trigger (invariant 7)
# ---------------------------------------------------------------------------


class PageSnapshot(Base):
    """One observed HTTP exchange. Append-only, forever.

    CONSTITUTION P1: this row IS the retrievable artifact of observation that
    justifies every claim about the URL at this moment.

    ``body_sha256`` points into object storage rather than holding the body:
    §8 notes "identical content across crawls costs zero additional storage",
    which at 50k URLs and repeated crawls is the difference between a viable
    and an unviable storage bill.
    """

    __tablename__ = "page_snapshots"
    __neptiq_lifecycle__ = "immutable"
    __neptiq_tenant__ = True

    id: Mapped[UUID] = _uuid7_pk()
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    crawl_run_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    url_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Content-addressed pointer into S3-compatible storage.
    body_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    body_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Response headers as observed. Tainted content: read-only, never an
    # instruction. Stored so a finding can be re-derived without a re-fetch.
    response_headers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    was_rendered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    redirect_chain: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        # §8: "snapshots by crawl+url" is one of the four hot query shapes.
        Index("ix_snapshots_crawl_url", "crawl_run_id", "url_id"),
        Index("ix_snapshots_org", "org_id"),
        CheckConstraint("http_status between 100 and 599", name="ck_snapshot_status_range"),
        CheckConstraint(
            "body_sha256 is null or body_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_snapshot_sha256_shape",
        ),
    )


class Evidence(Base):
    """A byte-anchored excerpt justifying one claim. Append-only.

    §16 requires "every finding traces to a stored HTTP response and a
    byte-anchored excerpt". ``byte_start``/``byte_end`` are that anchor: they
    index into the stored body, so the excerpt can be re-derived and verified
    rather than trusted as a copied string.
    """

    __tablename__ = "evidence"
    __neptiq_lifecycle__ = "immutable"
    __neptiq_tenant__ = True

    id: Mapped[UUID] = _uuid7_pk()
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("page_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    selector: Mapped[str | None] = mapped_column(Text, nullable=True)
    byte_start: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    byte_end: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        Index("ix_evidence_snapshot", "snapshot_id"),
        Index("ix_evidence_org", "org_id"),
        CheckConstraint(
            "byte_start is null or byte_end is null or byte_end >= byte_start",
            name="ck_evidence_byte_range",
        ),
    )


class CostRecord(Base):
    """One unit of billable work. Append-only.

    Invariant 8: "Every unit of billable work writes a ``cost_records`` row in
    the same transaction." Amounts are integer micro-cents, never floats —
    §16 requires cost to "reconcile to within 5% of provider invoices", and
    accumulated float error across millions of rows makes that untestable.
    """

    __tablename__ = "cost_records"
    __neptiq_lifecycle__ = "immutable"
    __neptiq_tenant__ = True

    id: Mapped[UUID] = _uuid7_pk()
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    workflow_run_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    micro_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        Index("ix_cost_org_occurred", "org_id", "occurred_at"),
        Index("ix_cost_project", "project_id"),
        CheckConstraint("micro_cents >= 0", name="ck_cost_non_negative"),
    )


class AuditEvent(Base):
    """State transitions and consequential actions. Append-only."""

    __tablename__ = "audit_events"
    __neptiq_lifecycle__ = "immutable"
    __neptiq_tenant__ = True

    id: Mapped[UUID] = _uuid7_pk()
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    entity_table: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    from_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        Index("ix_audit_entity", "entity_table", "entity_id"),
        Index("ix_audit_org_occurred", "org_id", "occurred_at"),
    )


# ---------------------------------------------------------------------------
# Versioned exemplar — correction by superseding, never by mutation
# ---------------------------------------------------------------------------


class FindingState(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    FIXED = "fixed"
    VERIFIED_FIXED = "verified_fixed"
    VERIFICATION_FAILED = "verification_failed"
    WONT_FIX = "wont_fix"
    SUPERSEDED = "superseded"


class Severity(str, enum.Enum):
    # INFO exists as a real severity because §12 automatically demotes any rule
    # measuring below 0.85 precision to INFO. That demotion must be
    # representable in data, not a UI filter.
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Finding(Base):
    """A derived problem. Versioned: superseded, never updated.

    ``identity_hash`` is the load-bearing column. §8: "``findings.identity_hash``
    = hash(rule_id, scope_key), giving stable identity across crawls — without
    this, history is garbage." It is what lets a second crawl say "this is the
    same finding, now fixed" instead of creating a new row and losing the
    lifecycle.

    The partial unique index on ``(site_id, identity_hash) WHERE
    superseded_at IS NULL`` is what enforces "exactly one current version" —
    at the database level, so a concurrent analysis run cannot create two.
    """

    __tablename__ = "findings"
    __neptiq_lifecycle__ = "versioned"
    __neptiq_tenant__ = True

    id: Mapped[UUID] = _uuid7_pk()
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scope_key: Mapped[str] = mapped_column(Text, nullable=False)

    state: Mapped[FindingState] = mapped_column(
        SaEnum(FindingState, name="finding_state", native_enum=True), nullable=False
    )
    severity: Mapped[Severity] = mapped_column(
        SaEnum(Severity, name="finding_severity", native_enum=True), nullable=False
    )
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)

    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    supersedes_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("findings.id", ondelete="RESTRICT"), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Provenance is stored, not recomputed: P8 requires any run be explainable
    # after the fact, including with what code and rule versions.
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        Index(
            "uq_finding_current",
            "site_id",
            "identity_hash",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        # §8 hot query shape 1: findings by site+state+priority.
        Index("ix_findings_site_state_priority", "site_id", "state", "priority"),
        Index("ix_findings_org", "org_id"),
        CheckConstraint("identity_hash ~ '^[0-9a-f]{64}$'", name="ck_finding_identity_shape"),
        CheckConstraint("version >= 1", name="ck_finding_version_positive"),
        CheckConstraint(
            "priority is null or priority between 0 and 1000", name="ck_finding_priority_range"
        ),
    )


class Embedding(Base):
    """pgvector column, proving the extension is wired and exercised.

    §4 mandates pgvector; §11 T4 requires embeddings ALWAYS be self-hosted,
    because "a deprecated hosted embedding model invalidates your entire
    index". ``model_id`` and ``dim`` are stored per row so a model change is
    detectable rather than silently mixing incompatible vector spaces.

    1024 dimensions matches the BGE-M3-class floor named in §4.
    """

    __tablename__ = "embeddings"
    __neptiq_lifecycle__ = "immutable"
    __neptiq_tenant__ = True

    id: Mapped[UUID] = _uuid7_pk()
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    subject_table: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[Any] = mapped_column(Vector(1024), nullable=False)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        Index("ix_embeddings_subject", "subject_table", "subject_id"),
        Index("ix_embeddings_org", "org_id"),
        CheckConstraint("dim = 1024", name="ck_embedding_dim"),
    )


# Tables declared immutable here; the migration installs the reject trigger on
# each. Kept as an explicit list so the migration and the CI check read from
# one source rather than re-deriving it and disagreeing.
IMMUTABLE_TABLES: tuple[str, ...] = tuple(
    sorted(m.__tablename__ for m in Base.__subclasses__() if m.__neptiq_lifecycle__ == "immutable")
)

TENANT_TABLES: tuple[str, ...] = tuple(
    sorted(m.__tablename__ for m in Base.__subclasses__() if m.__neptiq_tenant__)
)


__all__ = [
    "IMMUTABLE_TABLES",
    "TENANT_TABLES",
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
]
