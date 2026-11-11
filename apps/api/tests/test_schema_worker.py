"""IT-08 model and migration parity, single head; IT-13 worker without web modules, correlation ID; settings."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from conftest import TEST_ENV, World
from scenario import Pilot
from sqlalchemy import text

from fc_db.tables import TENANT_TABLES, metadata
from fc_platform.settings import Settings, SettingsError

REPO = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO / "packages" / "db" / "alembic.ini"


def test_it08_no_drift_between_models_and_migrations(owner_engine) -> None:  # type: ignore[no-untyped-def]
    with owner_engine.connect() as conn:
        mc = MigrationContext.configure(conn, opts={"compare_type": True, "compare_server_default": False})
        diffs = compare_metadata(mc, metadata)
    assert diffs == [], diffs


def test_it08_checks_exclusion_and_rls_match_models(owner_engine) -> None:  # type: ignore[no-untyped-def]
    with owner_engine.connect() as conn:
        db_checks = set(
            conn.execute(
                text(
                    "select conrelid::regclass::text || '.' || conname from pg_constraint "
                    "where contype = 'c' and connamespace = 'public'::regnamespace"
                )
            ).scalars()
        )
        db_excl = set(conn.execute(text("select conname from pg_constraint where contype = 'x'")).scalars())
        rls = dict(
            conn.execute(
                text(
                    "select relname, relrowsecurity and relforcerowsecurity from pg_class "
                    "where relnamespace = 'public'::regnamespace and relkind = 'r'"
                )
            ).all()
        )
        policies = set(conn.execute(text("select tablename from pg_policies where policyname = 'tenant_isolation'")).scalars())
    model_checks = set()
    model_excl = set()
    for t in metadata.tables.values():
        for c in t.constraints:
            kind = type(c).__name__
            if kind == "CheckConstraint":
                model_checks.add(f"{t.name}.{c.name}")
            elif kind == "ExcludeConstraint":
                model_excl.add(c.name)
    assert model_checks == db_checks
    assert model_excl == db_excl == {"ex_rate_document_confirmed_overlap"}
    for t in (*TENANT_TABLES, "tenant"):
        assert rls[t] is True, t
        assert t in policies, t
    tenant_cols = {t.name for t in metadata.tables.values() if "tenant_id" in t.c}
    assert tenant_cols == set(TENANT_TABLES), "every table with tenant_id must be under RLS"


def test_it17_single_migration_head() -> None:
    cfg = Config(str(ALEMBIC_INI))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, heads


BLOCKER = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in {'fastapi', 'starlette', 'uvicorn', 'fc_api', 'httpx'}:
            raise ImportError('web module blocked: ' + name)
        return None
sys.meta_path.insert(0, Block())
from fc_worker.main import main
rc = main(['--once'])
assert not any(m.split('.')[0] in {'fastapi', 'starlette', 'uvicorn', 'fc_api'} for m in sys.modules)
sys.exit(rc)
"""


def test_it13_worker_runs_without_web_modules_and_carries_correlation_id(world: World) -> None:
    p = Pilot(world)
    body = {
        "carrier_account_id": p.carrier_id,
        "invoice_number": "IT13-1",
        "pro_number": "PRO-IT13",
        "invoice_date": "2026-03-16",
        "pickup_date": "2026-03-14",
        "billed_weight_lb": "1200",
        "billed_class": "70",
        "total_cents": 26630,
        "lines": [
            {"line_no": 1, "charge_type": "linehaul", "amount_cents": 20328},
            {"line_no": 2, "charge_type": "fuel", "amount_cents": 6302},
        ],
    }
    p.auditor.post("/api/v1/invoices", body, expect=201, headers={"X-Correlation-ID": "it13corr0001"})
    env = {k: v for k, v in os.environ.items() if not k.startswith("FC_")} | TEST_ENV
    proc = subprocess.run([sys.executable, "-c", BLOCKER], env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    lines = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.startswith("{")]
    done = [ln for ln in lines if ln["event"] == "job.done"]
    assert done and done[0]["correlation_id"] == "it13corr0001"
    for ln in lines:
        assert not any(k.endswith("_cents") or k in ("amount", "price", "rate") for k in ln), ln
    assert "20328" not in proc.stdout and "203.28" not in proc.stdout


def test_settings_refuse_unknown_and_missing_keys() -> None:
    with pytest.raises(SettingsError, match="unknown"):
        Settings.from_env({**TEST_ENV, "FC_TYPO": "1"})
    missing = dict(TEST_ENV)
    missing.pop("FC_DATABASE_URL")
    with pytest.raises(SettingsError, match="missing"):
        Settings.from_env(missing)
    with pytest.raises(SettingsError, match="FC_FIXED_TODAY"):
        Settings.from_env({**TEST_ENV, "FC_ENV": "prod"})
    assert Settings.from_env(TEST_ENV).api_port == 8102


def test_readyz_reports_schema_head(world: World) -> None:
    from fastapi.testclient import TestClient

    r = TestClient(world.app).get("/readyz")
    assert r.status_code == 200 and r.json()["schema"] == "0003"
