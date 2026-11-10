#!/bin/sh
# Local start without Docker (the TRD's Compose stack stays proposed): migrate the dev
# database, seed a synthetic tenant, start the API on FC_API_PORT and the worker, wait for
# /readyz, then stay in the foreground until Ctrl-C. Exits non-zero naming the unhealthy service.
set -eu
cd "$(dirname "$0")/.."
[ -f .env.local ] || { echo "no .env.local: run 'make env' first" >&2; exit 2; }
set -a
. ./.env.local
set +a
psql -q -h localhost -U zakria -d postgres -f tools/db_bootstrap.sql
(cd packages/db && ../../.venv/bin/alembic upgrade head)
.venv/bin/python tools/seed_dev.py
.venv/bin/uvicorn fc_api.app:create_app --factory --host 127.0.0.1 --port "$FC_API_PORT" &
API=$!
.venv/bin/python -m fc_worker &
WORKER=$!
trap 'kill $API $WORKER 2>/dev/null' INT TERM EXIT
i=0
until curl -fs "http://127.0.0.1:$FC_API_PORT/readyz" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 30 ]; then echo "api unhealthy: /readyz did not answer in 30 s" >&2; exit 1; fi
  if ! kill -0 "$API" 2>/dev/null; then echo "api exited" >&2; exit 1; fi
  sleep 1
done
if ! kill -0 "$WORKER" 2>/dev/null; then echo "worker exited" >&2; exit 1; fi
echo "ready: api http://127.0.0.1:$FC_API_PORT (readyz ok), worker pid $WORKER"
if [ "${DEV_SMOKE:-}" = "1" ]; then exit 0; fi
wait "$API"
