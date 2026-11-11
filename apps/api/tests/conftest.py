"""Integration harness: real Postgres (freightcheck_test), app role for every request and
isolation read, owner role only to seed fixtures and to truncate between tests.

`World.user` writes a signed-in session row directly: the B1 stand-in for sign-in, kept only
here so the core-path tests do not each walk the sign-in flow. B2 sign-in itself is tested end
to end in test_b2_sign_in.py through the real endpoints, Mailpit and MinIO."""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

TEST_ENV = {
    "FC_ENV": "test",
    "FC_DATABASE_URL": "postgresql+psycopg://freightcheck_app@localhost:5432/freightcheck_test",
    "FC_MIGRATION_DATABASE_URL": "postgresql+psycopg://zakria@localhost:5432/freightcheck_test",
    "FC_PUBLIC_BASE_URL": "http://localhost:8102",
    "FC_SIGNING_KEY": "test-signing-key-" + "0" * 32,
    "FC_DATA_KEY": "11" * 32,
    "FC_LOG_LEVEL": "INFO",
    "FC_FIXED_TODAY": "2026-04-01",
}
for _k in [k for k in os.environ if k.startswith("FC_")]:
    del os.environ[_k]
os.environ.update(TEST_ENV)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from fc_api.app import create_app  # noqa: E402
from fc_api.core import CSRF_HEADER, SESSION_COOKIE, token_hash  # noqa: E402
from fc_db.tables import app_user, membership, tenant, user_session  # noqa: E402
from fc_platform.auth import csrf_token  # noqa: E402
from fc_platform.settings import reset_settings_cache  # noqa: E402

OWNER_URL = TEST_ENV["FC_MIGRATION_DATABASE_URL"]
APP_URL = TEST_ENV["FC_DATABASE_URL"]


@pytest.fixture(scope="session")
def owner_engine():  # type: ignore[no-untyped-def]
    eng = create_engine(OWNER_URL)
    with eng.connect() as c:
        head = c.execute(text("select version_num from alembic_version")).scalar_one_or_none()
    assert head, "run `make test-db` first: the test database is not migrated"
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def app_engine():  # type: ignore[no-untyped-def]
    eng = create_engine(APP_URL)
    with eng.connect() as c:
        assert c.execute(text("select rolsuper or rolbypassrls from pg_roles where rolname = current_user")).scalar() is False
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def clean(owner_engine, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FC_STORAGE_DIR", str(tmp_path / "storage"))
    reset_settings_cache()
    with owner_engine.begin() as c:
        c.execute(text("SET LOCAL lock_timeout = '10s'"))  # fail, never hang, if a test leaks a lock
        c.execute(text("TRUNCATE tenant, app_user, auth_attempt CASCADE"))
    yield
    reset_settings_cache()


def set_today(monkeypatch: pytest.MonkeyPatch, iso: str) -> None:
    monkeypatch.setenv("FC_FIXED_TODAY", iso)
    reset_settings_cache()


@dataclass
class Api:
    client: TestClient
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    last: Any = field(default=None)

    def post(self, path: str, json: Any = None, key: str | None = None, expect: int | None = None, **kw: Any) -> Any:
        headers = {"Idempotency-Key": key or uuid.uuid4().hex, **kw.pop("headers", {})}
        r = self.client.post(path, json=json, headers=headers, **kw)
        self.last = r
        if expect is not None:
            assert r.status_code == expect, r.text
        return r

    def get(self, path: str, expect: int | None = 200, **kw: Any) -> Any:
        r = self.client.get(path, **kw)
        self.last = r
        if expect is not None:
            assert r.status_code == expect, r.text
        return r


class World:
    """Creates synthetic tenants and signed-in users."""

    def __init__(self, owner_engine: Any) -> None:
        self.owner = owner_engine
        self.app = create_app()

    def tenant(self, name: str = "Synthetic Shipper T1", plan: str = "pilot_gainshare") -> uuid.UUID:
        with self.owner.begin() as c:
            return c.execute(
                tenant.insert().values(name=name, plan=plan, inbox_token=secrets.token_hex(8)).returning(tenant.c.id)
            ).scalar_one()

    def user(self, tenant_id: uuid.UUID, role: str) -> Api:
        token = secrets.token_urlsafe(24)
        with self.owner.begin() as c:
            uid = c.execute(
                app_user.insert().values(email=f"{role}-{secrets.token_hex(4)}@shipper.example").returning(app_user.c.id)
            ).scalar_one()
            c.execute(membership.insert().values(tenant_id=tenant_id, user_id=uid, role=role))
            c.execute(
                user_session.insert().values(
                    user_id=uid,
                    active_tenant_id=tenant_id,
                    token_hash=token_hash(token),
                    stage="full",
                    expires_at=datetime.now(UTC) + timedelta(hours=12),
                )
            )
        client = TestClient(self.app, base_url="https://testserver", raise_server_exceptions=True)
        client.cookies.set(SESSION_COOKIE, token)
        client.headers[CSRF_HEADER] = csrf_token(token, TEST_ENV["FC_SIGNING_KEY"])
        return Api(client, tenant_id, uid, role)


@pytest.fixture
def world(owner_engine) -> Iterator[World]:  # type: ignore[no-untyped-def]
    yield World(owner_engine)
