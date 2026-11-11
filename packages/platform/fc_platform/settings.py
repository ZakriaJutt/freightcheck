"""One typed settings object read from the environment (T-2.1.4).

Unknown FC_* keys and missing required keys stop startup.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import MISSING, dataclass, fields
from datetime import date


class SettingsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    env: str
    database_url: str
    migration_database_url: str
    public_base_url: str
    signing_key: str
    data_key: str  # 64 hex chars: AES-256-GCM key for TOTP secrets at rest (B2)
    api_port: int = 8102
    log_level: str = "INFO"
    storage_dir: str = ".local/storage"
    # Object storage (B2): "s3" talks the S3 API (MinIO locally, a managed bucket later);
    # "local" is the on-disk fake kept for unit-level tests.
    storage_backend: str = "local"
    s3_endpoint: str = ""
    s3_region: str = "us-east-1"
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    # Outgoing mail (B2): SMTP to Mailpit locally; a real provider later by settings only.
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025
    smtp_starttls: bool = False
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = "FreightCheck <no-reply@freightcheck.example>"
    fixed_today: date | None = None  # tests only; refused in production

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        known = {f"FC_{f.name.upper()}": f for f in fields(cls)}
        unknown = sorted(k for k in env if k.startswith("FC_") and k not in known)
        if unknown:
            raise SettingsError(f"unknown settings: {', '.join(unknown)}")
        values: dict[str, object] = {}
        for key, f in known.items():
            if key not in env:
                if f.default is MISSING:
                    raise SettingsError(f"missing setting {key}")
                continue
            raw = env[key]
            if f.name in ("api_port", "smtp_port"):
                values[f.name] = int(raw)
            elif f.name == "smtp_starttls":
                if raw not in ("true", "false"):
                    raise SettingsError(f"{key} must be true or false")
                values[f.name] = raw == "true"
            elif f.name == "fixed_today":
                values[f.name] = date.fromisoformat(raw) if raw else None
            else:
                values[f.name] = raw
        s = cls(**values)  # type: ignore[arg-type]
        if s.env not in ("dev", "test", "staging", "prod"):
            raise SettingsError("FC_ENV must be dev, test, staging or prod")
        if s.env in ("staging", "prod") and s.fixed_today is not None:
            raise SettingsError("FC_FIXED_TODAY is allowed only in dev and test")
        if len(s.signing_key) < 32:
            raise SettingsError("FC_SIGNING_KEY must be at least 32 characters")
        try:
            if len(bytes.fromhex(s.data_key)) != 32:
                raise ValueError
        except ValueError:
            raise SettingsError("FC_DATA_KEY must be 64 hex characters") from None
        if s.storage_backend not in ("local", "s3"):
            raise SettingsError("FC_STORAGE_BACKEND must be local or s3")
        if s.storage_backend == "s3" and not (s.s3_bucket and s.s3_access_key and s.s3_secret_key):
            raise SettingsError("FC_STORAGE_BACKEND=s3 needs FC_S3_BUCKET, FC_S3_ACCESS_KEY and FC_S3_SECRET_KEY")
        if s.env in ("staging", "prod"):
            if s.storage_backend != "s3":
                raise SettingsError("staging and prod need FC_STORAGE_BACKEND=s3")
            if not s.smtp_starttls:
                raise SettingsError("staging and prod need FC_SMTP_STARTTLS=true")
        return s


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def reset_settings_cache() -> None:
    global _settings
    _settings = None
