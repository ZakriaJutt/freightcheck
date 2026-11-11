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
    # True when a document may govern but cannot be used (unconfirmed, lane unknown, ambiguous,
    # basis date missing): the caller must fail closed and never fall back to another document.
    final: bool = False


def in_effect(doc: RateDocument, on: date) -> bool:
    if on < doc.effective_from:
        return False
    return doc.effective_to is None or on <= doc.effective_to


def may_govern(doc: RateDocument, invoice: Invoice) -> bool:
    """In effect on its own governing date, or that date is unknown (cannot rule it out)."""
    gd = invoice.date_for(doc.date_basis)
    return gd is None or in_effect(doc, gd)


def _pending_revision(doc: RateDocument, documents: list[RateDocument]) -> bool:
    """An entered revision of a document that is still confirmed: the prior governs until confirmation."""
    if doc.revises_id is None:
        return False
    return any(d.id == doc.revises_id and d.status == "confirmed" for d in documents)


def scope_for(invoice: Invoice) -> str:
    return invoice.lane_key or "*"


def resolve(
    documents: tuple[RateDocument, ...] | list[RateDocument],
    doc_type: DocType,
    invoice: Invoice,
    scope_key: str = "*",
) -> Resolved | Unresolved:
    """Resolve one document type for one invoice. Fails closed (B1-004):

    - a specific scope (lane group or PRO) is tried before the wildcard; a specific-scope
      document whose basis date is missing never falls through to the wildcard;
    - an entered document that may govern (and is not a pending revision of a confirmed one)
      blocks resolution instead of being skipped;
    - when the invoice's lane is unknown and a lane-scoped document may govern, nothing is chosen.
    """
    typed = [d for d in documents if d.doc_type == doc_type]
    if scope_key == "*" and doc_type != "rate_confirmation":
        lane_docs = [d for d in typed if d.scope_key != "*" and d.status != "superseded" and may_govern(d, invoice)]
        if lane_docs:
            ids = ", ".join(sorted(d.id for d in lane_docs))
            return Unresolved("GOVERNING_RATE_MISSING", f"lane-scoped {doc_type} {ids} may apply; invoice lane unknown", True)
    scopes = [scope_key, "*"] if scope_key != "*" else ["*"]
    for scope in scopes:
        tier = [d for d in typed if d.scope_key == scope]
        blocking = [d for d in tier if d.status == "entered" and not _pending_revision(d, typed) and may_govern(d, invoice)]
        if blocking:
            ids = ", ".join(sorted(d.id for d in blocking))
            return Unresolved("GOVERNING_RATE_MISSING", f"unconfirmed {doc_type} {ids} may govern", True)
        matches: list[Resolved] = []
        date_missing = False
        for doc in (d for d in tier if d.status == "confirmed"):
            gd = invoice.date_for(doc.date_basis)
            if gd is None:
                date_missing = True
            elif in_effect(doc, gd):
                matches.append(Resolved(doc, gd))
        if len(matches) > 1 or (matches and date_missing):
            ids = ", ".join(sorted(m.document.id for m in matches))
            return Unresolved("GOVERNING_RATE_MISSING", f"ambiguous {doc_type}: {ids}", True)
        if len(matches) == 1:
            return matches[0]
        if date_missing:
            return Unresolved("GOVERNING_DATE_MISSING", f"invoice lacks the date the {doc_type} basis needs", True)
        # B1-015: an entered revision covering a date its confirmed prior does not is not merely
        # pending there: it may govern, so it blocks (never fall through to another tier or type).
        uncovered = [d for d in tier if d.status == "entered" and _pending_revision(d, typed) and may_govern(d, invoice)]
        if uncovered:
            ids = ", ".join(sorted(d.id for d in uncovered))
            return Unresolved("GOVERNING_RATE_MISSING", f"unconfirmed revision {ids} may govern this date", True)
    return Unresolved("GOVERNING_RATE_MISSING", f"no confirmed {doc_type} in effect")


LINEHAUL_DOC_ORDER: tuple[DocType, ...] = ("rate_confirmation", "contract_rate_sheet", "tariff")


def resolve_linehaul(documents: tuple[RateDocument, ...] | list[RateDocument], invoice: Invoice) -> Resolved | Unresolved:
    """Rate confirmation for this PRO first, then contract rate sheet, then tariff.

    A later type is tried only when the earlier type has no document that may govern; any
    final failure (unconfirmed, lane unknown, ambiguous, date missing) stops the search.
    A rate confirmation for this PRO that cannot be used is always final.
    """
    for doc_type in LINEHAUL_DOC_ORDER:
        if doc_type == "rate_confirmation":
            if not invoice.pro_number:
                continue
            own = [
                d for d in documents if d.doc_type == doc_type and d.scope_key == invoice.pro_number and d.status != "superseded"
            ]
            if not own:
                continue
            result = resolve(own, doc_type, invoice, invoice.pro_number)
            if isinstance(result, Unresolved):
                return Unresolved(result.exception_code, f"rate confirmation for this PRO: {result.detail}", True)
            return result
        result = resolve(documents, doc_type, invoice, scope_for(invoice))
        if isinstance(result, Resolved) or result.final:
            return result
    return Unresolved("GOVERNING_RATE_MISSING", "no confirmed linehaul document in effect")
