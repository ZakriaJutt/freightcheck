"""Engine factory. The application always connects as the non-superuser app role."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

_engines: dict[str, Engine] = {}


def engine_for(url: str) -> Engine:
    if url not in _engines:
        _engines[url] = create_engine(url, pool_pre_ping=True, future=True)
    return _engines[url]
