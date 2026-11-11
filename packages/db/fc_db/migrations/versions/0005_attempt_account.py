"""sign-in attempt log keyed by account as well as address (B2 security review B2-S07). Expand only.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_attempt", sa.Column("user_id", sa.UUID(), nullable=True))
    op.create_index("ix_auth_attempt_user_id_created_at", "auth_attempt", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_attempt_user_id_created_at", table_name="auth_attempt")
    op.drop_column("auth_attempt", "user_id")
