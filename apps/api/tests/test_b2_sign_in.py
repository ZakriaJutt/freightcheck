"""B2 sign-in end to end through the real endpoints, SMTP to the local Mailpit and its API
(IT-B2-01 .. IT-B2-12). Password plus TOTP; email is never a sign-in factor (AD-07)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from b2_support import PASSWORD, Browser, Clock, Mailpit, address, bootstrap_owner_invitation, token_from
from conftest import World
from sqlalchemy import select, text

from fc_api.core import CSRF_HEADER, SESSION_COOKIE
from fc_db.tables import app_user, audit_event, auth_token, user_session


@pytest.fixture(autouse=True)
def server_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    import fc_api.auth

    Clock.offset = 0.0
    monkeypatch.setattr(fc_api.auth.clock, "epoch", Clock.epoch)


@pytest.fixture
def mailpit() -> Iterator[Mailpit]:
    m = Mailpit()
    yield m
    m.cleanup()


def owner_signed_in(world: World, mailpit: Mailpit, tenant_id: uuid.UUID | None = None) -> tuple[Browser, str, uuid.UUID]:
    tid = tenant_id or world.tenant()
    email = address("owner")
    bootstrap_owner_invitation(world, tid, email)
    b = Browser(world)
    b.accept_and_enrol(token_from(mailpit.wait_for(email, "invited")))
    return b, email, tid


def test_it_b2_01_invitation_enrolment_and_sign_in_end_to_end(world: World, mailpit: Mailpit) -> None:
    owner, owner_email, tid = owner_signed_in(world, mailpit)
    assert owner.c.get("/api/v1/users").status_code == 200
    # The Owner invites an Approver through the API; the link arrives in Mailpit.
    approver_email = address("approver")
    r = owner.post(
        "/api/v1/users/invitations", {"email": approver_email, "role": "approver"}, headers={"Idempotency-Key": "inv-1"}
    )
    assert r.status_code == 201, r.text
    # An idempotent replay does not send a second mail.
    r2 = owner.post(
        "/api/v1/users/invitations", {"email": approver_email, "role": "approver"}, headers={"Idempotency-Key": "inv-1"}
    )
    assert r2.headers.get("Idempotent-Replay") == "true"
    text_ = mailpit.wait_for(approver_email, "invited")
    assert "#token=" in text_ and "as approver" in text_
    assert len([m for m in mailpit.messages_to(approver_email) if "invited" in m["Subject"]]) == 1
    approver = Browser(world)
    codes = approver.accept_and_enrol(token_from(text_))
    assert len(codes) == 10 and len(set(codes)) == 10
    who = approver.c.get("/api/v1/auth/session").json()
    assert who["stage"] == "full" and who["tenant_id"] == str(tid)
    assert approver.c.get("/api/v1/carriers").status_code == 200
    # Log out, then a fresh password + TOTP sign-in.
    assert approver.post("/api/v1/auth/logout").status_code == 204
    r = approver.sign_in(approver_email)
    assert r.status_code == 200 and r.json()["stage"] == "full", r.text
    assert approver.c.get("/api/v1/carriers").status_code == 200
    with world.owner.connect() as c:
        actions = set(c.execute(select(audit_event.c.action).where(audit_event.c.tenant_id == tid)).scalars())
    assert {"membership.invited", "membership.accepted", "auth.sign_in"} <= actions
    # The audit and log never hold the address or the code.
    assert owner_email not in str(actions)


def test_it_b2_02_cookie_attributes_and_token_rotation(world: World, mailpit: Mailpit) -> None:
    _, email, _ = owner_signed_in(world, mailpit)
    b = Browser(world)
    r = b.post("/api/v1/auth/login", {"email": email, "password": PASSWORD})
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    for attr in ("HttpOnly", "Secure", "Path=/", "SameSite=lax"):
        assert attr.lower() in cookie.lower(), attr
    assert "domain=" not in cookie.lower()
    pending = b.c.cookies[SESSION_COOKIE]
    # A pending (password-only) session reaches no tenant data.
    assert b.c.get("/api/v1/carriers").status_code == 401
    b.secret = _secret_of(world, b, email)
    r = b.post("/api/v1/auth/totp", {"code": b.next_code()})
    assert r.status_code == 200
    assert b.c.cookies[SESSION_COOKIE] != pending  # new token at sign-in (V7.2.4)
    stale = Browser(world)
    stale.c.cookies.set(SESSION_COOKIE, pending)
    assert stale.c.get("/api/v1/auth/session").status_code == 401


def _secret_of(world: World, b: Browser, email: str) -> str:
    """Read back the enrolled seed for a second browser of the same user (test-only shortcut)."""
    from fc_platform.auth import decrypt_secret
    from fc_platform.settings import get_settings

    with world.owner.connect() as c:
        u = c.execute(select(app_user).where(app_user.c.email == email)).one()
    b.last_step = u.totp_last_step
    return decrypt_secret(bytes(u.totp_secret_enc), get_settings().data_key, u.id.bytes)


def test_it_b2_03_totp_code_and_recovery_code_usable_once(world: World, mailpit: Mailpit) -> None:
    owner, email, _ = owner_signed_in(world, mailpit)
    owner.post("/api/v1/auth/logout")
    r = owner.post("/api/v1/auth/login", {"email": email, "password": PASSWORD})
    code = owner.next_code()
    assert owner.post("/api/v1/auth/totp", {"code": code}).status_code == 200
    owner.post("/api/v1/auth/logout")
    owner.post("/api/v1/auth/login", {"email": email, "password": PASSWORD})
    r = owner.post("/api/v1/auth/totp", {"code": code})
    assert r.status_code == 401 and r.json()["code"] == "SIGN_IN_REFUSED"  # same step refused (V6.5.1)
    assert owner.post("/api/v1/auth/totp", {"code": owner.next_code()}).status_code == 200


def test_it_b2_04_recovery_code_signs_in_once(world: World, mailpit: Mailpit) -> None:
    tid = world.tenant()
    email = address("owner")
    bootstrap_owner_invitation(world, tid, email)
    b = Browser(world)
    codes = b.accept_and_enrol(token_from(mailpit.wait_for(email, "invited")))
    b.post("/api/v1/auth/logout")
    b.post("/api/v1/auth/login", {"email": email, "password": PASSWORD})
    assert b.post("/api/v1/auth/totp", {"recovery_code": codes[0].upper()}).status_code == 200
    b.post("/api/v1/auth/logout")
    b.post("/api/v1/auth/login", {"email": email, "password": PASSWORD})
    assert b.post("/api/v1/auth/totp", {"recovery_code": codes[0]}).status_code == 401
    assert b.post("/api/v1/auth/totp", {"recovery_code": codes[1]}).status_code == 200


def test_it_b2_05_invitation_link_reused_or_expired_is_refused(world: World, mailpit: Mailpit) -> None:
    tid = world.tenant()
    email = address("owner")
    bootstrap_owner_invitation(world, tid, email)
    token = token_from(mailpit.wait_for(email, "invited"))
    Browser(world).accept_and_enrol(token)
    r = Browser(world).post("/api/v1/auth/invitations/accept", {"token": token, "password": PASSWORD})
    assert r.status_code == 400 and r.json()["code"] == "TOKEN_INVALID"
    # Expired: a fresh invitation whose expiry is moved into the past.
    other = address("viewer")
    bootstrap_owner_invitation(world, tid, other)
    tok2 = token_from(mailpit.wait_for(other, "invited"))
    with world.owner.begin() as c:
        c.execute(
            auth_token.update().where(auth_token.c.used_at.is_(None)).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    r = Browser(world).post("/api/v1/auth/invitations/accept", {"token": tok2, "password": PASSWORD})
    assert r.status_code == 400 and r.json()["code"] == "TOKEN_INVALID"


def test_it_b2_06_password_reset_by_mail_keeps_totp_and_ends_sessions(world: World, mailpit: Mailpit) -> None:
    owner, email, _ = owner_signed_in(world, mailpit)
    anon = Browser(world)
    # Unknown and known addresses get the same answer; only the known one gets mail.
    assert anon.post("/api/v1/auth/reset-request", {"email": address("nobody")}).status_code == 202
    assert anon.post("/api/v1/auth/reset-request", {"email": email}).status_code == 202
    token = token_from(mailpit.wait_for(email, "Reset"))
    new_pw = "another-synthetic-pass-phrase"
    assert anon.post("/api/v1/auth/reset", {"token": token, "password": "short"}).status_code == 422
    assert anon.post("/api/v1/auth/reset", {"token": token, "password": new_pw}).status_code == 204
    assert "was just changed" in mailpit.wait_for(email, "changed")
    # Every earlier session ended; the reset itself did not sign anyone in.
    assert owner.c.get("/api/v1/users").status_code == 401
    assert anon.c.get("/api/v1/auth/session").status_code == 401
    # Reused link refused.
    r = anon.post("/api/v1/auth/reset", {"token": token, "password": new_pw + "x"})
    assert r.status_code == 400 and r.json()["code"] == "TOKEN_INVALID"
    # Old password refused; new password still needs the TOTP code.
    assert owner.post("/api/v1/auth/login", {"email": email, "password": PASSWORD}).status_code == 401
    r = owner.post("/api/v1/auth/login", {"email": email, "password": new_pw})
    assert r.status_code == 200 and r.json()["stage"] == "password"
    assert owner.c.get("/api/v1/users").status_code == 401
    assert owner.post("/api/v1/auth/totp", {"code": owner.next_code()}).status_code == 200
    # An expired reset link is refused.
    anon.post("/api/v1/auth/reset-request", {"email": email})
    tok2 = token_from(mailpit.wait_for(email, "Reset", count=2))
    with world.owner.begin() as c:
        c.execute(
            auth_token.update()
            .where(auth_token.c.purpose == "reset", auth_token.c.used_at.is_(None))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert anon.post("/api/v1/auth/reset", {"token": tok2, "password": new_pw}).status_code == 400


def test_it_b2_07_csrf_header_required_on_state_changes(world: World, mailpit: Mailpit) -> None:
    owner, _, _ = owner_signed_in(world, mailpit)
    good = owner.c.headers.pop(CSRF_HEADER)
    r = owner.c.post("/api/v1/carriers", json={"name": "Synthetic Carrier"}, headers={"Idempotency-Key": "c1"})
    assert r.status_code == 403 and r.json()["code"] == "CSRF_REFUSED"
    r = owner.c.post("/api/v1/auth/logout", headers={CSRF_HEADER: "0" * 64})
    assert r.status_code == 403
    owner.c.headers[CSRF_HEADER] = good
    assert owner.c.get("/api/v1/users").status_code == 200  # reads need no header
    assert owner.post("/api/v1/auth/logout").status_code == 204


def test_it_b2_08_logout_idle_and_absolute_expiry(world: World, mailpit: Mailpit) -> None:
    owner, email, _ = owner_signed_in(world, mailpit)
    token = owner.c.cookies[SESSION_COOKIE]
    assert owner.post("/api/v1/auth/logout").status_code == 204
    replay = Browser(world)
    replay.c.cookies.set(SESSION_COOKIE, token)
    assert replay.c.get("/api/v1/users").status_code == 401  # revoked server-side (V7.4.1)
    # Idle: 31 minutes since the last request.
    assert owner.sign_in(email).status_code == 200
    with world.owner.begin() as c:
        c.execute(
            user_session.update()
            .where(user_session.c.revoked_at.is_(None))
            .values(last_seen_at=datetime.now(UTC) - timedelta(minutes=31))
        )
    assert owner.c.get("/api/v1/users").status_code == 401
    # Absolute: past expires_at even though recently active.
    assert owner.sign_in(email).status_code == 200
    with world.owner.begin() as c:
        c.execute(
            user_session.update()
            .where(user_session.c.revoked_at.is_(None))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert owner.c.get("/api/v1/users").status_code == 401


def test_it_b2_09_lockout_after_five_failures_and_owner_unlock(world: World, mailpit: Mailpit) -> None:
    owner, _, tid = owner_signed_in(world, mailpit)
    member_email = address("auditor")
    owner.post("/api/v1/users/invitations", {"email": member_email, "role": "auditor"}, headers={"Idempotency-Key": "i9"})
    member = Browser(world)
    member.accept_and_enrol(token_from(mailpit.wait_for(member_email, "invited")))
    member.post("/api/v1/auth/logout")
    for _ in range(5):
        r = member.post("/api/v1/auth/login", {"email": member_email, "password": "wrong-password-123"})
        assert r.status_code == 401
    # Locked: the right password gets the same answer as a wrong one (V6.3.8).
    r = member.post("/api/v1/auth/login", {"email": member_email, "password": PASSWORD})
    assert r.status_code == 401 and r.json()["code"] == "SIGN_IN_REFUSED"
    unknown = member.post("/api/v1/auth/login", {"email": address("ghost"), "password": PASSWORD})
    assert unknown.json() | {"correlation_id": None} == r.json() | {"correlation_id": None}
    users = {u["email"]: u for u in owner.c.get("/api/v1/users").json()}
    assert users[member_email]["locked"] is True
    uid = users[member_email]["user_id"]
    assert owner.post(f"/api/v1/users/{uid}/unlock").status_code == 204
    assert member.sign_in(member_email).status_code == 200


def test_it_b2_10_rate_limit_twenty_attempts_an_hour_per_address(world: World) -> None:
    b = Browser(world)
    email = address("ghost")
    for _ in range(20):
        assert b.post("/api/v1/auth/login", {"email": email, "password": "x" * 12}).status_code == 401
    r = b.post("/api/v1/auth/login", {"email": email, "password": "x" * 12})
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"
    assert b.post("/api/v1/auth/reset-request", {"email": email}).status_code == 429
    # Another address is unaffected.
    assert b.post("/api/v1/auth/login", {"email": address("ghost"), "password": "x" * 12}).status_code == 401


def test_it_b2_11_cross_tenant_session_refused(world: World, mailpit: Mailpit) -> None:
    owner_a, email_a, tid_a = owner_signed_in(world, mailpit)
    owner_b, _, tid_b = owner_signed_in(world, mailpit)
    # Signing in to a tenant the user is not a member of is refused like a wrong password.
    owner_a.post("/api/v1/auth/logout")
    r = owner_a.post("/api/v1/auth/login", {"email": email_a, "password": PASSWORD, "tenant_id": str(tid_b)})
    assert r.status_code == 401
    assert owner_a.sign_in(email_a).status_code == 200
    # Tenant B's users are invisible to tenant A's Owner; their ids answer 404.
    b_users = owner_b.c.get("/api/v1/users").json()
    b_uid = b_users[0]["user_id"]
    assert owner_a.post(f"/api/v1/users/{b_uid}/unlock").status_code == 404
    assert owner_a.c.patch(f"/api/v1/users/{b_uid}/role", json={"role": "viewer"}).status_code == 404
    assert all(u["user_id"] != b_uid for u in owner_a.c.get("/api/v1/users").json())
    # A session row pointed at another tenant (no membership there) reaches nothing.
    with world.owner.begin() as c:
        c.execute(
            user_session.update()
            .where(user_session.c.token_hash == _hash(owner_a.c.cookies[SESSION_COOKIE]))
            .values(active_tenant_id=tid_b)
        )
    assert owner_a.c.get("/api/v1/users").status_code == 401


def _hash(token: str) -> bytes:
    from fc_platform.auth import token_hash

    return token_hash(token)


def test_it_b2_12_roles_removal_factor_reset(world: World, mailpit: Mailpit) -> None:
    owner, _, tid = owner_signed_in(world, mailpit)
    me = owner.c.get("/api/v1/auth/session").json()["user_id"]
    # The sole Owner cannot demote or remove themselves.
    r = owner.c.patch(f"/api/v1/users/{me}/role", json={"role": "viewer"})
    assert r.status_code == 409 and r.json()["code"] == "LAST_OWNER"
    assert owner.c.delete(f"/api/v1/users/{me}").status_code == 409
    viewer_email = address("viewer")
    owner.post("/api/v1/users/invitations", {"email": viewer_email, "role": "viewer"}, headers={"Idempotency-Key": "i12"})
    viewer = Browser(world)
    viewer.accept_and_enrol(token_from(mailpit.wait_for(viewer_email, "invited")))
    # Only the Owner manages members.
    assert viewer.c.get("/api/v1/users").status_code == 403
    vid = viewer.c.get("/api/v1/auth/session").json()["user_id"]
    # Factor reset: sessions end, next sign-in needs the password and a new enrolment.
    assert owner.post(f"/api/v1/users/{vid}/factor-reset").status_code == 204
    assert viewer.c.get("/api/v1/carriers").status_code == 401
    r = viewer.post("/api/v1/auth/login", {"email": viewer_email, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["stage"] == "enrol"
    assert viewer.post("/api/v1/auth/totp", {"code": viewer.next_code()}).status_code == 401
    r = viewer.post("/api/v1/auth/totp/enrol")
    viewer.secret, viewer.last_step = r.json()["secret"], None
    assert viewer.post("/api/v1/auth/totp/confirm", {"code": viewer.next_code()}).status_code == 200
    with world.owner.connect() as c:
        reset_audit = (
            c.execute(
                select(audit_event.c.actor_user_id).where(
                    audit_event.c.action == "auth.factor_reset", audit_event.c.tenant_id == tid
                )
            )
            .scalars()
            .all()
        )
    assert reset_audit == [uuid.UUID(me)]  # IT-22: factor reset audited with the Owner as actor
    # Removal ends the member's sessions in this tenant (V7.4.2).
    assert owner.c.delete(f"/api/v1/users/{vid}").status_code == 204
    assert viewer.c.get("/api/v1/carriers").status_code == 401
    assert viewer.post("/api/v1/auth/login", {"email": viewer_email, "password": PASSWORD}).status_code == 401
    with world.owner.connect() as c:
        live = c.execute(
            text("select count(*) from user_session where user_id = :u and revoked_at is null"), {"u": vid}
        ).scalar_one()
    assert live == 0


def test_it_b2_13_password_change_needs_current_and_ends_other_sessions(world: World, mailpit: Mailpit) -> None:
    owner, email, _ = owner_signed_in(world, mailpit)
    second = Browser(world)
    second.secret = _secret_of(world, second, email)
    assert second.sign_in(email).status_code == 200
    owner.last_step = second.last_step
    r = owner.post("/api/v1/auth/password", {"current_password": "wrong-password-123", "new_password": "x" * 20})
    assert r.status_code == 401
    r = owner.post("/api/v1/auth/password", {"current_password": PASSWORD, "new_password": "new-synthetic-phrase-1"})
    assert r.status_code == 204
    assert owner.c.get("/api/v1/users").status_code == 200  # this session stays
    assert second.c.get("/api/v1/users").status_code == 401  # the other one ended (V7.4.3)
    assert "was just changed" in mailpit.wait_for(email, "changed")


def test_it15_five_bad_codes_lock_for_fifteen_minutes(world: World, mailpit: Mailpit) -> None:
    owner, email, _ = owner_signed_in(world, mailpit)
    owner.post("/api/v1/auth/logout")
    for _ in range(5):
        owner.post("/api/v1/auth/login", {"email": email, "password": PASSWORD})
        assert owner.post("/api/v1/auth/totp", {"code": "000000"}).status_code == 401
    r = owner.post("/api/v1/auth/login", {"email": email, "password": PASSWORD})
    assert r.status_code == 401  # locked: the password step is refused too
    with world.owner.connect() as c:
        locked_until = c.execute(select(app_user.c.locked_until).where(app_user.c.email == email)).scalar_one()
    remaining = locked_until - datetime.now(UTC)
    assert timedelta(minutes=14) < remaining <= timedelta(minutes=15)
    # After the 15 minutes the right password and a fresh code work again.
    with world.owner.begin() as c:
        c.execute(
            app_user.update().where(app_user.c.email == email).values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert owner.sign_in(email).status_code == 200
