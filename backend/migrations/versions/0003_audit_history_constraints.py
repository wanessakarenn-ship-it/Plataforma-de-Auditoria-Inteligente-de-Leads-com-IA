"""Align audit history constraints and indexes.

Revision ID: 0003_audit_history_constraints
Revises: 0002_evidence_audit_history
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_audit_history_constraints"
down_revision = "0002_evidence_audit_history"
branch_labels = None
depends_on = None


def _ensure_not_null(table: str, column: str, column_type, backfill: str) -> None:
    inspector = sa.inspect(op.get_bind())
    metadata = next(
        (item for item in inspector.get_columns(table) if item["name"] == column),
        None,
    )
    if metadata is None:
        raise RuntimeError(f"Expected {table}.{column} to exist after revision 0002.")
    op.execute(
        sa.text(f'UPDATE "{table}" SET "{column}" = {backfill} WHERE "{column}" IS NULL')
    )
    if metadata["nullable"]:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=column_type, nullable=False)


def upgrade() -> None:
    _ensure_not_null("conversations", "sync_state", sa.String(24), "'local'")
    _ensure_not_null("messages", "message_type", sa.String(32), "'text'")
    for table, column in (
        ("audits", "reprocess_of_id"),
        ("evidence", "message_id"),
    ):
        index_name = f"ix_{table}_{column}"
        indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
        if index_name not in indexes:
            op.create_index(index_name, table, [column], unique=False)


def downgrade() -> None:
    for table, column in (
        ("audits", "reprocess_of_id"),
        ("evidence", "message_id"),
    ):
        index_name = f"ix_{table}_{column}"
        indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
        if index_name in indexes:
            op.drop_index(index_name, table_name=table)
    with op.batch_alter_table("conversations") as batch:
        batch.alter_column("sync_state", existing_type=sa.String(24), nullable=True)
    with op.batch_alter_table("messages") as batch:
        batch.alter_column("message_type", existing_type=sa.String(32), nullable=True)
