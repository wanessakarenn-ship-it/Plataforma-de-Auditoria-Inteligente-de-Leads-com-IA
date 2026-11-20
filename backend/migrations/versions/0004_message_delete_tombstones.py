"""Suppress provider message reimports after a deletion until retention expires.

Revision ID: 0004_message_delete_tombstones
Revises: 0003_audit_history_constraints
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_message_delete_tombstones"
down_revision = "0003_audit_history_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("message_events")}
    if "provider_id_hash" not in columns:
        op.add_column(
            "message_events",
            sa.Column("provider_id_hash", sa.String(64), nullable=True),
        )
    if "tombstone_until" not in columns:
        op.add_column(
            "message_events",
            sa.Column("tombstone_until", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("message_events")}
    with op.batch_alter_table("message_events") as batch:
        if "tombstone_until" in columns:
            batch.drop_column("tombstone_until")
        if "provider_id_hash" in columns:
            batch.drop_column("provider_id_hash")
