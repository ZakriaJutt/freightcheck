"""Request plumbing: errors, session auth, tenant transaction, roles, idempotency."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, Engine, func, select, text

from fc_db.repo import NotFound, get_row
from fc_db.tables import app_user, idempotency_record, membership, user_session
from fc_platform.clock import now
from fc_platform.logging import correlation_id
from fc_platform.tenant import set_tenant

logger = logging.getLogger("fc_api")
SESSION_COOKIE = "fc_session"
IDEMPOTENCY_TTL = timedelta(hours=24)

AUDITOR_PLUS = frozenset({"owner", "approver", "auditor"})
APPROVER_PLUS = frozenset({"owner", "approver"})
VIEWER_PLUS = frozenset({"owner", "approver", "auditor", "viewer"})


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None, **extra: Any) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.field, self.extra = status, code, message, field, extra


def error_body(code: str, message: str, field: str | None = None, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "correlation_id": correlation_id.get()}
    if field:
        body["field"] = field
    body.update(extra)
    return body


def not_found(entity: str, entity_id: Any) -> ApiError:
    # IT-01: a foreign or unknown id is logged and answered 404, never 403.
    logger.warning("id.not_found", extra={"fields": {"entity": entity, "entity_id": str(entity_id)}})
    return ApiError(404, "NOT_FOUND", f"{entity} not found")


@dataclass(frozen=True)
class Ctx:
    conn: Connection
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str

    def row(self, table: Any, row_id: Any, *, for_update: bool = False) -> Any:
        try:
            return get_row(self.conn, table, row_id, for_update=for_update)
        except NotFound as exc:
            raise not_found(exc.entity, exc.entity_id) from exc

    def require(self, roles: frozenset[str]) -> None:
        if self.role not in roles:
            raise ApiError(403, "FORBIDDEN", "your role cannot do this")


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def get_engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def tenant_ctx(request: Request, engine: Engine = Depends(get_engine)) -> Iterator[Ctx]:
    """One transaction per request with the tenant context set from the session."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise ApiError(401, "UNAUTHENTICATED", "sign in first")
    with engine.begin() as conn:
        sess = conn.execute(
            select(user_session.c.user_id, user_session.c.active_tenant_id)
            .join(app_user, app_user.c.id == user_session.c.user_id)
            .where(
                user_session.c.token_hash == token_hash(token),
                user_session.c.revoked_at.is_(None),
                user_session.c.expires_at > func.now(),
            )
        ).first()
        if sess is None:
            raise ApiError(401, "UNAUTHENTICATED", "session expired or signed out")
        set_tenant(conn, sess.active_tenant_id)
        role = conn.execute(select(membership.c.role).where(membership.c.user_id == sess.user_id)).scalar_one_or_none()
        if role is None:
            raise ApiError(401, "UNAUTHENTICATED", "no membership in this tenant")
        yield Ctx(conn, sess.user_id, sess.active_tenant_id, role)


def _request_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def idempotent(request: Request, ctx: Ctx, payload: Any, handler: Callable[[], tuple[int, dict[str, Any]]]) -> JSONResponse:
    """Idempotency-Key is required on every POST that creates or sends (TRD 5.1, R-02).

    A replay with the same key and body returns the stored response; the same key with a
    different body is refused. Only successful responses are stored.
    """
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise ApiError(428, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required", field="Idempotency-Key")
    route = f"{request.method} {request.url.path}"
    rhash = _request_hash(payload)
    ctx.conn.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"{ctx.tenant_id}|{route}|{key}"})
    prior = ctx.conn.execute(
        select(idempotency_record).where(
            idempotency_record.c.route == route,
            idempotency_record.c.key == key,
            idempotency_record.c.expires_at > func.now(),
        )
    ).first()
    if prior is not None:
        if prior.request_hash != rhash:
            raise ApiError(422, "IDEMPOTENCY_KEY_REUSED", "this key was used with a different request")
        return JSONResponse(prior.response_body, status_code=prior.response_status, headers={"Idempotent-Replay": "true"})
    status, body = handler()
    body = json.loads(json.dumps(body, default=str))
    ctx.conn.execute(idempotency_record.delete().where(idempotency_record.c.route == route, idempotency_record.c.key == key))
    ctx.conn.execute(
        idempotency_record.insert().values(
            tenant_id=ctx.tenant_id,
            key=key,
            route=route,
            request_hash=rhash,
            response_status=status,
            response_body=body,
            expires_at=now() + IDEMPOTENCY_TTL,
        )
    )
    return JSONResponse(body, status_code=status)


def jsonable(row: Any, *, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row._mapping.items():
        if k in exclude:
            continue
        out[k] = v if v is None or isinstance(v, int | bool | dict | list) else str(v)
    return out
