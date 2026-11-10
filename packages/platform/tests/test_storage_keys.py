"""UT-13 storage keys; signed-URL host and expiry (part of IT-11 logic, no proxy)."""

from __future__ import annotations

import uuid

import pytest

from fc_platform.storage import SIGNED_URL_SECONDS, signed_url, storage_key, verify

TENANT = uuid.UUID("00000000-0000-4000-8000-000000000001")


def test_ut13_key_shape_has_no_user_filename_and_two_calls_differ() -> None:
    a = storage_key(TENANT, "invoice", "upload")
    b = storage_key(TENANT, "invoice", "upload")
    assert a != b
    prefix, tid, purpose, source, rand = a.split("/")
    assert (prefix, tid, purpose, source) == ("t", str(TENANT), "invoice", "upload")
    assert uuid.UUID(rand).version == 4
    assert "invoice.pdf" not in a


def test_ut13_unknown_purpose_or_source_refused() -> None:
    with pytest.raises(ValueError):
        storage_key(TENANT, "../etc", "upload")
    with pytest.raises(ValueError):
        storage_key(TENANT, "invoice", "ftp")


def test_signed_url_uses_public_base_url_and_expires_under_5_minutes() -> None:
    key = storage_key(TENANT, "bol", "email")
    url = signed_url("https://app.freightcheck.example/", key, 1_000, "k" * 32)
    assert url.startswith("https://app.freightcheck.example/files/raw?")
    sig = url.split("&s=")[1]
    assert SIGNED_URL_SECONDS < 300
    assert verify(key, 1_000 + SIGNED_URL_SECONDS, sig, 1_100, "k" * 32)
    assert not verify(key, 1_000 + SIGNED_URL_SECONDS, sig, 1_000 + SIGNED_URL_SECONDS + 1, "k" * 32)
    assert not verify(key + "x", 1_000 + SIGNED_URL_SECONDS, sig, 1_100, "k" * 32)
