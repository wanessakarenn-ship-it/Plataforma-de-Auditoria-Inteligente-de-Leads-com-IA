"""Scope Salesforce external ID uniqueness to each organization.

Revision ID: 0006_tenant_scoped_external_ids
Revises: 0005_tenant_access_and_admin_actions
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_tenant_scoped_external_ids"
down_revision = "0005_tenant_access_and_admin_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    constraint = next(
        (
            item
            for item in sa.inspect(op.get_bind()).get_unique_constraints("leads")
            if item["column_names"] == ["external_id"]
        ),
        None,
    )
    if constraint is None:
        return
    convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    name = constraint["name"] or "uq_leads_external_id"
    with op.batch_alter_table("leads", naming_convention=convention) as batch:
        batch.drop_constraint(name, type_="unique")
        batch.create_unique_constraint(
            "uq_leads_tenant_external_id",
            ["tenant_id", "external_id"],
        )


def downgrade() -> None:
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("leads")
    if not any(
        item["name"] == "uq_leads_tenant_external_id" for item in constraints
    ):
        return
    with op.batch_alter_table("leads") as batch:
        batch.drop_constraint("uq_leads_tenant_external_id", type_="unique")
        batch.create_unique_constraint("uq_leads_external_id", ["external_id"])
