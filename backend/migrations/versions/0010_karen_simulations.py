"""Add tenant-scoped Karen simulation journeys and append-only events.

Revision ID: 0010_karen_simulations
Revises: 0009_knowledge_base
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_karen_simulations"
down_revision = "0009_knowledge_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "karen_simulations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("scenario_key", sa.String(48), nullable=False),
        sa.Column("state", sa.String(48), nullable=False),
        sa.Column("created_by_uid", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["ai_agents.tenant_id", "ai_agents.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_karen_simulations_tenant_id"),
    )
    op.create_index(
        "ix_karen_simulations_tenant_state",
        "karen_simulations",
        ["tenant_id", "state"],
    )
    op.create_table(
        "karen_simulation_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("simulation_id", sa.String(36), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("from_state", sa.String(48), nullable=True),
        sa.Column("to_state", sa.String(48), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("decision_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("evaluation_json", sa.JSON(), nullable=False),
        sa.Column("actor_uid", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "simulation_id"],
            ["karen_simulations.tenant_id", "karen_simulations.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "simulation_id",
            "sequence_no",
            name="uq_karen_simulation_event_sequence",
        ),
    )
    op.create_index(
        "ix_karen_simulation_events_tenant_simulation",
        "karen_simulation_events",
        ["tenant_id", "simulation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_karen_simulation_events_tenant_simulation",
        table_name="karen_simulation_events",
    )
    op.drop_table("karen_simulation_events")
    op.drop_index("ix_karen_simulations_tenant_state", table_name="karen_simulations")
    op.drop_table("karen_simulations")
