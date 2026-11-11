"""sign-in (B2, T-2.2.3): session stage, emailed single-use tokens, recovery codes, attempt log,
membership lookup at sign-in. Expand only: new tables, a relaxed NOT NULL, new nullable columns,
and a stage column whose backfill default is dropped after the backfill.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

APP_ROLE = "freightcheck_app"


def upgrade() -> None:
    op.alter_column("app_user", "password_hash", existing_type=sa.Text(), nullable=True)
    # B1 wrote a placeholder, not a hash; such users have no password until invited again.
    op.execute("UPDATE app_user SET password_hash = NULL WHERE password_hash NOT LIKE '$argon2%'")
    op.add_column("app_user", sa.Column("totp_enrolled_at", postgresql.TIMESTAMP(timezone=True), nullable=True))

    # Sessions written before B2 were the B1 dev/test stand-in; they are revoked, not upgraded.
    op.add_column("user_session", sa.Column("stage", sa.Text(), server_default=sa.text("'password'"), nullable=False))
    op.alter_column("user_session", "stage", server_default=None)
    op.execute("UPDATE user_session SET revoked_at = now() WHERE revoked_at IS NULL")
    op.create_check_constraint("stage", "user_session", "stage IN ('password', 'enrol', 'full')")
    op.create_index("ix_user_session_user_id", "user_session", ["user_id"])

    op.create_table(
        "auth_token",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", postgresql.BYTEA(), nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("invited_tenant_id", sa.UUID(), nullable=True),
        sa.Column("invited_role", sa.Text(), nullable=True),
        sa.Column("invited_by", sa.UUID(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("purpose IN ('invite', 'reset')", name=op.f("ck_auth_token_purpose")),
        sa.CheckConstraint(
            "(purpose = 'invite') = (invited_tenant_id IS NOT NULL AND invited_role IS NOT NULL)",
            name=op.f("ck_auth_token_invite_has_tenant"),
        ),
        sa.CheckConstraint(
            "invited_role IS NULL OR invited_role IN ('owner', 'approver', 'auditor', 'viewer')",
            name=op.f("ck_auth_token_invited_role"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], name=op.f("fk_auth_token_user_id_app_user")),
        sa.ForeignKeyConstraint(["invited_tenant_id"], ["tenant.id"], name=op.f("fk_auth_token_invited_tenant_id_tenant")),
        sa.ForeignKeyConstraint(["invited_by"], ["app_user.id"], name=op.f("fk_auth_token_invited_by_app_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_token")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_token_token_hash")),
    )
    op.create_index("ix_auth_token_user_id", "auth_token", ["user_id"])

    op.create_table(
        "recovery_code",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code_hash", postgresql.BYTEA(), nullable=False),
        sa.Column("used_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], name=op.f("fk_recovery_code_user_id_app_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recovery_code")),
        sa.UniqueConstraint("user_id", "code_hash", name=op.f("uq_recovery_code_user_id_code_hash")),
    )

    op.create_table(
        "auth_attempt",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('password', 'code', 'reset_request', 'invitation')", name=op.f("ck_auth_attempt_kind")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_attempt")),
    )
    op.create_index("ix_auth_attempt_email_created_at", "auth_attempt", ["email", "created_at"])

    # At sign-in the tenant is not yet known and membership is under forced RLS. This returns
    # only the (tenant, role) pairs of one user, so the API can pick the session's tenant; all
    # later reads run under that tenant's context (TRD 8.1).
    op.execute(
        """
        CREATE FUNCTION fc_user_tenants(p_user_id uuid) RETURNS TABLE(tenant_id uuid, role text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT m.tenant_id, m.role FROM membership m JOIN tenant t ON t.id = m.tenant_id
          WHERE m.user_id = p_user_id AND t.deleted_at IS NULL
          ORDER BY m.created_at
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION fc_user_tenants(uuid) FROM PUBLIC")
    op.execute(
        f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON auth_token, recovery_code TO {APP_ROLE}';
            EXECUTE 'GRANT SELECT, INSERT, DELETE ON auth_attempt TO {APP_ROLE}';
            EXECUTE 'GRANT EXECUTE ON FUNCTION fc_user_tenants(uuid) TO {APP_ROLE}';
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS fc_user_tenants(uuid)")
    op.drop_index("ix_auth_attempt_email_created_at", table_name="auth_attempt")
    op.drop_table("auth_attempt")
    op.drop_table("recovery_code")
    op.drop_index("ix_auth_token_user_id", table_name="auth_token")
    op.drop_table("auth_token")
    op.drop_index("ix_user_session_user_id", table_name="user_session")
    op.drop_constraint("ck_user_session_stage", "user_session", type_="check")
    op.drop_column("user_session", "stage")
    op.drop_column("app_user", "totp_enrolled_at")
    op.execute("UPDATE app_user SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column("app_user", "password_hash", existing_type=sa.Text(), nullable=False)
