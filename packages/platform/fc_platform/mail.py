"""Outgoing mail to users only (TRD 3: password reset, invitations, reminders; B2).

FreightCheck never mails a carrier. Locally SMTP goes to Mailpit (127.0.0.1:1025, no auth);
a real provider later uses the same interface with STARTTLS and credentials from settings.
Logs carry the message kind and a message id, never the address or the body (R-12).
"""

from __future__ import annotations

import logging
import queue
import smtplib
import threading
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Protocol

from fc_platform.logging import log
from fc_platform.settings import Settings

logger = logging.getLogger("fc_platform.mail")


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str, *, kind: str) -> str: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def send(self, to: str, subject: str, body: str, *, kind: str) -> str:
        msg = EmailMessage()
        msg["From"] = self.s.mail_from
        msg["To"] = to
        msg["Subject"] = subject
        msg_id = make_msgid(domain="freightcheck.example")
        msg["Message-ID"] = msg_id
        msg["X-FC-Kind"] = kind
        msg.set_content(body)
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=10) as smtp:
            if self.s.smtp_starttls:
                smtp.starttls()
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password)
            smtp.send_message(msg)
        log(logger, "mail.sent", kind=kind, message_id=msg_id)
        return msg_id


@dataclass
class FakeMailer:
    """Collects messages in memory for unit tests."""

    sent: list[tuple[str, str, str, str]] = field(default_factory=list)

    def send(self, to: str, subject: str, body: str, *, kind: str) -> str:
        self.sent.append((to, subject, body, kind))
        return f"<fake-{len(self.sent)}@freightcheck.example>"


def mailer_from_settings(settings: Settings) -> Mailer:
    return SmtpMailer(settings)


class Outbox:
    """Sends mail on a background thread so the caller's response neither waits for SMTP nor
    depends on it (B2-S03: a reset request answers the same, in the same time, whether or not
    the address exists and whether or not mail is up). A failed send is logged by kind only.
    Messages are held in memory: a crash loses unsent ones and the user asks again."""

    def __init__(self) -> None:
        self._q: queue.Queue[tuple[Mailer, str, str, str, str]] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def put(self, mailer: Mailer, to: str, subject: str, body: str, *, kind: str) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="fc-outbox", daemon=True)
                self._thread.start()
        self._q.put((mailer, to, subject, body, kind))

    def _run(self) -> None:
        while True:
            mailer, to, subject, body, kind = self._q.get()
            try:
                mailer.send(to, subject, body, kind=kind)
            except Exception as exc:  # noqa: BLE001 - one bad message must not stop the outbox
                logger.error("mail.failed", extra={"fields": {"kind": kind, "error": type(exc).__name__}})
            finally:
                self._q.task_done()

    def join(self) -> None:
        """Wait until every queued message was attempted (tests and shutdown)."""
        self._q.join()


OUTBOX = Outbox()
