"""Check engine (T-4.2.1 to T-4.2.5, T-4.2.6 part C-08; MH-04, MH-05, MH-06).

Every check is an independent function returning one or more results with status
`pass`, `variance`, `exception` or `not_applicable`. The runner isolates each check:
an exception (or a crash, recorded as ENGINE_ERROR) never stops the other checks and
never counts as a pass.

Rule parameters (validated by `validate_rule_params`):
  linehaul        {"basis": "per_cwt", "rate": "38.50", "class": "70"?}
                  {"basis": "flat", "amount": "1200.00"}
  discount        {"percent": "62"}
  minimum         {"amount": "145.00"}
  base_tariff_ref {"tariff_name": "..."}        base rates held by the carrier only
  accessorial     {"code": "LIFTGATE", "amount": "85.00"}
  fuel_band       {"index_name": "...", "min": "3.700", "max": "3.749", "percent": "28.0"}
  fuel_week_rule  {"index_name": "...", "published_weekday": 0,
                   "applies_from_days": 1, "applies_through_days": 7}
                  A value published on weekday W applies to governing dates from
                  published_on + applies_from_days through published_on + applies_through_days.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fc_core.model import (
    BasisRef,
    CheckResult,
    CheckStatus,
    Invoice,
    InvoiceStatus,
    RateDocument,
    RateRule,
    RunContext,
    basis_of,
)
from fc_core.money import HUNDRED, dollars_to_cents, percent_of_cents, to_decimal
from fc_core.resolver import Resolved, Unresolved, resolve, resolve_linehaul

ENGINE_VERSION = "core-1.0.0"


class RuleParamError(ValueError):
    pass


def _dec(params: dict[str, Any], key: str) -> Decimal:
    if key not in params:
        raise RuleParamError(f"missing parameter {key}")
    value = params[key]
    if not isinstance(value, str | int) or isinstance(value, bool):
        raise RuleParamError(f"{key} must be a decimal string")
    try:
        return to_decimal(value)
    except InvalidOperation as exc:
        raise RuleParamError(f"{key} is not a decimal") from exc


def validate_rule_params(rule_type: str, params: dict[str, Any]) -> None:
    """Raise RuleParamError when params do not fit the rule type."""
    if rule_type == "linehaul":
        basis = params.get("basis")
        if basis == "per_cwt":
            _dec(params, "rate")
        elif basis == "flat":
            _dec(params, "amount")
        else:
            raise RuleParamError("linehaul basis must be per_cwt or flat")
    elif rule_type == "discount":
        pct = _dec(params, "percent")
        if not Decimal(0) <= pct <= HUNDRED:
            raise RuleParamError("percent must be between 0 and 100")
    elif rule_type == "minimum":
        _dec(params, "amount")
    elif rule_type == "base_tariff_ref":
        if not params.get("tariff_name"):
            raise RuleParamError("tariff_name required")
    elif rule_type == "accessorial":
        if not params.get("code"):
            raise RuleParamError("code required")
        _dec(params, "amount")
    elif rule_type == "fuel_band":
        if not params.get("index_name"):
            raise RuleParamError("index_name required")
        if _dec(params, "min") > _dec(params, "max"):
            raise RuleParamError("min above max")
        _dec(params, "percent")
    elif rule_type == "fuel_week_rule":
        if not params.get("index_name"):
            raise RuleParamError("index_name required")
        for key in ("published_weekday", "applies_from_days", "applies_through_days"):
            if not isinstance(params.get(key), int) or isinstance(params.get(key), bool):
                raise RuleParamError(f"{key} must be an integer")
        if not 0 <= params["published_weekday"] <= 6:
            raise RuleParamError("published_weekday is 0 (Monday) to 6")
        if params["applies_from_days"] > params["applies_through_days"]:
            raise RuleParamError("applies_from_days after applies_through_days")
    else:
        raise RuleParamError(f"unknown rule type {rule_type}")


def _compare(
    check_code: str,
    expected: int,
    billed: int,
    tolerance_cents: int,
    **kwargs: Any,
) -> CheckResult:
    variance = billed - expected
    status: CheckStatus = "variance" if abs(variance) > tolerance_cents else "pass"
    return CheckResult(
        check_code=check_code,
        status=status,
        expected_cents=expected,
        billed_cents=billed,
        variance_cents=variance,
        **kwargs,
    )


def _exception(check_code: str, code: str, detail: str, **kwargs: Any) -> CheckResult:
    arithmetic = dict(kwargs.pop("arithmetic", {}))
    arithmetic["detail"] = detail
    return CheckResult(
        check_code=check_code,
        status="exception",
        exception_code=code,
        arithmetic=arithmetic,
        **kwargs,
    )


# ---------------------------------------------------------------- C-02 linehaul


@dataclass(frozen=True)
class LinehaulExpectation:
    expected_cents: int | None  # None when the base rate is unavailable
    document: RateDocument
    governing_date: Any
    results: tuple[CheckResult, ...]


def _billed_net_linehaul(invoice: Invoice) -> int:
    return sum(ln.amount_cents for ln in invoice.lines_of("linehaul")) + sum(
        ln.amount_cents for ln in invoice.lines_of("discount")
    )


def _pick_linehaul_rule(doc: RateDocument, invoice: Invoice) -> RateRule | None:
    rules = doc.rules_of("linehaul")
    with_class = [r for r in rules if r.params.get("class") is not None]
    if with_class:
        for r in with_class:
            if invoice.billed_class is not None and str(r.params["class"]) == invoice.billed_class:
                return r
    generic = [r for r in rules if r.params.get("class") is None]
    return generic[0] if len(generic) == 1 else None


def linehaul_expectation(invoice: Invoice, ctx: RunContext) -> LinehaulExpectation | CheckResult:
    """Compute C-02. Returns an exception result when no document governs."""
    linehaul_lines = invoice.lines_of("linehaul")
    first_line = linehaul_lines[0].line_no if linehaul_lines else None
    resolution = resolve_linehaul(ctx.documents, invoice)
    if isinstance(resolution, Unresolved):
        return _exception("C-02", resolution.exception_code, resolution.detail, line_no=first_line)
    assert isinstance(resolution, Resolved)
    doc, gd = resolution.document, resolution.governing_date
    basis = basis_of(doc)
    common: dict[str, Any] = {
        "line_no": first_line,
        "rate_document_revision": doc.revision,
        "governing_date": gd,
        "basis": basis,
    }
    discount_rule: RateRule | None = next(iter(doc.rules_of("discount")), None)
    minimum_rule: RateRule | None = next(iter(doc.rules_of("minimum")), None)
    billed_net = _billed_net_linehaul(invoice)
    steps: dict[str, Any] = {"document_id": doc.id, "date_basis": doc.date_basis}
    results: list[CheckResult] = []

    rule = _pick_linehaul_rule(doc, invoice)
    if rule is not None:
        if rule.params["basis"] == "per_cwt":
            if invoice.billed_weight_lb is None:
                return _exception("C-02", "FIELD_UNCONFIRMED", "billed weight is missing", **common)
            cwt = invoice.billed_weight_lb / HUNDRED
            rate = to_decimal(rule.params["rate"])
            gross = dollars_to_cents(cwt * rate)
            steps.update(cwt=str(cwt), rate_per_cwt=str(rate), gross_cents=gross)
        else:
            gross = dollars_to_cents(rule.params["amount"])
            steps.update(flat_cents=gross, gross_cents=gross)
        gross_source = "rate_rule"
        rule_id: str | None = rule.id
    elif doc.rules_of("base_tariff_ref"):
        ref = doc.rules_of("base_tariff_ref")[0]
        results.append(
            _exception(
                "C-02-BASE",
                "BASE_TARIFF_UNAVAILABLE",
                f"base rates of {ref.params.get('tariff_name')} are not held",
                rate_rule_id=ref.id,
                **common,
            )
        )
        if discount_rule is None and minimum_rule is None:
            results.append(CheckResult("C-02", "not_applicable", arithmetic={"detail": "no discount or minimum"}, **common))
            return LinehaulExpectation(None, doc, gd, tuple(results))
        gross = sum(ln.amount_cents for ln in linehaul_lines)
        steps.update(gross_cents=gross, gross_source="printed_on_invoice")
        gross_source = "invoice"
        rule_id = discount_rule.id if discount_rule else (minimum_rule.id if minimum_rule else None)
    else:
        return _exception("C-02", "GOVERNING_RATE_MISSING", f"no linehaul rule for class {invoice.billed_class}", **common)

    discount_cents = 0
    if discount_rule is not None:
        pct = to_decimal(discount_rule.params["percent"])
        discount_cents = percent_of_cents(gross, pct)
        steps.update(discount_percent=str(pct), discount_cents=discount_cents)
    net = gross - discount_cents
    if minimum_rule is not None:
        minimum = dollars_to_cents(minimum_rule.params["amount"])
        steps.update(minimum_cents=minimum, minimum_applied=net < minimum)
        net = max(net, minimum)
    steps.update(expected_net_cents=net, billed_net_cents=billed_net, gross_from=gross_source)
    results.append(_compare("C-02", net, billed_net, ctx.tolerance_cents, rate_rule_id=rule_id, arithmetic=steps, **common))
    expected = net if gross_source == "rate_rule" else None
    return LinehaulExpectation(expected, doc, gd, tuple(results))


def check_linehaul(invoice: Invoice, ctx: RunContext) -> list[CheckResult]:
    if not invoice.lines_of("linehaul"):
        return [CheckResult("C-02", "not_applicable")]
    outcome = linehaul_expectation(invoice, ctx)
    if isinstance(outcome, CheckResult):
        return [outcome]
    return list(outcome.results)


# ---------------------------------------------------------------- C-03 fuel


def check_fuel(invoice: Invoice, ctx: RunContext) -> list[CheckResult]:
    fuel_lines = invoice.lines_of("fuel")
    if not fuel_lines:
        return [CheckResult("C-03", "not_applicable")]
    line_no = fuel_lines[0].line_no
    resolution = resolve(ctx.documents, "fuel_schedule", invoice)
    if isinstance(resolution, Unresolved):
        return [_exception("C-03", resolution.exception_code, resolution.detail, line_no=line_no)]
    doc, gd = resolution.document, resolution.governing_date
    basis = basis_of(doc)
    common: dict[str, Any] = {
        "line_no": line_no,
        "rate_document_revision": doc.revision,
        "governing_date": gd,
    }
    week_rules = doc.rules_of("fuel_week_rule")
    if len(week_rules) != 1:
        return [_exception("C-03", "FSC_BASIS_MISSING", "schedule has no single week rule", basis=basis, **common)]
    wr = week_rules[0].params
    index_name = wr["index_name"]
    earliest = gd - timedelta(days=wr["applies_through_days"])
    latest = gd - timedelta(days=wr["applies_from_days"])
    window = [
        v
        for v in ctx.fuel_values
        if v.index_name == index_name
        and earliest <= v.published_on <= latest
        and v.published_on.weekday() == wr["published_weekday"]
    ]
    confirmed = [v for v in window if v.status == "confirmed"]
    if not confirmed:
        code = "INDEX_PRICE_UNCONFIRMED" if any(v.status == "entered" for v in window) else "INDEX_PRICE_MISSING"
        return [
            _exception(
                "C-03",
                code,
                f"{index_name} value published {earliest}..{latest}",
                basis=basis,
                **common,
            )
        ]
    if len({v.published_on for v in confirmed}) > 1:
        return [_exception("C-03", "FSC_BASIS_MISSING", "week rule selects more than one value", basis=basis, **common)]
    value = max(confirmed, key=lambda v: v.revision)
    bands = [
        r
        for r in doc.rules_of("fuel_band")
        if r.params["index_name"] == index_name and to_decimal(r.params["min"]) <= value.price <= to_decimal(r.params["max"])
    ]
    fuel_basis = basis.merge(BasisRef(fuel_index_price_ids=(value.id,)))
    if len(bands) != 1:
        return [
            _exception(
                "C-03",
                "FSC_BASIS_MISSING",
                f"no single band for index {value.price}",
                basis=fuel_basis,
                fuel_index_price_id=value.id,
                **common,
            )
        ]
    band = bands[0]
    pct = to_decimal(band.params["percent"])
    lh = linehaul_expectation(invoice, ctx)
    if isinstance(lh, LinehaulExpectation) and lh.expected_cents is not None:
        base = lh.expected_cents
        base_source = "expected_linehaul"
        fuel_basis = fuel_basis.merge(basis_of(lh.document))
    else:
        base = _billed_net_linehaul(invoice)
        base_source = "billed_linehaul"
    expected = percent_of_cents(base, pct)
    billed = sum(ln.amount_cents for ln in fuel_lines)
    return [
        _compare(
            "C-03",
            expected,
            billed,
            ctx.tolerance_cents,
            rate_rule_id=band.id,
            fuel_index_price_id=value.id,
            basis=fuel_basis,
            arithmetic={
                "document_id": doc.id,
                "index_name": index_name,
                "index_value": str(value.price),
                "index_published_on": value.published_on.isoformat(),
                "index_week_start": value.week_start.isoformat(),
                "band": [band.params["min"], band.params["max"]],
                "percent": str(pct),
                "base_cents": base,
                "base_source": base_source,
                "expected_cents": expected,
                "billed_cents": billed,
            },
            **common,
        )
    ]


# ---------------------------------------------------------------- C-04 accessorials


def check_accessorials(invoice: Invoice, ctx: RunContext) -> list[CheckResult]:
    lines = invoice.lines_of("accessorial")
    if not lines:
        return [CheckResult("C-04", "not_applicable")]
    resolution = resolve(ctx.documents, "accessorial_schedule", invoice)
    out: list[CheckResult] = []
    for ln in lines:
        if isinstance(resolution, Unresolved):
            out.append(_exception("C-04", resolution.exception_code, resolution.detail, line_no=ln.line_no))
        else:
            doc = resolution.document
            rules = [r for r in doc.rules_of("accessorial") if r.params["code"] == ln.accessorial_code]
            common: dict[str, Any] = {
                "line_no": ln.line_no,
                "rate_document_revision": doc.revision,
                "governing_date": resolution.governing_date,
                "basis": basis_of(doc),
            }
            if len(rules) != 1:
                out.append(_exception("C-04", "GOVERNING_RATE_MISSING", f"no schedule entry for {ln.accessorial_code}", **common))
            else:
                expected = dollars_to_cents(rules[0].params["amount"])
                out.append(
                    _compare(
                        "C-04",
                        expected,
                        ln.amount_cents,
                        ctx.tolerance_cents,
                        rate_rule_id=rules[0].id,
                        arithmetic={"code": ln.accessorial_code, "schedule_cents": expected},
                        **common,
                    )
                )
        # Support test: a question for a person, never an assertion that the carrier is wrong.
        if invoice.bol_accessorials is None:
            out.append(_exception("C-04-SUPPORT", "DOCUMENT_MISSING", "no bill of lading linked", line_no=ln.line_no))
        elif ln.accessorial_code in invoice.bol_accessorials:
            out.append(CheckResult("C-04-SUPPORT", "pass", line_no=ln.line_no))
        else:
            out.append(
                CheckResult(
                    "C-04-SUPPORT",
                    "variance",
                    line_no=ln.line_no,
                    review_flags=("not_requested_on_bol",),
                    arithmetic={"question": "not requested on BOL; review"},
                )
            )
    return out


# ---------------------------------------------------------------- C-01 duplicates


def check_duplicates(invoice: Invoice, ctx: RunContext) -> list[CheckResult]:
    matches: list[dict[str, str]] = []
    for c in ctx.duplicate_candidates:
        same_carrier = c.carrier_key == invoice.carrier_key
        reason = None
        if same_carrier and c.invoice_number and c.invoice_number == invoice.invoice_number:
            reason = "same_carrier_invoice_number"
        elif same_carrier and invoice.pro_number and c.pro_number == invoice.pro_number:
            reason = "same_carrier_pro"
        elif (
            invoice.pro_number
            and c.pro_number == invoice.pro_number
            and c.total_cents == invoice.total_cents
            and (c.invoice_date is None or c.invoice_date == invoice.invoice_date)
        ):
            reason = "same_pro_date_total"
        if reason:
            matches.append({"match": c.ref, "reason": reason})
    if not matches:
        return [CheckResult("C-01", "pass")]
    return [
        CheckResult(
            "C-01",
            "variance",
            expected_cents=0,
            billed_cents=invoice.total_cents,
            variance_cents=invoice.total_cents,
            arithmetic={"candidates": matches},
        )
    ]


# ---------------------------------------------------------------- C-07 arithmetic


def check_arithmetic(invoice: Invoice, ctx: RunContext) -> list[CheckResult]:
    line_sum = sum(ln.amount_cents for ln in invoice.lines)
    return [
        _compare(
            "C-07",
            line_sum,
            invoice.total_cents,
            ctx.tolerance_cents,
            arithmetic={"line_sum_cents": line_sum, "total_cents": invoice.total_cents},
        )
    ]


# ---------------------------------------------------------------- C-08 late rebill

LATE_REBILL_DAYS = 180


def check_late_rebill(invoice: Invoice, ctx: RunContext) -> list[CheckResult]:
    if invoice.original_bill_receipt_date is None:
        return [CheckResult("C-08", "not_applicable")]
    if invoice.invoice_date is None:
        return [_exception("C-08", "GOVERNING_DATE_MISSING", "additional bill has no invoice date")]
    days = (invoice.invoice_date - invoice.original_bill_receipt_date).days
    arithmetic = {
        "original_receipt": invoice.original_bill_receipt_date.isoformat(),
        "rebill_date": invoice.invoice_date.isoformat(),
        "days": days,
    }
    if days > LATE_REBILL_DAYS:
        arithmetic["question"] = "Possible late rebill, review"
        return [CheckResult("C-08", "variance", review_flags=("possible_late_rebill",), arithmetic=arithmetic)]
    return [CheckResult("C-08", "pass", arithmetic=arithmetic)]


# ---------------------------------------------------------------- runner

CHECKS: tuple[tuple[str, Callable[[Invoice, RunContext], list[CheckResult]]], ...] = (
    ("C-01", check_duplicates),
    ("C-02", check_linehaul),
    ("C-03", check_fuel),
    ("C-04", check_accessorials),
    ("C-07", check_arithmetic),
    ("C-08", check_late_rebill),
)


def run_checks(invoice: Invoice, ctx: RunContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    for code, fn in CHECKS:
        try:
            produced = fn(invoice, ctx)
        except Exception as exc:  # noqa: BLE001 - a crash is an exception result, never a pass
            produced = [_exception(code, "ENGINE_ERROR", type(exc).__name__)]
        results.extend(replace(r, arithmetic={**r.arithmetic, "engine_version": ENGINE_VERSION}) for r in produced)
    return results


def roll_up(invoice: Invoice, results: list[CheckResult]) -> InvoiceStatus:
    """`clean` only when every applicable check passed and fields are confirmed."""
    if not invoice.fields_confirmed:
        return "needs_review"
    if any(r.status == "exception" for r in results):
        return "needs_input"
    if any(r.status == "variance" for r in results):
        return "variance"
    if any(r.status not in ("pass", "not_applicable") for r in results):  # pragma: no cover
        return "needs_input"
    return "clean"


__all__ = [
    "CHECKS",
    "ENGINE_VERSION",
    "RuleParamError",
    "roll_up",
    "run_checks",
    "validate_rule_params",
]
