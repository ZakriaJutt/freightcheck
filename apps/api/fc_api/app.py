"""FastAPI application factory (TRD 5.1). Run: uvicorn fc_api.app:create_app --factory --port 8102."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from fc_api import auth, claims, invoices, rates, users
from fc_api.core import ApiError, error_body
from fc_platform.db import engine_for
from fc_platform.logging import configure_logging, correlation_id, log
from fc_platform.mail import Mailer, mailer_from_settings
from fc_platform.settings import Settings, get_settings
from fc_platform.storage import ObjectStorage, storage_from_settings

logger = logging.getLogger("fc_api")


def create_app(
    settings: Settings | None = None, *, mailer: Mailer | None = None, storage: ObjectStorage | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="FreightCheck API", version="0.1.0")
    app.state.engine = engine_for(settings.database_url)
    app.state.mailer = mailer or mailer_from_settings(settings)
    app.state.storage = storage or storage_from_settings(settings)

    @app.middleware("http")
    async def correlation(request: Request, call_next):  # type: ignore[no-untyped-def]
        cid = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
        if len(cid) > 64 or not cid.replace("-", "").isalnum():
            cid = uuid.uuid4().hex
        token = correlation_id.set(cid)
        try:
            try:
                response = await call_next(request)
            except Exception as exc:  # noqa: BLE001 - B1-010: one JSON error contract, with the correlation ID
                logger.error("unhandled", extra={"fields": {"error": type(exc).__name__}})
                response = JSONResponse(
                    error_body("INTERNAL_ERROR", "unexpected error; quote the correlation ID"), status_code=500
                )
            log(logger, "request", method=request.method, path=request.url.path, status=response.status_code)
            response.headers["X-Correlation-ID"] = cid
            # Responses carry tenant data or credentials: never cached (ASVS V14.3.2).
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        finally:
            correlation_id.reset(token)

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.field, **exc.extra), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", ())[1:]) or None
        return JSONResponse(error_body("VALIDATION_ERROR", str(first.get("msg", "invalid request")), field), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        try:
            with app.state.engine.connect() as conn:
                head = conn.execute(text("select version_num from alembic_version")).scalar_one_or_none()
        except Exception:  # noqa: BLE001
            return JSONResponse({"status": "not_ready", "database": "unreachable"}, status_code=503)
        if head is None:
            return JSONResponse({"status": "not_ready", "database": "not migrated"}, status_code=503)
        return JSONResponse({"status": "ready", "schema": head})

    app.include_router(auth.router)
    app.include_router(users.api)
    app.include_router(rates.router)
    app.include_router(invoices.api)
    app.include_router(invoices.router)
    app.include_router(claims.router)
    return app
