"""Enable row-level security: apply every policy in db/policies/.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-01

ARCHITECTURE §6 invariant 3: "Every table with an org_id column must have a
row-level security policy." This migration is intentionally thin — it reads
and executes the .sql files in db/policies/ verbatim rather than re-encoding
policy logic here, so the file a human reviews under "RLS policies, reviewed
separately" (§5) is exactly the SQL that runs. See db/policies/README.md for
the design and tools/check_rls_coverage.py for the mechanical check that every
TENANT_TABLES entry has a file here.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# Applied in this explicit order rather than a directory glob: memberships
# and organizations must exist before any table whose bootstrap reasoning
# refers to them is even relevant to reason about, and an explicit list means
# adding a new tenant table without adding it here is visible in the diff
# instead of silently picked up (or missed) by a glob.
_POLICY_FILES: tuple[str, ...] = (
    "memberships.sql",
    "organizations.sql",
    "projects.sql",
    "sites.sql",
    "page_snapshots.sql",
    "evidence.sql",
    "cost_records.sql",
    "audit_events.sql",
    "findings.sql",
    "embeddings.sql",
)

_POLICIES_DIR = Path(__file__).resolve().parent.parent.parent / "policies"

_TABLE_FROM_FILE: dict[str, str] = {f: f.removesuffix(".sql") for f in _POLICY_FILES}


def _statements(sql: str) -> list[str]:
    """Split a policy file into individual statements.

    asyncpg's ``execute`` (which SQLAlchemy's ``op.execute`` ultimately calls)
    does not accept multiple ``;``-separated commands in one call the way a
    psql session does — confirmed empirically: running a whole policy file
    through a single ``op.execute`` failed against the real PostgreSQL 18
    instance in this sandbox.

    Comments are stripped BEFORE splitting on ``;``, not after: a first
    attempt split raw text on ``;`` and dropped lines that STARTED with
    ``--``, and failed against the real database with a syntax error whose
    text began mid-sentence inside a comment. Cause, found by reading the
    actual error rather than assuming the fix worked: one comment line in
    memberships.sql itself contains a semicolon ("...by default; FORCE
    closes...", prose, not SQL), so splitting on raw ``;`` cut the file
    inside that comment. Stripping every ``--...`` line-comment first removes
    the problem at its source rather than trying to make the splitter smarter
    about where semicolons are allowed to appear.
    """
    without_comments = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    return [s.strip() for s in without_comments.split(";") if s.strip()]


def upgrade() -> None:
    for filename in _POLICY_FILES:
        sql = (_POLICIES_DIR / filename).read_text(encoding="utf-8")
        for statement in _statements(sql):
            op.execute(statement)


def downgrade() -> None:
    for filename in reversed(_POLICY_FILES):
        table = _TABLE_FROM_FILE[filename]
        policy_name = (
            f"{table}_tenant_isolation"
            if table
            not in (
                "memberships",
                "organizations",
            )
            else (
                "memberships_tenant_isolation"
                if table == "memberships"
                else "organizations_member_or_bound"
            )
        )
        op.execute(f"DROP POLICY IF EXISTS {policy_name} ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
