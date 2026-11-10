"""UT-01 to UT-06, UT-08, UT-11: check engine with worked arithmetic."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from core_fixtures import CARRIER, contract_v, fuel_schedule, fuel_values, ut01_invoice

from fc_core.checks import RuleParamError, check_fuel, check_linehaul, roll_up, run_checks, validate_rule_params
from fc_core.model import DuplicateCandidate, Invoice, InvoiceLine, RateDocument, RateRule, RunContext
from fc_core.money import round_half_up_cents
from fc_core.resolver import Resolved, Unresolved, resolve


def by_code(results: list, code: str):  # type: ignore[no-untyped-def]
    return [r for r in results if r.check_code == code]


def test_ut01_linehaul_12cwt_x_38_50_x_0_38_is_175_56_variance_27_72_identical_1000_runs() -> None:
    """12 cwt × 38.50 = 462.00 gross; discount 62% = 286.44; net 175.56 (> minimum 145.00).
    Billed 203.28 − 175.56 = 27.72."""
    ctx = RunContext(documents=(contract_v(),))
    inv = ut01_invoice(with_fuel=False)
    first = check_linehaul(inv, ctx)
    for _ in range(1000):
        assert check_linehaul(inv, ctx) == first
    (r,) = first
    assert (r.status, r.expected_cents, r.billed_cents, r.variance_cents) == ("variance", 17556, 20328, 2772)
    assert r.rate_rule_id == "rs-v2-lh" and r.rate_document_revision == 2
    assert r.arithmetic["gross_cents"] == 46200 and r.arithmetic["discount_cents"] == 28644


def test_ut01_minimum_applies_when_net_below_145() -> None:
    """300 lb: 3 cwt × 38.50 = 115.50; × 0.38 = 43.89 → minimum 145.00."""
    inv = replace(ut01_invoice(with_fuel=False), billed_weight_lb=Decimal("300"))
    (r,) = check_linehaul(inv, RunContext(documents=(contract_v(),)))
    assert r.expected_cents == 14500 and r.arithmetic["minimum_applied"] is True


class TestUT02Resolver:
    docs = (
        contract_v(2, effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30)),
        contract_v(3, effective_from=date(2026, 7, 1), effective_to=None, rate="40.00"),
        contract_v(4, status="entered", effective_from=date(2026, 6, 1), effective_to=None, rate="99.00"),
    )

    @pytest.mark.parametrize(("pickup", "expected"), [(date(2026, 6, 30), 2), (date(2026, 7, 1), 3)])
    def test_boundary_30_jun_is_v2_and_1_jul_is_v3_v4_never(self, pickup: date, expected: int) -> None:
        res = resolve(self.docs, "contract_rate_sheet", ut01_invoice(pickup=pickup))
        assert isinstance(res, Resolved) and res.document.revision == expected
        assert res.governing_date == pickup

    def test_before_1_jan_is_governing_rate_missing(self) -> None:
        res = resolve(self.docs, "contract_rate_sheet", ut01_invoice(pickup=date(2025, 12, 31)))
        assert isinstance(res, Unresolved) and res.exception_code == "GOVERNING_RATE_MISSING"

    def test_no_pickup_date_under_pickup_basis_is_governing_date_missing(self) -> None:
        (r,) = check_linehaul(ut01_invoice(pickup=None, with_fuel=False), RunContext(documents=self.docs))
        assert (r.status, r.exception_code) == ("exception", "GOVERNING_DATE_MISSING")

    def test_superseded_never_chosen(self) -> None:
        docs = (contract_v(2, status="superseded"),)
        res = resolve(docs, "contract_rate_sheet", ut01_invoice(pickup=date(2026, 3, 1)))
        assert isinstance(res, Unresolved)

    def test_base_tariff_unavailable_but_discount_and_minimum_still_checked(self) -> None:
        """Printed gross 462.00; discount 62% → 286.44; net 175.56; billed 203.28 → variance 27.72."""
        doc = RateDocument(
            "rs-bt",
            1,
            "contract_rate_sheet",
            "confirmed",
            date(2026, 1, 1),
            None,
            "pickup_date",
            rules=(
                RateRule("bt", "base_tariff_ref", {"tariff_name": "Carrier base tariff 500"}),
                RateRule("bt-disc", "discount", {"percent": "62"}),
                RateRule("bt-min", "minimum", {"amount": "145.00"}),
            ),
        )
        inv = replace(
            ut01_invoice(with_fuel=False),
            lines=(InvoiceLine(1, "linehaul", 46200), InvoiceLine(2, "discount", -25872)),
            total_cents=20328,
        )
        results = check_linehaul(inv, RunContext(documents=(doc,)))
        (base,) = by_code(results, "C-02-BASE")
        (net,) = by_code(results, "C-02")
        assert base.exception_code == "BASE_TARIFF_UNAVAILABLE"
        assert (net.status, net.expected_cents, net.variance_cents) == ("variance", 17556, 2772)


class TestUT03Fuel:
    def ctx(self, **kw) -> RunContext:  # type: ignore[no-untyped-def]
        return RunContext(
            documents=(contract_v(), kw.pop("schedule", fuel_schedule())),
            fuel_values=kw.pop("values", fuel_values()),
        )

    def test_pickup_sat_14_mar_uses_3_78_published_9_mar_expected_50_03_variance_12_99(self) -> None:
        """175.56 × 28.5% = 50.0346 → 50.03; billed 63.02 − 50.03 = 12.99."""
        (r,) = check_fuel(ut01_invoice(pickup=date(2026, 3, 14)), self.ctx())
        assert (r.status, r.expected_cents, r.variance_cents) == ("variance", 5003, 1299)
        assert r.fuel_index_price_id == "fv-0309" and r.arithmetic["index_value"] == "3.78"
        assert set(r.basis.document_ids) == {"fsc-r1", "rs-v2"}

    def test_pickup_mon_9_mar_uses_3_74_published_2_mar_expected_49_16_variance_13_86(self) -> None:
        """9 Mar value applies from 10 Mar; 9 Mar uses 2 Mar 3.74 → 28.0%: 175.56 × 0.28 = 49.1568 → 49.16."""
        (r,) = check_fuel(ut01_invoice(pickup=date(2026, 3, 9)), self.ctx())
        assert (r.expected_cents, r.variance_cents) == (4916, 1386)
        assert r.fuel_index_price_id == "fv-0302"

    @pytest.mark.parametrize(
        ("kwargs", "code"),
        [
            ({"values": fuel_values(status_9mar=None)}, "INDEX_PRICE_MISSING"),
            ({"values": fuel_values(status_9mar="entered")}, "INDEX_PRICE_UNCONFIRMED"),
            ({"schedule": fuel_schedule(with_week_rule=False)}, "FSC_BASIS_MISSING"),
        ],
    )
    def test_fuel_exceptions_and_linehaul_still_returns_variance(self, kwargs: dict, code: str) -> None:
        results = run_checks(ut01_invoice(pickup=date(2026, 3, 14)), self.ctx(**kwargs))
        (fuel,) = by_code(results, "C-03")
        (lh,) = by_code(results, "C-02")
        assert (fuel.status, fuel.exception_code) == ("exception", code)
        assert (lh.status, lh.variance_cents) == ("variance", 2772)


def test_ut04_liftgate_schedule_85_billed_125_variance_40_support_flag_and_document_missing() -> None:
    sched = RateDocument(
        "acc-1",
        1,
        "accessorial_schedule",
        "confirmed",
        date(2026, 1, 1),
        None,
        "pickup_date",
        rules=(RateRule("acc-lift", "accessorial", {"code": "LIFTGATE", "amount": "85.00"}),),
    )
    base = replace(
        ut01_invoice(with_fuel=False),
        lines=(InvoiceLine(1, "linehaul", 17556), InvoiceLine(2, "accessorial", 12500, "LIFTGATE")),
        total_cents=30056,
    )
    ctx = RunContext(documents=(contract_v(), sched))
    with_bol = run_checks(replace(base, bol_accessorials=frozenset()), ctx)
    (amount,) = by_code(with_bol, "C-04")
    (support,) = by_code(with_bol, "C-04-SUPPORT")
    assert (amount.status, amount.variance_cents) == ("variance", 4000)
    assert support.review_flags == ("not_requested_on_bol",) and support.variance_cents is None
    assert not support.claimable
    no_bol = run_checks(base, ctx)
    (support2,) = by_code(no_bol, "C-04-SUPPORT")
    assert support2.exception_code == "DOCUMENT_MISSING"
    assert by_code(no_bol, "C-04")[0].variance_cents == 4000


def test_ut05_three_duplicate_candidates_each_naming_its_match() -> None:
    inv = ut01_invoice()
    cands = (
        DuplicateCandidate("invoice:a", CARRIER, "884213", "PRO-5550001", inv.invoice_date, inv.total_cents),
        DuplicateCandidate("invoice:b", CARRIER, "884377", "PRO-5550001", date(2026, 3, 20), 1),
        DuplicateCandidate("ap_payment:c", "example freight lines inc", None, "PRO-5550001", None, inv.total_cents),
        DuplicateCandidate("invoice:d", CARRIER, "999999", "PRO-OTHER", inv.invoice_date, inv.total_cents),
    )
    (r,) = run_checks(inv, RunContext(documents=(), duplicate_candidates=cands))[:1]
    assert r.check_code == "C-01" and r.status == "variance"
    assert [c["match"] for c in r.arithmetic["candidates"]] == ["invoice:a", "invoice:b", "ap_payment:c"]


def test_ut06_no_fuel_schedule_and_linehaul_overcharge_is_needs_input_never_clean() -> None:
    inv = ut01_invoice()
    results = run_checks(inv, RunContext(documents=(contract_v(),)))
    assert by_code(results, "C-03")[0].status == "exception"
    assert by_code(results, "C-02")[0].status == "variance"
    assert by_code(results, "C-01")[0].status == "pass"
    assert roll_up(inv, results) == "needs_input"


def test_ut06_crash_in_one_check_is_engine_error_and_others_still_run(monkeypatch: pytest.MonkeyPatch) -> None:
    import fc_core.checks as checks

    def boom(invoice: Invoice, ctx: RunContext) -> list:  # type: ignore[type-arg]
        raise RuntimeError("x")

    monkeypatch.setattr(checks, "CHECKS", (("C-01", boom), *checks.CHECKS[1:]))
    inv = ut01_invoice()
    results = checks.run_checks(inv, RunContext(documents=(contract_v(),)))
    assert by_code(results, "C-01")[0].exception_code == "ENGINE_ERROR"
    assert by_code(results, "C-02")[0].status == "variance"
    assert roll_up(inv, results) != "clean"


def test_ut06_clean_only_when_all_pass_and_unconfirmed_fields_never_clean() -> None:
    inv = replace(ut01_invoice(with_fuel=False), lines=(InvoiceLine(1, "linehaul", 17556),), total_cents=17556)
    results = run_checks(inv, RunContext(documents=(contract_v(),)))
    assert roll_up(inv, results) == "clean"
    assert roll_up(replace(inv, fields_confirmed=False), results) == "needs_review"


@pytest.mark.parametrize(("billed", "status"), [(17556 + 199, "pass"), (17556 + 200, "pass"), (17556 + 201, "variance")])
def test_ut08_tolerance_2_00_variance_1_99_pass_2_01_variance(billed: int, status: str) -> None:
    inv = replace(ut01_invoice(with_fuel=False), lines=(InvoiceLine(1, "linehaul", billed),), total_cents=billed)
    (r,) = check_linehaul(inv, RunContext(documents=(contract_v(),), tolerance_cents=200))
    assert r.status == status


def test_ut08_half_cents_round_half_up_per_line() -> None:
    assert round_half_up_cents(Decimal("0.005")) == 1
    assert round_half_up_cents(Decimal("50.0346")) == 5003
    assert round_half_up_cents(Decimal("2.675")) == 268
    assert round_half_up_cents(Decimal("-0.005")) == -1


def test_ut11_late_rebill_226_days_and_arithmetic_1_00_under_total_is_pass_shown() -> None:
    """1 Feb → 15 Sep 2026 = 226 days > 180; lines sum to total − 1.00, within tolerance 2.00."""
    inv = Invoice(
        id="inv-bd",
        carrier_key=CARRIER,
        invoice_number="BD-1",
        invoice_date=date(2026, 9, 15),
        total_cents=10100,
        lines=(InvoiceLine(1, "other", 10000),),
        original_bill_receipt_date=date(2026, 2, 1),
    )
    results = run_checks(inv, RunContext(documents=()))
    (c08,) = by_code(results, "C-08")
    (c07,) = by_code(results, "C-07")
    assert c08.status == "variance" and c08.arithmetic["days"] == 226
    assert c08.arithmetic["question"] == "Possible late rebill, review" and not c08.claimable
    assert (c07.status, c07.variance_cents) == ("pass", 100)


def test_rule_params_are_validated() -> None:
    validate_rule_params("discount", {"percent": "62"})
    with pytest.raises(RuleParamError):
        validate_rule_params("discount", {"percent": 0.62})
    with pytest.raises(RuleParamError):
        validate_rule_params(
            "fuel_week_rule", {"index_name": "X", "published_weekday": 9, "applies_from_days": 1, "applies_through_days": 7}
        )
    with pytest.raises(RuleParamError):
        validate_rule_params("magic", {})
