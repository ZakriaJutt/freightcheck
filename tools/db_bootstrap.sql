-- Idempotent: the non-superuser application role used by the API, the worker and every
-- isolation test. Superusers bypass row-level security, so the app never uses one.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'freightcheck_app') THEN
    CREATE ROLE freightcheck_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END $$;
ALTER ROLE freightcheck_app NOSUPERUSER NOBYPASSRLS;
