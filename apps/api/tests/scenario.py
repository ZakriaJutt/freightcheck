"""Synthetic pilot scenario over the API: the UT-01 and UT-03 invoice (execution-plan 7)."""

from __future__ import annotations

from typing import Any

from conftest import APP_URL, Api, World

from fc_platform.db import engine_for
from fc_worker.main import run_until_idle

INDEX = "US_DIESEL_WEEKLY"
PDF = b"%PDF-1.4\n% synthetic test document\n"


def upload(api: Api, purpose: str, tag: str) -> str:
    r = api.post(
        "/api/v1/files",
        data={"purpose": purpose},
        files={"file": (f"{tag}.pdf", PDF + tag.encode(), "application/pdf")},
        expect=201,
    )
    return str(r.json()["id"])


def run_worker() -> int:
    return run_until_idle(engine_for(APP_URL))


class Pilot:
    """One tenant with an Auditor and an Approver, a carrier, confirmed rates and fuel values."""

    def __init__(self, world: World, name: str = "Synthetic Shipper T1") -> None:
        self.tenant_id = world.tenant(name)
        self.auditor = world.user(self.tenant_id, "auditor")
        self.approver = world.user(self.tenant_id, "approver")
        self.viewer = world.user(self.tenant_id, "viewer")
        p = self.approver
        self.carrier_id = p.post(
            "/api/v1/carriers", {"name": "Example Freight Lines", "carrier_type": "motor_carrier"}, expect=201
        ).json()["id"]
        self.contract_id = self.doc(
            "contract_rate_sheet",
            "2026-01-01",
            "2026-12-31",
            [
                {"rule_type": "linehaul", "params": {"basis": "per_cwt", "rate": "38.50", "class": "70"}, "source_page": 2},
                {"rule_type": "discount", "params": {"percent": "62"}, "source_page": 2},
                {"rule_type": "minimum", "params": {"amount": "145.00"}, "source_page": 3},
            ],
        )
        self.fuel_id = self.doc("fuel_schedule", "2026-01-01", None, self.fuel_rules("28.5"))
        self.fv_0302 = self.fuel_value("2026-03-02", "3.74")
        self.fv_0309 = self.fuel_value("2026-03-09", "3.78")

    @staticmethod
    def fuel_rules(upper_pct: str) -> list[dict[str, Any]]:
        return [
            {"rule_type": "fuel_band", "params": {"index_name": INDEX, "min": "3.700", "max": "3.749", "percent": "28.0"}},
            {"rule_type": "fuel_band", "params": {"index_name": INDEX, "min": "3.750", "max": "3.799", "percent": upper_pct}},
            {
                "rule_type": "fuel_week_rule",
                "params": {"index_name": INDEX, "published_weekday": 0, "applies_from_days": 1, "applies_through_days": 7},
            },
        ]

    def doc(self, doc_type: str, start: str, end: str | None, rules: list[dict[str, Any]]) -> str:
        src = upload(self.auditor, "rate_document", f"{doc_type}-{start}")
        d = self.auditor.post(
            "/api/v1/rate-documents",
            {
                "carrier_account_id": self.carrier_id,
                "doc_type": doc_type,
                "effective_from": start,
                "effective_to": end,
                "date_basis": "pickup_date",
                "date_basis_source_page": 1,
                "source_file_id": src,
            },
            expect=201,
        ).json()
        self.auditor.post(f"/api/v1/rate-documents/{d['id']}/rules", {"rules": rules}, expect=201)
        self.approver.post(f"/api/v1/rate-documents/{d['id']}/confirm", expect=200)
        return str(d["id"])

    def fuel_value(self, published: str, price: str, revises: str | None = None) -> str:
        v = self.auditor.post(
            "/api/v1/fuel-index",
            {
                "carrier_account_id": None,
                "index_name": INDEX,
                "week_start": published,
                "price": price,
                "published_on": published,
                "source_note": "weekly index page, synthetic",
                "revises_id": revises,
            },
            expect=201,
        ).json()
        self.approver.post(f"/api/v1/fuel-index/{v['id']}/confirm", expect=200)
        return str(v["id"])

    def invoice(
        self, number: str = "884213", pro: str = "PRO-5550001", ap_received: str | None = "2026-03-16", **kw: Any
    ) -> dict[str, Any]:
        body = {
            "carrier_account_id": self.carrier_id,
            "invoice_number": number,
            "pro_number": pro,
            "invoice_date": "2026-03-16",
            "pickup_date": "2026-03-14",
            "billed_weight_lb": "1200",
            "billed_class": "70",
            "total_cents": 26630,
            "lines": [
                {"line_no": 1, "charge_type": "linehaul", "amount_cents": 20328},
                {"line_no": 2, "charge_type": "fuel", "amount_cents": 6302},
            ],
            "receipt_evidence": {"ap_received_on": ap_received},
            **kw,
        }
        inv = self.auditor.post("/api/v1/invoices", body, expect=201).json()
        run_worker()
        return dict(self.auditor.get(f"/api/v1/invoices/{inv['id']}").json())

    def draft_claim(self, inv: dict[str, Any]) -> dict[str, Any]:
        findings = self.auditor.get(f"/api/v1/findings?invoice_id={inv['id']}").json()
        for f in findings:
            if f["result_status"] == "variance" and (f["variance_cents"] or 0) > 0:
                self.auditor.post(f"/api/v1/findings/{f['id']}/decision", {"decision": "confirmed_for_claim"}, expect=200)
        return dict(self.auditor.post("/api/v1/claims", {"invoice_id": inv["id"], "origin": "pilot"}, expect=201).json())

    def approved_claim(self, inv: dict[str, Any]) -> dict[str, Any]:
        c = self.draft_claim(inv)
        return dict(self.approver.post(f"/api/v1/claims/{c['id']}/approve", {}, expect=200).json())

    def sent_claim(self, inv: dict[str, Any]) -> dict[str, Any]:
        c = self.approved_claim(inv)
        return dict(
            self.approver.post(
                f"/api/v1/claims/{c['id']}/sent", {"sent_on": "2026-04-01", "sent_to": "claims@carrier.example"}, expect=200
            ).json()
        )
