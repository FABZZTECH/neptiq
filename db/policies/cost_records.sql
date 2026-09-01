-- RLS for cost_records. Plain org_id comparison — see db/policies/README.md
-- "Design". current_setting('neptiq.org_id', true) returns NULL when
-- unbound, and org_id = NULL is NULL (not true) in USING/WITH CHECK, so an
-- unbound or wrongly-bound session sees and can write zero rows: fails
-- closed.

ALTER TABLE cost_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE cost_records FORCE ROW LEVEL SECURITY;

CREATE POLICY cost_records_tenant_isolation ON cost_records
    USING (org_id = current_setting('neptiq.org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('neptiq.org_id', true)::uuid);
