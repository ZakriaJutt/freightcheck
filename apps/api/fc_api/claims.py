"""Claims: draft, approve with recompute, send record, events, settlements (T-5.1.3, T-5.1.4).

Guards against the highest-consequence error (wrong-basis dispute sent):
  - approval recomputes every line against confirmed documents and index values as of the
    governing date and fails closed with 409 STALE_BASIS on any difference;
  - approval after the contest-by date needs a typed override reason (409 PAST_CONTEST_BY);
  - a stale approved claim cannot be marked sent;
  - a sent claim whose basis later changes is flagged with old and new amounts and a
    withdrawal note.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fc_api.core import APPROVER_PLUS, AUDITOR_PLUS, VIEWER_PLUS, ApiError, Ctx, idempotent, jsonable, tenant_ctx
from fc_core.ledger import ClaimEvent, LineBasis, evaluate_approval, validate_event, withdrawal_note
from fc_db import ops
from fc_db.tables import (
    carrier_account,
    check_result,
    claim,
    claim_event,
    claim_line,
    fee_statement,
    fee_statement_line,
    finding,
    invoice,
    settlement,
    source_file,
)
from fc_platform.clock import today

router = APIRouter(prefix="/api/v1")

UNSENT = ("draft", "approved")
CLOSED = ("withdrawn", "expired")


def _snapshot(lines: list[dict[str, Any]]) -> dict[str, Any]:
    doc_ids: list[str] = []
    fuel_ids: list[str] = []
    for ln in lines:
        doc_ids += [d for d in ln["basis"]["document_ids"] if d not in doc_ids]
        fuel_ids += [f for f in ln["basis"]["fuel_index_price_ids"] if f not in fuel_ids]
    return {"lines": lines, "document_ids": doc_ids, "fuel_index_price_ids": fuel_ids}


def _draft_lines(ctx: Ctx, invoice_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = ctx.conn.execute(
        select(
            finding.c.id,
            finding.c.check_code,
            finding.c.line_no,
            check_result.c.status,
            check_result.c.variance_cents,
            check_result.c.arithmetic,
        )
        .join(check_result, check_result.c.id == finding.c.current_result_id)
        .where(finding.c.invoice_id == invoice_id, finding.c.decision == "confirmed_for_claim")
        .order_by(finding.c.check_code, finding.c.line_no)
    ).all()
    lines = []
    for r in rows:
        if r.status != "variance" or (r.variance_cents or 0) <= 0:
            continue  # result changed since the decision; it no longer supports a claim line
        lines.append(
            {
                "finding_id": str(r.id),
                "key": ops.finding_key(r.check_code, r.line_no),
                "claimed_cents": r.variance_cents,
                "basis": r.arithmetic["basis"],
            }
        )
    return lines


def _event(ctx: Ctx, claim_id: uuid.UUID, event_type: str, occurred_on: date, **kw: Any) -> None:
    ctx.conn.execute(
        pg_insert(claim_event)
        .values(
            tenant_id=ctx.tenant_id,
            claim_id=claim_id,
            event_type=event_type,
            occurred_on=occurred_on,
            client_event_id=kw.pop("client_event_id", f"sys-{uuid.uuid4().hex}"),
            **kw,
        )
        .on_conflict_do_nothing(index_elements=["claim_id", "client_event_id"])
    )


def _replace_lines(ctx: Ctx, claim_id: uuid.UUID, lines: list[dict[str, Any]]) -> None:
    ctx.conn.execute(claim_line.delete().where(claim_line.c.claim_id == claim_id))
    for ln in lines:
        ctx.conn.execute(
            claim_line.insert().values(
                tenant_id=ctx.tenant_id,
                claim_id=claim_id,
                finding_id=uuid.UUID(ln["finding_id"]),
                claimed_cents=ln["claimed_cents"],
            )
        )


def claim_out(ctx: Ctx, claim_id: uuid.UUID) -> dict[str, Any]:
    c = ctx.row(claim, claim_id)
    inv = ctx.row(invoice, c.invoice_id)
    out = jsonable(c)
    out["amounts"] = {"claimed_cents": c.claimed_cents, "accepted_cents": c.accepted_cents, "settled_cents": c.settled_cents}
    out["contest_by"] = str(inv.contest_by) if inv.contest_by else None
    out["deadline_basis"] = inv.deadline_basis
    out["lines"] = (c.basis_snapshot or {}).get("lines", [])
    out["events"] = [
        jsonable(e, exclude=("tenant_id",))
        for e in ctx.conn.execute(
            select(claim_event).where(claim_event.c.claim_id == c.id).order_by(claim_event.c.created_at)
        ).all()
    ]
    banner = None
    if c.stale_basis or c.basis_changed_after_send:
        recomputed = ops.recompute(ctx.conn, c.invoice_id)
        old_total = sum(ln["claimed_cents"] for ln in out["lines"])
        new_lines = []
        for ln in out["lines"]:
            rc = recomputed.get(ln["key"])
            new_amount = (
                rc.variance_cents if rc is not None and rc.status == "variance" and (rc.variance_cents or 0) > 0 else None
            )
            new_lines.append({"key": ln["key"], "old_cents": ln["claimed_cents"], "new_cents": new_amount})
        new_total = sum(n["new_cents"] or 0 for n in new_lines)
        banner = {
            "kind": "basis_changed_after_send" if c.basis_changed_after_send else "stale_basis",
            "old_total_cents": old_total,
            "new_total_cents": new_total,
            "lines": new_lines,
        }
        if c.basis_changed_after_send:
            carrier = ctx.row(carrier_account, c.carrier_account_id)
            banner["withdrawal_note"] = withdrawal_note(
                c.reference, carrier.name, inv.invoice_number, old_total, new_total or None
            )
        else:
            banner["message"] = "basis changed since drafting; redraft and approve again before sending"
    out["banner"] = banner
    return out


class ClaimIn(BaseModel):
    invoice_id: uuid.UUID
    origin: Literal["lookback", "pilot", "recurring"]


@router.post("/claims")
def create_claim(body: ClaimIn, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(AUDITOR_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        inv = ctx.row(invoice, body.invoice_id, for_update=True)
        if not inv.fields_confirmed:
            raise ApiError(409, "FIELDS_UNCONFIRMED", "confirm the invoice fields before drafting a claim")
        active = ctx.conn.execute(
            select(claim.c.id).where(claim.c.invoice_id == inv.id, claim.c.status != "withdrawn")
        ).scalar_one_or_none()
        if active is not None:
            raise ApiError(409, "CLAIM_EXISTS", "this invoice already has a claim", claim_id=str(active))
        lines = _draft_lines(ctx, inv.id)
        if not lines:
            raise ApiError(422, "NO_CLAIM_LINES", "no finding is confirmed for claim")
        cid = ctx.conn.execute(
            claim.insert()
            .values(
                tenant_id=ctx.tenant_id,
                carrier_account_id=inv.carrier_account_id,
                invoice_id=inv.id,
                reference=f"FC-{secrets.token_hex(4).upper()}",
                origin=body.origin,
                basis_snapshot=_snapshot(lines),
            )
            .returning(claim.c.id)
        ).scalar_one()
        _replace_lines(ctx, cid, lines)
        _event(ctx, cid, "drafted", today())
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="claim.drafted",
            entity_type="claim",
            entity_id=cid,
        )
        return 201, claim_out(ctx, cid)

    return idempotent(request, ctx, body.model_dump(mode="json"), go)


@router.get("/claims/{claim_id}")
def get_claim(claim_id: str, ctx: Ctx = Depends(tenant_ctx)) -> dict[str, Any]:
    ctx.require(VIEWER_PLUS)
    return claim_out(ctx, ctx.row(claim, claim_id).id)


@router.post("/claims/{claim_id}/redraft")
def redraft_claim(claim_id: str, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    """Rebuild an unsent claim's lines from the latest results and clear the stale flag."""
    ctx.require(AUDITOR_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        c = ctx.row(claim, claim_id, for_update=True)
        if c.status not in UNSENT:
            raise ApiError(409, "ALREADY_SENT", "a sent claim is withdrawn, not redrafted")
        ops.run_checks_for_invoice(ctx.conn, c.invoice_id)  # a new stored run on the current basis
        lines = _draft_lines(ctx, c.invoice_id)
        if not lines:
            raise ApiError(422, "NO_CLAIM_LINES", "no finding supports a claim on the current basis")
        ctx.conn.execute(
            claim.update()
            .where(claim.c.id == c.id)
            .values(
                basis_snapshot=_snapshot(lines),
                stale_basis=False,
                claimed_cents=None,
                approved_by=None,
                approved_at=None,
                late_override_reason=None,
                version=claim.c.version + 1,
                updated_at=func.now(),
            )
        )
        _replace_lines(ctx, c.id, lines)
        _event(ctx, c.id, "drafted", today())
        ops.refresh_claim_state(ctx.conn, c.id)
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="claim.redrafted",
            entity_type="claim",
            entity_id=c.id,
        )
        return 200, claim_out(ctx, c.id)

    return idempotent(request, ctx, {"claim_id": claim_id}, go)


class ApproveIn(BaseModel):
    override_reason: str | None = None
    expected_version: int | None = None


@router.post("/claims/{claim_id}/approve")
def approve_claim(claim_id: str, body: ApproveIn, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(APPROVER_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        c = ctx.row(claim, claim_id, for_update=True)  # serialises concurrent approvals (IT-16)
        if c.status != "draft":
            raise ApiError(409, "NOT_DRAFT", f"claim is {c.status}", claim=claim_out(ctx, c.id))
        if body.expected_version is not None and body.expected_version != c.version:
            raise ApiError(409, "VERSION_CONFLICT", "the claim changed; reload", claim=claim_out(ctx, c.id))
        inv = ctx.row(invoice, c.invoice_id)
        if not inv.fields_confirmed:
            raise ApiError(409, "FIELDS_UNCONFIRMED", "invoice fields are not confirmed")
        snap_lines = (c.basis_snapshot or {}).get("lines", [])
        lines = [LineBasis(ln["key"], ln["claimed_cents"], ln["basis"]) for ln in snap_lines]
        recomputed = ops.recompute(ctx.conn, c.invoice_id)
        decision = evaluate_approval(
            lines, recomputed, c.stale_basis, inv.contest_by, inv.deadline_basis, today(), body.override_reason
        )
        if not decision.ok:
            raise ApiError(
                409, decision.code or "REFUSED", decision.message, old_lines=decision.old_lines, new_lines=decision.new_lines
            )
        late = (inv.contest_by is None and inv.deadline_basis != "none_broker") or (
            inv.contest_by is not None and today() > inv.contest_by
        )
        ctx.conn.execute(
            claim.update()
            .where(claim.c.id == c.id)
            .values(
                claimed_cents=decision.claimed_cents,
                basis_snapshot=_snapshot(snap_lines),
                approved_by=ctx.user_id,
                approved_at=func.now(),
                late_override_reason=body.override_reason.strip() if late and body.override_reason else None,
                version=claim.c.version + 1,
                updated_at=func.now(),
            )
        )
        _event(ctx, c.id, "approved", today())
        ops.refresh_claim_state(ctx.conn, c.id)
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="claim.approved_late_override" if late else "claim.approved",
            entity_type="claim",
            entity_id=c.id,
            after={"claimed_cents": decision.claimed_cents, "override": bool(late)},
        )
        return 200, claim_out(ctx, c.id)

    return idempotent(request, ctx, {"claim_id": claim_id, **body.model_dump()}, go)


class SentIn(BaseModel):
    sent_on: date
    sent_to: str = Field(min_length=3)


@router.post("/claims/{claim_id}/sent")
def mark_sent(claim_id: str, body: SentIn, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    """Records that the user sent the dispute from their own mailbox. FreightCheck sends nothing."""
    ctx.require(APPROVER_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        c = ctx.row(claim, claim_id, for_update=True)
        if c.stale_basis:
            raise ApiError(
                409, "STALE_BASIS", "the basis changed after approval; redraft and approve again", claim=claim_out(ctx, c.id)
            )
        if c.status != "approved":
            raise ApiError(409, "NOT_APPROVED", f"claim is {c.status}")
        ctx.conn.execute(
            claim.update()
            .where(claim.c.id == c.id)
            .values(sent_at=body.sent_on, sent_to=body.sent_to, version=claim.c.version + 1, updated_at=func.now())
        )
        _event(ctx, c.id, "sent", body.sent_on)
        ops.refresh_claim_state(ctx.conn, c.id)
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="claim.sent_recorded",
            entity_type="claim",
            entity_id=c.id,
        )
        return 200, claim_out(ctx, c.id)

    return idempotent(request, ctx, {"claim_id": claim_id, **body.model_dump(mode="json")}, go)


class EventIn(BaseModel):
    event_type: Literal[
        "acknowledged", "decision_accepted", "decision_partial", "decision_denied", "short_paid", "carrier_rebilled", "withdrawn"
    ]
    occurred_on: date
    client_event_id: str = Field(min_length=1)
    amount_cents: int | None = None
    evidence_file_id: uuid.UUID | None = None
    reason_code: Literal["wrong_rate_basis", "charge_supported_by_carrier", "time_barred", "duplicate_claim", "other"] | None = (
        None
    )
    reason_note: str | None = None


@router.post("/claims/{claim_id}/events")
def add_event(claim_id: str, body: EventIn, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(APPROVER_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        c = ctx.row(claim, claim_id, for_update=True)
        try:
            validate_event(
                ClaimEvent(
                    body.event_type,
                    body.occurred_on,
                    body.client_event_id,
                    0,
                    body.amount_cents,
                    str(body.evidence_file_id) if body.evidence_file_id else None,
                    body.reason_code,
                )
            )
        except ValueError as exc:
            raise ApiError(422, "BAD_EVENT", str(exc)) from exc
        if c.status in CLOSED:
            raise ApiError(409, "CLAIM_CLOSED", f"claim is {c.status}")
        if body.event_type != "withdrawn" and c.status in UNSENT:
            raise ApiError(409, "NOT_SENT", "carrier events need a sent claim")
        if body.evidence_file_id:
            ctx.row(source_file, body.evidence_file_id)
        if body.event_type == "decision_partial" and c.claimed_cents is not None and (body.amount_cents or 0) > c.claimed_cents:
            raise ApiError(422, "ABOVE_CLAIMED", "accepted cannot exceed claimed", field="amount_cents")
        _event(
            ctx,
            c.id,
            body.event_type,
            body.occurred_on,
            client_event_id=body.client_event_id,
            amount_cents=body.amount_cents,
            evidence_file_id=body.evidence_file_id,
            reason_code=body.reason_code,
            reason_note=body.reason_note,
        )
        if body.event_type == "withdrawn":
            ctx.conn.execute(
                claim.update()
                .where(claim.c.id == c.id)
                .values(basis_changed_after_send=False, stale_basis=False, version=claim.c.version + 1, updated_at=func.now())
            )
        ops.refresh_claim_state(ctx.conn, c.id)
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action=f"claim.event.{body.event_type}",
            entity_type="claim",
            entity_id=c.id,
        )
        return 201, claim_out(ctx, c.id)

    return idempotent(request, ctx, {"claim_id": claim_id, **body.model_dump(mode="json")}, go)


class SettlementIn(BaseModel):
    method: Literal["credit_memo", "refund_payment", "corrected_invoice", "short_pay_accepted"]
    amount_cents: int = Field(gt=0)
    settled_on: date
    evidence_file_id: uuid.UUID  # required: no settlement without the carrier's document
    carrier_reference: str | None = None


@router.post("/claims/{claim_id}/settlements")
def add_settlement(claim_id: str, body: SettlementIn, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(APPROVER_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        c = ctx.row(claim, claim_id, for_update=True)
        if c.status in UNSENT or c.status in CLOSED:
            raise ApiError(409, "NOT_SETTLEABLE", f"claim is {c.status}")
        ctx.row(source_file, body.evidence_file_id)
        if body.method == "short_pay_accepted" and not c.accepted_cents:
            raise ApiError(409, "NO_ACCEPTANCE", "a short-pay counts only after the carrier accepted the claim")
        sid = ctx.conn.execute(
            settlement.insert().values(tenant_id=ctx.tenant_id, claim_id=c.id, **body.model_dump()).returning(settlement.c.id)
        ).scalar_one()
        ops.refresh_claim_state(ctx.conn, c.id)
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="settlement.recorded",
            entity_type="settlement",
            entity_id=sid,
        )
        return 201, {**claim_out(ctx, c.id), "settlement_id": str(sid)}

    return idempotent(request, ctx, {"claim_id": claim_id, **body.model_dump(mode="json")}, go)


class ReverseIn(BaseModel):
    reason: str = Field(min_length=1)


@router.post("/settlements/{settlement_id}/reverse")
def reverse_settlement(settlement_id: str, body: ReverseIn, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(APPROVER_PLUS)

    def go() -> tuple[int, dict[str, Any]]:
        s = ctx.row(settlement, settlement_id, for_update=True)
        if s.reversed_at is not None:
            raise ApiError(409, "ALREADY_REVERSED", "settlement already reversed")
        ctx.conn.execute(
            settlement.update()
            .where(settlement.c.id == s.id)
            .values(
                reversed_at=func.now(),
                reversed_by=ctx.user_id,
                reverse_reason=body.reason,
                version=settlement.c.version + 1,
                updated_at=func.now(),
            )
        )
        ops.refresh_claim_state(ctx.conn, s.claim_id)
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="settlement.reversed",
            entity_type="settlement",
            entity_id=s.id,
        )
        return 200, claim_out(ctx, s.claim_id)

    return idempotent(request, ctx, {"settlement_id": settlement_id, **body.model_dump()}, go)


# ------------------------------------------------------------------ results


@router.get("/fee-statements")
def list_fee_statements(ctx: Ctx = Depends(tenant_ctx)) -> list[dict[str, Any]]:
    ctx.require(VIEWER_PLUS)
    out = []
    for st in ctx.conn.execute(select(fee_statement).order_by(fee_statement.c.period_start)).all():
        d = jsonable(st)
        d["lines"] = [
            jsonable(ln)
            for ln in ctx.conn.execute(select(fee_statement_line).where(fee_statement_line.c.fee_statement_id == st.id)).all()
        ]
        out.append(d)
    return out


@router.get("/reports/basis-metrics")
def basis_metrics(ctx: Ctx = Depends(tenant_ctx)) -> dict[str, int]:
    """Wrong-basis disputes sent (PRD guardrail) and approvals by date override (IT-19)."""
    ctx.require(VIEWER_PLUS)
    wrong_sent = ctx.conn.execute(
        select(func.count()).select_from(claim).where(claim.c.basis_changed_after_send_at.is_not(None))
    ).scalar_one()
    overrides = ctx.conn.execute(
        select(func.count()).select_from(claim).where(claim.c.late_override_reason.is_not(None))
    ).scalar_one()
    return {"wrong_basis_sent": wrong_sent, "approvals_by_date_override": overrides}
