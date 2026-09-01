-- RLS for organizations. This table is NOT in neptiq_db.models.TENANT_TABLES
-- (it has no org_id column — it IS the org, per Organization's docstring)
-- and so is outside what invariant 3 mandates. It gets a policy anyway; see
-- db/policies/README.md "Design" for the reasoning.

ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations FORCE ROW LEVEL SECURITY;

CREATE POLICY organizations_member_or_bound ON organizations
    USING (
        id = current_setting('neptiq.org_id', true)::uuid
        OR EXISTS (
            SELECT 1 FROM memberships m
            WHERE m.org_id = organizations.id
              AND m.user_id = current_setting('neptiq.user_id', true)::uuid
        )
    )
    -- Organizations are created by a dedicated signup flow, not by a
    -- tenant-bound or identity-bound session; WITH CHECK false means no
    -- session using this policy's grant may INSERT/UPDATE a row here at all.
    WITH CHECK (false);
