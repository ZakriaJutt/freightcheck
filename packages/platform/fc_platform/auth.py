"""Credential primitives for sign-in (B2, TRD 8.1, AD-07): passwords, TOTP, tokens, secrets at rest.

No database access here; `fc_api.auth` composes these with the session tables.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
from urllib.parse import quote

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PASSWORD_MIN = 12  # TRD 8.1 [P]; ASVS V6.2.1
PASSWORD_MAX = 128  # ASVS V6.2.9 asks that at least 64 be allowed
TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6
TOTP_WINDOW = 1  # one step either side for clock drift
RECOVERY_CODE_COUNT = 10

_hasher = PasswordHasher()  # argon2id with the library's current recommended parameters
# Verified against when the address is unknown, so the response time does not reveal it (ASVS V6.3.8).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


class PasswordPolicyError(ValueError):
    pass


def check_password_policy(password: str) -> None:
    """Length only: any characters, no composition rules (ASVS V6.2.1, V6.2.5, V6.2.9)."""
    if len(password) < PASSWORD_MIN:
        raise PasswordPolicyError(f"use at least {PASSWORD_MIN} characters")
    if len(password) > PASSWORD_MAX:
        raise PasswordPolicyError(f"use at most {PASSWORD_MAX} characters")


def hash_password(password: str) -> str:
    check_password_policy(password)
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Exact comparison of what was typed (no trimming or case change, ASVS V6.2.8)."""
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerificationError, InvalidHashError):
        return False


# ------------------------------------------------------------------ tokens


def new_token() -> str:
    """256-bit opaque token from the OS CSPRNG (sessions, invitations, resets; ASVS V7.2.3)."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def csrf_token(session_token: str, signing_key: str) -> str:
    """Per-session anti-forgery value, derived so nothing extra is stored (TRD 8.1, ASVS V3.5.1)."""
    return hmac.new(signing_key.encode(), b"csrf|" + session_token.encode(), hashlib.sha256).hexdigest()


def csrf_matches(session_token: str, presented: str | None, signing_key: str) -> bool:
    return presented is not None and hmac.compare_digest(csrf_token(session_token, signing_key), presented)


def new_recovery_codes(n: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Ten single-use codes of 80 random bits each, shown once (TRD 8.1, ASVS V6.5.1, V6.5.3)."""
    out = []
    for _ in range(n):
        raw = secrets.token_hex(10)
        out.append("-".join(raw[i : i + 5] for i in range(0, 20, 5)))
    return out


def normalise_recovery_code(code: str) -> str:
    return code.strip().lower().replace(" ", "")


def recovery_code_hash(code: str) -> bytes:
    return hashlib.sha256(normalise_recovery_code(code).encode()).digest()


# ------------------------------------------------------------------ TOTP (RFC 6238, HMAC-SHA1, 6 digits, 30 s)


def new_totp_secret() -> str:
    """160-bit seed from the CSPRNG, base32 for authenticator apps (ASVS V6.5.3)."""
    return base64.b32encode(os.urandom(20)).decode()


def totp_code(secret_b32: str, step: int) -> str:
    key = base64.b32decode(secret_b32)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def totp_step(epoch_seconds: float) -> int:
    return int(epoch_seconds // TOTP_STEP_SECONDS)


def verify_totp(secret_b32: str, code: str, epoch_seconds: float, last_step: int | None) -> int | None:
    """Return the matched time step, or None. A step at or before `last_step` is refused, so
    each code is usable once (TRD 8.1 `totp_last_step`, ASVS V6.5.1). Time comes from the
    server clock, never the client (ASVS V6.5.8)."""
    code = code.strip()
    if len(code) != TOTP_DIGITS or not code.isdigit():
        return None
    now_step = totp_step(epoch_seconds)
    for step in range(now_step - TOTP_WINDOW, now_step + TOTP_WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(totp_code(secret_b32, step), code):
            return step
    return None


def otpauth_uri(secret_b32: str, account: str, issuer: str = "FreightCheck") -> str:
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(issuer)}&digits={TOTP_DIGITS}&period={TOTP_STEP_SECONDS}"


# ------------------------------------------------------------------ secrets at rest (AES-256-GCM)


def encrypt_secret(plaintext: str, data_key_hex: str, associated: bytes) -> bytes:
    """Nonce-prefixed AES-GCM ciphertext; `associated` binds it to its row (the user id)."""
    nonce = os.urandom(12)
    return nonce + AESGCM(bytes.fromhex(data_key_hex)).encrypt(nonce, plaintext.encode(), associated)


def decrypt_secret(blob: bytes, data_key_hex: str, associated: bytes) -> str:
    return AESGCM(bytes.fromhex(data_key_hex)).decrypt(blob[:12], blob[12:], associated).decode()
