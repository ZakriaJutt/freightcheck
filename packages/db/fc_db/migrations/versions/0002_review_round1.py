"""review round 1: invoice lane, late-send override, settlement excess reason, notifications,
deadline-sweep enqueue function (B1-002, B1-004, B1-007). Expand only: nullable columns and a new table.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = "freightcheck_app"
TENANT_EXPR = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column("invoice", sa.Column("lane_key", sa.Text(), nullable=True))
    op.add_column("claim", sa.Column("late_send_reason", sa.Text(), nullable=True))
    op.add_column("claim", sa.Column("late_send_by", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_claim_late_send_by_app_user", "claim", "app_user", ["late_send_by"], ["id"])
    op.create_check_constraint(
        "late_send_has_actor", "claim", "(late_send_reason IS NULL) = (late_send_by IS NULL)"
    )
    op.add_column("settlement", sa.Column("excess_reason", sa.Text(), nullable=True))
    op.create_table(
        "notification",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("sent_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('deadline_30', 'deadline_14', 'deadline_3', 'carrier_overdue')", name="kind"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_notification_tenant_id_tenant"),
        sa.PrimaryKeyConstraint("id", name="pk_notification"),
        sa.UniqueConstraint("tenant_id", "kind", "entity_id", name="uq_notification_tenant_id_kind_entity_id"),
    )
    op.execute("ALTER TABLE notification ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notification FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON notification USING (tenant_id = {TENANT_EXPR}) "
        f"WITH CHECK (tenant_id = {TENANT_EXPR})"
    )
    # The daily sweep needs one job per tenant; this inserts them without exposing any tenant row.
    op.execute(
        """
        CREATE FUNCTION fc_enqueue_deadline_sweeps(p_run_date date) RETURNS integer
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          WITH ins AS (
            INSERT INTO job (tenant_id, kind, idempotency_key, payload)
            SELECT id, 'deadline_sweep', p_run_date::text, jsonb_build_object('run_date', p_run_date::text)
            FROM tenant WHERE deleted_at IS NULL
            ON CONFLICT (tenant_id, kind, idempotency_key) DO NOTHING
            RETURNING 1
          ) SELECT count(*)::integer FROM ins
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION fc_enqueue_deadline_sweeps(date) FROM PUBLIC")
    op.execute(
        f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT ON notification TO {APP_ROLE}';
            EXECUTE 'GRANT EXECUTE ON FUNCTION fc_enqueue_deadline_sweeps(date) TO {APP_ROLE}';
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS fc_enqueue_deadline_sweeps(date)")
    op.drop_table("notification")
    op.drop_column("settlement", "excess_reason")
    op.drop_constraint("ck_claim_late_send_has_actor", "claim", type_="check")
    op.drop_constraint("fk_claim_late_send_by_app_user", "claim", type_="foreignkey")
    op.drop_column("claim", "late_send_by")
    op.drop_column("claim", "late_send_reason")
    op.drop_column("invoice", "lane_key")
