"""Governing-rate resolver (T-4.1.3, MH-03, MH-04).

A document governs an invoice when it is confirmed, its type and scope match, and the
governing date selected by the document's own date basis lies inside its effective dates
(both ends inclusive). Entered or superseded revisions are never chosen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fc_core.model import DocType, Invoice, RateDocument


@dataclass(frozen=True)
class Resolved:
    document: RateDocument
    governing_date: date


@dataclass(frozen=True)
class Unresolved:
    exception_code: str  # GOVERNING_RATE_MISSING or GOVERNING_DATE_MISSING
    detail: str


def in_effect(doc: RateDocument, on: date) -> bool:
    if on < doc.effective_from:
        return False
    return doc.effective_to is None or on <= doc.effective_to


def resolve(
    documents: tuple[RateDocument, ...] | list[RateDocument],
    doc_type: DocType,
    invoice: Invoice,
    scope_key: str = "*",
) -> Resolved | Unresolved:
    """Resolve one document type for one invoice.

    A specific scope (lane group or PRO) is preferred over the wildcard scope.
    """
    scopes = [scope_key, "*"] if scope_key != "*" else ["*"]
    date_missing = False
    for scope in scopes:
        candidates = [d for d in documents if d.doc_type == doc_type and d.status == "confirmed" and d.scope_key == scope]
        matches: list[Resolved] = []
        for doc in candidates:
            gd = invoice.date_for(doc.date_basis)
            if gd is None:
                date_missing = True
                continue
            if in_effect(doc, gd):
                matches.append(Resolved(doc, gd))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            # Overlap is refused by the database; with different date bases two
            # documents could still both claim a shipment. Fail closed.
            ids = ", ".join(sorted(m.document.id for m in matches))
            return Unresolved("GOVERNING_RATE_MISSING", f"ambiguous {doc_type}: {ids}")
    if date_missing:
        return Unresolved("GOVERNING_DATE_MISSING", f"invoice lacks the date the {doc_type} basis needs")
    return Unresolved("GOVERNING_RATE_MISSING", f"no confirmed {doc_type} in effect")


LINEHAUL_DOC_ORDER: tuple[DocType, ...] = ("rate_confirmation", "contract_rate_sheet", "tariff")


def resolve_linehaul(documents: tuple[RateDocument, ...] | list[RateDocument], invoice: Invoice) -> Resolved | Unresolved:
    """Rate confirmation for this PRO first, then contract rate sheet, then tariff."""
    failures: list[Unresolved] = []
    for doc_type in LINEHAUL_DOC_ORDER:
        if doc_type == "rate_confirmation":
            if not invoice.pro_number:
                continue
            # A rate confirmation applies only to its own PRO, never the wildcard.
            own = [d for d in documents if d.scope_key == invoice.pro_number]
            if not own:
                continue
            result = resolve(own, doc_type, invoice, invoice.pro_number)
        else:
            result = resolve(documents, doc_type, invoice)
        if isinstance(result, Resolved):
            return result
        failures.append(result)
    for failure in failures:
        if failure.exception_code == "GOVERNING_DATE_MISSING":
            return failure
    return Unresolved("GOVERNING_RATE_MISSING", "no confirmed linehaul document in effect")
