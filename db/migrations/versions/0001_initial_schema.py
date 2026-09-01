"""Initial schema: tenancy spine + one exemplar of each lifecycle class.

Revision ID: 0001
Revises:
Create Date: 2026-09-01

ARCHITECTURE §5 / §8. This migration creates the eleven tables declared in
``packages/neptiq_db/src/neptiq_db/models.py`` — organizations, users,
memberships, projects, sites (tenancy spine); page_snapshots, evidence,
cost_records, audit_events, embeddings (immutable exemplars); findings
(versioned exemplar). The remaining tables in ARCHITECTURE §8's full list
land with the features that use them (ADR 0001 entry 6).

Table/column DDL was drafted by ``alembic revision --autogenerate`` against
this exact ORM metadata (verified: the autogenerate diff against a running
PostgreSQL 18 + pgvector/pg_trgm/citext/btree_gin scratch database was empty
after this file was written — see the Task 2B-1 report for the command run
and its output), then hand-edited for the parts autogenerate cannot express:

  * The four immutability triggers below (invariant 7). autogenerate only
    diffs table/column/index/constraint DDL; it has no concept of triggers.
  * ``uuidv7()`` as the primary-key server_default (autogenerate infers this
    correctly by reading the model, but it is called out here because it is
    the one thing in this file that depends on PostgreSQL 18 specifically —
    the function does not exist on 17 and earlier).

RLS policies are deliberately NOT in this file. ARCHITECTURE §5 lists
``db/policies/`` as "RLS policies, reviewed separately" — a schema migration
and a security-policy change are different review concerns, and conflating
them here would mean a reviewer approving a column rename also silently
approves (or misses) a policy edit. See db/policies/*.sql and
0002_enable_row_level_security.py, which applies them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Invariant 7: "Immutable tables reject UPDATE and DELETE at the database
# level." A trigger, not an ORM guard — ARCHITECTURE §8 models.py docstring:
# "at the database level" means a psql session and a buggy worker are both
# stopped. One trigger function, installed on every table in IMMUTABLE_TABLES
# (models.py is the single source of truth the migration reads from, so the
# two cannot silently disagree about which tables are immutable).
# ---------------------------------------------------------------------------
_REJECT_MUTATION_FUNCTION = """
CREATE OR REPLACE FUNCTION neptiq_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'table % is immutable (ARCHITECTURE invariant 7): % is not permitted',
        TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'read_only_sql_transaction';
END;
$$ LANGUAGE plpgsql;
"""

_DROP_REJECT_MUTATION_FUNCTION = "DROP FUNCTION IF EXISTS neptiq_reject_mutation();"


def _immutable_tables() -> tuple[str, ...]:
    """Read the immutable-table list from the ORM, not a hand-copied literal.

    Importing neptiq_db here (rather than re-listing table names) is exactly
    what ADR 0001 entry 13's rule requires: this migration's claim "these
    tables are immutable" is checked against the same declaration
    tools/check_rls_coverage.py reads, so the two cannot drift apart the way
    the original (uncommitted) entry 6 claim did.
    """
    from neptiq_db.models import IMMUTABLE_TABLES

    return IMMUTABLE_TABLES


def _install_immutability_trigger(table: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER trg_{table}_immutable
        BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION neptiq_reject_mutation();
        """
    )


def _drop_immutability_trigger(table: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table};")


def upgrade() -> None:
    op.execute(_REJECT_MUTATION_FUNCTION)

    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", postgresql.CITEXT(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'", name="ck_org_slug_shape"),
        sa.CheckConstraint("length(name) between 1 and 200", name="ck_org_name_len"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("totp_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "memberships",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("OWNER", "ADMIN", "MEMBER", "VIEWER", name="membership_role"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),
    )
    op.create_index("ix_membership_user", "memberships", ["user_id"], unique=False)

    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_org", "projects", ["org_id"], unique=False)

    op.create_table(
        "sites",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column(
            "verified_methods",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("crawl_url_cap", sa.Integer(), server_default=sa.text("50"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("crawl_url_cap > 0", name="ck_site_cap_positive"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "origin", name="uq_site_project_origin"),
    )
    op.create_index("ix_sites_org", "sites", ["org_id"], unique=False)

    op.create_table(
        "page_snapshots",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("crawl_run_id", sa.UUID(), nullable=False),
        sa.Column("url_id", sa.UUID(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=True),
        sa.Column("body_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column(
            "response_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("was_rendered", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "redirect_chain",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "body_sha256 is null or body_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_snapshot_sha256_shape",
        ),
        sa.CheckConstraint("http_status between 100 and 599", name="ck_snapshot_status_range"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_snapshots_crawl_url", "page_snapshots", ["crawl_run_id", "url_id"], unique=False
    )
    op.create_index("ix_snapshots_org", "page_snapshots", ["org_id"], unique=False)

    op.create_table(
        "evidence",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("selector", sa.Text(), nullable=True),
        sa.Column("byte_start", sa.BigInteger(), nullable=True),
        sa.Column("byte_end", sa.BigInteger(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "byte_start is null or byte_end is null or byte_end >= byte_start",
            name="ck_evidence_byte_range",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["page_snapshots.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_org", "evidence", ["org_id"], unique=False)
    op.create_index("ix_evidence_snapshot", "evidence", ["snapshot_id"], unique=False)

    op.create_table(
        "cost_records",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("workflow_run_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("micro_cents", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("micro_cents >= 0", name="ck_cost_non_negative"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cost_org_occurred", "cost_records", ["org_id", "occurred_at"], unique=False)
    op.create_index("ix_cost_project", "cost_records", ["project_id"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("entity_table", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("from_state", sa.Text(), nullable=True),
        sa.Column("to_state", sa.Text(), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_entity", "audit_events", ["entity_table", "entity_id"], unique=False)
    op.create_index(
        "ix_audit_org_occurred", "audit_events", ["org_id", "occurred_at"], unique=False
    )

    op.create_table(
        "findings",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("scope_key", sa.Text(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "OPEN",
                "ACKNOWLEDGED",
                "IN_PROGRESS",
                "FIXED",
                "VERIFIED_FIXED",
                "VERIFICATION_FAILED",
                "WONT_FIX",
                "SUPERSEDED",
                name="finding_state",
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL", name="finding_severity"),
            nullable=False,
        ),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("identity_hash ~ '^[0-9a-f]{64}$'", name="ck_finding_identity_shape"),
        sa.CheckConstraint(
            "priority is null or priority between 0 and 1000", name="ck_finding_priority_range"
        ),
        sa.CheckConstraint("version >= 1", name="ck_finding_version_positive"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["findings.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_findings_org", "findings", ["org_id"], unique=False)
    op.create_index(
        "ix_findings_site_state_priority",
        "findings",
        ["site_id", "state", "priority"],
        unique=False,
    )
    op.create_index(
        "uq_finding_current",
        "findings",
        ["site_id", "identity_hash"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    op.create_table(
        "embeddings",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("subject_table", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vector", Vector(1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("dim = 1024", name="ck_embedding_dim"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_embeddings_org", "embeddings", ["org_id"], unique=False)
    op.create_index(
        "ix_embeddings_subject", "embeddings", ["subject_table", "subject_id"], unique=False
    )

    # Invariant 7. Installed AFTER every table exists, read from the ORM's own
    # declaration rather than repeated as a literal list.
    for table in _immutable_tables():
        _install_immutability_trigger(table)


def downgrade() -> None:
    for table in reversed(_immutable_tables()):
        _drop_immutability_trigger(table)

    op.drop_index("ix_embeddings_subject", table_name="embeddings")
    op.drop_index("ix_embeddings_org", table_name="embeddings")
    op.drop_table("embeddings")

    op.drop_index(
        "uq_finding_current",
        table_name="findings",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.drop_index("ix_findings_site_state_priority", table_name="findings")
    op.drop_index("ix_findings_org", table_name="findings")
    op.drop_table("findings")

    op.drop_index("ix_audit_org_occurred", table_name="audit_events")
    op.drop_index("ix_audit_entity", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_cost_project", table_name="cost_records")
    op.drop_index("ix_cost_org_occurred", table_name="cost_records")
    op.drop_table("cost_records")

    op.drop_index("ix_evidence_snapshot", table_name="evidence")
    op.drop_index("ix_evidence_org", table_name="evidence")
    op.drop_table("evidence")

    op.drop_index("ix_snapshots_org", table_name="page_snapshots")
    op.drop_index("ix_snapshots_crawl_url", table_name="page_snapshots")
    op.drop_table("page_snapshots")

    op.drop_index("ix_sites_org", table_name="sites")
    op.drop_table("sites")

    op.drop_index("ix_projects_org", table_name="projects")
    op.drop_table("projects")

    op.drop_index("ix_membership_user", table_name="memberships")
    op.drop_table("memberships")

    op.drop_table("users")
    op.drop_table("organizations")

    op.execute(_DROP_REJECT_MUTATION_FUNCTION)
