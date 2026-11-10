"""IT-01 cross-tenant denial on API, worker and file links; RLS without context; T-2.2.4 audit rollback."""

from __future__ import annotations

import logging
import uuid

import pytest
from conftest import APP_URL, World
from scenario import Pilot, run_worker, upload
from sqlalchemy import func, select, text

from fc_db import ops
from fc_db.tables import TENANT_TABLES, audit_event, job
from fc_platform.db import engine_for
from fc_platform.tenant import tenant_transaction


@pytest.fixture
def two(world: World) -> tuple[Pilot, Pilot, dict, dict]:  # type: ignore[type-arg]
    t1 = Pilot(world, "Synthetic Shipper T1")
    t2 = Pilot(world, "Synthetic Shipper T2")
    inv1 = t1.invoice()
    inv2 = t2.invoice()  # same invoice number and PRO in another tenant: allowed, never a duplicate
    c2 = t2.sent_claim(inv2)
    return t1, t2, inv1, {"invoice": inv2, "claim": c2}


def test_rls_without_tenant_context_returns_zero_rows(two, app_engine) -> None:  # type: ignore[no-untyped-def]
    with app_engine.connect() as conn:
        for t in (*TENANT_TABLES, "tenant"):
            assert conn.execute(text(f"select count(*) from {t}")).scalar() == 0, t
    with tenant_transaction(app_engine, two[0].tenant_id) as conn:
        assert conn.execute(text("select count(distinct tenant_id) from invoice")).scalar() == 1
        assert conn.execute(text("select count(*) from claim")).scalar() == 0  # T1 has no claim; T2's is invisible


def test_rls_refuses_writes_into_another_tenant(two, app_engine) -> None:  # type: ignore[no-untyped-def]
    t1, t2, _, _ = two
    with pytest.raises(Exception, match="row-level security"):
        with tenant_transaction(app_engine, t1.tenant_id) as conn:
            conn.execute(audit_event.insert().values(tenant_id=t2.tenant_id, action="x", entity_type="x"))


def test_it01_api_returns_404_for_every_foreign_id(two, caplog) -> None:  # type: ignore[no-untyped-def]
    t1, t2, _, other = two
    inv2, c2 = other["invoice"], other["claim"]
    f2 = t2.auditor.get(f"/api/v1/findings?invoice_id={inv2['id']}").json()[0]["id"]
    file2 = upload(t2.approver, "carrier_response", "t2-file")
    caplog.set_level(logging.WARNING, logger="fc_api")
    for path in (
        f"/api/v1/invoices/{inv2['id']}",
        f"/api/v1/claims/{c2['id']}",
        f"/api/v1/rate-documents/{t2.contract_id}",
        f"/api/v1/files/{file2}/url",
        f"/api/v1/findings?invoice_id={inv2['id']}",
    ):
        assert t1.approver.get(path, expect=404).json()["code"] == "NOT_FOUND", path
    for path, body in (
        (f"/api/v1/claims/{c2['id']}/approve", {}),
        (
            f"/api/v1/claims/{c2['id']}/events",
            {"event_type": "acknowledged", "occurred_on": "2026-04-02", "client_event_id": "x"},
        ),
        (f"/api/v1/rate-documents/{t2.contract_id}/confirm", None),
        (f"/api/v1/fuel-index/{t2.fv_0309}/confirm", None),
        (f"/api/v1/findings/{f2}/decision", {"decision": "dismissed", "reason": "x"}),
        ("/api/v1/claims", {"invoice_id": inv2["id"], "origin": "pilot"}),
    ):
        assert t1.approver.post(path, body, expect=404).json()["code"] == "NOT_FOUND", path
    # A T1 settlement may not cite a T2 file as evidence.
    c1 = t1.sent_claim(t1.invoice(number="884999", pro="PRO-T1-9"))
    t1.approver.post(
        f"/api/v1/claims/{c1['id']}/settlements",
        {"method": "credit_memo", "amount_cents": 100, "settled_on": "2026-04-02", "evidence_file_id": file2},
        expect=404,
    )
    assert any(getattr(r, "fields", {}).get("entity") for r in caplog.records if r.getMessage() == "id.not_found")
    # T2's claim is untouched.
    assert t2.approver.get(f"/api/v1/claims/{c2['id']}").json()["status"] == "sent"


def test_it01_worker_job_of_t1_naming_a_t2_invoice_fails_closed(two) -> None:  # type: ignore[no-untyped-def]
    t1, t2, _, other = two
    eng = engine_for(APP_URL)
    with tenant_transaction(eng, t1.tenant_id) as conn:
        jid = ops.enqueue_job(conn, t1.tenant_id, "run_checks", "foreign", {"invoice_id": other["invoice"]["id"]})
    run_worker()
    with tenant_transaction(eng, t1.tenant_id) as conn:
        row = conn.execute(select(job).where(job.c.id == jid)).one()
    assert (row.state, row.last_error) == ("failed", "NotFound: not found")
    assert t2.auditor.get(f"/api/v1/invoices/{other['invoice']['id']}").json()["run_no"] == 1


def test_it01_signed_link_is_bound_to_its_key_and_host(two) -> None:  # type: ignore[no-untyped-def]
    t1, _, _, _ = two
    fid = upload(t1.auditor, "invoice", "t1-link")
    url = t1.auditor.get(f"/api/v1/files/{fid}/url").json()["url"]
    assert url.startswith("http://localhost:8102/files/raw?")
    path = url.removeprefix("http://localhost:8102")
    assert t1.auditor.client.get(path).status_code == 200
    tampered = path.replace("&s=", "&s=0")
    assert t1.auditor.client.get(tampered).status_code == 404
    assert "t1-link" not in url  # the user's file name never appears in a key


def test_audit_row_rolls_back_with_its_change(world: World, app_engine) -> None:  # type: ignore[no-untyped-def]
    tid = world.tenant()
    with pytest.raises(RuntimeError):
        with tenant_transaction(app_engine, tid) as conn:
            ops.audit(
                conn, tenant_id=tid, actor_user_id=None, actor_role="test", action="x", entity_type="x", entity_id=uuid.uuid4()
            )
            raise RuntimeError("change failed")
    with tenant_transaction(app_engine, tid) as conn:
        assert conn.execute(select(func.count()).select_from(audit_event)).scalar() == 0


def test_app_role_cannot_update_or_delete_append_only_rows(world: World, app_engine) -> None:  # type: ignore[no-untyped-def]
    tid = world.tenant()
    with pytest.raises(Exception, match="permission denied"):
        with tenant_transaction(app_engine, tid) as conn:
            conn.execute(text("delete from audit_event"))
