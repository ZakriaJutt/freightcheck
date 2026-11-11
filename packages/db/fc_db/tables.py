"""SQLAlchemy 2 table models for the B1 subset of schema.md (T-2.2.1).

Conventions (schema.md section 2): uuid ids, `tenant_id` on tenant tables, composite
foreign keys with `tenant_id`, money as bigint cents, enumerations as text with checks.
Every tenant table is listed in TENANT_TABLES and gets FORCE ROW LEVEL SECURITY in the
migration; IT-08 compares this module with the migrated database.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, CITEXT, JSONB, TIMESTAMP, UUID, ExcludeConstraint

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING)


def _id() -> Column:  # type: ignore[type-arg]
    return Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _tenant() -> Column:  # type: ignore[type-arg]
    return Column("tenant_id", UUID(as_uuid=True), nullable=False)


def _created() -> Column:  # type: ignore[type-arg]
    return Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


def _mutable() -> list[Column]:  # type: ignore[type-arg]
    return [
        Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
        Column("version", Integer, nullable=False, server_default=text("1")),
    ]


def _tfk(col: str, ref: str, name: str | None = None) -> ForeignKeyConstraint:
    """Composite foreign key (tenant_id, col) -> ref(tenant_id, id)."""
    return ForeignKeyConstraint(
        ["tenant_id", col],
        [f"{ref}.tenant_id", f"{ref}.id"],
        name=name or f"fk_{col}_{ref}"[:63],
    )


def _tenant_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["tenant_id"], ["tenant.id"])


def _uq_tid() -> UniqueConstraint:
    """(tenant_id, id) target for composite foreign keys."""
    return UniqueConstraint("tenant_id", "id")


def _enum(col: str, values: tuple[str, ...], name: str | None = None) -> CheckConstraint:
    vals = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{col} IN ({vals})", name=name or col)


def _usd() -> list:  # type: ignore[type-arg]
    return [
        Column("currency", Text, nullable=False, server_default=text("'USD'")),
        CheckConstraint("currency = 'USD'", name="currency_usd"),
    ]


# ------------------------------------------------------------------ identity and access

tenant = Table(
    "tenant",
    metadata,
    _id(),
    Column("name", Text, nullable=False),
    Column("plan", Text, nullable=False),
    Column("hourly_rate_cents", BigInteger),
    Column("tolerance_cents", BigInteger, nullable=False, server_default=text("200")),
    Column("min_claim_cents", BigInteger, nullable=False, server_default=text("2500")),
    Column("sender_domains", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    Column("inbox_token", Text, nullable=False, unique=True),
    Column("deleted_at", TIMESTAMP(timezone=True)),
    _created(),
    *_mutable(),
    _enum("plan", ("pilot_flat", "pilot_gainshare", "starter", "pro", "business", "gainshare")),
)

app_user = Table(
    "app_user",
    metadata,
    _id(),
    Column("email", CITEXT, nullable=False, unique=True),
    # Null until the invited user sets a password (B2, migration 0004).
    Column("password_hash", Text),
    Column("totp_secret_enc", BYTEA),
    Column("totp_last_step", BigInteger),
    # B2: set when the second factor is confirmed; a secret without it is an unfinished enrolment.
    Column("totp_enrolled_at", TIMESTAMP(timezone=True)),
    Column("failed_count", Integer, nullable=False, server_default=text("0")),
    Column("locked_until", TIMESTAMP(timezone=True)),
    _created(),
    *_mutable(),
)

user_session = Table(
    "user_session",
    metadata,
    _id(),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    # B1 addition: the tenant chosen at sign-in; membership is re-checked under RLS.
    Column("active_tenant_id", UUID(as_uuid=True), nullable=False),
    Column("token_hash", BYTEA, nullable=False, unique=True),
    # B2: `password` waits for the TOTP code, `enrol` waits for factor enrolment, `full` is signed in.
    # Only `full` reaches tenant data; the token is replaced when a session becomes `full`.
    Column("stage", Text, nullable=False),
    _created(),
    Column("last_seen_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    ForeignKeyConstraint(["user_id"], ["app_user.id"]),
    ForeignKeyConstraint(["active_tenant_id"], ["tenant.id"]),
    _enum("stage", ("password", "enrol", "full")),
)
Index("ix_user_session_user_id", user_session.c.user_id)

# B2 (migration 0004): single-use emailed tokens. No tenant_id and no RLS, like user_session.
auth_token = Table(
    "auth_token",
    metadata,
    _id(),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("purpose", Text, nullable=False),
    Column("token_hash", BYTEA, nullable=False, unique=True),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("used_at", TIMESTAMP(timezone=True)),
    Column("invited_tenant_id", UUID(as_uuid=True)),
    Column("invited_role", Text),
    Column("invited_by", UUID(as_uuid=True)),
    _created(),
    ForeignKeyConstraint(["user_id"], ["app_user.id"]),
    ForeignKeyConstraint(["invited_tenant_id"], ["tenant.id"]),
    ForeignKeyConstraint(["invited_by"], ["app_user.id"]),
    _enum("purpose", ("invite", "reset")),
    CheckConstraint(
        "(purpose = 'invite') = (invited_tenant_id IS NOT NULL AND invited_role IS NOT NULL)", name="invite_has_tenant"
    ),
    CheckConstraint("invited_role IS NULL OR invited_role IN ('owner', 'approver', 'auditor', 'viewer')", name="invited_role"),
)
Index("ix_auth_token_user_id", auth_token.c.user_id)

recovery_code = Table(
    "recovery_code",
    metadata,
    _id(),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("code_hash", BYTEA, nullable=False),
    Column("used_at", TIMESTAMP(timezone=True)),
    _created(),
    ForeignKeyConstraint(["user_id"], ["app_user.id"]),
    UniqueConstraint("user_id", "code_hash"),
)

# B2: one row per sign-in attempt (password, code, reset request) for the per-address limit of
# 20 an hour (TRD 8.1). Kept 24 hours; holds the address only, never what was typed.
auth_attempt = Table(
    "auth_attempt",
    metadata,
    _id(),
    Column("email", CITEXT, nullable=False),
    Column("kind", Text, nullable=False),
    Column("succeeded", Boolean, nullable=False),
    _created(),
    _enum("kind", ("password", "code", "reset_request", "invitation")),
)
Index("ix_auth_attempt_email_created_at", auth_attempt.c.email, auth_attempt.c.created_at)

membership = Table(
    "membership",
    metadata,
    _id(),
    _tenant(),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("role", Text, nullable=False),
    _created(),
    *_mutable(),
    _tenant_fk(),
    ForeignKeyConstraint(["user_id"], ["app_user.id"]),
    UniqueConstraint("tenant_id", "user_id"),
    _enum("role", ("owner", "approver", "auditor", "viewer")),
)

idempotency_record = Table(
    "idempotency_record",
    metadata,
    _id(),
    _tenant(),
    Column("key", Text, nullable=False),
    Column("route", Text, nullable=False),
    Column("request_hash", Text, nullable=False),
    Column("response_status", Integer, nullable=False),
    Column("response_body", JSONB, nullable=False),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    _created(),
    _tenant_fk(),
    UniqueConstraint("tenant_id", "route", "key"),
)

# ------------------------------------------------------------------ files

source_file = Table(
    "source_file",
    metadata,
    _id(),
    _tenant(),
    Column("sha256", BYTEA, nullable=False),
    Column("purpose", Text, nullable=False),
    Column("storage_key", Text, nullable=False, unique=True),
    Column("byte_size", BigInteger, nullable=False),
    Column("mime", Text, nullable=False),
    Column("scan_state", Text, nullable=False),
    Column("expires_at", TIMESTAMP(timezone=True)),
    _created(),
    _tenant_fk(),
    _uq_tid(),
    UniqueConstraint("tenant_id", "sha256", "purpose"),
    _enum(
        "purpose",
        (
            "invoice",
            "bol",
            "rate_confirmation",
            "delivery_receipt",
            "weight_certificate",
            "rate_document",
            "carrier_response",
            "settlement_evidence",
            "ap_export",
        ),
    ),
    _enum("scan_state", ("pending", "clean", "infected")),
)

# ------------------------------------------------------------------ rates

carrier_account = Table(
    "carrier_account",
    metadata,
    _id(),
    _tenant(),
    Column("name", Text, nullable=False),
    Column("scac", Text),
    Column("carrier_type", Text, nullable=False),
    Column("claims_email", CITEXT),
    Column("dispute_window_days", Integer),
    Column("dispute_window_source_file_id", UUID(as_uuid=True)),
    _created(),
    *_mutable(),
    _tenant_fk(),
    _uq_tid(),
    _tfk("dispute_window_source_file_id", "source_file"),
    _enum("carrier_type", ("motor_carrier", "broker", "other")),
    CheckConstraint("dispute_window_days IS NULL OR dispute_window_source_file_id IS NOT NULL", name="window_has_source"),
)
Index("uq_carrier_account_tenant_lower_name", carrier_account.c.tenant_id, func.lower(carrier_account.c.name), unique=True)

rate_document = Table(
    "rate_document",
    metadata,
    _id(),
    _tenant(),
    Column("carrier_account_id", UUID(as_uuid=True), nullable=False),
    Column("doc_type", Text, nullable=False),
    Column("effective_from", Date, nullable=False),
    Column("effective_to", Date),
    Column("scope_key", Text, nullable=False, server_default=text("'*'")),
    Column("date_basis", Text, nullable=False),
    Column("date_basis_source_page", Integer),
    Column("revision", Integer, nullable=False, server_default=text("1")),
    Column("revises_id", UUID(as_uuid=True)),
    Column("status", Text, nullable=False, server_default=text("'entered'")),
    Column("confirmed_by", UUID(as_uuid=True)),
    Column("confirmed_at", TIMESTAMP(timezone=True)),
    Column("source_file_id", UUID(as_uuid=True), nullable=False),
    _created(),
    *_mutable(),
    _tenant_fk(),
    _uq_tid(),
    _tfk("carrier_account_id", "carrier_account"),
    _tfk("revises_id", "rate_document"),
    _tfk("source_file_id", "source_file"),
    ForeignKeyConstraint(["confirmed_by"], ["app_user.id"]),
    _enum("doc_type", ("contract_rate_sheet", "tariff", "accessorial_schedule", "fuel_schedule", "rate_confirmation")),
    _enum("date_basis", ("pickup_date", "tender_date", "delivery_date", "invoice_date")),
    _enum("status", ("entered", "confirmed", "superseded")),
    CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="effective_range"),
    CheckConstraint(
        "status <> 'confirmed' OR (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)", name="confirmed_has_actor"
    ),
    CheckConstraint("revision >= 1", name="revision_positive"),
    ExcludeConstraint(
        ("tenant_id", "="),
        ("carrier_account_id", "="),
        ("doc_type", "="),
        ("scope_key", "="),
        (func.daterange(text("effective_from"), text("effective_to"), text("'[]'")), "&&"),
        name="ex_rate_document_confirmed_overlap",
        using="gist",
        where=text("status = 'confirmed'"),
    ),
)

rate_rule = Table(
    "rate_rule",
    metadata,
    _id(),
    _tenant(),
    Column("rate_document_id", UUID(as_uuid=True), nullable=False),
    Column("rule_type", Text, nullable=False),
    Column("params", JSONB, nullable=False),
    Column("source_page", Integer),
    Column("entered_by", UUID(as_uuid=True), nullable=False),
    _created(),
    _tenant_fk(),
    _uq_tid(),
    _tfk("rate_document_id", "rate_document"),
    ForeignKeyConstraint(["entered_by"], ["app_user.id"]),
    _enum(
        "rule_type",
        ("linehaul", "minimum", "discount", "base_tariff_ref", "accessorial", "fuel_band", "fuel_week_rule"),
    ),
)
Index("ix_rate_rule_tenant_id_rate_document_id", rate_rule.c.tenant_id, rate_rule.c.rate_document_id)

fuel_index_price = Table(
    "fuel_index_price",
    metadata,
    _id(),
    _tenant(),
    Column("carrier_account_id", UUID(as_uuid=True)),
    Column("index_name", Text, nullable=False),
    Column("week_start", Date, nullable=False),
    Column("price", Numeric(7, 4), nullable=False),
    Column("published_on", Date, nullable=False),
    Column("source_note", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'entered'")),
    Column("confirmed_by", UUID(as_uuid=True)),
    Column("confirmed_at", TIMESTAMP(timezone=True)),
    Column("revision", Integer, nullable=False, server_default=text("1")),
    Column("revises_id", UUID(as_uuid=True)),
    _created(),
    *_mutable(),
    _tenant_fk(),
    _uq_tid(),
    _tfk("carrier_account_id", "carrier_account"),
    _tfk("revises_id", "fuel_index_price"),
    ForeignKeyConstraint(["confirmed_by"], ["app_user.id"]),
    _enum("status", ("entered", "confirmed", "superseded")),
    CheckConstraint(
        "status <> 'confirmed' OR (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)", name="confirmed_has_actor"
    ),
    UniqueConstraint(
        "tenant_id",
        "carrier_account_id",
        "index_name",
        "week_start",
        "revision",
        name="uq_fuel_index_price_week_revision",
        postgresql_nulls_not_distinct=True,
    ),
)
Index(
    "uq_fuel_index_price_one_confirmed",
    fuel_index_price.c.tenant_id,
    fuel_index_price.c.carrier_account_id,
    fuel_index_price.c.index_name,
    fuel_index_price.c.week_start,
    unique=True,
    postgresql_where=text("status = 'confirmed'"),
    postgresql_nulls_not_distinct=True,
)

# ------------------------------------------------------------------ invoices and checks

invoice = Table(
    "invoice",
    metadata,
    _id(),
    _tenant(),
    Column("carrier_account_id", UUID(as_uuid=True), nullable=False),
    Column("invoice_number", Text, nullable=False),
    Column("pro_number", Text),
    Column("revision_of", UUID(as_uuid=True)),
    Column("invoice_date", Date),
    Column("pickup_date", Date),
    Column("tender_date", Date),
    Column("delivery_date", Date),
    Column("receipt_date", Date),
    Column("receipt_basis", Text, nullable=False),
    Column("receipt_note", Text),
    Column("contest_by", Date),
    Column("deadline_basis", Text, nullable=False),
    Column("total_cents", BigInteger, nullable=False),
    *_usd(),
    Column("billed_weight_lb", Numeric(10, 2)),
    Column("billed_class", Text),
    # Migration 0002 (B1-004): lane group that selects lane-scoped rate documents; null = unknown.
    Column("lane_key", Text),
    Column("fields_confirmed", Boolean, nullable=False, server_default=text("false")),
    Column("status", Text, nullable=False, server_default=text("'needs_review'")),
    Column("field_revision", Integer, nullable=False, server_default=text("1")),
    Column("ruleset_revision", Integer, nullable=False, server_default=text("1")),
    _created(),
    *_mutable(),
    _tenant_fk(),
    _uq_tid(),
    _tfk("carrier_account_id", "carrier_account"),
    _tfk("revision_of", "invoice"),
    UniqueConstraint("tenant_id", "carrier_account_id", "invoice_number", "revision_of"),
    _enum("receipt_basis", ("carrier_transmission", "ap_received_stamp", "user_entered", "unknown")),
    _enum("deadline_basis", ("receipt_plus_180", "invoice_date_proxy_plus_180", "contract_term", "none_broker")),
    _enum("status", ("needs_review", "needs_input", "variance", "clean")),
    CheckConstraint("receipt_basis <> 'user_entered' OR receipt_note IS NOT NULL", name="user_receipt_has_note"),
)
Index("ix_invoice_tenant_id_status_contest_by", invoice.c.tenant_id, invoice.c.status, invoice.c.contest_by)
Index(
    "ix_invoice_tenant_id_carrier_account_id_pro_number", invoice.c.tenant_id, invoice.c.carrier_account_id, invoice.c.pro_number
)
Index(
    "ix_invoice_tenant_id_pro_number_invoice_date_total_cents",
    invoice.c.tenant_id,
    invoice.c.pro_number,
    invoice.c.invoice_date,
    invoice.c.total_cents,
)
Index("ix_invoice_tenant_id_contest_by", invoice.c.tenant_id, invoice.c.contest_by)

invoice_line = Table(
    "invoice_line",
    metadata,
    _id(),
    _tenant(),
    Column("invoice_id", UUID(as_uuid=True), nullable=False),
    Column("line_no", Integer, nullable=False),
    Column("charge_type", Text, nullable=False),
    Column("accessorial_code", Text),
    Column("description", Text),
    Column("amount_cents", BigInteger, nullable=False),
    _created(),
    _tenant_fk(),
    _tfk("invoice_id", "invoice"),
    UniqueConstraint("invoice_id", "line_no"),
    _enum("charge_type", ("linehaul", "fuel", "accessorial", "discount", "other")),
)

check_result = Table(
    "check_result",
    metadata,
    _id(),
    _tenant(),
    Column("invoice_id", UUID(as_uuid=True), nullable=False),
    Column("run_no", Integer, nullable=False),
    Column("check_code", Text, nullable=False),
    Column("line_no", Integer),
    Column("status", Text, nullable=False),
    Column("exception_code", Text),
    Column("expected_cents", BigInteger),
    Column("billed_cents", BigInteger),
    Column("variance_cents", BigInteger),
    Column("rate_rule_id", UUID(as_uuid=True)),
    Column("rate_document_revision", Integer),
    Column("fuel_index_price_id", UUID(as_uuid=True)),
    Column("governing_date", Date),
    Column("arithmetic", JSONB, nullable=False),
    Column("engine_version", Text, nullable=False),
    _created(),
    _tenant_fk(),
    _uq_tid(),
    _tfk("invoice_id", "invoice"),
    _tfk("rate_rule_id", "rate_rule"),
    _tfk("fuel_index_price_id", "fuel_index_price"),
    UniqueConstraint(
        "invoice_id",
        "run_no",
        "check_code",
        "line_no",
        name="uq_check_result_run_check_line",
        postgresql_nulls_not_distinct=True,
    ),
    _enum("status", ("pass", "variance", "exception", "not_applicable")),
    CheckConstraint("(status = 'exception') = (exception_code IS NOT NULL)", name="exception_has_code"),
    _enum(
        "exception_code",
        (
            "GOVERNING_RATE_MISSING",
            "GOVERNING_DATE_MISSING",
            "BASE_TARIFF_UNAVAILABLE",
            "FSC_BASIS_MISSING",
            "INDEX_PRICE_MISSING",
            "INDEX_PRICE_UNCONFIRMED",
            "FIELD_UNCONFIRMED",
            "DOCUMENT_MISSING",
            "ENGINE_ERROR",
        ),
        name="exception_code_known",
    ),
)
Index(
    "ix_check_result_tenant_id_invoice_id_run_no",
    check_result.c.tenant_id,
    check_result.c.invoice_id,
    check_result.c.run_no.desc(),
)

finding = Table(
    "finding",
    metadata,
    _id(),
    _tenant(),
    Column("invoice_id", UUID(as_uuid=True), nullable=False),
    Column("check_code", Text, nullable=False),
    Column("line_no", Integer),
    Column("current_result_id", UUID(as_uuid=True), nullable=False),
    Column("decision", Text, nullable=False, server_default=text("'open'")),
    Column("dismiss_reason", Text),
    Column("decided_by", UUID(as_uuid=True)),
    Column("decided_at", TIMESTAMP(timezone=True)),
    _created(),
    *_mutable(),
    _tenant_fk(),
    _uq_tid(),
    _tfk("invoice_id", "invoice"),
    _tfk("current_result_id", "check_result"),
    ForeignKeyConstraint(["decided_by"], ["app_user.id"]),
    UniqueConstraint(
        "tenant_id",
        "invoice_id",
        "check_code",
        "line_no",
        name="uq_finding_invoice_check_line",
        postgresql_nulls_not_distinct=True,
    ),
    _enum("decision", ("open", "confirmed_for_claim", "dismissed", "below_threshold")),
    CheckConstraint("decision <> 'dismissed' OR dismiss_reason IS NOT NULL", name="dismiss_has_reason"),
)
Index("ix_finding_tenant_id_decision_check_code", finding.c.tenant_id, finding.c.decision, finding.c.check_code)

# ------------------------------------------------------------------ claims, settlements, fees

claim = Table(
    "claim",
    metadata,
    _id(),
    _tenant(),
    Column("carrier_account_id", UUID(as_uuid=True), nullable=False),
    Column("invoice_id", UUID(as_uuid=True), nullable=False),
    Column("reference", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'draft'")),
    Column("claimed_cents", BigInteger),
    Column("accepted_cents", BigInteger),
    Column("settled_cents", BigInteger, nullable=False, server_default=text("0")),
    *_usd(),
    Column("basis_snapshot", JSONB),
    Column("origin", Text, nullable=False),
    Column("stale_basis", Boolean, nullable=False, server_default=text("false")),
    Column("basis_changed_after_send", Boolean, nullable=False, server_default=text("false")),
    # B1 addition: first time the flag was set; never cleared, feeds the wrong-basis metric.
    Column("basis_changed_after_send_at", TIMESTAMP(timezone=True)),
    Column("late_override_reason", Text),
    # Migration 0002 (B1-002): override recorded when the send is recorded after contest-by.
    Column("late_send_reason", Text),
    Column("late_send_by", UUID(as_uuid=True)),
    # Migration 0003 (B1-014): set by the daily sweep when an unsent claim passes contest-by. A mark only:
    # approval and send stay possible with a recorded override (MH-08); never cleared.
    Column("past_contest_by", Boolean, nullable=False, server_default=text("false")),
    Column("past_contest_by_at", TIMESTAMP(timezone=True)),
    Column("approved_by", UUID(as_uuid=True)),
    Column("approved_at", TIMESTAMP(timezone=True)),
    Column("sent_at", Date),
    Column("sent_to", Text),
    _created(),
    *_mutable(),
    _tenant_fk(),
    _uq_tid(),
    _tfk("carrier_account_id", "carrier_account"),
    _tfk("invoice_id", "invoice"),
    ForeignKeyConstraint(["approved_by"], ["app_user.id"]),
    ForeignKeyConstraint(["late_send_by"], ["app_user.id"]),
    UniqueConstraint("tenant_id", "reference"),
    CheckConstraint("(late_send_reason IS NULL) = (late_send_by IS NULL)", name="late_send_has_actor"),
    _enum(
        "status",
        (
            "draft",
            "approved",
            "sent",
            "acknowledged",
            "accepted",
            "partly_accepted",
            "denied",
            "settled",
            "withdrawn",
            "expired",
        ),
    ),
    _enum("origin", ("lookback", "pilot", "recurring")),
    CheckConstraint("settled_cents >= 0", name="settled_nonnegative"),
    CheckConstraint("claimed_cents IS NULL OR claimed_cents > 0", name="claimed_positive"),
    CheckConstraint("accepted_cents IS NULL OR accepted_cents >= 0", name="accepted_nonnegative"),
)
Index(
    "uq_claim_tenant_id_invoice_id_active",
    claim.c.tenant_id,
    claim.c.invoice_id,
    unique=True,
    postgresql_where=text("status <> 'withdrawn'"),
)
Index("ix_claim_tenant_id_status_sent_at", claim.c.tenant_id, claim.c.status, claim.c.sent_at)

claim_line = Table(
    "claim_line",
    metadata,
    _id(),
    _tenant(),
    Column("claim_id", UUID(as_uuid=True), nullable=False),
    Column("finding_id", UUID(as_uuid=True), nullable=False),
    Column("claimed_cents", BigInteger, nullable=False),
    _created(),
    _tenant_fk(),
    _tfk("claim_id", "claim"),
    _tfk("finding_id", "finding"),
    UniqueConstraint("claim_id", "finding_id"),
    CheckConstraint("claimed_cents > 0", name="claimed_positive"),
)

claim_event = Table(
    "claim_event",
    metadata,
    _id(),
    _tenant(),
    Column("claim_id", UUID(as_uuid=True), nullable=False),
    Column("event_type", Text, nullable=False),
    Column("occurred_on", Date, nullable=False),
    Column("amount_cents", BigInteger),
    Column("evidence_file_id", UUID(as_uuid=True)),
    Column("reason_code", Text),
    Column("reason_note", Text),
    Column("client_event_id", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.clock_timestamp()),
    _tenant_fk(),
    _tfk("claim_id", "claim"),
    _tfk("evidence_file_id", "source_file"),
    UniqueConstraint("claim_id", "client_event_id"),
    _enum(
        "event_type",
        (
            "drafted",
            "approved",
            "sent",
            "acknowledged",
            "decision_accepted",
            "decision_partial",
            "decision_denied",
            "short_paid",
            "carrier_rebilled",
            "withdrawn",
            "expired",
        ),
    ),
    CheckConstraint(
        "event_type NOT IN ('decision_accepted', 'decision_partial', 'decision_denied') OR evidence_file_id IS NOT NULL",
        name="decision_has_evidence",
    ),
    CheckConstraint(
        "event_type NOT IN ('decision_denied', 'decision_partial', 'withdrawn') OR reason_code IS NOT NULL",
        name="reason_required",
    ),
    _enum(
        "reason_code",
        ("wrong_rate_basis", "charge_supported_by_carrier", "time_barred", "duplicate_claim", "other"),
        name="reason_code_known",
    ),
)
Index("ix_claim_event_tenant_id_claim_id", claim_event.c.tenant_id, claim_event.c.claim_id)

settlement = Table(
    "settlement",
    metadata,
    _id(),
    _tenant(),
    Column("claim_id", UUID(as_uuid=True), nullable=False),
    Column("method", Text, nullable=False),
    Column("amount_cents", BigInteger, nullable=False),
    *_usd(),
    Column("settled_on", Date, nullable=False),
    Column("evidence_file_id", UUID(as_uuid=True), nullable=False),
    Column("carrier_reference", Text),
    Column("reversed_at", TIMESTAMP(timezone=True)),
    Column("reversed_by", UUID(as_uuid=True)),
    Column("reverse_reason", Text),
    # Migration 0002 (B1-007): why settlements may exceed the accepted (or claimed) amount.
    Column("excess_reason", Text),
    _created(),
    *_mutable(),
    _tenant_fk(),
    _uq_tid(),
    _tfk("claim_id", "claim"),
    _tfk("evidence_file_id", "source_file"),
    ForeignKeyConstraint(["reversed_by"], ["app_user.id"]),
    UniqueConstraint("tenant_id", "claim_id", "method", "carrier_reference"),
    _enum("method", ("credit_memo", "refund_payment", "corrected_invoice", "short_pay_accepted")),
    CheckConstraint("amount_cents > 0", name="amount_positive"),
    CheckConstraint("reversed_at IS NULL OR reverse_reason IS NOT NULL", name="reversal_has_reason"),
)
Index(
    "ix_settlement_tenant_id_settled_on_open",
    settlement.c.tenant_id,
    settlement.c.settled_on,
    postgresql_where=text("reversed_at IS NULL"),
)

fee_statement = Table(
    "fee_statement",
    metadata,
    _id(),
    _tenant(),
    Column("period_start", Date, nullable=False),
    Column("period_end", Date, nullable=False),
    Column("plan", Text, nullable=False),
    Column("total_cents", BigInteger, nullable=False),
    *_usd(),
    Column("issued_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
    _created(),
    _tenant_fk(),
    _uq_tid(),
    UniqueConstraint("tenant_id", "period_start", "plan"),
)

fee_statement_line = Table(
    "fee_statement_line",
    metadata,
    _id(),
    _tenant(),
    Column("fee_statement_id", UUID(as_uuid=True), nullable=False),
    Column("settlement_id", UUID(as_uuid=True), nullable=False),
    Column("basis_cents", BigInteger, nullable=False),
    Column("fee_cents", BigInteger, nullable=False),
    _created(),
    _tenant_fk(),
    _tfk("fee_statement_id", "fee_statement"),
    _tfk("settlement_id", "settlement"),
    UniqueConstraint("settlement_id", "fee_statement_id"),
)

# ------------------------------------------------------------------ jobs and audit

job = Table(
    "job",
    metadata,
    _id(),
    _tenant(),
    Column("kind", Text, nullable=False),
    Column("state", Text, nullable=False, server_default=text("'queued'")),
    Column("idempotency_key", Text, nullable=False),
    Column("attempt", Integer, nullable=False, server_default=text("0")),
    Column("run_after", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
    Column("correlation_id", Text),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("last_error", Text),
    _created(),
    *_mutable(),
    _tenant_fk(),
    UniqueConstraint("tenant_id", "kind", "idempotency_key"),
    _enum("state", ("queued", "running", "done", "failed", "needs_manual")),
)
Index("ix_job_state_run_after_queued", job.c.state, job.c.run_after, postgresql_where=text("state = 'queued'"))

audit_event = Table(
    "audit_event",
    metadata,
    _id(),
    _tenant(),
    Column("actor_user_id", UUID(as_uuid=True)),
    Column("actor_role", Text),
    Column("operator_grant_id", UUID(as_uuid=True)),
    Column("action", Text, nullable=False),
    Column("entity_type", Text, nullable=False),
    Column("entity_id", UUID(as_uuid=True)),
    Column("before_hash", Text),
    Column("after_hash", Text),
    Column("correlation_id", Text),
    _created(),
    _tenant_fk(),
)
Index("ix_audit_event_tenant_id_created_at", audit_event.c.tenant_id, audit_event.c.created_at.desc())

notification = Table(
    "notification",
    metadata,
    _id(),
    _tenant(),
    Column("kind", Text, nullable=False),
    Column("entity_id", UUID(as_uuid=True), nullable=False),
    Column("sent_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
    _created(),
    _tenant_fk(),
    UniqueConstraint("tenant_id", "kind", "entity_id"),
    _enum("kind", ("deadline_30", "deadline_14", "deadline_3", "carrier_overdue")),
)

TENANT_TABLES = (
    "membership",
    "idempotency_record",
    "source_file",
    "carrier_account",
    "rate_document",
    "rate_rule",
    "fuel_index_price",
    "invoice",
    "invoice_line",
    "check_result",
    "finding",
    "claim",
    "claim_line",
    "claim_event",
    "settlement",
    "fee_statement",
    "fee_statement_line",
    "job",
    "audit_event",
    "notification",
)
# The app role may insert and read these, never update or delete (append-only).
APPEND_ONLY = ("audit_event", "claim_event", "check_result", "fee_statement", "fee_statement_line", "notification")
