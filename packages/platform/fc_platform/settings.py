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
    api_port: int = 8102
    log_level: str = "INFO"
    storage_dir: str = ".local/storage"
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
            if f.name == "api_port":
                values[f.name] = int(raw)
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
