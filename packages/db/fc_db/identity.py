"""Invitations (B2, TRD 8.1): shared by the Owner's API route and the dev/bootstrap seed.

An invitation is a single-use emailed link valid 7 days. It creates the user row (without a
password) if the address is new; accepting it sets the password, adds the membership and
leads straight to second-factor enrolment.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Connection, func, select

from fc_db.tables import app_user, auth_token
from fc_platform.auth import new_token, token_hash
from fc_platform.clock import now

INVITE_TTL = timedelta(days=7)

INVITE_SUBJECT = "You are invited to FreightCheck"
INVITE_BODY = """You were invited to the FreightCheck account "{tenant_name}" as {role}.

Open this link within 7 days to set your password and enrol an authenticator app:
{link}

The link works once. If you did not expect this invitation, ignore this message.
"""


@dataclass(frozen=True)
class Invitation:
    token: str
    token_id: uuid.UUID
    user_id: uuid.UUID
    expires_at: datetime


def issue_invitation(conn: Connection, tenant_id: uuid.UUID, email: str, role: str, invited_by: uuid.UUID | None) -> Invitation:
    user_id = conn.execute(select(app_user.c.id).where(app_user.c.email == email)).scalar_one_or_none()
    if user_id is None:
        user_id = conn.execute(app_user.insert().values(email=email).returning(app_user.c.id)).scalar_one()
    # An earlier unused invitation to the same tenant stops working.
    conn.execute(
        auth_token.update()
        .where(
            auth_token.c.user_id == user_id,
            auth_token.c.purpose == "invite",
            auth_token.c.invited_tenant_id == tenant_id,
            auth_token.c.used_at.is_(None),
        )
        .values(used_at=func.now())
    )
    token = new_token()
    expires = now() + INVITE_TTL
    token_id = conn.execute(
        auth_token.insert()
        .values(
            user_id=user_id,
            purpose="invite",
            token_hash=token_hash(token),
            expires_at=expires,
            invited_tenant_id=tenant_id,
            invited_role=role,
            invited_by=invited_by,
        )
        .returning(auth_token.c.id)
    ).scalar_one()
    return Invitation(token, token_id, user_id, expires)


def invitation_link(public_base_url: str, token: str) -> str:
    # The token is in the fragment, which browsers never send to a server (ASVS V14.2.1).
    return f"{public_base_url.rstrip('/')}/accept-invitation#token={token}"
