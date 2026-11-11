"""Members, invitations, roles, removal, factor reset, unlock (B2; TRD 5.1, schema section 4: Owner only).

`{user_id}` is resolved through the membership table under RLS, so a user of another tenant
answers 404 (IT-01).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from fc_api.auth import mailer, revoke, send_mail
from fc_api.core import ApiError, Ctx, idempotent, not_found, tenant_ctx
from fc_db import ops
from fc_db.identity import INVITE_BODY, INVITE_SUBJECT, invitation_link, issue_invitation
from fc_db.tables import app_user, auth_token, membership, recovery_code, tenant, user_session
from fc_platform.clock import now
from fc_platform.settings import get_settings

api = APIRouter(prefix="/api/v1/users")
OWNER = frozenset({"owner"})
Role = Literal["owner", "approver", "auditor", "viewer"]


def member(ctx: Ctx, user_id: uuid.UUID, *, for_update: bool = False) -> Any:
    q = select(membership).where(membership.c.user_id == user_id)
    row = ctx.conn.execute(q.with_for_update() if for_update else q).first()
    if row is None:
        raise not_found("user", user_id)
    return row


def guard_last_owner(ctx: Ctx, m: Any) -> None:
    if m.role != "owner":
        return
    owners = ctx.conn.execute(select(func.count()).select_from(membership).where(membership.c.role == "owner")).scalar_one()
    if owners <= 1:
        raise ApiError(409, "LAST_OWNER", "an account needs at least one Owner")


@api.get("")
def list_users(ctx: Ctx = Depends(tenant_ctx)) -> list[dict[str, Any]]:
    ctx.require(OWNER)
    rows = ctx.conn.execute(
        select(membership.c.user_id, membership.c.role, app_user.c.email, app_user.c.totp_enrolled_at, app_user.c.locked_until)
        .join(app_user, app_user.c.id == membership.c.user_id)
        .order_by(app_user.c.email)
    ).all()
    return [
        {
            "user_id": str(r.user_id),
            "email": r.email,
            "role": r.role,
            "second_factor_enrolled": r.totp_enrolled_at is not None,
            "locked": r.locked_until is not None and r.locked_until > now(),
        }
        for r in rows
    ]


class InviteBody(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: Role


@api.post("/invitations")
def invite(body: InviteBody, request: Request, ctx: Ctx = Depends(tenant_ctx)) -> JSONResponse:
    ctx.require(OWNER)
    email = body.email.strip()

    def go() -> tuple[int, dict[str, Any]]:
        existing = ctx.conn.execute(
            select(membership.c.id).join(app_user, app_user.c.id == membership.c.user_id).where(app_user.c.email == email)
        ).first()
        if existing is not None:
            raise ApiError(409, "ALREADY_MEMBER", "this address is already a member", field="email")
        inv = issue_invitation(ctx.conn, ctx.tenant_id, email, body.role, ctx.user_id)
        tenant_name = ctx.conn.execute(select(tenant.c.name).where(tenant.c.id == ctx.tenant_id)).scalar_one()
        ops.audit(
            ctx.conn,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            actor_role=ctx.role,
            action="membership.invited",
            entity_type="app_user",
            entity_id=inv.user_id,
            after={"role": body.role},
        )
        link = invitation_link(get_settings().public_base_url, inv.token)
        send_mail(
            mailer(request),
            email,
            INVITE_SUBJECT,
            INVITE_BODY.format(tenant_name=tenant_name, role=body.role, link=link),
            "invitation",
        )
        return 201, {
            "invitation_id": str(inv.token_id),
            "user_id": str(inv.user_id),
            "role": body.role,
            "expires_at": inv.expires_at.isoformat(),
        }

    return idempotent(request, ctx, {"email": email.lower(), "role": body.role}, go)


class RoleBody(BaseModel):
    role: Role


@api.patch("/{user_id}/role")
def change_role(user_id: uuid.UUID, body: RoleBody, ctx: Ctx = Depends(tenant_ctx)) -> dict[str, str]:
    ctx.require(OWNER)
    m = member(ctx, user_id, for_update=True)
    if body.role != "owner":
        guard_last_owner(ctx, m)
    ctx.conn.execute(
        membership.update()
        .where(membership.c.id == m.id)
        .values(role=body.role, version=membership.c.version + 1, updated_at=func.now())
    )
    ops.audit(
        ctx.conn,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="membership.role",
        entity_type="app_user",
        entity_id=user_id,
        before={"role": m.role},
        after={"role": body.role},
    )
    return {"user_id": str(user_id), "role": body.role}


@api.delete("/{user_id}", status_code=204)
def remove_user(user_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx)) -> Response:
    """Removes the membership and ends the user's sessions in this tenant (ASVS V7.4.2)."""
    ctx.require(OWNER)
    m = member(ctx, user_id, for_update=True)
    guard_last_owner(ctx, m)
    ctx.conn.execute(membership.delete().where(membership.c.id == m.id))
    revoke(ctx.conn, user_session.c.user_id == user_id, user_session.c.active_tenant_id == ctx.tenant_id)
    ctx.conn.execute(
        auth_token.update()
        .where(auth_token.c.user_id == user_id, auth_token.c.invited_tenant_id == ctx.tenant_id, auth_token.c.used_at.is_(None))
        .values(used_at=func.now())
    )
    ops.audit(
        ctx.conn,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="membership.removed",
        entity_type="app_user",
        entity_id=user_id,
        before={"role": m.role},
    )
    return Response(status_code=204)


@api.post("/{user_id}/factor-reset", status_code=204)
def factor_reset(user_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx)) -> Response:
    """After the Owner confirms identity by a call (TRD 8.1): the second factor and recovery
    codes are removed and every session ends; the next sign-in needs the password and a new
    enrolment. The factor is the user's, so this applies in every tenant they belong to."""
    ctx.require(OWNER)
    member(ctx, user_id)
    ctx.conn.execute(
        app_user.update().where(app_user.c.id == user_id).values(totp_secret_enc=None, totp_enrolled_at=None, totp_last_step=None)
    )
    ctx.conn.execute(recovery_code.delete().where(recovery_code.c.user_id == user_id))
    revoke(ctx.conn, user_session.c.user_id == user_id)
    ops.audit(
        ctx.conn,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="auth.factor_reset",
        entity_type="app_user",
        entity_id=user_id,
    )
    return Response(status_code=204)


@api.post("/{user_id}/unlock", status_code=204)
def unlock(user_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx)) -> Response:
    """An Owner can lift the 15-minute lockout (TRD 8.1)."""
    ctx.require(OWNER)
    member(ctx, user_id)
    ctx.conn.execute(app_user.update().where(app_user.c.id == user_id).values(locked_until=None, failed_count=0))
    ops.audit(
        ctx.conn,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="auth.unlocked",
        entity_type="app_user",
        entity_id=user_id,
    )
    return Response(status_code=204)
