"""The single tenant context module used by API and worker (AD-06, R-05).

Every transaction sets `app.tenant_id` with SET LOCAL semantics; row-level security denies
every row when it is unset.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, text

from fc_platform.logging import tenant_id_var


def set_tenant(conn: Connection, tenant_id: uuid.UUID | str) -> None:
    tid = str(uuid.UUID(str(tenant_id)))
    conn.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": tid})
    tenant_id_var.set(tid)


@contextmanager
def tenant_transaction(engine: Engine, tenant_id: uuid.UUID | str) -> Iterator[Connection]:
    with engine.begin() as conn:
        set_tenant(conn, tenant_id)
        yield conn
