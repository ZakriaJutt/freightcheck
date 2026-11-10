"""Regression tests from review round 1 (reviewer API cases B1-B9; findings B1-001 to B1-011)."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import APP_URL, World, set_today
from scenario import INDEX, Pilot, run_worker, upload

from fc_platform.db import engine_for
from fc_worker.main import enqueue_daily_sweeps

SENT = {"sent_on": "2026-04-01", "sent_to": "claims@carrier.example"}


def result(inv: dict[str, Any], code: str) -> dict[str, Any]:
    return next(r for r in inv["results"] if r["check_code"] == code)


def rate_confirmation_for_pro(p: Pilot, amount: str = "203.28") -> dict[str, Any]:
    """A rate confirmation for PRO-5550001 at a flat 203.28: C-02 becomes a pass (billed 203.28)."""
    src = upload(p.auditor, "rate_document", f"rc-{amount}")
    d = p.auditor.post(
        "/api/v1/rate-documents",
        {
            "carrier_account_id": p.carrier_id,
            "doc_type": "rate_confirmation",
            "effective_from": "2026-03-01",
            "effective_to": "2026-03-31",
            "scope_key": "PRO-5550001",
            "date_basis": "pickup_date",
            "date_basis_source_page": 1,
            "source_file_id": src,
        },
        expect=201,
    ).json()
    p.auditor.post(
        f"/api/v1/rate-documents/{d['id']}/rules",
        {"rules": [{"rule_type": "linehaul", "params": {"basis": "flat", "amount": amount}}]},
        expect=201,
    )
    return dict(p.approver.post(f"/api/v1/rate-documents/{d['id']}/confirm", expect=200).json())


# ------------------------------------------------------------------ B1-001


def test_b3_new_governing_document_after_approval_marks_stale_and_blocks_send(world: World) -> None:
    p = Pilot(world)
    c = p.approved_claim(p.invoice())
    conf = rate_confirmation_for_pro(p)
    assert conf["marked_claims"]["stale"] == [c["id"]]
    r = p.approver.post(f"/api/v1/claims/{c['id']}/sent", SENT, expect=409).json()
    assert r["code"] == "STALE_BASIS"


def test_b4_new_governing_document_after_send_flags_claim(world: World) -> None:
    """Old total 27.72 + 12.99 = 40.71; on the rate confirmation C-02 passes and C-03 is 63.02 − 28.5% × 203.28
    (57.93) = 5.09, which the banner shows as the new fuel amount."""
    p = Pilot(world)
    sent = p.sent_claim(p.invoice())
    conf = rate_confirmation_for_pro(p)
    assert conf["marked_claims"]["changed_after_send"] == [sent["id"]]
    s = p.approver.get(f"/api/v1/claims/{sent['id']}").json()
    assert s["basis_changed_after_send"] is True
    assert (s["banner"]["old_total_cents"], s["banner"]["new_total_cents"]) == (4071, 509)
    assert p.viewer.get("/api/v1/reports/basis-metrics").json()["wrong_basis_sent"] == 1


def test_send_refused_when_basis_changed_even_if_no_flag_was_set(world: World, owner_engine) -> None:  # type: ignore[no-untyped-def]
    """Defence in depth: the send recomputes; a flag missed by marking does not let the claim out."""
    from sqlalchemy import text

    p = Pilot(world)
    c = p.approved_claim(p.invoice())
    rate_confirmation_for_pro(p)
    with owner_engine.begin() as conn:
        conn.execute(text("update claim set stale_basis = false where id = :i"), {"i": c["id"]})
    assert p.approver.post(f"/api/v1/claims/{c['id']}/sent", SENT, expect=409).json()["code"] == "STALE_BASIS"


# ------------------------------------------------------------------ B1-002


def test_b2_send_after_contest_by_needs_override_with_approver(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    p = Pilot(world)
    inv = p.invoice()  # contest-by 12 Sep 2026
    set_today(monkeypatch, "2026-09-12")
    c = p.approved_claim(inv)
    set_today(monkeypatch, "2026-09-30")
    body = {"sent_on": "2026-09-30", "sent_to": "claims@carrier.example"}
    assert p.approver.post(f"/api/v1/claims/{c['id']}/sent", body, expect=409).json()["code"] == "PAST_CONTEST_BY"
    ok = p.approver.post(
        f"/api/v1/claims/{c['id']}/sent", {**body, "override_reason": "carrier accepts late claims in writing"}, expect=200
    ).json()
    assert ok["late_send_reason"] == "carrier accepts late claims in writing" and ok["late_send_by"] == str(p.approver.user_id)
    assert p.viewer.get("/api/v1/reports/basis-metrics").json()["approvals_by_date_override"] == 1


def test_sweep_expires_unsent_claims_past_contest_by_and_reminds_once(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date

    p = Pilot(world)
    draft = p.draft_claim(p.invoice())  # contest-by 12 Sep 2026
    engine = engine_for(APP_URL)
    assert enqueue_daily_sweeps(engine, date(2026, 9, 9)) >= 1  # 3 days left
    assert enqueue_daily_sweeps(engine, date(2026, 9, 9)) == 0  # idempotent per run date
    run_worker()
    run_worker()
    set_today(monkeypatch, "2026-09-13")
    enqueue_daily_sweeps(engine, date(2026, 9, 13))
    run_worker()
    c = p.approver.get(f"/api/v1/claims/{draft['id']}").json()
    assert c["status"] == "expired" and c["events"][-1]["event_type"] == "expired"
    assert (
        p.approver.post(f"/api/v1/claims/{draft['id']}/approve", {"override_reason": "x"}, expect=409).json()["code"]
        == "NOT_DRAFT"
    )
    from sqlalchemy import text

    from fc_platform.tenant import tenant_transaction

    with tenant_transaction(engine, p.tenant_id) as conn:
        kinds = conn.execute(text("select kind from notification")).scalars().all()
    assert kinds == ["deadline_3"]


# ------------------------------------------------------------------ B1-003, B1-004, B1-005


def test_b1_disagreeing_carrier_and_tenant_fuel_values_fail_closed(world: World) -> None:
    p = Pilot(world)
    v = p.auditor.post(
        "/api/v1/fuel-index",
        {
            "carrier_account_id": p.carrier_id,
            "index_name": INDEX,
            "week_start": "2026-03-09",
            "price": "3.72",
            "published_on": "2026-03-09",
            "source_note": "synthetic",
        },
        expect=201,
    ).json()
    p.approver.post(f"/api/v1/fuel-index/{v['id']}/confirm", expect=200)
    c3 = result(p.invoice(), "C-03")
    assert (c3["status"], c3["exception_code"]) == ("exception", "FSC_BASIS_MISSING")


def test_unconfirmed_rate_confirmation_blocks_linehaul_and_fuel(world: World) -> None:
    p = Pilot(world)
    src = upload(p.auditor, "rate_document", "rc-entered")
    d = p.auditor.post(
        "/api/v1/rate-documents",
        {
            "carrier_account_id": p.carrier_id,
            "doc_type": "rate_confirmation",
            "effective_from": "2026-03-01",
            "scope_key": "PRO-5550001",
            "date_basis": "pickup_date",
            "source_file_id": src,
        },
        expect=201,
    ).json()
    p.auditor.post(
        f"/api/v1/rate-documents/{d['id']}/rules",
        {"rules": [{"rule_type": "linehaul", "params": {"basis": "flat", "amount": "150.00"}}]},
        expect=201,
    )
    inv = p.invoice()
    assert result(inv, "C-02")["status"] == "exception"
    assert result(inv, "C-03")["exception_code"] == "FSC_BASIS_MISSING"  # no expected linehaul, no fuel base


def test_lane_key_on_invoice_selects_lane_document(world: World) -> None:
    """Lane sheet 40.00/cwt: 12 × 40.00 = 480.00 × 0.38 = 182.40; billed 203.28 → variance 20.88."""
    p = Pilot(world)
    src = upload(p.auditor, "rate_document", "lane")
    d = p.auditor.post(
        "/api/v1/rate-documents",
        {
            "carrier_account_id": p.carrier_id,
            "doc_type": "contract_rate_sheet",
            "effective_from": "2026-01-01",
            "scope_key": "LANE-CHI-DET",
            "date_basis": "pickup_date",
            "date_basis_source_page": 1,
            "source_file_id": src,
        },
        expect=201,
    ).json()
    p.auditor.post(
        f"/api/v1/rate-documents/{d['id']}/rules",
        {
            "rules": [
                {"rule_type": "linehaul", "params": {"basis": "per_cwt", "rate": "40.00", "class": "70"}},
                {"rule_type": "discount", "params": {"percent": "62"}},
            ]
        },
        expect=201,
    )
    p.approver.post(f"/api/v1/rate-documents/{d['id']}/confirm", expect=200)
    assert result(p.invoice(number="L-0", pro="PRO-L0"), "C-02")["exception_code"] == "GOVERNING_RATE_MISSING"
    c2 = result(p.invoice(number="L-1", pro="PRO-L1", lane_key="LANE-CHI-DET"), "C-02")
    assert (c2["expected_cents"], c2["variance_cents"]) == (18240, 2088)


# ------------------------------------------------------------------ B1-006


def test_b5_corrected_invoice_is_not_flagged_as_duplicate_and_duplicates_are_not_claimable(world: World) -> None:
    p = Pilot(world)
    orig = p.invoice()
    rev = p.invoice(revision_of=orig["id"])
    assert result(rev, "C-01")["status"] == "pass"
    resent = p.invoice(number="884213", pro="PRO-5550001", ap_received="2026-03-17")  # same number again, not a revision
    c1 = result(resent, "C-01")
    assert c1["status"] == "variance" and c1["variance_cents"] is None
    f = next(x for x in p.auditor.get(f"/api/v1/findings?invoice_id={resent['id']}").json() if x["check_code"] == "C-01")
    assert (
        p.auditor.post(f"/api/v1/findings/{f['id']}/decision", {"decision": "confirmed_for_claim"}, expect=409).json()["code"]
        == "NOT_CLAIMABLE"
    )


# ------------------------------------------------------------------ B1-007, B1-011


def test_b6_b7_settlement_caps_decision_required_and_evidence_purpose(world: World) -> None:
    p = Pilot(world)
    sent = p.sent_claim(p.invoice())
    cm = upload(p.approver, "settlement_evidence", "cm")
    wrong = upload(p.approver, "invoice", "not-evidence")
    cid = sent["id"]
    base = {"method": "credit_memo", "settled_on": "2026-04-01", "evidence_file_id": cm}
    assert (
        p.approver.post(
            f"/api/v1/claims/{cid}/settlements", {**base, "amount_cents": 90000, "carrier_reference": "A"}, expect=422
        ).json()["code"]
        == "ABOVE_ACCEPTED"
    )
    assert (
        p.approver.post(
            f"/api/v1/claims/{cid}/settlements",
            {**base, "amount_cents": 100, "evidence_file_id": wrong, "carrier_reference": "W"},
            expect=422,
        ).json()["code"]
        == "WRONG_EVIDENCE"
    )
    one_cent = p.approver.post(
        f"/api/v1/claims/{cid}/settlements", {**base, "amount_cents": 1, "carrier_reference": "B"}, expect=201
    ).json()
    assert one_cent["status"] == "sent" and one_cent["amounts"] == {
        "claimed_cents": 4071,
        "accepted_cents": None,
        "settled_cents": 1,
    }
    ev = upload(p.approver, "carrier_response", "decision")
    over = {
        "event_type": "decision_accepted",
        "occurred_on": "2026-04-01",
        "client_event_id": "acc-1",
        "amount_cents": 90000,
        "evidence_file_id": ev,
    }
    assert p.approver.post(f"/api/v1/claims/{cid}/events", over, expect=422).json()["code"] == "ABOVE_CLAIMED"
    bad_ev = {**over, "amount_cents": None, "evidence_file_id": wrong}
    assert p.approver.post(f"/api/v1/claims/{cid}/events", bad_ev, expect=422).json()["code"] == "WRONG_EVIDENCE"
    acc = p.approver.post(f"/api/v1/claims/{cid}/events", {**over, "amount_cents": None}, expect=201).json()
    assert acc["amounts"]["accepted_cents"] == 4071 and acc["status"] == "accepted"
    done = p.approver.post(
        f"/api/v1/claims/{cid}/settlements", {**base, "amount_cents": 4070, "carrier_reference": "C"}, expect=201
    ).json()
    assert done["status"] == "settled" and done["amounts"]["settled_cents"] == 4071
    excess = {**base, "amount_cents": 500, "carrier_reference": "D"}
    p.approver.post(f"/api/v1/claims/{cid}/settlements", excess, expect=422)
    rec = p.approver.post(
        f"/api/v1/claims/{cid}/settlements", {**excess, "excess_reason": "carrier added interest"}, expect=201
    ).json()
    assert rec["amounts"]["settled_cents"] == 4571


# ------------------------------------------------------------------ B1-008, B1-009, B1-010


def test_b8_future_or_post_forward_receipt_refused(world: World) -> None:
    p = Pilot(world)
    r = p.auditor.post(
        "/api/v1/invoices",
        {
            "carrier_account_id": p.carrier_id,
            "invoice_number": "X-1",
            "invoice_date": "2026-03-16",
            "total_cents": 100,
            "lines": [{"line_no": 1, "charge_type": "other", "amount_cents": 100}],
            "receipt_evidence": {"user_entered_on": "2026-03-25", "user_note": "clerk"},
            "forwarded_received_at": "2026-03-20T09:00:00Z",
        },
        expect=422,
    ).json()
    assert r["code"] == "RECEIPT_DATE_IMPOSSIBLE"
    r2 = p.auditor.post(
        "/api/v1/invoices",
        {
            "carrier_account_id": p.carrier_id,
            "invoice_number": "X-2",
            "invoice_date": "2026-03-16",
            "total_cents": 100,
            "lines": [{"line_no": 1, "charge_type": "other", "amount_cents": 100}],
            "receipt_evidence": {"ap_received_on": "2026-12-01"},
        },
        expect=422,
    ).json()
    assert r2["code"] == "RECEIPT_DATE_IMPOSSIBLE"


def test_b9_sent_on_in_future_or_before_approval_refused(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    p = Pilot(world)
    c = p.approved_claim(p.invoice())  # approved on 1 Apr 2026
    p.approver.post(f"/api/v1/claims/{c['id']}/sent", {**SENT, "sent_on": "2027-01-15"}, expect=422)
    p.approver.post(f"/api/v1/claims/{c['id']}/sent", {**SENT, "sent_on": "2026-03-31"}, expect=422)


def test_unexpected_error_returns_json_with_correlation_id(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    import fc_api.claims as claims_mod

    p = Pilot(world)
    c = p.draft_claim(p.invoice())

    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(claims_mod, "claim_out", boom)
    client = TestClient(world.app, raise_server_exceptions=False)
    client.cookies = p.viewer.client.cookies
    r = client.get("/api/v1/claims/00000000-0000-4000-8000-000000000000", headers={"X-Correlation-ID": "b1010corr"})
    assert r.status_code == 404  # unknown id still 404
    r = client.get(f"/api/v1/claims/{c['id']}", headers={"X-Correlation-ID": "b1010corr"})
    assert r.status_code == 500 and r.json() == {
        "code": "INTERNAL_ERROR",
        "message": "unexpected error; quote the correlation ID",
        "correlation_id": "b1010corr",
    }
