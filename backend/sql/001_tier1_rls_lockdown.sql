-- 001_tier1_rls_lockdown.sql
-- Tier-1 RLS lockdown: enable Row Level Security on every application table
-- with NO policies (default deny) and revoke direct access from Supabase's
-- public-facing roles.
--
-- Effect:
--   * anon / authenticated / service_role can no longer read or write these
--     tables through PostgREST / supabase-js, even with valid API keys.
--   * The Aruvi backend is unaffected: it connects as the table OWNER
--     (postgres), and owners bypass RLS unless FORCE ROW LEVEL SECURITY is
--     set (we do NOT force).
--
-- Idempotent: safe to re-run at any time (e.g. after adding new tables).

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'users',
        'files',
        'folders',
        'grab_groups',
        'login_codes',
        'refresh_sessions',
        'watch_progress'
    ]
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    END LOOP;
END $$;

-- Belt and braces: strip table grants from Supabase's API roles if they exist.
DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
        END IF;
    END LOOP;
END $$;
