"""Create Sprint 01 lead management schema.

Revision ID: 0001_initial_schema
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from backend.app.models import Base

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from backend.app.models import Base

    Base.metadata.drop_all(bind=op.get_bind())
