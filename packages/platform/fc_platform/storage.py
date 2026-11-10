"""Storage keys, signed URLs and the object-storage interface (T-2.2.5, R-13, R-16).

Keys are built only here: `t/{tenant}/{purpose}/{source}/{uuid}`. The user's file name
never appears in a key. Signed URLs carry only the opaque key and an expiry and always
use PUBLIC_BASE_URL as host.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

PURPOSES = frozenset(
    {
        "invoice",
        "bol",
        "rate_confirmation",
        "delivery_receipt",
        "weight_certificate",
        "rate_document",
        "carrier_response",
        "settlement_evidence",
        "ap_export",
    }
)
SOURCES = frozenset({"email", "upload", "import"})
SIGNED_URL_SECONDS = 240  # under 5 minutes


def storage_key(tenant_id: uuid.UUID | str, purpose: str, source: str) -> str:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown purpose {purpose}")
    if source not in SOURCES:
        raise ValueError(f"unknown source {source}")
    tid = uuid.UUID(str(tenant_id))
    return f"t/{tid}/{purpose}/{source}/{uuid.uuid4()}"


def sign(key: str, expires_epoch: int, secret: str) -> str:
    msg = f"{key}|{expires_epoch}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def signed_url(public_base_url: str, key: str, now_epoch: int, secret: str) -> str:
    exp = now_epoch + SIGNED_URL_SECONDS
    sig = sign(key, exp, secret)
    return f"{public_base_url.rstrip('/')}/files/raw?k={quote(key, safe='')}&e={exp}&s={sig}"


def verify(key: str, expires_epoch: int, signature: str, now_epoch: int, secret: str) -> bool:
    if now_epoch > expires_epoch:
        return False
    return hmac.compare_digest(sign(key, expires_epoch, secret), signature)


class ObjectStorage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...


class LocalFakeStorage:
    """Fake object storage on the local disk; stands in for S3 (no real provider in B1)."""

    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if ".." in key.split("/"):
            raise ValueError("bad key")
        return self.root / key

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class Scanner(Protocol):
    def scan(self, data: bytes) -> str: ...  # "clean" or "infected"


class FakeScanner:
    """Stands in for ClamAV. Flags the EICAR test string only."""

    EICAR = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"

    def scan(self, data: bytes) -> str:
        return "infected" if self.EICAR in data else "clean"


MAX_BYTES = 20 * 1024 * 1024


def sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    try:
        text = data[:4096].decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "," in text and "\x00" not in text:
        return "text/csv"
    return None
