-- RLS for audit_events. Plain org_id comparison — see db/policies/README.md
-- "Design". current_setting('neptiq.org_id', true) returns NULL when
-- unbound, and org_id = NULL is NULL (not true) in USING/WITH CHECK, so an
-- unbound or wrongly-bound session sees and can write zero rows: fails
-- closed.

ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;

CREATE POLICY audit_events_tenant_isolation ON audit_events
    USING (org_id = current_setting('neptiq.org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('neptiq.org_id', true)::uuid);
