"""Add tenant-scoped AI agent registry and immutable prompt versions.

Revision ID: 0008_ai_agent_registry
Revises: 0007_conversation_scoped_message_tombstones
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_ai_agent_registry"
down_revision = "0007_conversation_scoped_message_tombstones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("template_key", sa.String(80), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("process_role", sa.String(120), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("decision_criteria", sa.Text(), nullable=False),
        sa.Column("safety_rules", sa.Text(), nullable=False),
        sa.Column("human_handoff", sa.Text(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("max_cost_usd", sa.Numeric(10, 4), nullable=False),
        sa.Column("publication_state", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_by_uid", sa.String(128), nullable=False),
        sa.Column("approved_by_uid", sa.String(128), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "template_key", name="uq_ai_agents_tenant_template"),
    )
    op.create_index("ix_ai_agents_tenant_id", "ai_agents", ["tenant_id"])
    op.create_index("ix_ai_agents_tenant_active", "ai_agents", ["tenant_id", "is_active"])
    op.create_table(
        "ai_agent_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_by_uid", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["ai_agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("agent_id", "version_number", name="uq_ai_agent_versions_number"),
    )
    op.create_index(
        "ix_ai_agent_versions_tenant_id",
        "ai_agent_versions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_ai_agent_versions_tenant_agent",
        "ai_agent_versions",
        ["tenant_id", "agent_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_agent_versions_tenant_agent", table_name="ai_agent_versions")
    op.drop_index("ix_ai_agent_versions_tenant_id", table_name="ai_agent_versions")
    op.drop_table("ai_agent_versions")
    op.drop_index("ix_ai_agents_tenant_active", table_name="ai_agents")
    op.drop_index("ix_ai_agents_tenant_id", table_name="ai_agents")
    op.drop_table("ai_agents")
