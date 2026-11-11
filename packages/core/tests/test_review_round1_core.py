"""Regression tests from review round 1 (reviewer core cases A1, A2, A4, A5, A5b, A6, A8, A11, A12;
findings B1-003 to B1-008). Each test names the case and the worked numbers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from core_fixtures import CARRIER, INDEX, contract_v, fuel_schedule, ut01_invoice

from fc_core.checks import run_checks
from fc_core.deadline import DeadlineInput, ReceiptEvidence, SweepClaim, compute_deadline, deadline_sweep
from fc_core.ledger import ClaimEvent, derive, settlement_cap
from fc_core.model import DuplicateCandidate, FuelIndexValue, InvoiceLine, RateDocument, RateRule, RunContext
from fc_core.resolver import Resolved, Unresolved, resolve, resolve_linehaul

FV_0309 = FuelIndexValue("fv-0309", INDEX, date(2026, 3, 9), date(2026, 3, 9), Decimal("3.78"), "confirmed")


def one(results, code):  # type: ignore[no-untyped-def]
    (r,) = [x for x in results if x.check_code == code]
    return r


# ------------------------------------------------------------------ B1-003 fuel base


def test_a1_no_linehaul_document_and_all_in_other_line_fuel_is_exception_not_claimable() -> None:
    """Old behaviour: base 0.00 (no linehaul-typed line), expected 0.00, billed 50.03 → claimable 50.03."""
    inv = replace(ut01_invoice(), lines=(InvoiceLine(1, "other", 17556), InvoiceLine(2, "fuel", 5003)), total_cents=22559)
    c3 = one(run_checks(inv, RunContext(documents=(fuel_schedule(),), fuel_values=(FV_0309,))), "C-03")
    assert (c3.status, c3.exception_code, c3.claimable) == ("exception", "FSC_BASIS_MISSING", False)


def test_a2_fuel_on_gross_with_no_linehaul_document_is_exception() -> None:
    """Old behaviour: 28.5% of billed net 175.56 = 50.03 against billed 131.67 (28.5% of gross 462.00) → false 81.64."""
    inv = replace(
        ut01_invoice(),
        lines=(InvoiceLine(1, "linehaul", 46200), InvoiceLine(2, "discount", -28644), InvoiceLine(3, "fuel", 13167)),
        total_cents=30723,
    )
    res = run_checks(inv, RunContext(documents=(fuel_schedule(),), fuel_values=(FV_0309,)))
    assert one(res, "C-02").exception_code == "GOVERNING_RATE_MISSING"
    assert (one(res, "C-03").status, one(res, "C-03").claimable) == ("exception", False)


def test_fuel_base_with_base_tariff_unavailable_is_exception() -> None:
    doc = RateDocument(
        "bt",
        1,
        "contract_rate_sheet",
        "confirmed",
        date(2026, 1, 1),
        None,
        "pickup_date",
        rules=(
            RateRule("bt-ref", "base_tariff_ref", {"tariff_name": "Base 500"}),
            RateRule("bt-d", "discount", {"percent": "62"}),
        ),
    )
    c3 = one(run_checks(ut01_invoice(), RunContext(documents=(doc, fuel_schedule()), fuel_values=(FV_0309,))), "C-03")
    assert c3.exception_code == "FSC_BASIS_MISSING"


# ------------------------------------------------------------------ B1-004 resolver


def test_a4_entered_rate_confirmation_for_the_pro_blocks_instead_of_contract_fallback() -> None:
    rc = replace(
        contract_v(1, status="entered", effective_to=None, rate="30.00", doc_id="rc"),
        doc_type="rate_confirmation",
        scope_key="PRO-5550001",
    )
    c2 = one(run_checks(ut01_invoice(with_fuel=False), RunContext(documents=(contract_v(2), rc))), "C-02")
    assert (c2.status, c2.exception_code, c2.claimable) == ("exception", "GOVERNING_RATE_MISSING", False)


def test_new_unconfirmed_contract_sheet_blocks_but_pending_revision_does_not() -> None:
    new_doc = contract_v(1, status="entered", effective_from=date(2026, 3, 1), effective_to=None, doc_id="rs-new")
    assert isinstance(resolve((contract_v(2), new_doc), "contract_rate_sheet", ut01_invoice()), Unresolved)
    pending = replace(new_doc, revises_id="rs-v2")
    res = resolve((contract_v(2), pending), "contract_rate_sheet", ut01_invoice())
    assert isinstance(res, Resolved) and res.document.id == "rs-v2"


def test_a5_specific_scope_with_missing_basis_date_does_not_fall_to_wildcard() -> None:
    lane = replace(contract_v(1, effective_to=None, doc_id="lane"), scope_key="LANE-A", date_basis="delivery_date")
    res = resolve((contract_v(2), lane), "contract_rate_sheet", ut01_invoice(), "LANE-A")
    assert isinstance(res, Unresolved) and res.exception_code == "GOVERNING_DATE_MISSING"


def test_a5b_lane_document_with_unknown_invoice_lane_blocks_and_known_lane_resolves() -> None:
    """Lane LANE-CHI-DET at 30.00/cwt: 12 × 30.00 = 360.00; × 0.38 = 136.80 → minimum 145.00."""
    lane = replace(contract_v(1, effective_to=None, rate="30.00", doc_id="lane-chi"), scope_key="LANE-CHI-DET")
    docs = (contract_v(2), lane)
    unknown = resolve_linehaul(docs, ut01_invoice())
    assert isinstance(unknown, Unresolved) and unknown.final
    known = resolve_linehaul(docs, replace(ut01_invoice(), lane_key="LANE-CHI-DET"))
    assert isinstance(known, Resolved) and known.document.id == "lane-chi"
    other_lane = resolve_linehaul(docs, replace(ut01_invoice(), lane_key="LANE-STL-KC"))
    assert isinstance(other_lane, Resolved) and other_lane.document.id == "rs-v2"
    c2 = one(run_checks(replace(ut01_invoice(with_fuel=False), lane_key="LANE-CHI-DET"), RunContext(documents=docs)), "C-02")
    assert c2.expected_cents == 14500


# ------------------------------------------------------------------ B1-005 fuel value precedence


def _fuel(values: tuple[FuelIndexValue, ...]):  # type: ignore[no-untyped-def]
    inv = ut01_invoice(pickup=date(2026, 3, 14))
    return one(run_checks(inv, RunContext(documents=(contract_v(), fuel_schedule()), fuel_values=values)), "C-03")


def test_a6_two_confirmed_values_same_week_same_level_fail_closed_in_any_order() -> None:
    a = FuelIndexValue("fv-a", INDEX, date(2026, 3, 9), date(2026, 3, 9), Decimal("3.78"), "confirmed")
    b = FuelIndexValue("fv-b", INDEX, date(2026, 3, 9), date(2026, 3, 9), Decimal("3.72"), "confirmed")
    outcomes = {(r.status, r.exception_code) for r in (_fuel((a, b)), _fuel((b, a)))}
    assert outcomes == {("exception", "FSC_BASIS_MISSING")}


def test_carrier_and_tenant_values_disagreeing_fail_closed_agreeing_prefer_carrier() -> None:
    carrier = FuelIndexValue(
        "fv-c", INDEX, date(2026, 3, 9), date(2026, 3, 9), Decimal("3.72"), "confirmed", carrier_specific=True
    )
    assert _fuel((FV_0309, carrier)).exception_code == "FSC_BASIS_MISSING"
    same = replace(carrier, price=Decimal("3.78"))
    for order in ((FV_0309, same), (same, FV_0309)):
        r = _fuel(order)
        assert (r.fuel_index_price_id, r.expected_cents) == ("fv-c", 5003)


def test_unconfirmed_carrier_value_blocks_when_only_tenant_value_is_confirmed() -> None:
    pending = FuelIndexValue("fv-c", INDEX, date(2026, 3, 9), date(2026, 3, 9), Decimal("3.72"), "entered", carrier_specific=True)
    assert _fuel((FV_0309, pending)).exception_code == "INDEX_PRICE_UNCONFIRMED"


# ------------------------------------------------------------------ B1-006 duplicates


def test_duplicate_is_review_only_and_a_corrected_invoice_is_not_its_originals_duplicate() -> None:
    inv = ut01_invoice()
    orig = DuplicateCandidate("invoice:orig", CARRIER, "884213", "PRO-5550001", inv.invoice_date, inv.total_cents, "orig")
    flagged = one(run_checks(inv, RunContext(documents=(), duplicate_candidates=(orig,))), "C-01")
    assert flagged.status == "variance" and flagged.variance_cents is None and not flagged.claimable
    assert flagged.review_flags == ("possible_duplicate",)
    corrected = replace(inv, id="rev", revision_chain=frozenset({"orig"}))
    assert one(run_checks(corrected, RunContext(documents=(), duplicate_candidates=(orig,))), "C-01").status == "pass"


# ------------------------------------------------------------------ B1-007 ledger caps


def _sent() -> list[ClaimEvent]:
    return [ClaimEvent("approved", date(2026, 4, 1), "a", 0), ClaimEvent("sent", date(2026, 4, 1), "b", 1)]


def test_a11_settlement_without_decision_is_not_settled() -> None:
    d = derive(_sent(), 50000, 1)
    assert (d.status, d.accepted_cents) == ("sent", None)
    assert derive(_sent(), 50000, 50000).status == "sent"  # even in full: needs the carrier's decision


def test_a12_accepted_capped_at_claimed_and_settlement_cap() -> None:
    evs = [*_sent(), ClaimEvent("decision_accepted", date(2026, 4, 5), "c", 2, amount_cents=90000, evidence_file_id="f")]
    d = derive(evs, 50000, 0)
    assert (d.status, d.accepted_cents) == ("accepted", 50000)
    assert derive(evs, 50000, 50000).status == "settled"
    assert settlement_cap(50000, None) == 50000 and settlement_cap(50000, 2772) == 2772


# ------------------------------------------------------------------ B1-008 receipt bounds


def test_a8_receipt_after_forward_or_in_future_is_rejected_and_ignored() -> None:
    """Forward 20 Mar; user-entered 1 Jun is impossible → proxy 16 Mar + 180 = 12 Sep, evidence listed as rejected."""
    ev = ReceiptEvidence(
        user_entered_on=date(2026, 6, 1),
        user_note="clerk says",
        freightcheck_received_at=datetime(2026, 3, 20, 9, tzinfo=UTC),
    )
    d = compute_deadline(DeadlineInput("motor_carrier", date(2026, 3, 16), ev))
    assert (d.contest_by, d.deadline_basis) == (date(2026, 9, 12), "invoice_date_proxy_plus_180")
    assert d.rejected_evidence == ("user_entered:2026-06-01",)
    future = compute_deadline(
        DeadlineInput(
            "motor_carrier", date(2026, 3, 16), ReceiptEvidence(ap_received_on=date(2026, 12, 1)), today=date(2026, 4, 1)
        )
    )
    assert future.rejected_evidence == ("ap_received_stamp:2026-12-01",) and future.contest_by == date(2026, 9, 12)
    ok = compute_deadline(
        DeadlineInput(
            "motor_carrier", date(2026, 3, 16), ReceiptEvidence(ap_received_on=date(2026, 3, 18)), today=date(2026, 4, 1)
        )
    )
    assert ok.rejected_evidence == () and ok.contest_by == date(2026, 9, 14)


# ------------------------------------------------------------------ B1-002 sweep


@pytest.mark.parametrize("status", ["draft", "approved"])
def test_b1_014_sweep_marks_past_contest_by_once_and_never_expires(status: str) -> None:
    """Round 2 ruling: a draft or approved claim past contest-by is marked, not expired, so the MH-08
    override stays reachable; an already-marked claim is not marked again."""
    c = SweepClaim("c1", status, date(2026, 9, 12))
    assert [(a.action, a.kind) for a in deadline_sweep([c], date(2026, 9, 13), set())] == [("mark_past", None)]
    assert deadline_sweep([replace(c, already_marked=True)], date(2026, 9, 14), set()) == []


def test_b1_015_pending_revision_with_earlier_start_blocks_instead_of_tariff() -> None:
    """Reviewer case R9: contract rev 1 from 1 Jan 2026, rev 2 entered from 1 Dec 2025, tariff 20.00/cwt
    confirmed. Pickup 15 Dec 2025: old result was a tariff variance of 60.00 (claimable)."""
    rev1 = contract_v(1, effective_from=date(2026, 1, 1), effective_to=None, doc_id="rs1")
    rev2 = contract_v(2, status="entered", effective_from=date(2025, 12, 1), effective_to=None, doc_id="rs2", revises_id="rs1")
    tariff = replace(
        contract_v(1, effective_from=date(2025, 1, 1), effective_to=None, rate="20.00", doc_id="tar"), doc_type="tariff"
    )
    inv = replace(ut01_invoice(pickup=date(2025, 12, 15), with_fuel=False), invoice_date=date(2025, 12, 16))
    c2 = one(run_checks(inv, RunContext(documents=(rev1, rev2, tariff))), "C-02")
    assert (c2.status, c2.exception_code, c2.claimable) == ("exception", "GOVERNING_RATE_MISSING", False)
    # Inside the prior's dates the confirmed prior still governs while the revision is pending.
    c2_mar = one(run_checks(ut01_invoice(with_fuel=False), RunContext(documents=(rev1, rev2, tariff))), "C-02")
    assert (c2_mar.status, c2_mar.variance_cents) == ("variance", 2772)
