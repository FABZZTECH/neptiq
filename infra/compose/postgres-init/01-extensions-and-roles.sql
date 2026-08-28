-- NEPTIQ local database initialisation.
--
-- Runs ONCE, on first initialisation of an empty data directory. Mirrors what
-- the production provisioning does, so that a bug in the role split is found in
-- dev rather than discovered in production.
--
-- The role split is the important part. ARCHITECTURE §8: "No RLS-bypass role
-- for application code; only migrations run as owner." Two roles:
--
--   neptiq_migrator — owns the schema. Alembic connects as this. Table owners
--                     are exempt from their own RLS policies by default, which
--                     is exactly why the application must NOT be this role.
--   neptiq_app      — the application role. Owns nothing, has NOBYPASSRLS, and
--                     is therefore fully subject to every policy.
--
-- If the application connected as the owner, every RLS policy in db/policies/
-- would be silently inert and the tenant-isolation test would pass while
-- providing no isolation at all.

\set ON_ERROR_STOP on

-- Extensions required by §4. The compose healthcheck greps for exactly these
-- three, so adding one here means updating the healthcheck count.
CREATE EXTENSION IF NOT EXISTS vector;    -- pgvector: embeddings (§4, §11 T4)
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- trigram: fuzzy URL/content matching
CREATE EXTENSION IF NOT EXISTS citext;    -- case-insensitive email/slug columns

-- btree_gin is listed in §4 alongside pgvector and pg_trgm. It is created here
-- rather than in a migration because it is an infrastructure capability, not a
-- schema change.
CREATE EXTENSION IF NOT EXISTS btree_gin;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'neptiq_app') THEN
    -- NOBYPASSRLS is the default but stated explicitly: this is the single
    -- most important property of this role and it should be impossible to
    -- read this file and not notice it.
    CREATE ROLE neptiq_app LOGIN PASSWORD 'neptiq_dev_only' NOBYPASSRLS NOSUPERUSER
      NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END
$$;

-- The app role may use the schema and read/write rows, but may not create,
-- alter or drop anything. Schema change is a migration's job.
GRANT CONNECT ON DATABASE neptiq TO neptiq_app;
GRANT USAGE ON SCHEMA public TO neptiq_app;

-- Applies to tables created LATER by migrations, which is all of them.
ALTER DEFAULT PRIVILEGES FOR ROLE neptiq_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO neptiq_app;
ALTER DEFAULT PRIVILEGES FOR ROLE neptiq_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO neptiq_app;

-- Deliberately NOT granted: CREATE on schema public. An application that can
-- CREATE TABLE can create a table without an RLS policy.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Sanity assertions. A failure here aborts initialisation loudly rather than
-- leaving a half-configured database that looks fine until a tenant test runs.
DO $$
BEGIN
  IF (SELECT rolbypassrls FROM pg_roles WHERE rolname = 'neptiq_app') THEN
    RAISE EXCEPTION 'neptiq_app must NOT have BYPASSRLS (ARCHITECTURE §8)';
  END IF;
  IF (SELECT rolsuper FROM pg_roles WHERE rolname = 'neptiq_app') THEN
    RAISE EXCEPTION 'neptiq_app must NOT be a superuser (superusers bypass RLS)';
  END IF;
END
$$;
