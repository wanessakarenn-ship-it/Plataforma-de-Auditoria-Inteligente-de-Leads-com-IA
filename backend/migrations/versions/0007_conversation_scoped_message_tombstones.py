"""Scope message deletion tombstones to their conversation.

Revision ID: 0007_conversation_scoped_message_tombstones
Revises: 0006_tenant_scoped_external_ids
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_conversation_scoped_message_tombstones"
down_revision = "0006_tenant_scoped_external_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("message_events")
    }
    if "conversation_id_hash" not in columns:
        op.add_column(
            "message_events",
            sa.Column("conversation_id_hash", sa.String(64), nullable=True),
        )


def downgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("message_events")
    }
    if "conversation_id_hash" in columns:
        op.drop_column("message_events", "conversation_id_hash")
