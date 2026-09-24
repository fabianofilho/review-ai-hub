-- =============================================================================
-- ci_supabase_stub.sql
-- =============================================================================
-- Minimal stand-in for the Supabase-owned objects that the Alembic migrations
-- reference, so `alembic upgrade head` can run against a plain Postgres in CI.
--
-- This is NOT a Supabase schema. It only provides what the application
-- migrations need to exist:
--   - roles: anon, authenticated, service_role (targets of GRANT / TO clauses)
--   - auth.users (id, email, raw_user_meta_data): FK target, lookup table and
--     target of the handle_new_user trigger (supabase/migrations/0002)
--   - auth.uid(), auth.role(): helpers used by RLS policies and functions
--   - storage.buckets: target of supabase/migrations/0001
--   - storage.objects (bucket_id, name): target of the article file policies
--
-- CI applies this file, then supabase/migrations/*.sql in order, then
-- `alembic upgrade head`: the same order Supabase CLI and Alembic follow.
--
-- Real Supabase projects get these objects from Supabase itself; never apply
-- this file to a Supabase database.
-- =============================================================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    CREATE ROLE service_role NOLOGIN BYPASSRLS;
  END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
  id UUID PRIMARY KEY,
  email VARCHAR(255),
  raw_user_meta_data JSONB
);

-- Same contract as Supabase: read the caller from the request JWT claims,
-- NULL when there is no authenticated request.
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION auth.role() RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('request.jwt.claim.role', true), '')::text
$$;

CREATE SCHEMA IF NOT EXISTS storage;

CREATE TABLE IF NOT EXISTS storage.buckets (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  public BOOLEAN DEFAULT false
);

CREATE TABLE IF NOT EXISTS storage.objects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bucket_id TEXT,
  name TEXT,
  owner UUID,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
