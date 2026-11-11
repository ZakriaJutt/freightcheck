"""Storage keys, signed URLs and the object-storage interface (T-2.2.5, R-13, R-16; S3 backend B2).

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

from fc_platform.settings import Settings

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
    def delete(self, key: str) -> None: ...


def tenant_of_key(key: str) -> uuid.UUID:
    """The tenant a key belongs to; raises ValueError for anything not built by storage_key."""
    parts = key.split("/")
    if len(parts) != 5 or parts[0] != "t" or parts[2] not in PURPOSES or parts[3] not in SOURCES:
        raise ValueError("not a storage key")
    uuid.UUID(parts[4])
    return uuid.UUID(parts[1])


class S3Storage:
    """S3 API client (B2): MinIO locally, a managed private bucket later. Objects are never
    public; reads go through the API's signed `/files/raw` link only (TRD 8.5)."""

    def __init__(self, endpoint: str, region: str, bucket: str, access_key: str, secret_key: str) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
        )

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="application/octet-stream")

    def get(self, key: str) -> bytes:
        body: bytes = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return body

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def keys(self, prefix: str) -> list[str]:
        out: list[str] = []
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            out += [o["Key"] for o in page.get("Contents", []) if "Key" in o]
        return out


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

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def storage_from_settings(settings: Settings) -> ObjectStorage:
    if settings.storage_backend == "s3":
        return S3Storage(
            settings.s3_endpoint, settings.s3_region, settings.s3_bucket, settings.s3_access_key, settings.s3_secret_key
        )
    return LocalFakeStorage(settings.storage_dir)


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
