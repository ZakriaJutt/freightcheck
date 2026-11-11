"""B2 file storage through the S3 API to local MinIO (IT-B2-20 .. IT-B2-22): upload and download
for one tenant, refusal for another, keys isolate tenant, purpose and source (R-13), no public
object URL, cleanup of every test object."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from b2_support import minio_env
from conftest import World

from fc_api.app import create_app
from fc_platform.settings import Settings, get_settings, reset_settings_cache
from fc_platform.storage import S3Storage

PDF = b"%PDF-1.4\n% synthetic carrier invoice for B2 storage tests\n"


@pytest.fixture
def s3_world(world: World, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[World, S3Storage, list[uuid.UUID]]]:
    for k, v in minio_env().items():
        monkeypatch.setenv(k, v)
    reset_settings_cache()
    s: Settings = get_settings()
    world.app = create_app(s)
    store = S3Storage(s.s3_endpoint, s.s3_region, s.s3_bucket, s.s3_access_key, s.s3_secret_key)
    tenants: list[uuid.UUID] = []
    yield world, store, tenants
    for tid in tenants:
        for key in store.keys(f"t/{tid}/"):
            store.delete(key)
        assert store.keys(f"t/{tid}/") == []


def upload(api, data: bytes = PDF, purpose: str = "invoice") -> dict:  # type: ignore[no-untyped-def]
    r = api.post("/api/v1/files", data={"purpose": purpose}, files={"file": ("carrier-invoice.pdf", data, "application/pdf")})
    assert r.status_code == 201, r.text
    body: dict = r.json()  # type: ignore[type-arg]
    return body


def test_it_b2_20_upload_and_download_through_minio_for_one_tenant(s3_world) -> None:  # type: ignore[no-untyped-def]
    world, store, tenants = s3_world
    tid = world.tenant()
    tenants.append(tid)
    auditor = world.user(tid, "auditor")
    f = upload(auditor)
    assert "storage_key" not in f and "carrier-invoice" not in str(f)
    keys = store.keys(f"t/{tid}/")
    assert len(keys) == 1
    _, ktid, purpose, source, rand = keys[0].split("/")
    assert (ktid, purpose, source) == (str(tid), "invoice", "upload") and uuid.UUID(rand)
    assert store.get(keys[0]) == PDF
    url = auditor.get(f"/api/v1/files/{f['id']}/url").json()["url"]
    q = parse_qs(urlparse(url).query)
    r = auditor.client.get("/files/raw", params={k: v[0] for k, v in q.items()})
    assert r.status_code == 200 and r.content == PDF
    assert r.headers["content-disposition"] == 'attachment; filename="document"'
    # The bucket is private: the object has no anonymous URL.
    anon = httpx.get(f"{get_settings().s3_endpoint}/{get_settings().s3_bucket}/{keys[0]}", timeout=10)
    assert anon.status_code == 403


def test_it_b2_21_other_tenant_refused_and_links_cannot_be_forged(s3_world) -> None:  # type: ignore[no-untyped-def]
    world, store, tenants = s3_world
    ta, tb = world.tenant("Synthetic Shipper A"), world.tenant("Synthetic Shipper B")
    tenants += [ta, tb]
    a, b = world.user(ta, "auditor"), world.user(tb, "auditor")
    f = upload(a)
    assert b.get(f"/api/v1/files/{f['id']}/url", expect=404).json()["code"] == "NOT_FOUND"
    url = a.get(f"/api/v1/files/{f['id']}/url").json()["url"]
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    # Tampered signature, or tenant B's prefix with A's signature: both 404.
    assert b.client.get("/files/raw", params={**q, "s": "0" * 64}).status_code == 404
    forged = q["k"].replace(str(ta), str(tb))
    assert b.client.get("/files/raw", params={**q, "k": forged}).status_code == 404
    # The same bytes uploaded by B are B's own object under B's prefix.
    fb = upload(b)
    assert fb["id"] != f["id"]
    assert len(store.keys(f"t/{tb}/")) == 1 and len(store.keys(f"t/{ta}/")) == 1


def test_it_b2_22_link_stops_working_when_the_file_row_is_gone(s3_world) -> None:  # type: ignore[no-untyped-def]
    world, store, tenants = s3_world
    tid = world.tenant()
    tenants.append(tid)
    auditor = world.user(tid, "auditor")
    f = upload(auditor, purpose="rate_document")
    url = auditor.get(f"/api/v1/files/{f['id']}/url").json()["url"]
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert q["k"].startswith(f"t/{tid}/rate_document/upload/")
    from sqlalchemy import text

    with world.owner.begin() as c:
        c.execute(text("delete from source_file where id = :i"), {"i": f["id"]})
    assert auditor.client.get("/files/raw", params=q).status_code == 404
