"""The only source of "today" for apps; the core receives dates as arguments."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fc_platform.settings import get_settings


def today() -> date:
    fixed = get_settings().fixed_today
    return fixed if fixed is not None else datetime.now(UTC).date()


def now() -> datetime:
    return datetime.now(UTC)
