"""Outgoing mail to users only (TRD 3: password reset, invitations, reminders; B2).

FreightCheck never mails a carrier. Locally SMTP goes to Mailpit (127.0.0.1:1025, no auth);
a real provider later uses the same interface with STARTTLS and credentials from settings.
Logs carry the message kind and a message id, never the address or the body (R-12).
"""

from __future__ import annotations

import logging
import smtplib
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
