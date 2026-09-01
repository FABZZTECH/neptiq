# db/policies/

Row-level security policies. ARCHITECTURE §5 lists this directory as "RLS
policies, reviewed separately" — deliberately split from `db/migrations/`
because a schema change (add a column, rename a table) and a security-policy
change (who may see which row) are different review concerns. Conflating them
means a reviewer approving the former can miss a change to the latter.

## What's here

One `.sql` file per governed table, plus this README. Applied, in the order
listed in `_POLICY_FILES` in
`db/migrations/versions/0002_enable_row_level_security.py`, by that migration
— the file is the single source that both `alembic upgrade` and a human
reviewer read, so the two cannot disagree about what a policy says.

`tools/check_rls_coverage.py` reads `neptiq_db.models.TENANT_TABLES` (every
model with `__neptiq_tenant__ = True`, i.e. every table with an `org_id`
column) and fails the build if any of them has no corresponding file here.
That is ARCHITECTURE §6 invariant 3 — "every table with an org_id column must
have a row-level security policy" — made mechanically checkable instead of
merely stated. See ADR 0001 entry 6/13: this check is precisely the one that
would have caught the original false claim that RLS policies existed.

## Design

Every tenant table's policy compares the row's `org_id` column against
`current_setting('neptiq.org_id', true)::uuid` — the GUC that
`neptiq_db.session.tenant_session` binds `is_local => true` inside the request
transaction (ARCHITECTURE §8). `current_setting(..., true)` returns `NULL`
when unset, and `org_id = NULL` is `NULL` (not `true`) in a `USING` clause, so
an unbound session sees zero rows on every tenant table — fails closed, not
open, which matters because "unbound" also describes the historical bug this
Task fixed (see `identity_session`'s docstring in `neptiq_db/session.py`).

**`memberships` is the one exception**, and it exists for a real reason, not
convenience: `apps/api/src/neptiq_api/deps/tenancy.py`'s `get_tenant_context`
must resolve which org(s) a user belongs to *before* an `org_id` is known —
that resolution is what produces the `org_id` every other request binds. Its
policy additionally grants access when
`user_id = current_setting('neptiq.user_id', true)::uuid`, and
`identity_session` is the only session constructor that sets that GUC without
also setting `org_id`. `WITH CHECK` (governing writes) does **not** carry the
same OR-clause: a user resolving their own memberships must never be able to
write one through that path.

**`organizations`** carries no `org_id` column — per
`neptiq_db.models.Organization`'s docstring, "it IS the org" — so it is
outside `TENANT_TABLES` and invariant 3 does not require a policy here. It
gets one anyway, because the same bootstrap lookup joins `organizations` (by
slug) to `memberships` (by `user_id`) in one query, and a table with RLS
enabled but no policy denies all rows to every non-owner role. The policy
grants access when the row's `id` matches the bound `org_id` (ordinary tenant
access) OR a membership row links the bound `user_id` to that organization
(the bootstrap path) — the second condition itself passes through
`memberships`' own RLS policy, since the application role has no BYPASSRLS.

**`users`** has no policy and RLS is not enabled on it. It is explicitly
global (`Organization`'s docstring: "Global, not tenant-scoped — one user may
join many orgs"), the login lookup must find a user *before* any identity is
bound at all, and it carries no `org_id` column — invariant 3 does not apply.

## Verification

Applying these against a real, natively-installed PostgreSQL 18 (this
sandbox's package, not Docker) and exercising them with two organizations and
`SET ROLE neptiq_app_scratch` is exactly what `tests/integration/` runs — see
that directory's module docstring for the command and its output. `make
check` (static analysis, no DB) cannot exercise a policy; only a real
PostgreSQL connection can, which is why these tests are `ci_only` rather than
unit tests, per `tests/conftest.py`.
