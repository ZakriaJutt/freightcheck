"""Money arithmetic. Money is integer cents; rates and percentages are Decimal (AD-08).

Rounding lives only here: half-up to the cent, applied once per computed line.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HUNDRED = Decimal(100)


def to_decimal(value: str | int | Decimal) -> Decimal:
    """Parse a rate, percentage or dollar figure. Floats are refused (no float drift)."""
    if isinstance(value, float):  # pragma: no cover - guarded by type checker too
        raise TypeError("floats are not accepted for money or rates")
    if isinstance(value, bool):
        raise TypeError("booleans are not numbers here")
    return Decimal(value)


def round_half_up_cents(dollars: Decimal) -> int:
    """Round a dollar amount half-up to whole cents and return integer cents."""
    return int((dollars.quantize(CENT, rounding=ROUND_HALF_UP) * HUNDRED).to_integral_value())


def dollars_to_cents(value: str | int | Decimal) -> int:
    return round_half_up_cents(to_decimal(value))


def cents_to_dollars(cents: int) -> Decimal:
    return (Decimal(cents) / HUNDRED).quantize(CENT)


def mul_cents(cents: int, factor: Decimal) -> int:
    """cents × factor, rounded half-up to the cent (one computed line)."""
    return round_half_up_cents(cents_to_dollars(cents) * factor)


def percent_of_cents(cents: int, percent: Decimal) -> int:
    return mul_cents(cents, percent / HUNDRED)


def fmt(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}{c // 100}.{c % 100:02d}"
