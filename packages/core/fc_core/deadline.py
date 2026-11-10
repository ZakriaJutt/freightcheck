"""Contest-by calculator and deadline sweep logic (T-4.2.7, MH-09).

Receipt means the shipper's receipt of the carrier's bill. Evidence, earliest first, comes
only from: the carrier's original transmission, the shipper's AP received stamp, or a user
entry with a note. The time a forward reached FreightCheck is never evidence. With no
evidence the invoice date is used as a labelled proxy. A broker with no contract term gets
no deadline. Calendar arithmetic is exact (date + days).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Literal

DEFAULT_WINDOW_DAYS = 180
REMINDER_DAYS = (30, 14, 3)

ReceiptBasis = Literal["carrier_transmission", "ap_received_stamp", "user_entered", "unknown"]
DeadlineBasis = Literal["receipt_plus_180", "invoice_date_proxy_plus_180", "contract_term", "none_broker"]


@dataclass(frozen=True)
class ReceiptEvidence:
    carrier_transmission_on: date | None = None
    ap_received_on: date | None = None
    user_entered_on: date | None = None
    user_note: str | None = None
    # Accepted only so callers can pass it; deliberately never used (MH-09).
    freightcheck_received_at: datetime | None = None


@dataclass(frozen=True)
class DeadlineInput:
    carrier_type: Literal["motor_carrier", "broker", "other"]
    invoice_date: date | None
    evidence: ReceiptEvidence
    contract_term_days: int | None = None
    contract_term_has_source: bool = False
    today: date | None = None  # passed in by the caller; the core reads no clock


@dataclass(frozen=True)
class Deadline:
    contest_by: date | None
    deadline_basis: DeadlineBasis
    receipt_date: date | None
    receipt_basis: ReceiptBasis
    receipt_note: str | None = None
    exception_code: str | None = None
    # Evidence dates refused as impossible (B1-008): later than today or than the forward's arrival.
    rejected_evidence: tuple[str, ...] = ()


def receipt_upper_bound(ev: ReceiptEvidence, today: date | None) -> date | None:
    """The shipper cannot have received the bill after today, nor after it forwarded it to us."""
    bounds = [d for d in (today, ev.freightcheck_received_at.date() if ev.freightcheck_received_at else None) if d]
    return min(bounds) if bounds else None


def earliest_receipt(
    ev: ReceiptEvidence, upper: date | None = None
) -> tuple[date | None, ReceiptBasis, str | None, tuple[str, ...]]:
    options: list[tuple[date, ReceiptBasis, str | None]] = []
    if ev.carrier_transmission_on is not None:
        options.append((ev.carrier_transmission_on, "carrier_transmission", None))
    if ev.ap_received_on is not None:
        options.append((ev.ap_received_on, "ap_received_stamp", None))
    if ev.user_entered_on is not None:
        if not (ev.user_note and ev.user_note.strip()):
            raise ValueError("a user-entered receipt date needs a note")
        options.append((ev.user_entered_on, "user_entered", ev.user_note))
    rejected = tuple(f"{b}:{d.isoformat()}" for d, b, _ in options if upper is not None and d > upper)
    options = [o for o in options if upper is None or o[0] <= upper]
    if not options:
        return None, "unknown", None, rejected
    order = {"carrier_transmission": 0, "ap_received_stamp": 1, "user_entered": 2}
    when, basis, note = min(options, key=lambda o: (o[0], order[o[1]]))
    return when, basis, note, rejected


def compute_deadline(inp: DeadlineInput) -> Deadline:
    """Impossible evidence dates are dropped and listed in `rejected_evidence`; callers refuse them."""
    upper = receipt_upper_bound(inp.evidence, inp.today)
    receipt, receipt_basis, note, rejected = earliest_receipt(inp.evidence, upper)
    d = _deadline_from(inp, receipt, receipt_basis, note)
    return replace(d, rejected_evidence=rejected) if rejected else d


def _deadline_from(inp: DeadlineInput, receipt: date | None, receipt_basis: ReceiptBasis, note: str | None) -> Deadline:
    has_term = inp.contract_term_days is not None and inp.contract_term_has_source
    if inp.carrier_type == "broker" and not has_term:
        return Deadline(None, "none_broker", receipt, receipt_basis, note)
    start = receipt if receipt is not None else inp.invoice_date
    if has_term:
        assert inp.contract_term_days is not None
        if start is None:
            return Deadline(None, "contract_term", None, receipt_basis, note, "GOVERNING_DATE_MISSING")
        return Deadline(start + timedelta(days=inp.contract_term_days), "contract_term", receipt, receipt_basis, note)
    if receipt is not None:
        return Deadline(receipt + timedelta(days=DEFAULT_WINDOW_DAYS), "receipt_plus_180", receipt, receipt_basis, note)
    if inp.invoice_date is None:
        return Deadline(None, "invoice_date_proxy_plus_180", None, "unknown", None, "GOVERNING_DATE_MISSING")
    return Deadline(
        inp.invoice_date + timedelta(days=DEFAULT_WINDOW_DAYS),
        "invoice_date_proxy_plus_180",
        None,
        "unknown",
        None,
    )


def days_left(contest_by: date, today: date) -> int:
    return (contest_by - today).days


@dataclass(frozen=True)
class SweepClaim:
    claim_id: str
    status: str
    contest_by: date | None
    # An Approver recorded a late override at approval; the claim is not expired by the sweep
    # (the send step still requires its own recorded override, B1-002).
    override_recorded: bool = False


@dataclass(frozen=True)
class SweepAction:
    claim_id: str
    action: Literal["remind", "expire"]
    kind: str | None = None  # deadline_30, deadline_14, deadline_3


def deadline_sweep(claims: list[SweepClaim], today: date, already_sent: set[tuple[str, str]]) -> list[SweepAction]:
    """Reminders at 30, 14 and 3 days once each; unsent confirmed claims past contest-by expire.

    `already_sent` holds (kind, claim_id) pairs from the notification table.
    """
    actions: list[SweepAction] = []
    for c in claims:
        if c.status not in ("draft", "approved") or c.contest_by is None:
            continue
        left = days_left(c.contest_by, today)
        if left < 0:
            if not (c.override_recorded and c.status == "approved"):
                actions.append(SweepAction(c.claim_id, "expire"))
            continue
        for threshold in REMINDER_DAYS:
            kind = f"deadline_{threshold}"
            if left <= threshold and (kind, c.claim_id) not in already_sent:
                # Only the tightest threshold reached is sent; earlier ones are implied.
                tighter = [t for t in REMINDER_DAYS if t < threshold and left <= t]
                if not tighter:
                    actions.append(SweepAction(c.claim_id, "remind", kind))
    return actions
