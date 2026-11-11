"""UT-07, UT-09, UT-10, UT-15 and approval guards (core side of IT-06, IT-19)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from fc_core.deadline import (
    DeadlineInput,
    ReceiptEvidence,
    SweepClaim,
    compute_deadline,
    deadline_sweep,
)
from fc_core.ledger import (
    ClaimEvent,
    LineBasis,
    Recomputed,
    SettlementRow,
    derive,
    evaluate_approval,
    fee_lines,
    gainshare_fee,
    net_settled_value,
    time_cost_cents,
    validate_event,
    withdrawal_note,
)

INV_DATE = date(2026, 2, 27)


def dl(ev: ReceiptEvidence, carrier_type: str = "motor_carrier", term: int | None = None):  # type: ignore[no-untyped-def]
    return compute_deadline(
        DeadlineInput(carrier_type, INV_DATE, ev, contract_term_days=term, contract_term_has_source=term is not None)  # type: ignore[arg-type]
    )


class TestUT07Deadlines:
    def test_a_ap_stamp_2_mar_gives_29_aug_receipt_plus_180(self) -> None:
        d = dl(ReceiptEvidence(ap_received_on=date(2026, 3, 2)))
        assert (d.contest_by, d.deadline_basis, d.receipt_basis) == (date(2026, 8, 29), "receipt_plus_180", "ap_received_stamp")

    def test_b_no_evidence_invoice_27_feb_gives_26_aug_proxy(self) -> None:
        d = dl(ReceiptEvidence())
        assert (d.contest_by, d.deadline_basis, d.receipt_date) == (date(2026, 8, 26), "invoice_date_proxy_plus_180", None)

    def test_c_contract_90_days_receipt_2_mar_gives_31_may(self) -> None:
        d = dl(ReceiptEvidence(ap_received_on=date(2026, 3, 2)), term=90)
        assert (d.contest_by, d.deadline_basis) == (date(2026, 5, 31), "contract_term")

    def test_d_broker_without_term_gets_no_date(self) -> None:
        d = dl(ReceiptEvidence(ap_received_on=date(2026, 3, 2)), carrier_type="broker")
        assert (d.contest_by, d.deadline_basis) == (None, "none_broker")

    def test_e_forwarded_late_uses_proxy_26_aug_never_forward_plus_180(self) -> None:
        fwd = datetime(2026, 5, 28, 15, 0, tzinfo=UTC)
        d = dl(ReceiptEvidence(freightcheck_received_at=fwd))
        assert d.contest_by == date(2026, 8, 26) and d.deadline_basis == "invoice_date_proxy_plus_180"
        assert d.contest_by != date(2026, 11, 24)

    def test_f_original_message_3_mar_and_ap_stamp_5_mar_uses_earlier_30_aug(self) -> None:
        d = dl(
            ReceiptEvidence(
                carrier_transmission_on=date(2026, 3, 3),
                ap_received_on=date(2026, 3, 5),
                freightcheck_received_at=datetime(2026, 5, 28, tzinfo=UTC),
            )
        )
        assert (d.contest_by, d.receipt_date, d.receipt_basis) == (date(2026, 8, 30), date(2026, 3, 3), "carrier_transmission")

    def test_user_entered_receipt_needs_a_note(self) -> None:
        with pytest.raises(ValueError):
            dl(ReceiptEvidence(user_entered_on=date(2026, 3, 1)))
        d = dl(ReceiptEvidence(user_entered_on=date(2026, 3, 1), user_note="stamp on paper copy"))
        assert d.receipt_basis == "user_entered" and d.contest_by == date(2026, 8, 28)

    def test_missing_invoice_date_is_an_exception_not_a_guess(self) -> None:
        d = compute_deadline(DeadlineInput("motor_carrier", None, ReceiptEvidence()))
        assert d.contest_by is None and d.exception_code == "GOVERNING_DATE_MISSING"


def ev(t: str, day: int, cid: str, seq: int, **kw) -> ClaimEvent:  # type: ignore[no-untyped-def]
    return ClaimEvent(t, date(2026, 4, day), cid, seq, **kw)


def test_ut09_late_acknowledgment_and_duplicate_partial_do_not_regress() -> None:
    events = [
        ev("drafted", 1, "e0", 0),
        ev("approved", 1, "e1", 1),
        ev("sent", 2, "e2", 2),
        ev("decision_partial", 20, "e3", 3, amount_cents=2772, evidence_file_id="f", reason_code="other"),
        ev("acknowledged", 5, "e4", 4),
        ev("decision_partial", 20, "e3", 5, amount_cents=9999, evidence_file_id="f", reason_code="other"),
    ]
    d = derive(events, claimed_cents=4071, settled_cents=0)
    assert d.status == "partly_accepted" and d.accepted_cents == 2772


def test_claimed_accepted_settled_stay_separate() -> None:
    events = [
        ev("approved", 1, "a", 1),
        ev("sent", 2, "b", 2),
        ev("decision_partial", 3, "c", 3, amount_cents=2772, evidence_file_id="f", reason_code="other"),
    ]
    assert derive(events, 4071, 0).status == "partly_accepted"
    assert derive(events, 4071, 1000).status == "partly_accepted"  # part-settled is not settled
    s = derive(events, 4071, 2772)
    assert (s.status, s.accepted_cents) == ("settled", 2772)


def test_redraft_after_approval_returns_to_draft_before_send() -> None:
    events = [ev("drafted", 1, "a", 1), ev("approved", 1, "b", 2), ev("drafted", 2, "c", 3)]
    assert derive(events, None, 0).status == "draft"


def test_decision_events_need_document_and_reason() -> None:
    with pytest.raises(ValueError):
        validate_event(ev("decision_accepted", 1, "x", 1))
    with pytest.raises(ValueError):
        validate_event(ev("withdrawn", 1, "x", 1))
    validate_event(ev("withdrawn", 1, "x", 1, reason_code="wrong_rate_basis"))


def test_ut10_nsv_and_gainshare() -> None:
    """590 min × 40.00/h = 393.33; NSV 2,250.00 − 299.00 − 393.33 = 1,557.67; accepted 300.00 not an input.
    Gainshare 20% of 31.75 = 6.35 and of 120.00 = 24.00, total 30.35; reversal of 31.75 → −6.35."""
    assert time_cost_cents(590, 4000) == 39333
    assert net_settled_value(225000, 29900, 590, 4000) == 155767
    lines = fee_lines([SettlementRow("s1", 3175, False, False, False), SettlementRow("s2", 12000, False, False, False)])
    assert [ln.fee_cents for ln in lines] == [635, 2400] and sum(ln.fee_cents for ln in lines) == 3035
    rev = fee_lines([SettlementRow("s1", 3175, True, True, False), SettlementRow("s2", 12000, False, True, False)])
    assert [(ln.settlement_id, ln.basis_cents, ln.fee_cents) for ln in rev] == [("s1", -3175, -635)]
    assert fee_lines([SettlementRow("s3", 5000, True, False, False)]) == []  # reversed before billing
    assert gainshare_fee(3175) == 635


class TestUT15Sweep:
    today = date(2026, 6, 1)

    def claims(self) -> list[SweepClaim]:
        from datetime import timedelta

        return [SweepClaim(f"c{n}", "approved", self.today + timedelta(days=n)) for n in (30, 14, 3, -1)] + [
            SweepClaim("sent", "sent", self.today + timedelta(days=3))
        ]

    def test_one_reminder_per_threshold_none_repeated_and_minus_one_marked_past_not_expired(self) -> None:
        first = deadline_sweep(self.claims(), self.today, set())
        assert {(a.claim_id, a.action, a.kind) for a in first} == {
            ("c30", "remind", "deadline_30"),
            ("c14", "remind", "deadline_14"),
            ("c3", "remind", "deadline_3"),
            ("c-1", "mark_past", None),
        }
        sent = {(a.kind, a.claim_id) for a in first if a.kind}
        second = deadline_sweep(self.claims(), self.today, sent)
        assert [a for a in second if a.action == "remind"] == []


LINE = LineBasis("C-03:2", 1299, {"document_ids": ["fsc-r1"], "document_revisions": [1], "fuel_index_price_ids": ["fv-0309"]})


def recomputed(amount: int, fuel: str = "fv-0309") -> dict[str, Recomputed]:
    return {
        "C-03:2": Recomputed(
            "C-03:2",
            "variance",
            amount,
            {"document_ids": ["fsc-r1"], "document_revisions": [1], "fuel_index_price_ids": [fuel]},
        )
    }


def test_approval_refused_on_stale_basis_with_old_and_new_amounts() -> None:
    d = evaluate_approval(
        [LINE], recomputed(1386, "fv-0309r2"), False, date(2026, 9, 1), "receipt_plus_180", date(2026, 4, 1), None
    )
    assert (d.ok, d.code) == (False, "STALE_BASIS")
    assert d.old_lines[0]["claimed_cents"] == 1299 and d.new_lines[0]["claimed_cents"] == 1386


def test_approval_past_contest_by_refused_then_allowed_with_reason() -> None:
    args = ([LINE], recomputed(1299), False, date(2026, 3, 31), "receipt_plus_180", date(2026, 4, 1))
    assert evaluate_approval(*args, None).code == "PAST_CONTEST_BY"
    assert evaluate_approval(*args, "  ").code == "PAST_CONTEST_BY"
    ok = evaluate_approval(*args, "carrier agreed by phone to accept late claim")
    assert ok.ok and ok.claimed_cents == 1299


def test_stale_flag_cannot_be_overridden_by_a_date_reason() -> None:
    d = evaluate_approval([LINE], recomputed(1299), True, date(2026, 9, 1), "receipt_plus_180", date(2026, 4, 1), "x")
    assert d.code == "STALE_BASIS"


def test_withdrawal_note_is_a_template_with_both_amounts() -> None:
    note = withdrawal_note("FC-0001", "Example Freight Lines", "884213", 1299, 1386)
    assert "1299" not in note and "12.99" in note and "13.86" in note and "wrong rate basis" in note
