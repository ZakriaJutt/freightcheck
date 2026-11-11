"""past_contest_by mark on claims (B1-014): the deadline sweep marks, never expires. Expand only.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("claim", sa.Column("past_contest_by", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("claim", sa.Column("past_contest_by_at", postgresql.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("claim", "past_contest_by_at")
    op.drop_column("claim", "past_contest_by")
