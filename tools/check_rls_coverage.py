#!/usr/bin/env python3
"""Enforce ARCHITECTURE §6 invariant 3: every table with an org_id column must
have a row-level security policy.

This is the exact "missing check" ADR 0001 entry 13 names: it would have
exposed entry 6's false claim ("migrations and RLS policies had shipped") on
day one, because `db/policies/` was an empty untracked directory at the time
and this check would have failed immediately rather than the absence going
unnoticed for a full task. It runs statically (imports `neptiq_db.models`,
reads file names from `db/policies/` and `db/migrations/versions/`) — it does
NOT connect to a database and does not itself prove a policy is *correct*,
only that a policy *file exists* and is *wired into the migration that applies
it*. Correctness (does the policy actually isolate tenants) is what
`tests/integration/`'s RLS tests verify against a real PostgreSQL connection;
this check and that suite are deliberately two different mechanisms for two
different questions, per the same reasoning `db/policies/README.md` gives for
splitting schema migrations from policy review.

Three things are checked, corresponding to three distinct ways invariant 3
could silently fail:

  1. Coverage — every `neptiq_db.models.TENANT_TABLES` entry has a
     `db/policies/<table>.sql` file. This is the literal text of invariant 3
     and the one entry 13 was written about.
  2. Wiring — every policy file that exists is actually applied by
     `db/migrations/versions/0002_enable_row_level_security.py`'s
     `_POLICY_FILES` tuple. A policy file that exists on disk but was never
     added to that tuple is applied to nothing — the exact shape of bug this
     tool exists to catch, one level deeper than "does the file exist".
  3. No orphans — every entry in `_POLICY_FILES` corresponds to either a
     `TENANT_TABLES` table or the one documented exception
     (`organizations`, which carries no `org_id` column but is granted a
     policy anyway for the bootstrap join — see `db/policies/README.md`
     "Design"). A stray entry pointing at a renamed or deleted table would
     otherwise fail silently at migration time with no static signal.

Run at migration time: `make migrate` should not proceed past a coverage gap,
so this is wired into the `migrate` Makefile target (runs BEFORE
`alembic upgrade head`) as well as into `invariants`/`check`, so a coverage
gap is caught by `make check` in the authoring sandbox — no Docker required —
and not only when a real migration is attempted.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICIES_DIR = REPO_ROOT / "db" / "policies"
MIGRATION_0002 = REPO_ROOT / "db" / "migrations" / "versions" / "0002_enable_row_level_security.py"

# organizations carries no org_id column (it IS the org) and so is outside
# TENANT_TABLES, but db/policies/README.md's "Design" section documents why it
# is granted a policy anyway: the bootstrap join from identity_session needs
# one. This is the ONE name allowed in _POLICY_FILES without a matching
# TENANT_TABLES entry; anything else in that position is an orphan (check 3).
DOCUMENTED_NON_TENANT_POLICIES = frozenset({"organizations"})


def _tenant_tables() -> tuple[str, ...]:
    """Import neptiq_db.models.TENANT_TABLES.

    Imported rather than parsed with an AST walk (contrast
    tools/check_zone_imports.py, which deliberately avoids importing
    first-party code it is checking) because TENANT_TABLES is already a
    computed tuple derived from ClassVar declarations across many classes —
    re-deriving that computation with a second, separate AST-based
    implementation would itself be a second source of truth that could drift
    from models.py's own logic. Importing the real package means this tool
    and the ORM can never disagree about what TENANT_TABLES is.
    """
    sys.path.insert(0, str(REPO_ROOT / "packages" / "neptiq_db" / "src"))
    from neptiq_db.models import TENANT_TABLES

    return TENANT_TABLES


def _policy_files_on_disk() -> set[str]:
    """Table names with a db/policies/<table>.sql file present."""
    if not POLICIES_DIR.is_dir():
        return set()
    return {f.stem for f in POLICIES_DIR.glob("*.sql")}


_POLICY_FILES_PATTERN = re.compile(
    r"_POLICY_FILES\s*:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\((.*?)\)\n", re.DOTALL
)
_STRING_LITERAL = re.compile(r'"([a-zA-Z0-9_]+)\.sql"')


def _wired_into_migration() -> set[str]:
    """Table names actually applied by 0002's _POLICY_FILES tuple.

    Parsed as text (a small regex over the literal tuple), not imported as a
    module: Alembic revision files are meant to be run by Alembic, and
    importing one directly executes module-level code that assumes an
    Alembic `op` context is active, which this static check does not have and
    should not fake.
    """
    if not MIGRATION_0002.is_file():
        return set()
    source = MIGRATION_0002.read_text(encoding="utf-8")
    match = _POLICY_FILES_PATTERN.search(source)
    if not match:
        return set()
    return set(_STRING_LITERAL.findall(match.group(1)))


def main() -> int:
    tenant_tables = set(_tenant_tables())
    on_disk = _policy_files_on_disk()
    wired = _wired_into_migration()

    failures: list[str] = []

    # Check 1 (invariant 3 itself): every tenant table has a policy file.
    missing_files = sorted(tenant_tables - on_disk)
    for table in missing_files:
        failures.append(
            f"INVARIANT 3 VIOLATION: table '{table}' has __neptiq_tenant__ = True "
            f"(an org_id column) but db/policies/{table}.sql does not exist. "
            "Every tenant table must have a row-level security policy "
            "(ARCHITECTURE §6 invariant 3)."
        )

    # Check 2: every on-disk policy file is wired into migration 0002.
    unwired = sorted(on_disk - wired)
    for table in unwired:
        failures.append(
            f"WIRING GAP: db/policies/{table}.sql exists but is not listed in "
            f"_POLICY_FILES in {MIGRATION_0002.relative_to(REPO_ROOT)}. A policy "
            "file that is never applied by the migration protects nothing — "
            "this is precisely the gap ADR 0001 entry 13 was written about."
        )

    # Check 3: no orphan entries in _POLICY_FILES pointing at tables that are
    # neither a declared tenant table nor the one documented exception.
    orphans = sorted(wired - tenant_tables - DOCUMENTED_NON_TENANT_POLICIES)
    for table in orphans:
        failures.append(
            f"ORPHAN POLICY: '{table}' is applied by _POLICY_FILES in "
            f"{MIGRATION_0002.relative_to(REPO_ROOT)} but is neither a "
            "TENANT_TABLES entry nor a documented exception "
            f"({sorted(DOCUMENTED_NON_TENANT_POLICIES)}). If this table "
            "legitimately needs a policy without an org_id column, document "
            "why in db/policies/README.md and add it to "
            "DOCUMENTED_NON_TENANT_POLICIES in this script."
        )

    if failures:
        sys.stderr.write("RLS COVERAGE FAILURES\n" + "=" * 70 + "\n")
        for f in failures:
            sys.stderr.write(f"  - {f}\n")
        return 1

    print(
        f"RLS coverage holds: {len(tenant_tables)} tenant tables, all with a "
        f"db/policies/*.sql file, all wired into "
        f"{MIGRATION_0002.relative_to(REPO_ROOT)} "
        f"(plus {sorted(DOCUMENTED_NON_TENANT_POLICIES)} as documented "
        "non-tenant exceptions)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
