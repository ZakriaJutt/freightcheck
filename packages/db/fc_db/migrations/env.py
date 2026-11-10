"""Alembic environment. Migrations run as the migration (owner) role, never the app role."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, text

from fc_db.tables import metadata

url = os.environ.get("FC_MIGRATION_DATABASE_URL")
if not url:
    raise RuntimeError("FC_MIGRATION_DATABASE_URL is required for migrations")


def run() -> None:
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        context.configure(connection=conn, target_metadata=metadata, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
        conn.commit()


run()
