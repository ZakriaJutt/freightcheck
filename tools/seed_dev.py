"""Seed one synthetic tenant with an Approver session for local use (idempotent).

B1 has no sign-in endpoints (T-2.2.3 not built); this writes a dev-only session and stores
its cookie in the git-ignored `.local/dev-session.txt` (mode 0600). It prints the value only
with `--print-session` (B1-012). Synthetic names only. Refuses to run outside FC_ENV=dev.
"""

from __future__ import annotations

import hashlib
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, select

from fc_db.tables import app_user, membership, tenant, user_session
from fc_platform.settings import get_settings


def main() -> None:
    s = get_settings()
    if s.env != "dev":
        raise SystemExit("seed_dev runs only with FC_ENV=dev")
    eng = create_engine(s.migration_database_url)
    with eng.begin() as c:
        tid = c.execute(select(tenant.c.id).where(tenant.c.name == "Synthetic Shipper (dev)")).scalar_one_or_none()
        if tid is None:
            tid = c.execute(
                tenant.insert()
                .values(name="Synthetic Shipper (dev)", plan="pilot_gainshare", inbox_token=secrets.token_hex(8))
                .returning(tenant.c.id)
            ).scalar_one()
        uid = c.execute(select(app_user.c.id).where(app_user.c.email == "approver@shipper.example")).scalar_one_or_none()
        if uid is None:
            uid = c.execute(
                app_user.insert().values(email="approver@shipper.example", password_hash="unset-in-b1").returning(app_user.c.id)
            ).scalar_one()
            c.execute(membership.insert().values(tenant_id=tid, user_id=uid, role="approver"))
        token = secrets.token_urlsafe(24)
        c.execute(
            user_session.insert().values(
                user_id=uid,
                active_tenant_id=tid,
                token_hash=hashlib.sha256(token.encode()).digest(),
                expires_at=datetime.now(UTC) + timedelta(hours=12),
            )
        )
    out = Path(__file__).resolve().parents[1] / ".local" / "dev-session.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.touch(mode=0o600, exist_ok=True)
    out.chmod(0o600)
    out.write_text(f"fc_session={token}\n")
    if "--print-session" in sys.argv:
        print(f"dev session cookie: fc_session={token}")
    else:
        print(f"dev session cookie written to {out.relative_to(out.parents[1])}")


if __name__ == "__main__":
    main()
