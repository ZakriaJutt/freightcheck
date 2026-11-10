"""Core path over the API with worked arithmetic; IT-06, IT-07, IT-16, IT-19, IT-20, E2E-02 (API level)."""

from __future__ import annotations

import threading
import uuid

import pytest
from conftest import World, set_today
from scenario import Pilot, upload


def test_checks_through_worker_match_ut01_ut03_and_deadline_from_ap_stamp(world: World) -> None:
    """Linehaul 175.56 expected, 27.72 variance; fuel 50.03 expected (3.78 → 28.5%), 12.99 variance.
    AP stamp 16 Mar + 180 days = 12 Sep 2026."""
    p = Pilot(world)
    inv = p.invoice()
    res = {(r["check_code"], r["line_no"]): r for r in inv["results"]}
    assert (res[("C-02", 1)]["expected_cents"], res[("C-02", 1)]["variance_cents"]) == (17556, 2772)
    assert (res[("C-03", 2)]["expected_cents"], res[("C-03", 2)]["variance_cents"]) == (5003, 1299)
    assert res[("C-03", 2)]["fuel_index_price_id"] == p.fv_0309
    assert res[("C-01", None)]["status"] == "pass"
    assert inv["status"] == "variance"
    assert (inv["contest_by"], inv["deadline_basis"], inv["receipt_basis"]) == (
        "2026-09-12",
        "receipt_plus_180",
        "ap_received_stamp",
    )


def test_forwarded_late_invoice_uses_invoice_date_proxy_never_inbox_time(world: World) -> None:
    """Invoice 27 Feb, forward reached FreightCheck 28 May, no evidence: 27 Feb + 180 = 26 Aug, not 24 Nov."""
    p = Pilot(world)
    inv = p.invoice(ap_received=None, invoice_date="2026-02-27", forwarded_received_at="2026-05-28T15:00:00Z")
    assert (inv["contest_by"], inv["deadline_basis"], inv["receipt_basis"]) == (
        "2026-08-26",
        "invoice_date_proxy_plus_180",
        "unknown",
    )


def test_unconfirmed_fuel_value_blocks_fuel_check_and_linehaul_still_runs(world: World) -> None:
    p = Pilot(world)
    p.auditor.post(
        "/api/v1/fuel-index",
        {
            "index_name": "US_DIESEL_WEEKLY",
            "week_start": "2026-03-23",
            "price": "3.76",
            "published_on": "2026-03-23",
            "source_note": "synthetic",
        },
        expect=201,
    )
    inv = p.invoice(number="884600", pro="PRO-5550600", pickup_date="2026-03-25")
    res = {r["check_code"]: r for r in inv["results"]}
    assert (res["C-03"]["status"], res["C-03"]["exception_code"]) == ("exception", "INDEX_PRICE_UNCONFIRMED")
    assert res["C-02"]["variance_cents"] == 2772
    assert inv["status"] == "needs_input"


def test_overlapping_confirmed_document_refused_naming_the_revision(world: World) -> None:
    p = Pilot(world)
    src = upload(p.auditor, "rate_document", "overlap")
    d = p.auditor.post(
        "/api/v1/rate-documents",
        {
            "carrier_account_id": p.carrier_id,
            "doc_type": "contract_rate_sheet",
            "effective_from": "2026-06-01",
            "date_basis": "pickup_date",
            "source_file_id": src,
        },
        expect=201,
    ).json()
    assert d["date_basis_chosen_by_approver"] is True
    p.auditor.post(
        f"/api/v1/rate-documents/{d['id']}/rules", {"rules": [{"rule_type": "minimum", "params": {"amount": "1.00"}}]}, expect=201
    )
    r = p.approver.post(f"/api/v1/rate-documents/{d['id']}/confirm", expect=409).json()
    assert (
        r["code"] == "RATE_DOCUMENT_OVERLAP" and r["conflicting_document_id"] == p.contract_id and r["conflicting_revision"] == 1
    )


def test_auditor_cannot_confirm_or_approve(world: World) -> None:
    p = Pilot(world)
    c = p.draft_claim(p.invoice())
    assert p.auditor.post(f"/api/v1/claims/{c['id']}/approve", {}, expect=403).json()["code"] == "FORBIDDEN"
    assert c["amounts"] == {"claimed_cents": None, "accepted_cents": None, "settled_cents": 0}
    assert sum(ln["claimed_cents"] for ln in c["lines"]) == 4071


def test_it06_fuel_schedule_revision_with_earlier_start_makes_draft_stale_nothing_approved(world: World) -> None:
    """Revision 2 starts 1 Dec 2025 and moves the 3.750-3.799 band to 29.0%: 175.56 × 0.29 = 50.91,
    so the fuel line becomes 12.11 instead of 12.99."""
    p = Pilot(world)
    c = p.draft_claim(p.invoice())
    rev = p.auditor.post(f"/api/v1/rate-documents/{p.fuel_id}/revise", {"effective_from": "2025-12-01"}, expect=201).json()
    p.auditor.post(f"/api/v1/rate-documents/{rev['id']}/rules", {"rules": Pilot.fuel_rules("29.0"), "replace": True}, expect=201)
    conf = p.approver.post(f"/api/v1/rate-documents/{rev['id']}/confirm", expect=200).json()
    assert conf["marked_claims"]["stale"] == [c["id"]]
    r = p.approver.post(f"/api/v1/claims/{c['id']}/approve", {}, expect=409).json()
    assert r["code"] == "STALE_BASIS"
    old = {ln["finding"]: ln["claimed_cents"] for ln in r["old_lines"]}
    new = {ln["finding"]: ln["claimed_cents"] for ln in r["new_lines"]}
    assert (old["C-03:2"], new["C-03:2"]) == (1299, 1211)
    after = p.approver.get(f"/api/v1/claims/{c['id']}").json()
    assert after["status"] == "draft" and after["claimed_cents"] is None and after["approved_at"] is None
    # Redraft takes the corrected basis; approval then succeeds: 27.72 + 12.11 = 39.83.
    p.auditor.post(f"/api/v1/claims/{c['id']}/redraft", expect=200)
    ok = p.approver.post(f"/api/v1/claims/{c['id']}/approve", {}, expect=200).json()
    assert ok["claimed_cents"] == 3983 and ok["stale_basis"] is False


def test_it19_approval_past_contest_by_refused_then_allowed_with_reason(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    p = Pilot(world)
    c = p.draft_claim(p.invoice())  # contest-by 12 Sep 2026
    set_today(monkeypatch, "2026-09-13")
    r = p.approver.post(f"/api/v1/claims/{c['id']}/approve", {}, expect=409).json()
    assert r["code"] == "PAST_CONTEST_BY"
    ok = p.approver.post(
        f"/api/v1/claims/{c['id']}/approve", {"override_reason": "carrier agreed in writing to review"}, expect=200
    ).json()
    assert ok["status"] == "approved" and ok["late_override_reason"] == "carrier agreed in writing to review"
    assert p.viewer.get("/api/v1/reports/basis-metrics").json()["approvals_by_date_override"] == 1


def test_it19_override_is_audited(world: World, monkeypatch: pytest.MonkeyPatch, owner_engine) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    p = Pilot(world)
    c = p.draft_claim(p.invoice())
    set_today(monkeypatch, "2026-09-13")
    p.approver.post(f"/api/v1/claims/{c['id']}/approve", {"override_reason": "late but agreed"}, expect=200)
    with owner_engine.connect() as conn:
        actions = conn.execute(text("select action from audit_event where entity_id = :i"), {"i": c["id"]}).scalars().all()
    assert "claim.approved_late_override" in actions


def test_it20_correction_of_sent_fuel_value_flags_claim_and_draft_gets_stale(world: World) -> None:
    """Sent on 3.78 (28.5%: 50.03, line 12.99). Corrected to 3.74 (28.0%: 49.16, line 13.86).
    Old total 27.72 + 12.99 = 40.71; new 27.72 + 13.86 = 41.58."""
    p = Pilot(world)
    sent = p.sent_claim(p.invoice())
    draft = p.draft_claim(p.invoice(number="884500", pro="PRO-5550500"))
    corr = p.auditor.post(
        "/api/v1/fuel-index",
        {
            "index_name": "US_DIESEL_WEEKLY",
            "week_start": "2026-03-09",
            "price": "3.74",
            "published_on": "2026-03-09",
            "source_note": "publisher correction, synthetic",
            "revises_id": p.fv_0309,
        },
        expect=201,
    ).json()
    assert corr["revision"] == 2
    conf = p.approver.post(f"/api/v1/fuel-index/{corr['id']}/confirm", expect=200).json()
    assert conf["marked_claims"] == {"stale": [draft["id"]], "changed_after_send": [sent["id"]]}
    s = p.approver.get(f"/api/v1/claims/{sent['id']}").json()
    assert s["basis_changed_after_send"] is True and s["stale_basis"] is False
    b = s["banner"]
    assert (b["kind"], b["old_total_cents"], b["new_total_cents"]) == ("basis_changed_after_send", 4071, 4158)
    assert "40.71" in b["withdrawal_note"] and "41.58" in b["withdrawal_note"]
    d = p.approver.get(f"/api/v1/claims/{draft['id']}").json()
    assert d["stale_basis"] is True and d["basis_changed_after_send"] is False
    assert p.viewer.get("/api/v1/reports/basis-metrics").json()["wrong_basis_sent"] == 1
    w = p.approver.post(
        f"/api/v1/claims/{sent['id']}/events",
        {"event_type": "withdrawn", "occurred_on": "2026-04-02", "client_event_id": "wd-1", "reason_code": "wrong_rate_basis"},
        expect=201,
    ).json()
    assert w["status"] == "withdrawn" and w["basis_changed_after_send"] is False
    assert p.viewer.get("/api/v1/reports/basis-metrics").json()["wrong_basis_sent"] == 1


def test_e2e02_api_level_approved_unsent_blocked_and_sent_flagged(world: World) -> None:
    """API-level form of E2E-02 (no browser in B1)."""
    p = Pilot(world)
    approved = p.approved_claim(p.invoice())
    sent = p.sent_claim(p.invoice(number="884501", pro="PRO-5550501"))
    rev = p.auditor.post(f"/api/v1/rate-documents/{p.fuel_id}/revise", {}, expect=201).json()
    p.auditor.post(f"/api/v1/rate-documents/{rev['id']}/rules", {"rules": Pilot.fuel_rules("29.0"), "replace": True}, expect=201)
    p.approver.post(f"/api/v1/rate-documents/{rev['id']}/confirm", expect=200)
    blocked = p.approver.post(
        f"/api/v1/claims/{approved['id']}/sent", {"sent_on": "2026-04-02", "sent_to": "claims@carrier.example"}, expect=409
    ).json()
    assert blocked["code"] == "STALE_BASIS" and blocked["claim"]["banner"]["kind"] == "stale_basis"
    assert (blocked["claim"]["banner"]["old_total_cents"], blocked["claim"]["banner"]["new_total_cents"]) == (4071, 3983)
    flagged = p.approver.get(f"/api/v1/claims/{sent['id']}").json()
    assert flagged["banner"]["kind"] == "basis_changed_after_send" and "withdraw" in flagged["banner"]["withdrawal_note"]
    # Re-approval on the corrected basis unblocks the send.
    p.auditor.post(f"/api/v1/claims/{approved['id']}/redraft", expect=200)
    p.approver.post(f"/api/v1/claims/{approved['id']}/approve", {}, expect=200)
    done = p.approver.post(
        f"/api/v1/claims/{approved['id']}/sent", {"sent_on": "2026-04-02", "sent_to": "claims@carrier.example"}, expect=200
    ).json()
    assert done["status"] == "sent" and done["claimed_cents"] == 3983


def test_it07_settlement_needs_document_reversal_gives_negative_fee_line(world: World) -> None:
    """Partial acceptance 27.72; credit memo 27.72; fee 20% = 5.544 → 5.54; reversal → −5.54 next statement."""

    from conftest import APP_URL
    from scenario import run_worker

    from fc_db import ops
    from fc_platform.db import engine_for
    from fc_platform.tenant import tenant_transaction

    p = Pilot(world)
    c = p.sent_claim(p.invoice())
    ev = upload(p.approver, "carrier_response", "decision")
    memo = upload(p.approver, "settlement_evidence", "memo")
    no_doc = p.approver.post(
        f"/api/v1/claims/{c['id']}/settlements",
        {"method": "credit_memo", "amount_cents": 2772, "settled_on": "2026-03-30"},
        expect=422,
    ).json()
    assert no_doc["field"] == "evidence_file_id"
    sp = p.approver.post(
        f"/api/v1/claims/{c['id']}/settlements",
        {"method": "short_pay_accepted", "amount_cents": 2772, "settled_on": "2026-03-30", "evidence_file_id": memo},
        expect=409,
    )
    assert sp.json()["code"] == "NO_ACCEPTANCE"
    p.approver.post(
        f"/api/v1/claims/{c['id']}/events",
        {
            "event_type": "decision_partial",
            "occurred_on": "2026-03-28",
            "client_event_id": "dp-1",
            "amount_cents": 2772,
            "evidence_file_id": ev,
            "reason_code": "charge_supported_by_carrier",
        },
        expect=201,
    )
    mid = p.approver.get(f"/api/v1/claims/{c['id']}").json()
    assert mid["amounts"] == {"claimed_cents": 4071, "accepted_cents": 2772, "settled_cents": 0}
    assert mid["status"] == "partly_accepted"
    s = p.approver.post(
        f"/api/v1/claims/{c['id']}/settlements",
        {
            "method": "credit_memo",
            "amount_cents": 2772,
            "settled_on": "2026-03-30",
            "evidence_file_id": memo,
            "carrier_reference": "CM-1",
        },
        expect=201,
    ).json()
    assert s["amounts"] == {"claimed_cents": 4071, "accepted_cents": 2772, "settled_cents": 2772} and s["status"] == "settled"
    eng = engine_for(APP_URL)
    with tenant_transaction(eng, p.tenant_id) as conn:
        ops.enqueue_job(
            conn, p.tenant_id, "build_fee_statement", "2026-03", {"period_start": "2026-03-01", "period_end": "2026-03-31"}
        )
    run_worker()
    r = p.approver.post(
        f"/api/v1/settlements/{s['settlement_id']}/reverse", {"reason": "carrier reissued memo"}, expect=200
    ).json()
    assert r["amounts"]["settled_cents"] == 0 and r["status"] == "partly_accepted"
    with tenant_transaction(eng, p.tenant_id) as conn:
        ops.enqueue_job(
            conn, p.tenant_id, "build_fee_statement", "2026-04", {"period_start": "2026-04-01", "period_end": "2026-04-30"}
        )
    run_worker()
    stmts = p.viewer.get("/api/v1/fee-statements").json()
    assert [(st["period_start"], st["total_cents"]) for st in stmts] == [("2026-03-01", 554), ("2026-04-01", -554)]
    assert stmts[1]["lines"][0]["basis_cents"] == -2772


def test_it16_two_approvers_at_once_one_approval_and_double_click_replays(world: World) -> None:
    p = Pilot(world)
    c = p.draft_claim(p.invoice())
    second = world.user(p.tenant_id, "approver")
    results: list[int] = []

    def go(api) -> None:  # type: ignore[no-untyped-def]
        results.append(api.post(f"/api/v1/claims/{c['id']}/approve", {}).status_code)

    threads = [threading.Thread(target=go, args=(a,)) for a in (p.approver, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 409]
    second_body = second.last.json() if second.last.status_code == 409 else p.approver.last.json()
    assert second_body["code"] == "NOT_DRAFT" and second_body["claim"]["status"] == "approved"
    events = [e["event_type"] for e in p.approver.get(f"/api/v1/claims/{c['id']}").json()["events"]]
    assert events.count("approved") == 1
    # Double-click on "mark sent" with one key: the second call returns the stored result.
    key = uuid.uuid4().hex
    body = {"sent_on": "2026-04-01", "sent_to": "claims@carrier.example"}
    a = p.approver.post(f"/api/v1/claims/{c['id']}/sent", body, key=key, expect=200)
    b = p.approver.post(f"/api/v1/claims/{c['id']}/sent", body, key=key, expect=200)
    assert b.headers.get("Idempotent-Replay") == "true" and a.json() == b.json()
    assert (
        p.approver.post(f"/api/v1/claims/{c['id']}/sent", {**body, "sent_to": "other@x.example"}, key=key, expect=422).json()[
            "code"
        ]
        == "IDEMPOTENCY_KEY_REUSED"
    )


def test_post_without_idempotency_key_is_refused(world: World) -> None:
    p = Pilot(world)
    r = p.approver.client.post("/api/v1/carriers", json={"name": "Second Example Carrier", "carrier_type": "broker"})
    assert r.status_code == 428 and r.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"
