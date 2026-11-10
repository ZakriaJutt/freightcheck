"""Claim ledger (T-5.1.3, T-5.1.4, T-5.2.2, T-5.2.3 core parts; MH-08, MH-10, MH-12, MH-15).

Claimed, accepted and settled are three separate amounts and never merge:
  claimed  frozen at approval
  accepted set only by a decision event backed by a carrier document
  settled  the sum of unreversed settlements, each backed by a document
Status is derived from the append-only event list, so a late or duplicate event cannot
regress it (AD-09).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fc_core.money import fmt, percent_of_cents, round_half_up_cents

EVENT_TYPES = frozenset(
    {
        "drafted",
        "approved",
        "sent",
        "acknowledged",
        "decision_accepted",
        "decision_partial",
        "decision_denied",
        "short_paid",
        "carrier_rebilled",
        "withdrawn",
        "expired",
    }
)
DECISION_EVENTS = frozenset({"decision_accepted", "decision_partial", "decision_denied"})
EVIDENCE_REQUIRED = DECISION_EVENTS
REASON_REQUIRED = frozenset({"decision_denied", "decision_partial", "withdrawn"})
REASON_CODES = frozenset({"wrong_rate_basis", "charge_supported_by_carrier", "time_barred", "duplicate_claim", "other"})
SETTLEMENT_METHODS = frozenset({"credit_memo", "refund_payment", "corrected_invoice", "short_pay_accepted"})

ClaimStatus = Literal[
    "draft",
    "approved",
    "sent",
    "acknowledged",
    "accepted",
    "partly_accepted",
    "denied",
    "settled",
    "withdrawn",
    "expired",
]

_RANK = {"sent": 2, "acknowledged": 3}
_DECISION_STATUS: dict[str, ClaimStatus] = {
    "decision_accepted": "accepted",
    "decision_partial": "partly_accepted",
    "decision_denied": "denied",
}


@dataclass(frozen=True)
class ClaimEvent:
    event_type: str
    occurred_on: date
    client_event_id: str
    seq: int  # order recorded by FreightCheck
    amount_cents: int | None = None
    evidence_file_id: str | None = None
    reason_code: str | None = None


def validate_event(ev: ClaimEvent) -> None:
    if ev.event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type {ev.event_type}")
    if ev.event_type in EVIDENCE_REQUIRED and not ev.evidence_file_id:
        raise ValueError("a decision event needs the carrier's document")
    if ev.event_type in REASON_REQUIRED and ev.reason_code not in REASON_CODES:
        raise ValueError("a denial, partial decision or withdrawal needs a reason code")
    if ev.event_type == "decision_partial" and (ev.amount_cents is None or ev.amount_cents <= 0):
        raise ValueError("a partial decision needs the accepted amount")


@dataclass(frozen=True)
class Derived:
    status: ClaimStatus
    accepted_cents: int | None


def dedupe(events: list[ClaimEvent]) -> list[ClaimEvent]:
    seen: set[str] = set()
    out: list[ClaimEvent] = []
    for ev in sorted(events, key=lambda e: e.seq):
        if ev.client_event_id in seen:
            continue
        seen.add(ev.client_event_id)
        out.append(ev)
    return out


def derive(events: list[ClaimEvent], claimed_cents: int | None, settled_cents: int) -> Derived:
    evs = dedupe(events)
    types = [e.event_type for e in evs]
    if "withdrawn" in types:
        return Derived("withdrawn", _accepted(evs, claimed_cents))
    if "sent" not in types:
        if "expired" in types:
            return Derived("expired", None)
        pre = [e for e in evs if e.event_type in ("drafted", "approved")]
        last = pre[-1].event_type if pre else "drafted"
        return Derived("approved" if last == "approved" else "draft", None)
    accepted = _accepted(evs, claimed_cents)
    decisions = [e for e in evs if e.event_type in DECISION_EVENTS]
    if settled_cents > 0 and (accepted is None or settled_cents >= accepted):
        return Derived("settled", accepted)
    if decisions:
        latest = max(decisions, key=lambda e: (e.occurred_on, e.seq))
        return Derived(_DECISION_STATUS[latest.event_type], accepted)
    rank = max(_RANK.get(t, 0) for t in types)
    return Derived("acknowledged" if rank == 3 else "sent", accepted)


def _accepted(evs: list[ClaimEvent], claimed_cents: int | None) -> int | None:
    decisions = [e for e in evs if e.event_type in DECISION_EVENTS]
    if not decisions:
        return None
    latest = max(decisions, key=lambda e: (e.occurred_on, e.seq))
    if latest.event_type == "decision_denied":
        return 0
    if latest.event_type == "decision_partial":
        return latest.amount_cents
    return latest.amount_cents if latest.amount_cents is not None else claimed_cents


# ---------------------------------------------------------------- approval


@dataclass(frozen=True)
class LineBasis:
    """One claim line: what it was drafted from and what it claims."""

    finding_key: str  # "<check_code>:<line_no>"
    claimed_cents: int
    basis: dict[str, Any]  # BasisRef.to_json()


@dataclass(frozen=True)
class Recomputed:
    finding_key: str
    status: str  # pass, variance, exception, not_applicable, or "missing"
    variance_cents: int | None
    basis: dict[str, Any]


@dataclass(frozen=True)
class ApprovalDecision:
    ok: bool
    code: str | None = None  # STALE_BASIS, PAST_CONTEST_BY
    claimed_cents: int | None = None
    old_lines: list[dict[str, Any]] = field(default_factory=list)
    new_lines: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""


def compare_basis(lines: list[LineBasis], recomputed: dict[str, Recomputed]) -> list[str]:
    """Return the finding keys whose basis or amount differ, or that no longer vary."""
    changed: list[str] = []
    for ln in lines:
        rc = recomputed.get(ln.finding_key)
        if rc is None or rc.status != "variance" or rc.variance_cents != ln.claimed_cents or rc.basis != ln.basis:
            changed.append(ln.finding_key)
    return changed


def evaluate_approval(
    lines: list[LineBasis],
    recomputed: dict[str, Recomputed],
    stale_flag: bool,
    contest_by: date | None,
    deadline_basis: str,
    today: date,
    override_reason: str | None,
) -> ApprovalDecision:
    """Fail closed. Stale basis is checked before the date and cannot be overridden."""
    old = [{"finding": ln.finding_key, "claimed_cents": ln.claimed_cents} for ln in lines]
    new = [
        {
            "finding": ln.finding_key,
            "claimed_cents": recomputed[ln.finding_key].variance_cents if ln.finding_key in recomputed else None,
            "status": recomputed[ln.finding_key].status if ln.finding_key in recomputed else "missing",
        }
        for ln in lines
    ]
    if not lines:
        return ApprovalDecision(False, "STALE_BASIS", message="claim has no lines")
    changed = compare_basis(lines, recomputed)
    if stale_flag or changed:
        return ApprovalDecision(False, "STALE_BASIS", old_lines=old, new_lines=new, message="basis changed since drafting")
    reason = (override_reason or "").strip()
    if contest_by is None and deadline_basis != "none_broker" and not reason:
        return ApprovalDecision(False, "PAST_CONTEST_BY", message="contest-by date unknown; override needs a reason")
    if contest_by is not None and today > contest_by and not reason:
        return ApprovalDecision(False, "PAST_CONTEST_BY", message=f"contest-by date {contest_by} has passed")
    return ApprovalDecision(True, claimed_cents=sum(ln.claimed_cents for ln in lines), old_lines=old, new_lines=new)


def withdrawal_note(reference: str, carrier_name: str, invoice_number: str, old_cents: int, new_cents: int | None) -> str:
    """Deterministic template; the user sends it from their own mailbox."""
    revised = (
        f"A corrected computation gives {fmt(new_cents)} USD."
        if new_cents is not None
        else "No amount is claimed on the corrected basis."
    )
    return (
        f"To {carrier_name}: we withdraw claim {reference} on invoice {invoice_number} "
        f"for {fmt(old_cents)} USD. The rate basis it was computed on has since been corrected. "
        f"{revised} Reason: wrong rate basis."
    )


# ---------------------------------------------------------------- settlements and fees

GAINSHARE_PERCENT = Decimal("20")


@dataclass(frozen=True)
class SettlementRow:
    id: str
    amount_cents: int
    reversed: bool
    billed_positive: bool  # a positive fee line exists already
    billed_reversal: bool  # a negative fee line exists already


@dataclass(frozen=True)
class FeeLine:
    settlement_id: str
    basis_cents: int
    fee_cents: int


def gainshare_fee(amount_cents: int) -> int:
    return percent_of_cents(amount_cents, GAINSHARE_PERCENT)


def fee_lines(settlements: list[SettlementRow]) -> list[FeeLine]:
    """Lines for the next statement: unbilled settlements, and reversals of billed ones."""
    out: list[FeeLine] = []
    for s in settlements:
        if not s.billed_positive and not s.reversed:
            out.append(FeeLine(s.id, s.amount_cents, gainshare_fee(s.amount_cents)))
        elif s.billed_positive and s.reversed and not s.billed_reversal:
            out.append(FeeLine(s.id, -s.amount_cents, -gainshare_fee(s.amount_cents)))
    return out


def time_cost_cents(minutes: int, hourly_rate_cents: int) -> int:
    return round_half_up_cents(Decimal(minutes) * Decimal(hourly_rate_cents) / Decimal(60) / Decimal(100))


def net_settled_value(settled_cents: int, fee_cents: int, minutes: int, hourly_rate_cents: int) -> int:
    """NSV = settled − fee − time cost. Accepted or pending amounts are never inputs."""
    return settled_cents - fee_cents - time_cost_cents(minutes, hourly_rate_cents)
