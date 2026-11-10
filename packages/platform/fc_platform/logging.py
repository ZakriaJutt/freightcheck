"""JSON logs carrying the correlation ID (T-2.1.4, R-12).

Logs carry IDs only: never rates, amounts, customer file names or email bodies.
"""

from __future__ import annotations

import json
import logging as std_logging
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)

FORBIDDEN_FIELDS = frozenset({"amount", "amount_cents", "rate", "price", "body", "filename", "params"})


def new_correlation_id() -> str:
    return uuid.uuid4().hex


class JsonFormatter(std_logging.Formatter):
    def format(self, record: std_logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "correlation_id": correlation_id.get(),
            "tenant_id": tenant_id_var.get(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            for k, v in extra.items():
                if k in FORBIDDEN_FIELDS:
                    continue
                payload[k] = v
        if record.exc_info:
            payload["error"] = record.exc_info[0].__name__ if record.exc_info[0] else "error"
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = std_logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_fc", False):
            root.removeHandler(h)
    handler = std_logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._fc = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)


def log(logger: std_logging.Logger, event: str, **fields: Any) -> None:
    logger.info(event, extra={"fields": fields})
