# FreightCheck B1 commands. Python lives in .venv (`make venv`); no Docker (TRD Compose stays proposed).
PY := .venv/bin/python
PKGS := packages/core/fc_core packages/platform/fc_platform packages/db/fc_db apps/api/fc_api apps/worker/fc_worker

.PHONY: venv env dev migrate test-db test test-unit test-int lint typecheck check-boundaries check

venv:
	/opt/homebrew/bin/python3.12 -m venv .venv
	.venv/bin/pip install -q -r tools/requirements-dev.txt
	.venv/bin/pip install -q -e packages/core -e packages/platform -e packages/db -e apps/api -e apps/worker

env:
	$(PY) tools/make_env.py

dev:
	tools/dev.sh

migrate:
	set -a; . ./.env.local; set +a; cd packages/db && ../../.venv/bin/alembic upgrade head

test-db:
	tools/reset_db.sh freightcheck_test

test-unit:
	$(PY) -m pytest -c tools/pytest.ini --rootdir . packages/core/tests packages/platform/tests tools

test-int:
	$(PY) -m pytest -c tools/pytest.ini --rootdir . apps/api/tests

test: test-db test-unit test-int

lint:
	.venv/bin/ruff check --config tools/ruff.toml packages apps tools
	.venv/bin/ruff format --config tools/ruff.toml --check packages apps tools

typecheck:
	.venv/bin/mypy --config-file tools/mypy.ini $(PKGS)

check-boundaries:
	$(PY) tools/check_boundaries.py

check: lint typecheck check-boundaries test
