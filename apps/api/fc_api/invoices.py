"""Files, invoices (manual keying), findings (T-2.2.5, T-4.2.7, T-5.1.1 API subsets)."""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from fc_api.core import AUDITOR_PLUS, VIEWER_PLUS, ApiError, Ctx, idempotent, jsonable, tenant_ctx
from fc_core.deadline import DeadlineInput, ReceiptEvidence, compute_deadline, days_left
from fc_db import ops
from fc_db.tables import carrier_account, check_result, finding, invoice, invoice_line, source_file
from fc_platform.clock import today
from fc_platform.settings import get_settings
from fc_platform.storage import (
    MAX_BYTES,
    PURPOSES,
    FakeScanner,
    LocalFakeStorage,
    signed_url,
    sniff_mime,
    storage_key,
    verify,
)

router = APIRouter()
api = APIRouter(prefix="/api/v1")


def storage() -> LocalFakeStorage:
    return LocalFakeStorage(get_settings().storage_dir)


@api.post("/files")
async def upload_file(
    request: Request,
    purpose: str = Form(...),
    file: UploadFile = File(...),
    ctx: Ctx = Depends(tenant_ctx),
) -> JSONResponse:
    ctx.require(AUDITOR_PLUS)
    data = await file.read(MAX_BYTES + 1)
    digest = hashlib.sha256(data).digest()

    def go() -> tuple[int, dict[str, Any]]:
        if purpose not in PURPOSES:
            raise ApiError(422, "BAD_PURPOSE", "unknown purpose", field="purpose")
        if len(data) > MAX_BYTES:
            raise ApiError(413, "FILE_TOO_LARGE", "files are limited to 20 MB")
        mime = sniff_mime(data)
        if mime is None:
            raise ApiError(415, "UNSUPPORTED_TYPE", "PDF, PNG, JPEG or CSV only")
        if FakeScanner().scan(data) != "clean":
            raise ApiError(422, "INFECTED", "the file failed the malware scan")
        existing = ctx.conn.execute(
            select(source_file).where(source_file.c.sha256 == digest, source_file.c.purpose == purpose)
        ).first()
        if existing is not None:
            return 200, {**jsonable(existing, exclude=("sha256", "storage_key")), "duplicate": True}
        key = storage_key(ctx.tenant_id, purpose, "upload")
        storage().put(key, data)
        row = ctx.conn.execute(
            source_file.insert()
            .values(
                tenant_id=ctx.tenant_id,
                sha256=digest,
                purpose=purpose,
                storage_key=key,
                byte_size=len(data),
                mime=mime,
                scan_state="clean",
            )
            .returning(source_file)
        ).one()
        return 201, {**jsonable(row, exclude=("sha256", "storage_key")), "duplicate": False}

    return idempotent(request, ctx, {"purpose": purpose, "sha256": digest.hex()}, go)


@api.get("/files/{file_id}/url")
def file_url(file_id: str, ctx: Ctx = Depends(tenant_ctx)) -> dict[str, str]:
    ctx.require(AUDITOR_PLUS)
    row = ctx.row(source_file, file_id)
    s = get_settings()
    return {"url": signed_url(s.public_base_url, row.storage_key, int(time.time()), s.signing_key)}


@router.get("/files/raw")
def file_raw(k: str, e: int, s: str) -> Response:
    settings = get_settings()
    if not verify(k, e, s, int(time.time()), settings.signing_key):
        raise ApiError(404, "NOT_FOUND", "link expired or invalid")
    # The key was issued under RLS by file_url; only the HMAC signature grants access.
    return Response(
        storage().get(k),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="document"'},
    )


# ------------------------------------------------------------------ invoices


class LineIn(BaseModel):
    line_no: int = Field(gt=0)
    charge_type: Literal["linehaul", "fuel", "accessorial", "discount", "other"]
    amount_cents: int
    accessorial_code: str | None = None
    description: str | None = None


class ReceiptIn(BaseModel):
    carrier_transmission_on: date | None = None
    ap_received_on: date | None = None
    user_entered_on: date | None = None
    user_note: str | None = None


class InvoiceIn(BaseModel):
    carrier_account_id: uuid.UUID
    invoice_number: str = Field(min_length=1)
    pro_number: str | None = None
    invoice_date: date | None = None
    pickup_date: date | None = None
    tender_date: date | None = None
    delivery_date: date | None = None
    billed_weight_lb: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    billed_class: str | None = None
    total_cents: int
    lines: list[LineIn] = Field(min_length=1)
    receipt_evidence: ReceiptIn = ReceiptIn()
    # When the forward reached FreightCheck. Recorded for the trail only; never a receipt date.
    forwarded_received_at: datetime | None = None
    fields_confirmed: bool = True  # manual keying is a person's entry
    revision_of: uuid.UUID | None = None
    lane_key: str | None = Field(default=None, min_length=1)


def invoice_out(ctx: Ctx, inv_id: uuid.UUID) -> dict[str, Any]:
    inv = ctx.row(invoice, inv_id)
    out = jsonable(inv)
    out["days_left"] = days_left(inv.contest_by, today()) if inv.contest_by else None
    out["lines"] = [
        jsonable(r, exclude=("tenant_id",))
        for r in ctx.conn.execute(
            select(invoice_line).where(invoice_line.c.invoice_id == inv.id).order_by(invoice_line.c.line_no)
        ).all()
    ]
    latest = ctx.conn.execute(select(func.max(check_result.c.run_no)).where(check_result.c.invoice_id == inv.id)).scalar_one()
    out["run_no"] = latest
    out["results"] = (
        [
            jsonable(r)
            for r in ctx.conn.execute(
                select(check_result)
                .where(check_result.c.invoice_id == inv.id, check_result.c.run_no == latest)
                .order_by(check_result.c.check_code, check_result.c.line_no)
            ).all()
        ]
        if latest
        else []
    )
    return out


@api.post("/invoices")
def create_invoice(body: InvoiceIn, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(AUDITOR_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        carrier = ctx.row(carrier_account, body.carrier_account_id)
        if body.revision_of:
            ctx.row(invoice, body.revision_of)
        ev = body.receipt_evidence
        try:
            dl = compute_deadline(
                DeadlineInput(
                    carrier_type=carrier.carrier_type,
                    invoice_date=body.invoice_date,
                    evidence=ReceiptEvidence(
                        ev.carrier_transmission_on,
                        ev.ap_received_on,
                        ev.user_entered_on,
                        ev.user_note,
                        freightcheck_received_at=body.forwarded_received_at,
                    ),
                    contract_term_days=carrier.dispute_window_days,
                    contract_term_has_source=carrier.dispute_window_source_file_id is not None,
                    today=today(),
                )
            )
        except ValueError as exc:
            raise ApiError(422, "RECEIPT_NOTE_REQUIRED", str(exc), field="receipt_evidence.user_note") from exc
        if dl.rejected_evidence:
            # B1-008: a receipt cannot postdate today or the forward's arrival at FreightCheck.
            raise ApiError(
                422,
                "RECEIPT_DATE_IMPOSSIBLE",
                "receipt evidence after today or after the forward arrived: " + ", ".join(dl.rejected_evidence),
                field="receipt_evidence",
            )
        if len({ln.line_no for ln in body.lines}) != len(body.lines):
            raise ApiError(422, "DUPLICATE_LINE", "line numbers must be unique", field="lines")
        try:
            with ctx.conn.begin_nested():
                inv = ctx.conn.execute(
                    invoice.insert()
                    .values(
                        tenant_id=ctx.tenant_id,
                        carrier_account_id=carrier.id,
                        invoice_number=body.invoice_number,
                        pro_number=body.pro_number,
                        revision_of=body.revision_of,
                        invoice_date=body.invoice_date,
                        pickup_date=body.pickup_date,
                        tender_date=body.tender_date,
                        delivery_date=body.delivery_date,
                        billed_weight_lb=body.billed_weight_lb,
                        billed_class=body.billed_class,
                        lane_key=body.lane_key,
                        total_cents=body.total_cents,
                        fields_confirmed=body.fields_confirmed,
                        receipt_date=dl.receipt_date,
                        receipt_basis=dl.receipt_basis,
                        receipt_note=dl.receipt_note,
                        contest_by=dl.contest_by,
                        deadline_basis=dl.deadline_basis,
                    )
                    .returning(invoice)
                ).one()
        except IntegrityError as exc:
            raise ApiError(409, "DUPLICATE_INVOICE", "this invoice revision exists") from exc
        for ln in body.lines:
            ctx.conn.execute(invoice_line.insert().values(tenant_id=ctx.tenant_id, invoice_id=inv.id, **ln.model_dump()))
        job_id = ops.enqueue_run_checks(ctx.conn, inv)
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="invoice.keyed",
            entity_type="invoice",
            entity_id=inv.id,
        )
        out = invoice_out(ctx, inv.id)
        out["deadline_exception"] = dl.exception_code
        out["run_checks_job_id"] = str(job_id)
        return 201, out

    return idempotent(request, ctx, body.model_dump(mode="json"), go)


@api.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str, ctx: Ctx = Depends(tenant_ctx)) -> dict[str, Any]:
    ctx.require(VIEWER_PLUS)
    return invoice_out(ctx, ctx.row(invoice, invoice_id).id)


@api.post("/invoices/{invoice_id}/rerun")
def rerun_invoice(invoice_id: str, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(AUDITOR_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        inv = ctx.row(invoice, invoice_id, for_update=True)
        inv = ctx.conn.execute(
            invoice.update()
            .where(invoice.c.id == inv.id)
            .values(ruleset_revision=invoice.c.ruleset_revision + 1, version=invoice.c.version + 1, updated_at=func.now())
            .returning(invoice)
        ).one()
        return 202, {"job_id": str(ops.enqueue_run_checks(ctx.conn, inv))}

    return idempotent(request, ctx, {"invoice_id": invoice_id}, go)


# ------------------------------------------------------------------ findings


@api.get("/findings")
def list_findings(invoice_id: str | None = None, ctx: Ctx = Depends(tenant_ctx)) -> list[dict[str, Any]]:
    ctx.require(VIEWER_PLUS)
    stmt = select(
        finding, check_result.c.status.label("result_status"), check_result.c.variance_cents, check_result.c.exception_code
    ).join(check_result, check_result.c.id == finding.c.current_result_id)
    if invoice_id:
        stmt = stmt.where(finding.c.invoice_id == ctx.row(invoice, invoice_id).id)
    return [jsonable(r) for r in ctx.conn.execute(stmt.order_by(finding.c.check_code, finding.c.line_no)).all()]


class DecisionIn(BaseModel):
    decision: Literal["confirmed_for_claim", "dismissed"]
    reason: str | None = None


@api.post("/findings/{finding_id}/decision")
def decide_finding(finding_id: str, body: DecisionIn, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(AUDITOR_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        f = ctx.row(finding, finding_id, for_update=True)
        result = ctx.row(check_result, f.current_result_id)
        if body.decision == "dismissed" and not (body.reason or "").strip():
            raise ApiError(422, "REASON_REQUIRED", "dismissing needs a reason", field="reason")
        if body.decision == "confirmed_for_claim":
            if result.status == "exception":
                raise ApiError(409, "EXCEPTION_NOT_CLAIMABLE", "an exception is resolved by input, not claimed")
            if result.status != "variance" or (result.variance_cents or 0) <= 0:
                raise ApiError(409, "NOT_CLAIMABLE", "only a positive money variance can be claimed")
        row = ctx.conn.execute(
            finding.update()
            .where(finding.c.id == f.id)
            .values(
                decision=body.decision,
                dismiss_reason=body.reason if body.decision == "dismissed" else None,
                decided_by=ctx.user_id,
                decided_at=func.now(),
                version=finding.c.version + 1,
                updated_at=func.now(),
            )
            .returning(finding)
        ).one()
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action=f"finding.{body.decision}",
            entity_type="finding",
            entity_id=f.id,
        )
        return 200, jsonable(row)

    return idempotent(request, ctx, {"finding_id": finding_id, **body.model_dump()}, go)
