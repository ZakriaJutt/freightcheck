"""B2 test support: read sign-in mail from the local Mailpit API, walk the real sign-in flow,
and reach local MinIO with the keys from the git-ignored .env.local."""

from __future__ import annotations

import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from conftest import TEST_ENV, World
from fastapi.testclient import TestClient

from fc_api.core import CSRF_HEADER
from fc_db.identity import INVITE_BODY, INVITE_SUBJECT, invitation_link, issue_invitation
from fc_platform.auth import totp_code, totp_step
from fc_platform.mail import SmtpMailer
from fc_platform.settings import get_settings

MAILPIT = "http://127.0.0.1:8025/api/v1"
REPO = Path(__file__).resolve().parents[3]
PASSWORD = "synthetic-pass-phrase-for-tests"


def address(role: str) -> str:
    """A unique synthetic address per test, so parallel users of the shared Mailpit never collide."""
    return f"{role}-{secrets.token_hex(6)}@b2.freightcheck.example"


class Mailpit:
    def __init__(self) -> None:
        self.http = httpx.Client(base_url=MAILPIT, timeout=10)
        self.seen: list[str] = []

    def messages_to(self, to: str) -> list[dict[str, Any]]:
        r = self.http.get("/search", params={"query": f'to:"{to}"'})
        r.raise_for_status()
        msgs: list[dict[str, Any]] = r.json().get("messages") or []
        self.seen += [m["ID"] for m in msgs]
        return msgs

    def wait_for(self, to: str, subject_part: str, count: int = 1) -> str:
        """Text of the newest message to `to` whose subject contains `subject_part`."""
        for _ in range(50):
            msgs = [m for m in self.messages_to(to) if subject_part in m["Subject"]]
            if len(msgs) >= count:
                newest = max(msgs, key=lambda m: m["Created"])
                body = self.http.get(f"/message/{newest['ID']}")
                body.raise_for_status()
                text: str = body.json()["Text"]
                return text
            time.sleep(0.1)
        raise AssertionError(f"no mail '{subject_part}' to {to}")

    def cleanup(self) -> None:
        """Delete only the messages these tests produced; Mailpit is shared with other repos."""
        if self.seen:
            self.http.request("DELETE", "/messages", json={"IDs": sorted(set(self.seen))})
        self.http.close()


def token_from(text: str) -> str:
    m = re.search(r"#token=([A-Za-z0-9_\-]+)", text)
    assert m, "no token link in the message"
    return m.group(1)


def bootstrap_owner_invitation(world: World, tenant_id: uuid.UUID, email: str) -> None:
    """How the first Owner is invited (by FreightCheck staff; tools/seed_dev.py does the same)."""
    with world.owner.begin() as c:
        inv = issue_invitation(c, tenant_id, email, "owner", None)
    body = INVITE_BODY.format(
        tenant_name="Synthetic Shipper", role="owner", link=invitation_link("https://testserver", inv.token)
    )
    SmtpMailer(get_settings()).send(email, INVITE_SUBJECT, body, kind="invitation")


class Clock:
    """Server clock for TOTP checks, moved forward by whole steps when a test needs a fresh code
    sooner than 30 real seconds (installed by the `server_clock` fixture)."""

    offset = 0.0

    @classmethod
    def epoch(cls) -> float:
        return time.time() + cls.offset


class Browser:
    """A client that holds the session cookie and the anti-forgery token like a browser app."""

    def __init__(self, world: World) -> None:
        self.c = TestClient(world.app, base_url="https://testserver", raise_server_exceptions=True)
        self.secret: str | None = None
        self.last_step: int | None = None

    def remember(self, r: httpx.Response) -> httpx.Response:
        if r.status_code == 200 and "csrf_token" in r.json():
            self.c.headers[CSRF_HEADER] = r.json()["csrf_token"]
        return r

    def post(self, path: str, json: Any = None, **kw: Any) -> httpx.Response:
        return self.remember(self.c.post(path, json=json, **kw))

    def next_code(self) -> str:
        """The authenticator code for a step after the last one used (each step works once)."""
        assert self.secret
        step = totp_step(Clock.epoch())
        if self.last_step is not None and step <= self.last_step:
            Clock.offset += (self.last_step + 1 - step) * 30
            step = self.last_step + 1
        self.last_step = step
        return totp_code(self.secret, step)

    def accept_and_enrol(self, token: str, password: str = PASSWORD) -> list[str]:
        r = self.post("/api/v1/auth/invitations/accept", {"token": token, "password": password})
        assert r.status_code == 200 and r.json()["stage"] == "enrol", r.text
        # IT-22: no tenant data before the second factor is enrolled.
        assert self.c.get("/api/v1/carriers").status_code == 401
        r = self.post("/api/v1/auth/totp/enrol")
        assert r.status_code == 200, r.text
        self.secret = r.json()["secret"]
        assert r.json()["otpauth_uri"].startswith("otpauth://totp/")
        r = self.post("/api/v1/auth/totp/confirm", {"code": self.next_code()})
        assert r.status_code == 200 and r.json()["stage"] == "full", r.text
        codes: list[str] = r.json()["recovery_codes"]
        return codes

    def sign_in(self, email: str, password: str = PASSWORD, **extra: Any) -> httpx.Response:
        r = self.post("/api/v1/auth/login", {"email": email, "password": password, **extra})
        if r.status_code != 200:
            return r
        assert r.json()["stage"] == "password"
        return self.post("/api/v1/auth/totp", {"code": self.next_code()})


def minio_env() -> dict[str, str]:
    """FC_S3_* from the git-ignored .env.local; the keys are never written into the repository."""
    env: dict[str, str] = {}
    path = REPO / ".env.local"
    for line in path.read_text().splitlines() if path.exists() else []:
        k, _, v = line.partition("=")
        if k.startswith("FC_S3_"):
            env[k] = v
    assert env.get("FC_S3_ACCESS_KEY") and env.get("FC_S3_SECRET_KEY"), "put the local MinIO keys in .env.local"
    return {**env, "FC_STORAGE_BACKEND": "s3"}


__all__ = ["TEST_ENV"]
