"""UT-B2-01 .. UT-B2-06: credential primitives (RFC 6238 vectors, password policy, secrets at rest,
anti-forgery value, recovery codes, storage-key tenant parsing, settings for SMTP and S3)."""

from __future__ import annotations

import base64
import uuid

import pytest
from cryptography.exceptions import InvalidTag

from fc_platform import auth
from fc_platform.settings import Settings, SettingsError
from fc_platform.storage import storage_key, tenant_of_key

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize(
    ("epoch", "expected"),
    # RFC 6238 appendix B, SHA-1, last six digits of the eight-digit values.
    [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"), (2000000000, "279037")],
)
def test_ut_b2_01_totp_matches_rfc6238_vectors(epoch: int, expected: str) -> None:
    assert auth.totp_code(RFC_SECRET, auth.totp_step(epoch)) == expected


def test_ut_b2_01_totp_step_is_usable_once_and_window_is_one_step() -> None:
    step = auth.totp_step(1111111111)
    code = auth.totp_code(RFC_SECRET, step)
    assert auth.verify_totp(RFC_SECRET, code, 1111111111, None) == step
    assert auth.verify_totp(RFC_SECRET, code, 1111111111, step) is None  # replay refused
    assert auth.verify_totp(RFC_SECRET, code, 1111111111 + 30, None) == step  # one step of drift
    assert auth.verify_totp(RFC_SECRET, code, 1111111111 + 61, None) is None
    assert auth.verify_totp(RFC_SECRET, "12345", 1111111111, None) is None
    assert auth.verify_totp(RFC_SECRET, "abcdef", 1111111111, None) is None


def test_ut_b2_02_password_policy_and_hash() -> None:
    with pytest.raises(auth.PasswordPolicyError):
        auth.hash_password("eleven-char")
    with pytest.raises(auth.PasswordPolicyError):
        auth.hash_password("x" * 129)
    h = auth.hash_password("  any characters ü 12  ")
    assert h.startswith("$argon2id$")
    assert auth.verify_password(h, "  any characters ü 12  ")
    assert not auth.verify_password(h, "any characters ü 12")  # no trimming (V6.2.8)
    assert not auth.verify_password(None, "whatever-password")
    assert not auth.verify_password("not-a-hash", "whatever-password")
    assert auth.verify_password(auth.hash_password("p" * 64), "p" * 64)  # 64 allowed (V6.2.9)


def test_ut_b2_03_secret_at_rest_is_bound_to_its_user() -> None:
    key = "22" * 32
    uid = uuid.uuid4()
    blob = auth.encrypt_secret("JBSWY3DPEHPK3PXP", key, uid.bytes)
    assert b"JBSWY3DPEHPK3PXP" not in blob
    assert auth.decrypt_secret(blob, key, uid.bytes) == "JBSWY3DPEHPK3PXP"
    with pytest.raises(InvalidTag):
        auth.decrypt_secret(blob, key, uuid.uuid4().bytes)
    assert auth.encrypt_secret("same", key, uid.bytes) != auth.encrypt_secret("same", key, uid.bytes)


def test_ut_b2_04_csrf_and_recovery_codes() -> None:
    t = auth.new_token()
    v = auth.csrf_token(t, "k" * 32)
    assert auth.csrf_matches(t, v, "k" * 32)
    assert not auth.csrf_matches(auth.new_token(), v, "k" * 32)
    assert not auth.csrf_matches(t, None, "k" * 32)
    codes = auth.new_recovery_codes()
    assert len(codes) == 10 and len(set(codes)) == 10
    assert all(len(c.replace("-", "")) == 20 for c in codes)  # 80 bits each
    assert auth.recovery_code_hash(codes[0].upper()) == auth.recovery_code_hash(f" {codes[0]} ")


def test_ut_b2_05_tenant_of_key_accepts_only_built_keys() -> None:
    tid = uuid.uuid4()
    assert tenant_of_key(storage_key(tid, "invoice", "email")) == tid
    for bad in ("t/x/invoice/upload/y", f"t/{tid}/../upload/{uuid.uuid4()}", f"s/{tid}/invoice/upload/{uuid.uuid4()}", "t/a/b"):
        with pytest.raises(ValueError):
            tenant_of_key(bad)


BASE = {
    "FC_ENV": "test",
    "FC_DATABASE_URL": "postgresql+psycopg://x@localhost/y",
    "FC_MIGRATION_DATABASE_URL": "postgresql+psycopg://x@localhost/y",
    "FC_PUBLIC_BASE_URL": "http://localhost:8102",
    "FC_SIGNING_KEY": "s" * 32,
    "FC_DATA_KEY": "33" * 32,
}


def test_ut_b2_06_settings_for_mail_and_storage() -> None:
    s = Settings.from_env(BASE)
    assert (s.smtp_host, s.smtp_port, s.smtp_starttls, s.storage_backend) == ("127.0.0.1", 1025, False, "local")
    with pytest.raises(SettingsError, match="FC_DATA_KEY"):
        Settings.from_env({**BASE, "FC_DATA_KEY": "short"})
    with pytest.raises(SettingsError, match="FC_S3_BUCKET"):
        Settings.from_env({**BASE, "FC_STORAGE_BACKEND": "s3"})
    with pytest.raises(SettingsError, match="true or false"):
        Settings.from_env({**BASE, "FC_SMTP_STARTTLS": "yes"})
    s3 = {**BASE, "FC_STORAGE_BACKEND": "s3", "FC_S3_BUCKET": "b", "FC_S3_ACCESS_KEY": "a", "FC_S3_SECRET_KEY": "k"}
    with pytest.raises(SettingsError, match="STARTTLS"):
        Settings.from_env({**s3, "FC_ENV": "prod"})
    assert Settings.from_env({**s3, "FC_ENV": "prod", "FC_SMTP_STARTTLS": "true"}).smtp_starttls is True
