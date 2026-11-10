"""Plain input and output types for the check engine. No I/O; dates are passed in."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

DocType = Literal["contract_rate_sheet", "tariff", "accessorial_schedule", "fuel_schedule", "rate_confirmation"]
DateBasis = Literal["pickup_date", "tender_date", "delivery_date", "invoice_date"]
DocStatus = Literal["entered", "confirmed", "superseded"]
CheckStatus = Literal["pass", "variance", "exception", "not_applicable"]
ChargeType = Literal["linehaul", "fuel", "accessorial", "discount", "other"]
InvoiceStatus = Literal["needs_review", "needs_input", "variance", "clean"]

EXCEPTION_CODES = frozenset(
    {
        "GOVERNING_RATE_MISSING",
        "GOVERNING_DATE_MISSING",
        "BASE_TARIFF_UNAVAILABLE",
        "FSC_BASIS_MISSING",
        "INDEX_PRICE_MISSING",
        "INDEX_PRICE_UNCONFIRMED",
        "FIELD_UNCONFIRMED",
        "DOCUMENT_MISSING",
        "ENGINE_ERROR",
    }
)

RULE_TYPES = frozenset(
    {
        "linehaul",
        "minimum",
        "discount",
        "base_tariff_ref",
        "accessorial",
        "fuel_band",
        "fuel_week_rule",
    }
)


@dataclass(frozen=True)
class RateRule:
    id: str
    rule_type: str
    params: dict[str, Any]
    source_page: int | None = None


@dataclass(frozen=True)
class RateDocument:
    id: str
    revision: int
    doc_type: DocType
    status: DocStatus
    effective_from: date
    effective_to: date | None
    date_basis: DateBasis
    scope_key: str = "*"
    rules: tuple[RateRule, ...] = ()
    date_basis_source_page: int | None = None

    def rules_of(self, rule_type: str) -> list[RateRule]:
        return [r for r in self.rules if r.rule_type == rule_type]


@dataclass(frozen=True)
class FuelIndexValue:
    id: str
    index_name: str
    published_on: date
    week_start: date
    price: Decimal
    status: DocStatus
    revision: int = 1


@dataclass(frozen=True)
class InvoiceLine:
    line_no: int
    charge_type: ChargeType
    amount_cents: int
    accessorial_code: str | None = None


@dataclass(frozen=True)
class DuplicateCandidate:
    """Another invoice or an AP payment row to compare against for C-01."""

    ref: str  # "invoice:<id>" or "ap_payment:<id>"
    carrier_key: str
    invoice_number: str | None
    pro_number: str | None
    invoice_date: date | None
    total_cents: int | None


@dataclass(frozen=True)
class Invoice:
    id: str
    carrier_key: str
    invoice_number: str
    total_cents: int
    lines: tuple[InvoiceLine, ...]
    pro_number: str | None = None
    invoice_date: date | None = None
    pickup_date: date | None = None
    tender_date: date | None = None
    delivery_date: date | None = None
    billed_weight_lb: Decimal | None = None
    billed_class: str | None = None
    fields_confirmed: bool = True
    # Accessorial codes requested on the linked bill of lading; None = no BOL linked.
    bol_accessorials: frozenset[str] | None = None
    # Receipt of the original bill when this invoice is an additional or balance-due bill.
    original_bill_receipt_date: date | None = None

    def date_for(self, basis: DateBasis) -> date | None:
        value: date | None = getattr(self, basis)
        return value

    def lines_of(self, charge_type: ChargeType) -> list[InvoiceLine]:
        return [ln for ln in self.lines if ln.charge_type == charge_type]


@dataclass(frozen=True)
class BasisRef:
    """What a result was computed from: document revisions and index values."""

    document_ids: tuple[str, ...] = ()
    document_revisions: tuple[int, ...] = ()
    fuel_index_price_ids: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "document_ids": list(self.document_ids),
            "document_revisions": list(self.document_revisions),
            "fuel_index_price_ids": list(self.fuel_index_price_ids),
        }

    def merge(self, other: BasisRef) -> BasisRef:
        ids = list(self.document_ids)
        revs = list(self.document_revisions)
        for i, r in zip(other.document_ids, other.document_revisions, strict=True):
            if i not in ids:
                ids.append(i)
                revs.append(r)
        fuels = list(self.fuel_index_price_ids)
        fuels += [f for f in other.fuel_index_price_ids if f not in fuels]
        return BasisRef(tuple(ids), tuple(revs), tuple(fuels))


def basis_of(doc: RateDocument) -> BasisRef:
    return BasisRef((doc.id,), (doc.revision,))


@dataclass(frozen=True)
class CheckResult:
    check_code: str
    status: CheckStatus
    line_no: int | None = None
    exception_code: str | None = None
    expected_cents: int | None = None
    billed_cents: int | None = None
    variance_cents: int | None = None
    rate_rule_id: str | None = None
    rate_document_revision: int | None = None
    fuel_index_price_id: str | None = None
    governing_date: date | None = None
    basis: BasisRef = field(default_factory=BasisRef)
    arithmetic: dict[str, Any] = field(default_factory=dict)
    review_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status == "exception":
            if self.exception_code not in EXCEPTION_CODES:
                raise ValueError(f"exception result needs a known code, got {self.exception_code}")
        elif self.exception_code is not None:
            raise ValueError("exception_code is only allowed on an exception result")

    @property
    def claimable(self) -> bool:
        """Only a positive money variance can become a claim line."""
        return self.status == "variance" and (self.variance_cents or 0) > 0


@dataclass(frozen=True)
class RunContext:
    """Everything the checks need besides the invoice. All rate inputs as stored."""

    documents: tuple[RateDocument, ...]
    fuel_values: tuple[FuelIndexValue, ...] = ()
    duplicate_candidates: tuple[DuplicateCandidate, ...] = ()
    tolerance_cents: int = 200
