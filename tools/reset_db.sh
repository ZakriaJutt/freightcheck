#!/bin/sh
# Drop and re-create the public schema of ONE FreightCheck database, then migrate.
# Usage: tools/reset_db.sh freightcheck_test
set -eu
DB="$1"
case "$DB" in freightcheck_dev|freightcheck_test) ;; *) echo "refusing: $DB is not a FreightCheck database" >&2; exit 2;; esac
psql -q -h localhost -U zakria -d postgres -f tools/db_bootstrap.sql
psql -q -h localhost -U zakria -d "$DB" -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public AUTHORIZATION zakria;"
cd packages/db && FC_MIGRATION_DATABASE_URL="postgresql+psycopg://zakria@localhost:5432/$DB" ../../.venv/bin/alembic upgrade head
