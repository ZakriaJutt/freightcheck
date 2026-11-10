"""Worker loop over the Postgres job table (AD-05, T-3.1.3 subset).

The worker claims a job through `fc_claim_next_job`, which returns only the job id and its
tenant; every further query runs under that tenant's context with row-level security.
"""

from __future__ import annotations

import argparse
import logging
import time
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

from sqlalchemy import Connection, Engine, func, select, text

from fc_db import ops
from fc_db.repo import NotFound
from fc_db.tables import job
from fc_platform.db import engine_for
from fc_platform.logging import configure_logging, correlation_id, log, tenant_id_var
from fc_platform.settings import get_settings
from fc_platform.tenant import set_tenant

logger = logging.getLogger("fc_worker")
MAX_ATTEMPTS = 3


def _run_checks(conn: Connection, payload: dict[str, Any]) -> dict[str, Any]:
    run_no = ops.run_checks_for_invoice(conn, uuid.UUID(payload["invoice_id"]))
    return {"run_no": run_no}


def _fee_statement(conn: Connection, payload: dict[str, Any]) -> dict[str, Any]:
    sid = ops.issue_fee_statement(conn, date.fromisoformat(payload["period_start"]), date.fromisoformat(payload["period_end"]))
    return {"fee_statement_id": str(sid) if sid else None}


HANDLERS: dict[str, Callable[[Connection, dict[str, Any]], dict[str, Any]]] = {
    "run_checks": _run_checks,
    "build_fee_statement": _fee_statement,
}


def process_one(engine: Engine) -> uuid.UUID | None:
    """Claim and run one job. Returns its id, or None when the queue is empty."""
    with engine.begin() as conn:
        claimed = conn.execute(
            text("select job_id, job_tenant_id from fc_claim_next_job(:kinds)"), {"kinds": list(HANDLERS)}
        ).first()
    if claimed is None:
        return None
    job_id, tenant_id = claimed
    with engine.begin() as conn:
        set_tenant(conn, tenant_id)
        row = conn.execute(select(job).where(job.c.id == job_id)).one()
        token = correlation_id.set(row.correlation_id or uuid.uuid4().hex)
    try:
        log(logger, "job.start", job_id=str(job_id), kind=row.kind, attempt=row.attempt)
        try:
            with engine.begin() as conn:
                set_tenant(conn, tenant_id)
                result = HANDLERS[row.kind](conn, row.payload)
                conn.execute(
                    job.update()
                    .where(job.c.id == job_id, job.c.version == row.version)
                    .values(state="done", version=job.c.version + 1, updated_at=func.now(), last_error=None)
                )
            log(
                logger,
                "job.done",
                job_id=str(job_id),
                kind=row.kind,
                **{k: v for k, v in result.items() if k.endswith("_id") or k == "run_no"},
            )
        except Exception as exc:  # noqa: BLE001 - recorded on the job row, never swallowed silently
            permanent = isinstance(exc, NotFound)
            state = "failed" if permanent or row.attempt >= MAX_ATTEMPTS else "queued"
            with engine.begin() as conn:
                set_tenant(conn, tenant_id)
                conn.execute(
                    job.update()
                    .where(job.c.id == job_id)
                    .values(
                        state=state,
                        last_error=type(exc).__name__ + (": not found" if permanent else ""),
                        run_after=func.now() + text("interval '30 seconds'"),
                        version=job.c.version + 1,
                        updated_at=func.now(),
                    )
                )
            logger.warning(
                "job.error",
                extra={"fields": {"job_id": str(job_id), "kind": row.kind, "state": state, "error": type(exc).__name__}},
            )
    finally:
        correlation_id.reset(token)
        tenant_id_var.set(None)
    return uuid.UUID(str(job_id))


def run_until_idle(engine: Engine, limit: int = 1000) -> int:
    n = 0
    while n < limit and process_one(engine) is not None:
        n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fc-worker")
    parser.add_argument("--once", action="store_true", help="process jobs until the queue is empty, then exit")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = engine_for(settings.database_url)
    with engine.connect() as conn:
        conn.execute(text("select 1"))
    log(logger, "worker.ready")
    if args.once:
        run_until_idle(engine)
        return 0
    while True:  # pragma: no cover - long-running loop
        if process_one(engine) is None:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
