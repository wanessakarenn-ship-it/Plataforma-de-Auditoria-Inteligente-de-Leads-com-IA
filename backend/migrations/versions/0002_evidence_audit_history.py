"""Extend CRM imports, authorized conversation history and evidence audits.

Revision ID: 0002_evidence_audit_history
Revises: 0001_initial_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_evidence_audit_history"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def _column_names(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _add_column(
    inspector,
    table: str,
    name: str,
    column_type,
    *,
    nullable: bool = True,
    backfill: str | None = None,
    foreign_key: str | None = None,
) -> None:
    existing = next(
        (column for column in inspector.get_columns(table) if column["name"] == name),
        None,
    )
    if existing is None:
        column = sa.Column(name, column_type, nullable=True)
        if foreign_key:
            column.append_foreign_key(
                sa.ForeignKey(foreign_key, name=f"fk_{table}_{name}")
            )
        if foreign_key:
            with op.batch_alter_table(table) as batch:
                batch.add_column(column)
        else:
            op.add_column(table, column)
    if backfill is not None:
        op.execute(sa.text(f'UPDATE "{table}" SET "{name}" = {backfill} WHERE "{name}" IS NULL'))
    if not nullable and (existing is None or existing["nullable"]):
        with op.batch_alter_table(table) as batch:
            batch.alter_column(name, existing_type=column_type, nullable=False)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    additions = {
        "leads": [
            ("crm_created_at", sa.DateTime(timezone=True), True, None, None),
            ("campaign", sa.String(240), True, None, None),
            ("monthly_account_value", sa.Numeric(14, 2), True, None, None),
            ("loss_reason_description", sa.Text(), True, None, None),
        ],
        "conversations": [
            ("capture_source", sa.String(120), True, None, None),
            ("sync_state", sa.String(24), False, "'local'", None),
            ("started_at", sa.DateTime(timezone=True), True, None, None),
            ("ended_at", sa.DateTime(timezone=True), True, None, None),
        ],
        "messages": [
            ("provider_message_id", sa.String(160), True, None, None),
            ("sender", sa.String(320), True, None, None),
            ("recipient", sa.String(320), True, None, None),
            ("message_type", sa.String(32), False, "'text'", None),
            ("capture_source", sa.String(120), True, None, None),
            ("authorized_for_audit", sa.Boolean(), False, "false", None),
            ("sync_state", sa.String(24), False, "'local'", None),
            ("edited_at", sa.DateTime(timezone=True), True, None, None),
            ("deleted_at", sa.DateTime(timezone=True), True, None, None),
            ("retention_until", sa.DateTime(timezone=True), True, None, None),
        ],
        "audits": [
            ("execution_mode", sa.String(16), False, "'simulated'", None),
            ("model_version", sa.String(160), True, None, None),
            ("prompt_version", sa.String(64), True, None, None),
            ("classification", sa.String(24), False, "'inconclusive'", None),
            ("original_reason", sa.Text(), False, "''", None),
            ("justification", sa.Text(), False, "''", None),
            ("limitations_json", sa.JSON(), False, "'[]'", None),
            ("alternative_reason", sa.Text(), True, None, None),
            ("requires_human_review", sa.Boolean(), False, "true", None),
            ("estimated_cost_usd", sa.Float(), False, "0", None),
            ("input_tokens", sa.Integer(), False, "0", None),
            ("output_tokens", sa.Integer(), False, "0", None),
            ("request_hash", sa.String(64), False, "''", None),
            ("reprocess_of_id", sa.String(36), True, None, "audits.id"),
            ("review_status", sa.String(24), False, "'pending'", None),
            ("review_notes", sa.Text(), True, None, None),
            ("reviewed_at", sa.DateTime(timezone=True), True, None, None),
            ("finished_at", sa.DateTime(timezone=True), True, None, None),
        ],
        "evidence": [
            ("message_id", sa.String(36), True, None, "messages.id"),
            ("referenced_at", sa.DateTime(timezone=True), True, None, None),
            ("verified", sa.Boolean(), False, "false", None),
            ("retention_until", sa.DateTime(timezone=True), True, None, None),
        ],
    }
    for table, columns in additions.items():
        for name, kind, nullable, backfill, foreign_key in columns:
            _add_column(
                inspector,
                table,
                name,
                kind,
                nullable=nullable,
                backfill=backfill,
                foreign_key=foreign_key,
            )
        inspector = sa.inspect(op.get_bind())

    if "message_events" not in inspector.get_table_names():
        op.create_table(
            "message_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "message_id",
                sa.String(36),
                sa.ForeignKey("messages.id", name="fk_message_events_message_id"),
                nullable=False,
            ),
            sa.Column("event_type", sa.String(24), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source", sa.String(120), nullable=False),
            sa.Column("before_content_sha256", sa.String(64), nullable=True),
            sa.Column("after_content_sha256", sa.String(64), nullable=True),
        )
        op.create_index("ix_message_events_message_id", "message_events", ["message_id"])

    unique_names = {
        item["name"] for item in sa.inspect(op.get_bind()).get_unique_constraints("messages")
    }
    if "uq_message_conversation_provider_id" not in unique_names:
        with op.batch_alter_table("messages") as batch:
            batch.create_unique_constraint(
                "uq_message_conversation_provider_id",
                ["conversation_id", "provider_message_id"],
            )

    for table, column in (
        ("audits", "lead_id"),
        ("audits", "reprocess_of_id"),
        ("evidence", "audit_id"),
        ("evidence", "message_id"),
    ):
        index_name = f"ix_{table}_{column}"
        if index_name not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}:
            op.create_index(index_name, table, [column], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "message_events" in inspector.get_table_names():
        op.drop_table("message_events")
    unique_names = {
        item["name"] for item in sa.inspect(op.get_bind()).get_unique_constraints("messages")
    }
    if "uq_message_conversation_provider_id" in unique_names:
        with op.batch_alter_table("messages") as batch:
            batch.drop_constraint("uq_message_conversation_provider_id", type_="unique")
    for table, columns in {
        "leads": ["crm_created_at", "campaign", "monthly_account_value", "loss_reason_description"],
        "conversations": ["capture_source", "sync_state", "started_at", "ended_at"],
        "messages": [
            "provider_message_id", "sender", "recipient", "message_type", "capture_source",
            "authorized_for_audit", "sync_state", "edited_at", "deleted_at", "retention_until",
        ],
        "audits": [
            "execution_mode", "model_version", "prompt_version", "classification",
            "original_reason", "justification", "limitations_json", "alternative_reason",
            "requires_human_review", "estimated_cost_usd", "input_tokens", "output_tokens",
            "request_hash", "reprocess_of_id", "review_status", "review_notes", "reviewed_at",
            "finished_at",
        ],
        "evidence": ["message_id", "referenced_at", "verified", "retention_until"],
    }.items():
        present = _column_names(sa.inspect(op.get_bind()), table)
        with op.batch_alter_table(table) as batch:
            for column in reversed(columns):
                if column in present:
                    batch.drop_column(column)
