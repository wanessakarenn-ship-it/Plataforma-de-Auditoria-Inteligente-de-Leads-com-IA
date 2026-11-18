"""Scope imported lead data by tenant and record authorized mutations.

Revision ID: 0005_tenant_access_and_admin_actions
Revises: 0004_message_delete_tombstones
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_tenant_access_and_admin_actions"
down_revision = "0004_message_delete_tombstones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("import_batches", "leads"):
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "tenant_id" not in columns:
            op.add_column(
                table,
                sa.Column("tenant_id", sa.String(128), nullable=True),
            )
            op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    if "admin_action_logs" not in inspector.get_table_names():
        op.create_table(
            "admin_action_logs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("actor_uid", sa.String(128), nullable=False),
            sa.Column("actor_role", sa.String(24), nullable=False),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("method", sa.String(8), nullable=False),
            sa.Column("route", sa.String(240), nullable=False),
            sa.Column("resource_id", sa.String(160), nullable=True),
            sa.Column("outcome", sa.String(24), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_admin_action_logs_tenant_id",
            "admin_action_logs",
            ["tenant_id"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "admin_action_logs" in inspector.get_table_names():
        op.drop_table("admin_action_logs")
    for table in ("leads", "import_batches"):
        columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
        if "tenant_id" in columns:
            op.drop_index(f"ix_{table}_tenant_id", table_name=table)
            with op.batch_alter_table(table) as batch:
                batch.drop_column("tenant_id")
