"""Synthetic golden fixtures from execution-plan section 7 (carrier "Example Freight Lines")."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fc_core.model import FuelIndexValue, Invoice, InvoiceLine, RateDocument, RateRule

CARRIER = "example freight lines"
INDEX = "US_DIESEL_WEEKLY"


def contract_v(
    revision: int = 2,
    status: str = "confirmed",
    effective_from: date = date(2026, 1, 1),
    effective_to: date | None = date(2026, 6, 30),
    rate: str = "38.50",
    doc_id: str | None = None,
) -> RateDocument:
    did = doc_id or f"rs-v{revision}"
    return RateDocument(
        id=did,
        revision=revision,
        doc_type="contract_rate_sheet",
        status=status,  # type: ignore[arg-type]
        effective_from=effective_from,
        effective_to=effective_to,
        date_basis="pickup_date",
        rules=(
            RateRule(f"{did}-lh", "linehaul", {"basis": "per_cwt", "rate": rate, "class": "70"}),
            RateRule(f"{did}-disc", "discount", {"percent": "62"}),
            RateRule(f"{did}-min", "minimum", {"amount": "145.00"}),
        ),
    )


def fuel_schedule(with_week_rule: bool = True, status: str = "confirmed", revision: int = 1) -> RateDocument:
    did = f"fsc-r{revision}"
    rules = [
        RateRule(f"{did}-b1", "fuel_band", {"index_name": INDEX, "min": "3.700", "max": "3.749", "percent": "28.0"}),
        RateRule(f"{did}-b2", "fuel_band", {"index_name": INDEX, "min": "3.750", "max": "3.799", "percent": "28.5"}),
    ]
    if with_week_rule:
        rules.append(
            RateRule(
                f"{did}-wk",
                "fuel_week_rule",
                {"index_name": INDEX, "published_weekday": 0, "applies_from_days": 1, "applies_through_days": 7},
            )
        )
    return RateDocument(
        id=did,
        revision=revision,
        doc_type="fuel_schedule",
        status=status,  # type: ignore[arg-type]
        effective_from=date(2026, 1, 1),
        effective_to=None,
        date_basis="pickup_date",
        rules=tuple(rules),
    )


def fuel_values(status_9mar: str | None = "confirmed") -> tuple[FuelIndexValue, ...]:
    vals = [FuelIndexValue("fv-0302", INDEX, date(2026, 3, 2), date(2026, 3, 2), Decimal("3.74"), "confirmed")]
    if status_9mar is not None:
        vals.append(
            FuelIndexValue("fv-0309", INDEX, date(2026, 3, 9), date(2026, 3, 9), Decimal("3.78"), status_9mar)  # type: ignore[arg-type]
        )
    return tuple(vals)


def ut01_invoice(pickup: date | None = date(2026, 3, 14), with_fuel: bool = True, **kw: object) -> Invoice:
    lines = [InvoiceLine(1, "linehaul", 20328)]
    if with_fuel:
        lines.append(InvoiceLine(2, "fuel", 6302))
    total = sum(ln.amount_cents for ln in lines)
    return Invoice(
        id="inv-884213",
        carrier_key=CARRIER,
        invoice_number="884213",
        pro_number="PRO-5550001",
        invoice_date=date(2026, 3, 16),
        pickup_date=pickup,
        billed_weight_lb=Decimal("1200"),
        billed_class="70",
        total_cents=total,
        lines=tuple(lines),
        **kw,  # type: ignore[arg-type]
    )
