"""Seed one synthetic tenant and invite its first Owner by email (idempotent; B2).

Since B2 there is no dev-only session: the invitation goes through SMTP to the local Mailpit
inbox (http://127.0.0.1:8025). Open it, accept it at POST /api/v1/auth/invitations/accept, and
enrol an authenticator, exactly as a pilot user would. A new invitation is sent only while
the Owner has not yet set a password. Synthetic names only. Refuses to run outside FC_ENV=dev.
"""

from __future__ import annotations

import secrets

from sqlalchemy import create_engine, select

from fc_db.identity import INVITE_BODY, INVITE_SUBJECT, invitation_link, issue_invitation
from fc_db.tables import app_user, tenant
from fc_platform.mail import mailer_from_settings
from fc_platform.settings import get_settings

TENANT_NAME = "Synthetic Shipper (dev)"
OWNER_EMAIL = "owner@shipper.example"


def main() -> None:
    s = get_settings()
    if s.env != "dev":
        raise SystemExit("seed_dev runs only with FC_ENV=dev")
    eng = create_engine(s.migration_database_url)
    with eng.begin() as c:
        tid = c.execute(select(tenant.c.id).where(tenant.c.name == TENANT_NAME)).scalar_one_or_none()
        if tid is None:
            tid = c.execute(
                tenant.insert()
                .values(name=TENANT_NAME, plan="pilot_gainshare", inbox_token=secrets.token_hex(8))
                .returning(tenant.c.id)
            ).scalar_one()
        has_password = c.execute(
            select(app_user.c.password_hash.is_not(None)).where(app_user.c.email == OWNER_EMAIL)
        ).scalar_one_or_none()
        if has_password:
            print(f"owner {OWNER_EMAIL} already set a password; sign in at POST /api/v1/auth/login")
            return
        inv = issue_invitation(c, tid, OWNER_EMAIL, "owner", None)
        body = INVITE_BODY.format(tenant_name=TENANT_NAME, role="owner", link=invitation_link(s.public_base_url, inv.token))
        mailer_from_settings(s).send(OWNER_EMAIL, INVITE_SUBJECT, body, kind="invitation")
    print(f"invitation for {OWNER_EMAIL} sent to the local Mailpit inbox: http://127.0.0.1:8025")


if __name__ == "__main__":
    main()
