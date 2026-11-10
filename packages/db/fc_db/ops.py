"""Business operations shared by the API and the worker. Callers own the transaction and
have already set the tenant context; nothing here bypasses row-level security."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from typing import Any

from sqlalchemy import Connection, Row, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fc_core.checks import ENGINE_VERSION, roll_up, run_checks
from fc_core.deadline import SweepClaim, deadline_sweep
from fc_core.ledger import ClaimEvent, LineBasis, Recomputed, SettlementRow, compare_basis, derive, fee_lines
from fc_db.repo import get_row, load_context, load_invoice
from fc_db.tables import (
    audit_event,
    check_result,
    claim,
    claim_event,
    fee_statement,
    fee_statement_line,
    finding,
    invoice,
    job,
    notification,
    settlement,
    tenant,
)
from fc_platform.logging import correlation_id

# ------------------------------------------------------------------ audit


def _hash(obj: Any) -> str | None:
    if obj is None:
        return None
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def audit(
    conn: Connection,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    actor_role: str | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    before: Any = None,
    after: Any = None,
) -> None:
    """Audit row in the same transaction as the change (T-2.2.4)."""
    conn.execute(
        audit_event.insert().values(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_hash=_hash(before),
            after_hash=_hash(after),
            correlation_id=correlation_id.get(),
        )
    )


# ------------------------------------------------------------------ jobs


def enqueue_job(conn: Connection, tenant_id: uuid.UUID, kind: str, key: str, payload: dict[str, Any]) -> uuid.UUID:
    """Insert a job once per (tenant, kind, idempotency key); payload holds IDs only."""
    existing = conn.execute(select(job.c.id).where(job.c.kind == kind, job.c.idempotency_key == key)).scalar_one_or_none()
    if existing is not None:
        return uuid.UUID(str(existing))
    new_id = conn.execute(
        job.insert()
        .values(tenant_id=tenant_id, kind=kind, idempotency_key=key, payload=payload, correlation_id=correlation_id.get())
        .returning(job.c.id)
    ).scalar_one()
    return uuid.UUID(str(new_id))


def enqueue_run_checks(conn: Connection, inv: Row[Any]) -> uuid.UUID:
    key = f"{inv.id}:{inv.field_revision}:{inv.ruleset_revision}"
    return enqueue_job(conn, inv.tenant_id, "run_checks", key, {"invoice_id": str(inv.id)})


# ------------------------------------------------------------------ checks


def finding_key(check_code: str, line_no: int | None) -> str:
    return f"{check_code}:{line_no if line_no is not None else '-'}"


def run_checks_for_invoice(conn: Connection, invoice_id: uuid.UUID) -> int:
    """One check run: all results, findings upsert, invoice status, in the caller's transaction."""
    core_inv, inv, _carrier = load_invoice(conn, invoice_id)
    ctx = load_context(conn, inv)
    results = run_checks(core_inv, ctx)
    run_no = (
        conn.execute(
            select(func.coalesce(func.max(check_result.c.run_no), 0)).where(check_result.c.invoice_id == inv.id)
        ).scalar_one()
        + 1
    )
    for r in results:
        rid = conn.execute(
            check_result.insert()
            .values(
                tenant_id=inv.tenant_id,
                invoice_id=inv.id,
                run_no=run_no,
                check_code=r.check_code,
                line_no=r.line_no,
                status=r.status,
                exception_code=r.exception_code,
                expected_cents=r.expected_cents,
                billed_cents=r.billed_cents,
                variance_cents=r.variance_cents,
                rate_rule_id=uuid.UUID(r.rate_rule_id) if r.rate_rule_id else None,
                rate_document_revision=r.rate_document_revision,
                fuel_index_price_id=uuid.UUID(r.fuel_index_price_id) if r.fuel_index_price_id else None,
                governing_date=r.governing_date,
                arithmetic={**r.arithmetic, "basis": r.basis.to_json(), "review_flags": list(r.review_flags)},
                engine_version=ENGINE_VERSION,
            )
            .returning(check_result.c.id)
        ).scalar_one()
        existing = conn.execute(
            select(finding.c.id).where(
                finding.c.invoice_id == inv.id,
                finding.c.check_code == r.check_code,
                finding.c.line_no.is_(None) if r.line_no is None else finding.c.line_no == r.line_no,
            )
        ).scalar_one_or_none()
        if existing is not None:
            conn.execute(
                finding.update()
                .where(finding.c.id == existing)
                .values(current_result_id=rid, version=finding.c.version + 1, updated_at=func.now())
            )
        elif r.status in ("variance", "exception"):
            conn.execute(
                finding.insert().values(
                    tenant_id=inv.tenant_id, invoice_id=inv.id, check_code=r.check_code, line_no=r.line_no, current_result_id=rid
                )
            )
    invoice_t = invoice
    conn.execute(
        invoice_t.update()
        .where(invoice_t.c.id == inv.id)
        .values(status=roll_up(core_inv, results), version=invoice_t.c.version + 1, updated_at=func.now())
    )
    return int(run_no)


def recompute(conn: Connection, invoice_id: uuid.UUID) -> dict[str, Recomputed]:
    """Fresh run against the currently confirmed basis, not stored (approval and banners)."""
    core_inv, inv, _ = load_invoice(conn, invoice_id)
    results = run_checks(core_inv, load_context(conn, inv))
    return {
        finding_key(r.check_code, r.line_no): Recomputed(
            finding_key(r.check_code, r.line_no), r.status, r.variance_cents, r.basis.to_json()
        )
        for r in results
    }


# ------------------------------------------------------------------ claims


def claim_events(conn: Connection, claim_id: uuid.UUID) -> list[ClaimEvent]:
    rows = conn.execute(
        select(claim_event).where(claim_event.c.claim_id == claim_id).order_by(claim_event.c.created_at, claim_event.c.id)
    ).all()
    return [
        ClaimEvent(
            r.event_type,
            r.occurred_on,
            r.client_event_id,
            i,
            r.amount_cents,
            str(r.evidence_file_id) if r.evidence_file_id else None,
            r.reason_code,
        )
        for i, r in enumerate(rows)
    ]


def refresh_claim_state(conn: Connection, claim_id: uuid.UUID) -> Row[Any]:
    """Re-derive status, accepted and settled from events and settlements; three fields kept apart."""
    c = get_row(conn, claim, claim_id, for_update=True)
    settled = conn.execute(
        select(func.coalesce(func.sum(settlement.c.amount_cents), 0)).where(
            settlement.c.claim_id == claim_id, settlement.c.reversed_at.is_(None)
        )
    ).scalar_one()
    d = derive(claim_events(conn, claim_id), c.claimed_cents, int(settled))
    conn.execute(
        claim.update()
        .where(claim.c.id == claim_id)
        .values(
            status=d.status,
            accepted_cents=d.accepted_cents,
            settled_cents=int(settled),
            version=claim.c.version + 1,
            updated_at=func.now(),
        )
    )
    return get_row(conn, claim, claim_id)


def mark_dependent_claims(
    conn: Connection, *, prior_document_id: uuid.UUID | None = None, prior_fuel_index_price_id: uuid.UUID | None = None
) -> dict[str, list[uuid.UUID]]:
    """A basis was superseded: unsent claims become stale, sent ones are flagged (TRD 6.2)."""
    if prior_document_id is not None:
        cond = text("basis_snapshot->'document_ids' ? :ref").bindparams(ref=str(prior_document_id))
    elif prior_fuel_index_price_id is not None:
        cond = text("basis_snapshot->'fuel_index_price_ids' ? :ref").bindparams(ref=str(prior_fuel_index_price_id))
    else:
        raise ValueError("a prior basis is required")
    stale = (
        conn.execute(
            claim.update()
            .where(cond, claim.c.status.in_(("draft", "approved")))
            .values(stale_basis=True, version=claim.c.version + 1, updated_at=func.now())
            .returning(claim.c.id)
        )
        .scalars()
        .all()
    )
    flagged = (
        conn.execute(
            claim.update()
            .where(cond, claim.c.status.notin_(("draft", "approved", "withdrawn", "expired")))
            .values(
                basis_changed_after_send=True,
                basis_changed_after_send_at=func.coalesce(claim.c.basis_changed_after_send_at, func.now()),
                version=claim.c.version + 1,
                updated_at=func.now(),
            )
            .returning(claim.c.id)
        )
        .scalars()
        .all()
    )
    return {"stale": list(stale), "changed_after_send": list(flagged)}


# ------------------------------------------------------------------ fees

GAINSHARE_PLANS = ("pilot_gainshare", "gainshare")


def issue_fee_statement(conn: Connection, period_start: date, period_end: date) -> uuid.UUID | None:
    """Gainshare statement: each unbilled settlement at 20%; reversals of billed ones negative."""
    t = conn.execute(select(tenant)).one()
    if t.plan not in GAINSHARE_PLANS:
        return None
    rows = conn.execute(select(settlement).where(settlement.c.settled_on <= period_end)).all()
    billed = conn.execute(select(fee_statement_line.c.settlement_id, fee_statement_line.c.fee_cents)).all()
    pos = {b.settlement_id for b in billed if b.fee_cents > 0}
    neg = {b.settlement_id for b in billed if b.fee_cents < 0}
    lines = fee_lines(
        [SettlementRow(str(s.id), s.amount_cents, s.reversed_at is not None, s.id in pos, s.id in neg) for s in rows]
    )
    sid = conn.execute(
        fee_statement.insert()
        .values(
            tenant_id=t.id,
            period_start=period_start,
            period_end=period_end,
            plan=t.plan,
            total_cents=sum(ln.fee_cents for ln in lines),
        )
        .returning(fee_statement.c.id)
    ).scalar_one()
    for ln in lines:
        conn.execute(
            fee_statement_line.insert().values(
                tenant_id=t.id,
                fee_statement_id=sid,
                settlement_id=uuid.UUID(ln.settlement_id),
                basis_cents=ln.basis_cents,
                fee_cents=ln.fee_cents,
            )
        )
    audit(
        conn,
        tenant_id=t.id,
        actor_user_id=None,
        actor_role="worker",
        action="fee_statement.issued",
        entity_type="fee_statement",
        entity_id=sid,
    )
    return uuid.UUID(str(sid))


# ------------------------------------------------------------------ re-evaluation (B1-001)

UNSENT_STATUSES = ("draft", "approved")
CLOSED_STATUSES = ("withdrawn", "expired")


def basis_changed(conn: Connection, c: Row[Any]) -> list[str]:
    """Finding keys of a claim whose recomputed basis or amount differ from its snapshot."""
    lines = [LineBasis(ln["key"], ln["claimed_cents"], ln["basis"]) for ln in (c.basis_snapshot or {}).get("lines", [])]
    if not lines:
        return []
    return compare_basis(lines, recompute(conn, c.invoice_id))


def reevaluate_claims(conn: Connection, carrier_account_id: uuid.UUID | None) -> dict[str, list[uuid.UUID]]:
    """After any confirmation (new document, revision, index value or its correction), recompute
    every open claim of the carrier (all carriers for a tenant-wide index value). A changed
    unsent claim becomes stale; a changed sent claim is flagged basis_changed_after_send."""
    stmt = select(claim).where(claim.c.status.notin_(CLOSED_STATUSES))
    if carrier_account_id is not None:
        stmt = stmt.where(claim.c.carrier_account_id == carrier_account_id)
    out: dict[str, list[uuid.UUID]] = {"stale": [], "changed_after_send": []}
    for c in conn.execute(stmt.with_for_update()).all():
        if not basis_changed(conn, c):
            continue
        if c.status in UNSENT_STATUSES:
            if not c.stale_basis:
                conn.execute(
                    claim.update()
                    .where(claim.c.id == c.id)
                    .values(stale_basis=True, version=claim.c.version + 1, updated_at=func.now())
                )
            out["stale"].append(c.id)
        else:
            conn.execute(
                claim.update()
                .where(claim.c.id == c.id)
                .values(
                    basis_changed_after_send=True,
                    basis_changed_after_send_at=func.coalesce(claim.c.basis_changed_after_send_at, func.now()),
                    version=claim.c.version + 1,
                    updated_at=func.now(),
                )
            )
            out["changed_after_send"].append(c.id)
    return out


def merge_marked(*parts: dict[str, list[uuid.UUID]]) -> dict[str, list[uuid.UUID]]:
    out: dict[str, list[uuid.UUID]] = {"stale": [], "changed_after_send": []}
    for p in parts:
        for k, ids in p.items():
            out[k] += [i for i in ids if i not in out[k]]
    return out


# ------------------------------------------------------------------ deadline sweep (B1-002)


def run_deadline_sweep(conn: Connection, run_date: date) -> dict[str, int]:
    """Reminders at 30, 14 and 3 days (recorded once in `notification`; sending is a provider
    interface not built in B1) and expiry of unsent claims past contest-by."""
    rows = conn.execute(
        select(claim.c.id, claim.c.status, claim.c.late_override_reason, invoice.c.contest_by)
        .join(invoice, invoice.c.id == claim.c.invoice_id)
        .where(claim.c.status.in_(UNSENT_STATUSES))
    ).all()
    sent = {(n.kind, str(n.entity_id)) for n in conn.execute(select(notification.c.kind, notification.c.entity_id)).all()}
    actions = deadline_sweep(
        [SweepClaim(str(r.id), r.status, r.contest_by, r.late_override_reason is not None) for r in rows], run_date, sent
    )
    t = conn.execute(select(tenant.c.id)).scalar_one()
    counts = {"reminders": 0, "expired": 0}
    for a in actions:
        cid = uuid.UUID(a.claim_id)
        if a.action == "remind":
            conn.execute(
                pg_insert(notification)
                .values(tenant_id=t, kind=a.kind, entity_id=cid)
                .on_conflict_do_nothing(index_elements=["tenant_id", "kind", "entity_id"])
            )
            counts["reminders"] += 1
        else:
            conn.execute(
                pg_insert(claim_event)
                .values(
                    tenant_id=t, claim_id=cid, event_type="expired", occurred_on=run_date, client_event_id=f"sweep-{run_date}"
                )
                .on_conflict_do_nothing(index_elements=["claim_id", "client_event_id"])
            )
            refresh_claim_state(conn, cid)
            audit(
                conn,
                tenant_id=t,
                actor_user_id=None,
                actor_role="worker",
                action="claim.expired",
                entity_type="claim",
                entity_id=cid,
            )
            counts["expired"] += 1
    return counts
