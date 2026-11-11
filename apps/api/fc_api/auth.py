"""Sign-in (B2, T-2.2.3; TRD 5.1 and 8.1, AD-07): password plus TOTP, no email-link sign-in.

Flow: `/auth/login` (password) opens a short `password` or `enrol` session; `/auth/totp`
(code or recovery code) or `/auth/totp/enrol` + `/auth/totp/confirm` replace it with a new
`full` session token. Invitations and password resets are emailed single-use links; neither
signs a user in on its own, and a reset never bypasses the second factor.

Errors for a wrong address, a wrong password and a locked account are identical
(`SIGN_IN_REFUSED`, 401) so an address cannot be probed (ASVS V6.3.8).
"""

from __future__ import annotations

import logging
import smtplib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fc_api.core import (
    SESSION_ABSOLUTE,
    SESSION_COOKIE,
    SESSION_IDLE,
    ApiError,
    Ctx,
    find_session,
    get_engine,
    require_csrf,
    session_token,
    tenant_ctx,
)
from fc_db import ops
from fc_db.tables import app_user, auth_attempt, auth_token, membership, recovery_code, user_session
from fc_platform import clock
from fc_platform.auth import (
    PasswordPolicyError,
    check_password_policy,
    csrf_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    new_recovery_codes,
    new_token,
    new_totp_secret,
    otpauth_uri,
    recovery_code_hash,
    token_hash,
    verify_password,
    verify_totp,
)
from fc_platform.clock import now
from fc_platform.logging import log
from fc_platform.mail import Mailer
from fc_platform.settings import get_settings
from fc_platform.tenant import set_tenant

logger = logging.getLogger("fc_api.auth")
router = APIRouter(prefix="/api/v1/auth")

PENDING_TTL = timedelta(minutes=10)
LOCK_AFTER = 5
LOCK_FOR = timedelta(minutes=15)
HOURLY_LIMIT = 20
ATTEMPT_RETENTION = timedelta(hours=24)
RESET_TTL = timedelta(minutes=30)


def refused() -> ApiError:
    return ApiError(401, "SIGN_IN_REFUSED", "the address, password or code was not accepted")


def mailer(request: Request) -> Mailer:
    m: Mailer = request.app.state.mailer
    return m


def send_mail(m: Mailer, to: str, subject: str, body: str, kind: str) -> None:
    try:
        m.send(to, subject, body, kind=kind)
    except (OSError, smtplib.SMTPException) as exc:
        logger.error("mail.failed", extra={"fields": {"kind": kind, "error": type(exc).__name__}})
        raise ApiError(503, "MAIL_UNAVAILABLE", "the email could not be sent; try again") from exc


# ------------------------------------------------------------------ attempt limit and lockout


def rate_limited(conn: Connection, email: str) -> bool:
    """20 attempts an hour per address (TRD 8.1, ASVS V6.3.1), whether or not the address exists."""
    conn.execute(
        auth_attempt.delete().where(auth_attempt.c.email == email, auth_attempt.c.created_at < func.now() - ATTEMPT_RETENTION)
    )
    n = conn.execute(
        select(func.count())
        .select_from(auth_attempt)
        .where(auth_attempt.c.email == email, auth_attempt.c.created_at > func.now() - timedelta(hours=1))
    ).scalar_one()
    return int(n) >= HOURLY_LIMIT


def record_attempt(conn: Connection, email: str, kind: str, ok: bool) -> None:
    conn.execute(auth_attempt.insert().values(email=email, kind=kind, succeeded=ok))


def is_locked(user: Any) -> bool:
    return user.locked_until is not None and user.locked_until > now()


def register_failure(conn: Connection, user_id: uuid.UUID) -> None:
    """Five failed passwords or codes lock the account for 15 minutes (TRD 8.1)."""
    row = conn.execute(
        app_user.update()
        .where(app_user.c.id == user_id)
        .values(failed_count=app_user.c.failed_count + 1)
        .returning(app_user.c.failed_count)
    ).one()
    if row.failed_count >= LOCK_AFTER:
        conn.execute(app_user.update().where(app_user.c.id == user_id).values(failed_count=0, locked_until=now() + LOCK_FOR))
        log(logger, "auth.locked", user_id=str(user_id))


def user_tenants(conn: Connection, user_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    rows = conn.execute(text("select tenant_id, role from fc_user_tenants(:u)"), {"u": user_id}).all()
    return [(r.tenant_id, r.role) for r in rows]


# ------------------------------------------------------------------ sessions


@dataclass(frozen=True)
class Opened:
    token: str
    stage: str
    tenant_id: uuid.UUID
    expires_at: datetime


def open_session(conn: Connection, user_id: uuid.UUID, tenant_id: uuid.UUID, stage: str) -> Opened:
    """A new random token each time a session is opened or upgraded (ASVS V7.2.4)."""
    token = new_token()
    expires = now() + (SESSION_ABSOLUTE if stage == "full" else PENDING_TTL)
    conn.execute(
        user_session.insert().values(
            user_id=user_id, active_tenant_id=tenant_id, token_hash=token_hash(token), stage=stage, expires_at=expires
        )
    )
    return Opened(token, stage, tenant_id, expires)


def revoke(conn: Connection, *conds: Any) -> int:
    res = conn.execute(user_session.update().where(user_session.c.revoked_at.is_(None), *conds).values(revoked_at=func.now()))
    return int(res.rowcount)


def session_response(opened: Opened, status: int = 200, **extra: Any) -> JSONResponse:
    s = get_settings()
    body = {
        "stage": opened.stage,
        "tenant_id": str(opened.tenant_id),
        "csrf_token": csrf_token(opened.token, s.signing_key),
        "expires_at": opened.expires_at.isoformat(),
        **extra,
    }
    resp = JSONResponse(body, status_code=status)
    resp.set_cookie(
        SESSION_COOKIE,
        opened.token,
        max_age=int((SESSION_ABSOLUTE if opened.stage == "full" else PENDING_TTL).total_seconds()),
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return resp


def pending_session(request: Request, conn: Connection, stages: tuple[str, ...]) -> tuple[str, Any]:
    token = session_token(request)
    require_csrf(request, token)
    sess = find_session(conn, token, stages)
    if sess is None:
        raise ApiError(401, "UNAUTHENTICATED", "start again from the password step")
    return token, sess


def finish_sign_in(conn: Connection, user_id: uuid.UUID, pending_id: uuid.UUID, tenant_id: uuid.UUID) -> Opened:
    conn.execute(app_user.update().where(app_user.c.id == user_id).values(failed_count=0, locked_until=None))
    revoke(conn, user_session.c.id == pending_id)
    opened = open_session(conn, user_id, tenant_id, "full")
    set_tenant(conn, tenant_id)
    role = conn.execute(select(membership.c.role).where(membership.c.user_id == user_id)).scalar_one_or_none()
    ops.audit(
        conn,
        tenant_id=tenant_id,
        actor_user_id=user_id,
        actor_role=role,
        action="auth.sign_in",
        entity_type="app_user",
        entity_id=user_id,
    )
    log(logger, "auth.sign_in", user_id=str(user_id))
    return opened


def store_recovery_codes(conn: Connection, user_id: uuid.UUID) -> list[str]:
    codes = new_recovery_codes()
    conn.execute(recovery_code.delete().where(recovery_code.c.user_id == user_id))
    conn.execute(recovery_code.insert(), [{"user_id": user_id, "code_hash": recovery_code_hash(c)} for c in codes])
    return codes


def check_second_factor(conn: Connection, user: Any, code: str | None, recovery: str | None) -> bool:
    """A TOTP step or a recovery code is accepted once (ASVS V6.5.1)."""
    settings = get_settings()
    if code and user.totp_secret_enc is not None:
        secret = decrypt_secret(bytes(user.totp_secret_enc), settings.data_key, user.id.bytes)
        step = verify_totp(secret, code, clock.epoch(), user.totp_last_step)
        if step is not None:
            conn.execute(app_user.update().where(app_user.c.id == user.id).values(totp_last_step=step))
            return True
        return False
    if recovery:
        used = conn.execute(
            recovery_code.update()
            .where(
                recovery_code.c.user_id == user.id,
                recovery_code.c.code_hash == recovery_code_hash(recovery),
                recovery_code.c.used_at.is_(None),
            )
            .values(used_at=func.now())
            .returning(recovery_code.c.id)
        ).first()
        return used is not None
    return False


def load_user(conn: Connection, user_id: uuid.UUID) -> Any:
    return conn.execute(select(app_user).where(app_user.c.id == user_id).with_for_update()).one()


# ------------------------------------------------------------------ password step


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    tenant_id: uuid.UUID | None = None


@router.post("/login")
def login(body: LoginBody, engine: Engine = Depends(get_engine)) -> JSONResponse:
    email = body.email.strip()
    outcome: Opened | ApiError
    with engine.begin() as conn:
        if rate_limited(conn, email):
            outcome = ApiError(429, "RATE_LIMITED", "too many attempts for this address; wait an hour")
        else:
            user = conn.execute(select(app_user).where(app_user.c.email == email).with_for_update()).first()
            ok = verify_password(user.password_hash if user is not None else None, body.password)
            locked = user is not None and is_locked(user)
            record_attempt(conn, email, "password", ok and not locked)
            if user is None or locked or not ok:
                if user is not None and not locked:
                    register_failure(conn, user.id)
                log(logger, "auth.password_refused", user_id=str(user.id) if user else None, locked=locked)
                outcome = refused()
            else:
                tenants = user_tenants(conn, user.id)
                ids = [t for t, _ in tenants]
                if not ids or (body.tenant_id is not None and body.tenant_id not in ids):
                    outcome = refused()
                elif body.tenant_id is None and len(ids) > 1:
                    outcome = ApiError(409, "TENANT_REQUIRED", "choose the account to sign in to", tenants=[str(t) for t in ids])
                else:
                    stage = "password" if user.totp_enrolled_at is not None else "enrol"
                    outcome = open_session(conn, user.id, body.tenant_id or ids[0], stage)
    if isinstance(outcome, ApiError):
        raise outcome
    return session_response(outcome)


# ------------------------------------------------------------------ second factor


class CodeBody(BaseModel):
    code: str | None = Field(default=None, max_length=12)
    recovery_code: str | None = Field(default=None, max_length=40)


@router.post("/totp")
def totp(body: CodeBody, request: Request, engine: Engine = Depends(get_engine)) -> JSONResponse:
    outcome: Opened | ApiError
    with engine.begin() as conn:
        _, sess = pending_session(request, conn, ("password",))
        user = load_user(conn, sess.user_id)
        if rate_limited(conn, user.email):
            outcome = ApiError(429, "RATE_LIMITED", "too many attempts for this address; wait an hour")
        else:
            locked = is_locked(user)
            ok = not locked and check_second_factor(conn, user, body.code, body.recovery_code)
            record_attempt(conn, user.email, "code", ok)
            if not ok:
                if not locked:
                    register_failure(conn, user.id)
                log(logger, "auth.code_refused", user_id=str(user.id), locked=locked)
                outcome = refused()
            else:
                outcome = finish_sign_in(conn, user.id, sess.id, sess.active_tenant_id)
    if isinstance(outcome, ApiError):
        raise outcome
    return session_response(outcome)


@router.post("/totp/enrol")
def totp_enrol(request: Request, engine: Engine = Depends(get_engine)) -> dict[str, str]:
    """Issue a new TOTP seed for a user who has none confirmed (first sign-in or after a factor reset)."""
    settings = get_settings()
    with engine.begin() as conn:
        _, sess = pending_session(request, conn, ("enrol",))
        user = load_user(conn, sess.user_id)
        if user.totp_enrolled_at is not None:
            raise ApiError(409, "ALREADY_ENROLLED", "a second factor is already enrolled")
        secret = new_totp_secret()
        conn.execute(
            app_user.update()
            .where(app_user.c.id == user.id)
            .values(totp_secret_enc=encrypt_secret(secret, settings.data_key, user.id.bytes), totp_last_step=None)
        )
        return {"secret": secret, "otpauth_uri": otpauth_uri(secret, user.email)}


class ConfirmBody(BaseModel):
    code: str = Field(min_length=6, max_length=12)


@router.post("/totp/confirm")
def totp_confirm(body: ConfirmBody, request: Request, engine: Engine = Depends(get_engine)) -> JSONResponse:
    outcome: tuple[Opened, list[str]] | ApiError
    with engine.begin() as conn:
        _, sess = pending_session(request, conn, ("enrol",))
        user = load_user(conn, sess.user_id)
        if user.totp_secret_enc is None:
            raise ApiError(409, "ENROL_FIRST", "request a secret from /auth/totp/enrol first")
        if rate_limited(conn, user.email):
            outcome = ApiError(429, "RATE_LIMITED", "too many attempts for this address; wait an hour")
        else:
            locked = is_locked(user)
            ok = not locked and check_second_factor(conn, user, body.code, None)
            record_attempt(conn, user.email, "code", ok)
            if not ok:
                if not locked:
                    register_failure(conn, user.id)
                outcome = refused()
            else:
                conn.execute(app_user.update().where(app_user.c.id == user.id).values(totp_enrolled_at=func.now()))
                codes = store_recovery_codes(conn, user.id)
                outcome = (finish_sign_in(conn, user.id, sess.id, sess.active_tenant_id), codes)
    if isinstance(outcome, ApiError):
        raise outcome
    return session_response(outcome[0], recovery_codes=outcome[1])


@router.post("/recovery-codes")
def regenerate_recovery_codes(body: ConfirmBody, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    """Ten new codes replace the old ones; needs a current TOTP code (re-authentication)."""
    user = load_user(ctx.conn, ctx.user_id)
    if not check_second_factor(ctx.conn, user, body.code, None):
        raise refused()
    codes = store_recovery_codes(ctx.conn, ctx.user_id)
    ops.audit(
        ctx.conn,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="auth.recovery_codes",
        entity_type="app_user",
        entity_id=ctx.user_id,
    )
    return JSONResponse({"recovery_codes": codes})


# ------------------------------------------------------------------ session, logout, password change


@router.get("/session")
def current_session(request: Request, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    """Session state for the client, including the idle deadline for the expiry warning. Does
    not extend the session."""
    token = session_token(request)
    with engine.begin() as conn:
        sess = find_session(conn, token, ("password", "enrol", "full"))
        if sess is None:
            raise ApiError(401, "UNAUTHENTICATED", "session expired or signed out")
        return {
            "user_id": str(sess.user_id),
            "tenant_id": str(sess.active_tenant_id),
            "stage": sess.stage,
            "csrf_token": csrf_token(token, get_settings().signing_key),
            "expires_at": sess.expires_at.isoformat(),
            "idle_expires_at": (sess.last_seen_at + SESSION_IDLE).isoformat(),
        }


@router.post("/logout", status_code=204)
def logout(request: Request, engine: Engine = Depends(get_engine)) -> Response:
    """Revokes the session server-side (ASVS V7.4.1) and clears the cookie."""
    token = session_token(request)
    require_csrf(request, token)
    with engine.begin() as conn:
        revoke(conn, user_session.c.token_hash == token_hash(token))
    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return resp


class PasswordChangeBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


@router.post("/password", status_code=204)
def change_password(body: PasswordChangeBody, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> Response:
    """Needs the current password; ends every other session of the user (ASVS V6.2.2, V6.2.3, V7.4.3)."""
    user = load_user(ctx.conn, ctx.user_id)
    if not verify_password(user.password_hash, body.current_password):
        raise refused()
    try:
        new_hash = hash_password(body.new_password)
    except PasswordPolicyError as exc:
        raise ApiError(422, "PASSWORD_POLICY", str(exc), field="new_password") from exc
    ctx.conn.execute(app_user.update().where(app_user.c.id == ctx.user_id).values(password_hash=new_hash))
    revoke(ctx.conn, user_session.c.user_id == ctx.user_id, user_session.c.id != ctx.session_id)
    ops.audit(
        ctx.conn,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="auth.password_changed",
        entity_type="app_user",
        entity_id=ctx.user_id,
    )
    send_mail(mailer(request), user.email, "Your FreightCheck password was changed", CHANGED_BODY, "password_changed")
    return Response(status_code=204)


# ------------------------------------------------------------------ password reset (emailed single-use link)

RESET_BODY = """Someone asked to reset the FreightCheck password for this address.

Open this link within 30 minutes to choose a new password:
{link}

After the reset you still sign in with your authenticator code. If you did not ask for this,
ignore this message; your password is unchanged.
"""
CHANGED_BODY = """The password for your FreightCheck account was just changed and your other sessions
were signed out. If this was not you, contact your account Owner.
"""


class ResetRequestBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)


@router.post("/reset-request", status_code=202)
def reset_request(body: ResetRequestBody, request: Request, engine: Engine = Depends(get_engine)) -> dict[str, str]:
    """Always 202 so the answer does not reveal whether the address has an account."""
    email = body.email.strip()
    link: str | None = None
    to = ""
    with engine.begin() as conn:
        if rate_limited(conn, email):
            raise ApiError(429, "RATE_LIMITED", "too many attempts for this address; wait an hour")
        record_attempt(conn, email, "reset_request", True)
        user = conn.execute(select(app_user).where(app_user.c.email == email)).first()
        if user is not None and user.password_hash is not None:
            conn.execute(
                auth_token.update()
                .where(auth_token.c.user_id == user.id, auth_token.c.purpose == "reset", auth_token.c.used_at.is_(None))
                .values(used_at=func.now())
            )
            token = new_token()
            conn.execute(
                auth_token.insert().values(
                    user_id=user.id, purpose="reset", token_hash=token_hash(token), expires_at=now() + RESET_TTL
                )
            )
            # The token travels in the fragment, which browsers do not send to servers (ASVS V14.2.1).
            link = f"{get_settings().public_base_url.rstrip('/')}/reset-password#token={token}"
            to = user.email
            send_mail(mailer(request), to, "Reset your FreightCheck password", RESET_BODY.format(link=link), "password_reset")
            log(logger, "auth.reset_requested", user_id=str(user.id))
    return {"status": "accepted"}


class ResetBody(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


def take_token(conn: Connection, token: str, purpose: str) -> Any:
    row = conn.execute(
        select(auth_token)
        .where(
            auth_token.c.token_hash == token_hash(token),
            auth_token.c.purpose == purpose,
            auth_token.c.used_at.is_(None),
            auth_token.c.expires_at > func.now(),
        )
        .with_for_update()
    ).first()
    if row is None:
        log(logger, "auth.token_refused", purpose=purpose)
        raise ApiError(400, "TOKEN_INVALID", "this link has expired or was already used")
    return row


def consume(conn: Connection, token_id: uuid.UUID) -> None:
    conn.execute(auth_token.update().where(auth_token.c.id == token_id).values(used_at=func.now()))


@router.post("/reset", status_code=204)
def reset(body: ResetBody, request: Request, engine: Engine = Depends(get_engine)) -> Response:
    """Sets a new password and ends every session; it does not sign in, and the next sign-in
    still needs the second factor (TRD 8.4, ASVS V6.4.3)."""
    try:
        check_password_policy(body.password)
    except PasswordPolicyError as exc:
        raise ApiError(422, "PASSWORD_POLICY", str(exc), field="password") from exc
    with engine.begin() as conn:
        tok = take_token(conn, body.token, "reset")
        consume(conn, tok.id)
        user = load_user(conn, tok.user_id)
        conn.execute(app_user.update().where(app_user.c.id == user.id).values(password_hash=hash_password(body.password)))
        revoke(conn, user_session.c.user_id == user.id)
        send_mail(mailer(request), user.email, "Your FreightCheck password was changed", CHANGED_BODY, "password_changed")
        log(logger, "auth.password_reset", user_id=str(user.id))
    return Response(status_code=204)


# ------------------------------------------------------------------ invitation acceptance


class AcceptBody(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


@router.post("/invitations/accept")
def accept_invitation(body: AcceptBody, engine: Engine = Depends(get_engine)) -> JSONResponse:
    """A new user sets a password here; an existing user proves it. Either way the next step
    is the second factor: enrolment for a new user, the code for an enrolled one."""
    outcome: Opened | ApiError
    with engine.begin() as conn:
        tok = take_token(conn, body.token, "invite")
        user = load_user(conn, tok.user_id)
        if rate_limited(conn, user.email):
            raise ApiError(429, "RATE_LIMITED", "too many attempts for this address; wait an hour")
        if user.password_hash is None:
            try:
                new_hash = hash_password(body.password)
            except PasswordPolicyError as exc:
                raise ApiError(422, "PASSWORD_POLICY", str(exc), field="password") from exc
            conn.execute(app_user.update().where(app_user.c.id == user.id).values(password_hash=new_hash))
            ok = True
        else:
            ok = not is_locked(user) and verify_password(user.password_hash, body.password)
        record_attempt(conn, user.email, "invitation", ok)
        if not ok:
            register_failure(conn, user.id)
            outcome = refused()
        else:
            set_tenant(conn, tok.invited_tenant_id)
            consume(conn, tok.id)
            conn.execute(
                pg_insert(membership)
                .values(tenant_id=tok.invited_tenant_id, user_id=user.id, role=tok.invited_role)
                .on_conflict_do_nothing(index_elements=["tenant_id", "user_id"])
            )
            ops.audit(
                conn,
                tenant_id=tok.invited_tenant_id,
                actor_user_id=user.id,
                actor_role=tok.invited_role,
                action="membership.accepted",
                entity_type="app_user",
                entity_id=user.id,
            )
            stage = "password" if user.totp_enrolled_at is not None else "enrol"
            outcome = open_session(conn, user.id, tok.invited_tenant_id, stage)
    if isinstance(outcome, ApiError):
        raise outcome
    return session_response(outcome)
