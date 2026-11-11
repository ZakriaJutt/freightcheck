"""Regression tests for the B2 security review, round 1 (B2-S01 .. B2-S07). Each case that
failed in `_coordination/review/freightcheck-b2-sec_attack.py` at 63a9091 is kept here, adapted
to the coordinator's rulings of 2026-11-11 where they change the expected answer."""

from __future__ import annotations

import io
import logging
import statistics
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from b2_support import PASSWORD, Browser, Clock, Mailpit, address, token_from
from conftest import World
from sqlalchemy import func, select

from fc_db.tables import app_user, audit_event, auth_attempt
from fc_platform.logging import JsonFormatter
from fc_platform.mail import OUTBOX


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


def owner_of_new_tenant(world: World, mailpit: Mailpit) -> tuple[Browser, str, uuid.UUID]:
    from b2_support import bootstrap_owner_invitation

    tid = world.tenant()
    email = address("owner")
    bootstrap_owner_invitation(world, tid, email)
    b = Browser(world)
    b.accept_and_enrol(token_from(mailpit.wait_for(email, "invited")))
    return b, email, tid


def user_row(world: World, email: str) -> Any:
    with world.owner.connect() as c:
        return c.execute(select(app_user).where(app_user.c.email == email)).one()


def invite(owner: Browser, email: str, role: str) -> httpx.Response:
    return owner.post("/api/v1/users/invitations", {"email": email, "role": role}, headers={"Idempotency-Key": uuid.uuid4().hex})


# ------------------------------------------------------------------ B2-S01 re-authentication limits


def test_b2_s01_recovery_codes_wrong_codes_count_toward_lockout(world: World, mailpit: Mailpit) -> None:
    """Reviewer a08: 30 wrong codes at /auth/recovery-codes were all 401 with failed_count 0."""
    owner, email, _ = owner_of_new_tenant(world, mailpit)
    statuses = [owner.post("/api/v1/auth/recovery-codes", {"code": f"{i:06d}"}).status_code for i in range(6)]
    u = user_row(world, email)
    assert statuses[:5] == [401] * 5 and u.locked_until is not None  # locked after five, as at sign-in
    # Locked: even the right code is refused, and no new codes are issued.
    r = owner.post("/api/v1/auth/recovery-codes", {"code": owner.next_code()})
    assert r.status_code == 401 and "recovery_codes" not in r.json()


def test_b2_s01_recovery_codes_need_fresh_code_and_mail_a_notice(world: World, mailpit: Mailpit) -> None:
    owner, email, tid = owner_of_new_tenant(world, mailpit)
    r = owner.post("/api/v1/auth/recovery-codes", {"code": owner.next_code()})
    assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 10
    assert "recovery codes were just issued" in mailpit.wait_for(email, "recovery codes")
    with world.owner.connect() as c:
        assert (
            c.execute(
                select(func.count())
                .select_from(audit_event)
                .where(audit_event.c.action == "auth.recovery_codes", audit_event.c.tenant_id == tid)
            ).scalar_one()
            == 1
        )


def test_b2_s01_password_change_wrong_passwords_count_toward_lockout(world: World, mailpit: Mailpit) -> None:
    """Reviewer a09: 25 wrong current passwords at /auth/password were all 401 with failed_count 0."""
    owner, email, _ = owner_of_new_tenant(world, mailpit)
    for i in range(5):
        r = owner.post("/api/v1/auth/password", {"current_password": f"guess-{i:04d}-xxxxxx", "new_password": "z" * 16})
        assert r.status_code == 401
    assert user_row(world, email).locked_until is not None
    r = owner.post("/api/v1/auth/password", {"current_password": PASSWORD, "new_password": "z" * 16, "code": owner.next_code()})
    assert r.status_code == 401  # locked


def test_b2_s01_password_change_needs_a_fresh_totp_code(world: World, mailpit: Mailpit) -> None:
    owner, email, _ = owner_of_new_tenant(world, mailpit)
    r = owner.post("/api/v1/auth/password", {"current_password": PASSWORD, "new_password": "rotated-pass-phrase-1"})
    assert r.status_code == 401 and user_row(world, email).failed_count == 1
    r = owner.post(
        "/api/v1/auth/password", {"current_password": PASSWORD, "new_password": "rotated-pass-phrase-1", "code": "000000"}
    )
    assert r.status_code == 401
    r = owner.post(
        "/api/v1/auth/password",
        {"current_password": PASSWORD, "new_password": "rotated-pass-phrase-1", "code": owner.next_code()},
    )
    assert r.status_code == 204 and user_row(world, email).failed_count == 0


def test_b2_s01_reauthentication_counts_toward_the_hourly_limit(world: World, mailpit: Mailpit) -> None:
    owner, email, _ = owner_of_new_tenant(world, mailpit)
    with world.owner.begin() as c:
        uid = c.execute(select(app_user.c.id).where(app_user.c.email == email)).scalar_one()
        c.execute(auth_attempt.insert(), [{"email": email, "user_id": uid, "kind": "code", "succeeded": False}] * 20)
    r = owner.post("/api/v1/auth/recovery-codes", {"code": owner.next_code()})
    assert r.status_code == 429


# ------------------------------------------------------------------ B2-S02 factor reset and unlock across tenants


def test_b2_s02_owner_cannot_reset_or_unlock_a_user_of_another_tenant(world: World, mailpit: Mailpit) -> None:
    """Reviewer a18: B's Owner reset the factor that guards U's tenant-A sign-in. Ruling: refused
    when U belongs to another tenant (operator path deferred); removal from B stays allowed."""
    owner_a, email_a, tid_a = owner_of_new_tenant(world, mailpit)
    owner_b, _, _ = owner_of_new_tenant(world, mailpit)
    assert invite(owner_b, email_a, "viewer").status_code == 201
    x = Browser(world)
    r = x.post(
        "/api/v1/auth/invitations/accept", {"token": token_from(mailpit.wait_for(email_a, "invited")), "password": PASSWORD}
    )
    assert r.json()["stage"] == "password"
    uid = user_row(world, email_a).id
    r = owner_b.post(f"/api/v1/users/{uid}/factor-reset")
    assert r.status_code == 409 and r.json()["code"] == "OTHER_TENANTS"
    r = owner_b.post(f"/api/v1/users/{uid}/unlock")
    assert r.status_code == 409 and r.json()["code"] == "OTHER_TENANTS"
    u = user_row(world, email_a)
    assert u.totp_enrolled_at is not None and u.totp_secret_enc is not None
    assert owner_a.c.get("/api/v1/users").status_code == 200  # tenant-A session untouched
    y = Browser(world)
    stage = y.post("/api/v1/auth/login", {"email": email_a, "password": PASSWORD, "tenant_id": str(tid_a)}).json()["stage"]
    assert stage == "password"  # still needs the code, not a password-only enrolment
    assert owner_b.c.delete(f"/api/v1/users/{uid}").status_code == 204
    assert owner_a.c.get("/api/v1/users").status_code == 200


# ------------------------------------------------------------------ B2-S03 reset request enumeration


def _median_ms(fn: Callable[[], Any], n: int) -> float:
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t) * 1000)
    return statistics.median(xs)


def test_b2_s03_reset_request_same_answer_and_timing_for_known_and_unknown(world: World, mailpit: Mailpit) -> None:
    """Reviewer a21: 8.6 ms for a known address vs 2.3 ms unknown (mail sent in the request)."""
    _, email, _ = owner_of_new_tenant(world, mailpit)
    b = Browser(world)
    known = b.post("/api/v1/auth/reset-request", {"email": email})
    unknown = b.post("/api/v1/auth/reset-request", {"email": address("nobody")})
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json()) == (202, {"status": "accepted"})
    t_known = _median_ms(lambda: b.post("/api/v1/auth/reset-request", {"email": email}), 9)
    t_unknown = _median_ms(lambda: b.post("/api/v1/auth/reset-request", {"email": address("nobody")}), 9)
    assert abs(t_known - t_unknown) < max(5.0, 0.25 * t_unknown), (t_known, t_unknown)
    assert "#token=" in mailpit.wait_for(email, "Reset")  # the mail still arrives, after the answer


def test_b2_s03_reset_request_same_answer_when_mail_is_down(world: World, mailpit: Mailpit) -> None:
    """Reviewer a22: with SMTP down a known address got 503, an unknown one 202."""
    _, email, _ = owner_of_new_tenant(world, mailpit)

    class Broken:
        def send(self, *a: Any, **k: Any) -> str:
            raise OSError("smtp down")

    world.app.state.mailer = Broken()
    b = Browser(world)
    known = b.post("/api/v1/auth/reset-request", {"email": email})
    unknown = b.post("/api/v1/auth/reset-request", {"email": address("nobody")})
    OUTBOX.join()
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json()) == (202, {"status": "accepted"})


# ------------------------------------------------------------------ minors


def test_b2_s04_invitation_response_does_not_disclose_an_existing_account(world: World, mailpit: Mailpit) -> None:
    """Reviewer a17: B's Owner learnt A's user's global id from the invitation response."""
    _, email_a, _ = owner_of_new_tenant(world, mailpit)
    owner_b, _, _ = owner_of_new_tenant(world, mailpit)
    r = invite(owner_b, email_a, "viewer")
    assert r.status_code == 201
    assert r.json()["user_id"] is None and str(user_row(world, email_a).id) not in r.text
    fresh = invite(owner_b, address("viewer"), "viewer")
    assert set(fresh.json()) == set(r.json())  # same shape for a new address
    mailpit.wait_for(email_a, "invited")


def test_b2_s05_password_change_retires_open_reset_links(world: World, mailpit: Mailpit) -> None:
    """Reviewer a25: a reset link issued before /auth/password still worked afterwards."""
    owner, email, _ = owner_of_new_tenant(world, mailpit)
    Browser(world).post("/api/v1/auth/reset-request", {"email": email})
    rtok = token_from(mailpit.wait_for(email, "Reset"))
    r = owner.post(
        "/api/v1/auth/password",
        {"current_password": PASSWORD, "new_password": "rotated-pass-phrase-1", "code": owner.next_code()},
    )
    assert r.status_code == 204
    r = Browser(world).post("/api/v1/auth/reset", {"token": rtok, "password": "attacker-pass-phrase"})
    assert r.status_code == 400 and r.json()["code"] == "TOKEN_INVALID"


def test_b2_s06_logs_never_hold_passwords_tokens_codes_or_addresses(world: World, mailpit: Mailpit) -> None:
    """R-12, ASVS V16.2.5: fails if log masking (`FORBIDDEN_FIELDS`) or the ids-only rule regresses."""
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(JsonFormatter())
    logging.getLogger().addHandler(h)
    try:
        owner, email, _ = owner_of_new_tenant(world, mailpit)
        e2 = address("approver")
        invite(owner, e2, "approver")
        inv_tok = token_from(mailpit.wait_for(e2, "invited"))
        b = Browser(world)
        codes = b.accept_and_enrol(inv_tok, password="approver-secret-phrase-77")
        b.post("/api/v1/auth/logout")
        b.post("/api/v1/auth/login", {"email": e2, "password": "approver-secret-phrase-77"})
        b.post("/api/v1/auth/totp", {"code": "999999"})
        b.post("/api/v1/auth/totp", {"recovery_code": codes[1]})
        b.post("/api/v1/auth/password", {"current_password": "wrong-secret-phrase-88", "new_password": "z" * 16})
        Browser(world).post("/api/v1/auth/reset-request", {"email": e2})
        rtok = token_from(mailpit.wait_for(e2, "Reset"))
        OUTBOX.join()
    finally:
        logging.getLogger().removeHandler(h)
    logs = buf.getvalue()
    assert '"event": "auth.sign_in"' in logs and '"event": "mail.sent"' in logs  # the capture worked
    assert b.secret
    for needle in ("approver-secret-phrase-77", "wrong-secret-phrase-88", inv_tok, rtok, b.secret, codes[0], codes[1], e2, email):
        assert needle not in logs, f"log leaks {needle[:6]}..."


def test_b2_s07_hourly_limit_follows_the_account_as_well_as_the_address(world: World, mailpit: Mailpit) -> None:
    """Attempts recorded against the account (any address spelling) count toward its limit."""
    owner, email, _ = owner_of_new_tenant(world, mailpit)
    owner.post("/api/v1/auth/logout")
    with world.owner.begin() as c:
        uid = c.execute(select(app_user.c.id).where(app_user.c.email == email)).scalar_one()
        c.execute(
            auth_attempt.insert(),
            [{"email": "other-spelling@b2.freightcheck.example", "user_id": uid, "kind": "code", "succeeded": False}] * 20,
        )
    r = owner.post("/api/v1/auth/login", {"email": email, "password": PASSWORD})
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"
