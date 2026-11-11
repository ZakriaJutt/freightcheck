"""Carriers, rate documents and fuel index values (T-4.1.1, T-4.1.2 API subset; MH-03, MH-06)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from fc_api.core import APPROVER_PLUS, AUDITOR_PLUS, VIEWER_PLUS, ApiError, Ctx, idempotent, jsonable, tenant_ctx
from fc_core.checks import RuleParamError, validate_rule_params
from fc_db import ops
from fc_db.tables import carrier_account, fuel_index_price, rate_document, rate_rule, source_file

router = APIRouter(prefix="/api/v1")


class CarrierIn(BaseModel):
    name: str = Field(min_length=1)
    scac: str | None = None
    carrier_type: Literal["motor_carrier", "broker", "other"]
    claims_email: str | None = None
    dispute_window_days: int | None = Field(default=None, gt=0)
    dispute_window_source_file_id: uuid.UUID | None = None


@router.post("/carriers")
def create_carrier(body: CarrierIn, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(APPROVER_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        if body.dispute_window_source_file_id:
            ctx.row(source_file, body.dispute_window_source_file_id)
        if body.dispute_window_days is not None and body.dispute_window_source_file_id is None:
            raise ApiError(
                422,
                "SOURCE_REQUIRED",
                "a contract dispute window needs its source document",
                field="dispute_window_source_file_id",
            )
        row = ctx.conn.execute(
            carrier_account.insert().values(tenant_id=ctx.tenant_id, **body.model_dump()).returning(carrier_account)
        ).one()
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="carrier.created",
            entity_type="carrier_account",
            entity_id=row.id,
        )
        return 201, jsonable(row)

    return idempotent(request, ctx, body.model_dump(mode="json"), go)


@router.get("/carriers")
def list_carriers(ctx: Ctx = Depends(tenant_ctx)) -> list[dict[str, Any]]:
    ctx.require(VIEWER_PLUS)
    return [jsonable(r) for r in ctx.conn.execute(select(carrier_account).order_by(carrier_account.c.name)).all()]


# ------------------------------------------------------------------ rate documents


class RateDocumentIn(BaseModel):
    carrier_account_id: uuid.UUID
    doc_type: Literal["contract_rate_sheet", "tariff", "accessorial_schedule", "fuel_schedule", "rate_confirmation"]
    effective_from: date
    effective_to: date | None = None
    scope_key: str = "*"
    date_basis: Literal["pickup_date", "tender_date", "delivery_date", "invoice_date"]
    date_basis_source_page: int | None = Field(default=None, gt=0)
    source_file_id: uuid.UUID


def _doc_out(ctx: Ctx, doc_id: uuid.UUID) -> dict[str, Any]:
    doc = ctx.row(rate_document, doc_id)
    rules = ctx.conn.execute(
        select(rate_rule).where(rate_rule.c.rate_document_id == doc.id).order_by(rate_rule.c.created_at, rate_rule.c.id)
    ).all()
    out = jsonable(doc)
    out["date_basis_chosen_by_approver"] = doc.date_basis_source_page is None
    out["rules"] = [jsonable(r) for r in rules]
    return out


@router.post("/rate-documents")
def create_rate_document(body: RateDocumentIn, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(AUDITOR_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        ctx.row(carrier_account, body.carrier_account_id)
        ctx.row(source_file, body.source_file_id)
        if body.effective_to is not None and body.effective_to <= body.effective_from:
            raise ApiError(422, "BAD_RANGE", "effective_to must be after effective_from", field="effective_to")
        rid = ctx.conn.execute(
            rate_document.insert().values(tenant_id=ctx.tenant_id, **body.model_dump()).returning(rate_document.c.id)
        ).scalar_one()
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="rate_document.entered",
            entity_type="rate_document",
            entity_id=rid,
        )
        return 201, _doc_out(ctx, rid)

    return idempotent(request, ctx, body.model_dump(mode="json"), go)


@router.get("/rate-documents/{doc_id}")
def get_rate_document(doc_id: str, ctx: Ctx = Depends(tenant_ctx)) -> dict[str, Any]:
    ctx.require(VIEWER_PLUS)
    return _doc_out(ctx, ctx.row(rate_document, doc_id).id)


class RuleIn(BaseModel):
    rule_type: str
    params: dict[str, Any]
    source_page: int | None = Field(default=None, gt=0)


class RulesIn(BaseModel):
    rules: list[RuleIn] = Field(min_length=1)
    replace: bool = False


@router.post("/rate-documents/{doc_id}/rules")
def add_rules(doc_id: str, body: RulesIn, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(AUDITOR_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        doc = ctx.row(rate_document, doc_id, for_update=True)
        if doc.status != "entered":
            raise ApiError(409, "DOCUMENT_CONFIRMED", "a confirmed document is changed only by a new revision")
        for i, r in enumerate(body.rules):
            try:
                validate_rule_params(r.rule_type, r.params)
            except RuleParamError as exc:
                raise ApiError(422, "BAD_RULE", str(exc), field=f"rules[{i}]") from exc
        if body.replace:
            ctx.conn.execute(rate_rule.delete().where(rate_rule.c.rate_document_id == doc.id))
        for r in body.rules:
            ctx.conn.execute(
                rate_rule.insert().values(
                    tenant_id=ctx.tenant_id,
                    rate_document_id=doc.id,
                    rule_type=r.rule_type,
                    params=r.params,
                    source_page=r.source_page,
                    entered_by=ctx.user_id,
                )
            )
        return 201, _doc_out(ctx, doc.id)

    return idempotent(request, ctx, body.model_dump(mode="json"), go)


@router.post("/rate-documents/{doc_id}/confirm")
def confirm_rate_document(doc_id: str, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(APPROVER_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        doc = ctx.row(rate_document, doc_id, for_update=True)
        if doc.status != "entered":
            raise ApiError(409, "NOT_ENTERED", f"document is {doc.status}")
        rules = ctx.conn.execute(select(rate_rule).where(rate_rule.c.rate_document_id == doc.id)).all()
        if not rules:
            raise ApiError(422, "NO_RULES", "a document needs at least one rule before confirmation")
        for r in rules:
            try:
                validate_rule_params(r.rule_type, r.params)
            except RuleParamError as exc:
                raise ApiError(422, "BAD_RULE", str(exc)) from exc
        # B1-013: the governing state of every open claim line, taken before anything changes.
        before = ops.states_before(ctx.conn, doc.carrier_account_id)
        if doc.revises_id is not None:
            prior = ctx.row(rate_document, doc.revises_id, for_update=True)
            if prior.status != "confirmed":
                raise ApiError(409, "PRIOR_NOT_CONFIRMED", "the revised document is no longer confirmed")
            ctx.conn.execute(
                rate_document.update()
                .where(rate_document.c.id == prior.id)
                .values(status="superseded", version=rate_document.c.version + 1, updated_at=func.now())
            )
        overlap = ctx.conn.execute(
            select(rate_document.c.id, rate_document.c.revision).where(
                rate_document.c.status == "confirmed",
                rate_document.c.id != doc.id,
                rate_document.c.carrier_account_id == doc.carrier_account_id,
                rate_document.c.doc_type == doc.doc_type,
                rate_document.c.scope_key == doc.scope_key,
                text("daterange(effective_from, effective_to, '[]') && daterange(:f, :t, '[]')").bindparams(
                    f=doc.effective_from, t=doc.effective_to
                ),
            )
        ).first()
        if overlap is not None:
            raise ApiError(
                409,
                "RATE_DOCUMENT_OVERLAP",
                f"overlaps confirmed document {overlap.id} revision {overlap.revision}",
                conflicting_document_id=str(overlap.id),
                conflicting_revision=overlap.revision,
            )
        try:
            with ctx.conn.begin_nested():
                ctx.conn.execute(
                    rate_document.update()
                    .where(rate_document.c.id == doc.id)
                    .values(
                        status="confirmed",
                        confirmed_by=ctx.user_id,
                        confirmed_at=func.now(),
                        version=rate_document.c.version + 1,
                        updated_at=func.now(),
                    )
                )
        except IntegrityError as exc:
            raise ApiError(409, "RATE_DOCUMENT_OVERLAP", "overlaps another confirmed document") from exc
        # B1-001, B1-013: mark only claims whose own lines actually changed, compared before and after.
        marked = ops.reevaluate_claims(ctx.conn, doc.carrier_account_id, before)
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="rate_document.confirmed",
            entity_type="rate_document",
            entity_id=doc.id,
            after={"revision": doc.revision, "supersedes": str(doc.revises_id) if doc.revises_id else None},
        )
        out = _doc_out(ctx, doc.id)
        out["marked_claims"] = {k: [str(i) for i in v] for k, v in marked.items()}
        return 200, out

    return idempotent(request, ctx, {"doc_id": doc_id}, go)


class ReviseIn(BaseModel):
    effective_from: date | None = None
    effective_to: date | None = None
    source_file_id: uuid.UUID | None = None
    date_basis: Literal["pickup_date", "tender_date", "delivery_date", "invoice_date"] | None = None


@router.post("/rate-documents/{doc_id}/revise")
def revise_rate_document(doc_id: str, body: ReviseIn, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(AUDITOR_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        doc = ctx.row(rate_document, doc_id, for_update=True)
        if doc.status != "confirmed":
            raise ApiError(409, "NOT_CONFIRMED", "only a confirmed document is revised")
        if body.source_file_id:
            ctx.row(source_file, body.source_file_id)
        values = {
            "tenant_id": ctx.tenant_id,
            "carrier_account_id": doc.carrier_account_id,
            "doc_type": doc.doc_type,
            "effective_from": body.effective_from or doc.effective_from,
            "effective_to": body.effective_to if "effective_to" in body.model_fields_set else doc.effective_to,
            "scope_key": doc.scope_key,
            "date_basis": body.date_basis or doc.date_basis,
            "date_basis_source_page": doc.date_basis_source_page,
            "revision": doc.revision + 1,
            "revises_id": doc.id,
            "source_file_id": body.source_file_id or doc.source_file_id,
        }
        new_id = ctx.conn.execute(rate_document.insert().values(**values).returning(rate_document.c.id)).scalar_one()
        for r in ctx.conn.execute(select(rate_rule).where(rate_rule.c.rate_document_id == doc.id)).all():
            ctx.conn.execute(
                rate_rule.insert().values(
                    tenant_id=ctx.tenant_id,
                    rate_document_id=new_id,
                    rule_type=r.rule_type,
                    params=r.params,
                    source_page=r.source_page,
                    entered_by=ctx.user_id,
                )
            )
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="rate_document.revised",
            entity_type="rate_document",
            entity_id=new_id,
        )
        return 201, _doc_out(ctx, new_id)

    return idempotent(request, ctx, {"doc_id": doc_id, **body.model_dump(mode="json")}, go)


# ------------------------------------------------------------------ fuel index values


class FuelIndexIn(BaseModel):
    carrier_account_id: uuid.UUID | None = None
    index_name: str = Field(min_length=1)
    week_start: date
    price: Decimal = Field(max_digits=7, decimal_places=4)
    published_on: date
    source_note: str = Field(min_length=1)
    revises_id: uuid.UUID | None = None


@router.post("/fuel-index")
def create_fuel_index(body: FuelIndexIn, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(AUDITOR_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        if body.carrier_account_id:
            ctx.row(carrier_account, body.carrier_account_id)
        revision = 1
        if body.revises_id is not None:
            prior = ctx.row(fuel_index_price, body.revises_id)
            if prior.status != "confirmed":
                raise ApiError(409, "NOT_CONFIRMED", "only a confirmed value is corrected")
            if (prior.index_name, prior.week_start, prior.carrier_account_id) != (
                body.index_name,
                body.week_start,
                body.carrier_account_id,
            ):
                raise ApiError(422, "REVISION_MISMATCH", "a correction keeps index, week and carrier")
            revision = prior.revision + 1
        try:
            with ctx.conn.begin_nested():
                row = ctx.conn.execute(
                    fuel_index_price.insert()
                    .values(tenant_id=ctx.tenant_id, revision=revision, **body.model_dump())
                    .returning(fuel_index_price)
                ).one()
        except IntegrityError as exc:
            raise ApiError(409, "DUPLICATE_VALUE", "a value for this index, week and revision exists") from exc
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="fuel_index.entered",
            entity_type="fuel_index_price",
            entity_id=row.id,
        )
        return 201, jsonable(row)

    return idempotent(request, ctx, body.model_dump(mode="json"), go)


@router.post("/fuel-index/{value_id}/confirm")
def confirm_fuel_index(value_id: str, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(APPROVER_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        v = ctx.row(fuel_index_price, value_id, for_update=True)
        if v.status != "entered":
            raise ApiError(409, "NOT_ENTERED", f"value is {v.status}")
        # B1-013: the governing state of every open claim line, taken before anything changes.
        before = ops.states_before(ctx.conn, v.carrier_account_id)
        if v.revises_id is not None:
            prior = ctx.row(fuel_index_price, v.revises_id, for_update=True)
            if prior.status != "confirmed":  # B1-010: a racing correction already superseded it
                raise ApiError(409, "PRIOR_NOT_CONFIRMED", "the corrected value is no longer confirmed")
            ctx.conn.execute(
                fuel_index_price.update()
                .where(fuel_index_price.c.id == v.revises_id)
                .values(status="superseded", version=fuel_index_price.c.version + 1, updated_at=func.now())
            )
        try:
            with ctx.conn.begin_nested():
                ctx.conn.execute(
                    fuel_index_price.update()
                    .where(fuel_index_price.c.id == v.id)
                    .values(
                        status="confirmed",
                        confirmed_by=ctx.user_id,
                        confirmed_at=func.now(),
                        version=fuel_index_price.c.version + 1,
                        updated_at=func.now(),
                    )
                )
        except IntegrityError as exc:
            raise ApiError(
                409, "VALUE_ALREADY_CONFIRMED", "a confirmed value for this index and week exists; correct it instead"
            ) from exc
        # B1-001, B1-013: mark only claims whose own lines actually changed, compared before and after.
        marked = ops.reevaluate_claims(ctx.conn, v.carrier_account_id, before)
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="fuel_index.confirmed",
            entity_type="fuel_index_price",
            entity_id=v.id,
        )
        out = jsonable(ctx.row(fuel_index_price, v.id))
        out["marked_claims"] = {k: [str(i) for i in val] for k, val in marked.items()}
        return 200, out

    return idempotent(request, ctx, {"value_id": value_id}, go)
