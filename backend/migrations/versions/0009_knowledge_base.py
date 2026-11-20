"""Add tenant-scoped knowledge content, revisions, and agent associations.

Revision ID: 0009_knowledge_base
Revises: 0008_ai_agent_registry
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_knowledge_base"
down_revision = "0008_ai_agent_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_agents",
        sa.Column(
            "knowledge_requires_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_index(
        "uq_ai_agents_tenant_id",
        "ai_agents",
        ["tenant_id", "id"],
        unique=True,
    )
    op.create_table(
        "knowledge_contents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(300), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_name", sa.String(255), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_by_uid", sa.String(128), nullable=False),
        sa.Column("approved_by_uid", sa.String(128), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_knowledge_contents_tenant_id"),
    )
    op.create_index("ix_knowledge_contents_tenant_id", "knowledge_contents", ["tenant_id"])
    op.create_index("ix_knowledge_contents_status", "knowledge_contents", ["status"])
    op.create_index(
        "ix_knowledge_contents_tenant_status",
        "knowledge_contents",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_knowledge_contents_tenant_category",
        "knowledge_contents",
        ["tenant_id", "category"],
    )
    op.create_table(
        "knowledge_content_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("content_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_by_uid", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "content_id"],
            ["knowledge_contents.tenant_id", "knowledge_contents.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "content_id", "version_number", name="uq_knowledge_versions"
        ),
    )
    op.create_index(
        "ix_knowledge_versions_tenant_id",
        "knowledge_content_versions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_knowledge_versions_tenant_content",
        "knowledge_content_versions",
        ["tenant_id", "content_id"],
    )
    op.create_table(
        "knowledge_agent_links",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("agent_id", sa.String(36), primary_key=True),
        sa.Column("content_id", sa.String(36), primary_key=True),
        sa.Column("created_by_uid", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["ai_agents.tenant_id", "ai_agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "content_id"],
            ["knowledge_contents.tenant_id", "knowledge_contents.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_knowledge_agent_links_agent",
        "knowledge_agent_links",
        ["tenant_id", "agent_id"],
    )
    op.create_index(
        "ix_knowledge_agent_links_content",
        "knowledge_agent_links",
        ["tenant_id", "content_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_agent_links_content", table_name="knowledge_agent_links")
    op.drop_index("ix_knowledge_agent_links_agent", table_name="knowledge_agent_links")
    op.drop_table("knowledge_agent_links")
    op.drop_index("ix_knowledge_versions_tenant_content", table_name="knowledge_content_versions")
    op.drop_index("ix_knowledge_versions_tenant_id", table_name="knowledge_content_versions")
    op.drop_table("knowledge_content_versions")
    op.drop_index("ix_knowledge_contents_tenant_category", table_name="knowledge_contents")
    op.drop_index("ix_knowledge_contents_tenant_status", table_name="knowledge_contents")
    op.drop_index("ix_knowledge_contents_status", table_name="knowledge_contents")
    op.drop_index("ix_knowledge_contents_tenant_id", table_name="knowledge_contents")
    op.drop_table("knowledge_contents")
    op.drop_index("uq_ai_agents_tenant_id", table_name="ai_agents")
    with op.batch_alter_table("ai_agents") as batch:
        batch.drop_column("knowledge_requires_approval")
