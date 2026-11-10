"""Load rows (under the caller's tenant context) into pure core types."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Connection, Row, and_, or_, select

from fc_core.model import (
    DuplicateCandidate,
    FuelIndexValue,
    Invoice,
    InvoiceLine,
    RateDocument,
    RateRule,
    RunContext,
)
from fc_db.tables import (
    carrier_account,
    fuel_index_price,
    invoice,
    invoice_line,
    rate_document,
    rate_rule,
    tenant,
)


class NotFound(LookupError):
    def __init__(self, entity: str, entity_id: Any) -> None:
        super().__init__(f"{entity} {entity_id} not found")
        self.entity = entity
        self.entity_id = entity_id


def get_row(conn: Connection, table: Any, row_id: Any, *, for_update: bool = False) -> Row[Any]:
    """Fetch one row by id. Under RLS a foreign tenant's id simply yields nothing."""
    try:
        rid = uuid.UUID(str(row_id))
    except ValueError as exc:
        raise NotFound(table.name, row_id) from exc
    stmt = select(table).where(table.c.id == rid)
    if for_update:
        stmt = stmt.with_for_update()
    row = conn.execute(stmt).first()
    if row is None:
        raise NotFound(table.name, row_id)
    return row


def carrier_key(name: str) -> str:
    return name.strip().lower()


def load_invoice(conn: Connection, invoice_id: uuid.UUID) -> tuple[Invoice, Row[Any], Row[Any]]:
    inv = get_row(conn, invoice, invoice_id)
    carrier = get_row(conn, carrier_account, inv.carrier_account_id)
    lines = conn.execute(select(invoice_line).where(invoice_line.c.invoice_id == inv.id).order_by(invoice_line.c.line_no)).all()
    core_inv = Invoice(
        id=str(inv.id),
        carrier_key=carrier_key(carrier.name),
        invoice_number=inv.invoice_number,
        pro_number=inv.pro_number,
        invoice_date=inv.invoice_date,
        pickup_date=inv.pickup_date,
        tender_date=inv.tender_date,
        delivery_date=inv.delivery_date,
        billed_weight_lb=inv.billed_weight_lb,
        billed_class=inv.billed_class,
        total_cents=inv.total_cents,
        fields_confirmed=inv.fields_confirmed,
        lines=tuple(InvoiceLine(ln.line_no, ln.charge_type, ln.amount_cents, ln.accessorial_code) for ln in lines),
        # B1: bill-of-lading linking (invoice_document) is not built, so the support test
        # reports DOCUMENT_MISSING rather than guessing.
        bol_accessorials=None,
        original_bill_receipt_date=None,
    )
    return core_inv, inv, carrier


def load_documents(conn: Connection, carrier_account_id: uuid.UUID) -> tuple[RateDocument, ...]:
    docs = conn.execute(select(rate_document).where(rate_document.c.carrier_account_id == carrier_account_id)).all()
    if not docs:
        return ()
    rules = conn.execute(
        select(rate_rule)
        .where(rate_rule.c.rate_document_id.in_([d.id for d in docs]))
        .order_by(rate_rule.c.created_at, rate_rule.c.id)
    ).all()
    by_doc: dict[uuid.UUID, list[RateRule]] = {}
    for r in rules:
        by_doc.setdefault(r.rate_document_id, []).append(RateRule(str(r.id), r.rule_type, r.params, r.source_page))
    return tuple(
        RateDocument(
            id=str(d.id),
            revision=d.revision,
            doc_type=d.doc_type,
            status=d.status,
            effective_from=d.effective_from,
            effective_to=d.effective_to,
            date_basis=d.date_basis,
            scope_key=d.scope_key,
            rules=tuple(by_doc.get(d.id, [])),
            date_basis_source_page=d.date_basis_source_page,
        )
        for d in docs
    )


def load_fuel_values(conn: Connection, carrier_account_id: uuid.UUID) -> tuple[FuelIndexValue, ...]:
    rows = conn.execute(
        select(fuel_index_price).where(
            or_(
                fuel_index_price.c.carrier_account_id == carrier_account_id,
                fuel_index_price.c.carrier_account_id.is_(None),
            )
        )
    ).all()
    return tuple(
        FuelIndexValue(str(r.id), r.index_name, r.published_on, r.week_start, r.price, r.status, r.revision) for r in rows
    )


def load_duplicate_candidates(conn: Connection, inv: Row[Any]) -> tuple[DuplicateCandidate, ...]:
    conds = [and_(invoice.c.carrier_account_id == inv.carrier_account_id, invoice.c.invoice_number == inv.invoice_number)]
    if inv.pro_number:
        conds.append(invoice.c.pro_number == inv.pro_number)
    rows = conn.execute(
        select(invoice, carrier_account.c.name.label("carrier_name"))
        .join(carrier_account, carrier_account.c.id == invoice.c.carrier_account_id)
        .where(or_(*conds), invoice.c.id != inv.id)
    ).all()
    # B1: the AP payment import (ap_payment) is not built; only invoice history is compared.
    return tuple(
        DuplicateCandidate(
            f"invoice:{r.id}", carrier_key(r.carrier_name), r.invoice_number, r.pro_number, r.invoice_date, r.total_cents
        )
        for r in rows
    )


def load_context(conn: Connection, inv: Row[Any]) -> RunContext:
    t = conn.execute(select(tenant.c.tolerance_cents)).scalar_one()
    return RunContext(
        documents=load_documents(conn, inv.carrier_account_id),
        fuel_values=load_fuel_values(conn, inv.carrier_account_id),
        duplicate_candidates=load_duplicate_candidates(conn, inv),
        tolerance_cents=t,
    )
