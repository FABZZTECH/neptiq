-- RLS for memberships. See db/policies/README.md "Design" for why this table
-- is the one exception to the plain org_id-comparison pattern.
--
-- models.py's own docstring flags the hazard: "this table's own policy
-- cannot itself depend on a membership lookup without recursing." The OR
-- clause below does not recurse — it compares this row's OWN user_id column
-- directly against the bound GUC, never queries memberships again.

ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
-- Table owner (neptiq_migrator) is exempt from RLS by default; FORCE closes
-- that gap for completeness even though the application never connects as
-- the owner (ARCHITECTURE §8).
ALTER TABLE memberships FORCE ROW LEVEL SECURITY;

CREATE POLICY memberships_tenant_isolation ON memberships
    USING (
        org_id = current_setting('neptiq.org_id', true)::uuid
        OR user_id = current_setting('neptiq.user_id', true)::uuid
    )
    -- WITH CHECK deliberately narrower than USING: a session bound only by
    -- identity (get_tenant_context's bootstrap lookup) may ever SELECT its
    -- own memberships to discover which org to bind next, but must never be
    -- able to INSERT/UPDATE a membership row through that same bootstrap
    -- path — membership grants are a tenant-admin action, gated by
    -- Role/require_role in the API layer, not by "I can see rows here."
    WITH CHECK (org_id = current_setting('neptiq.org_id', true)::uuid);
