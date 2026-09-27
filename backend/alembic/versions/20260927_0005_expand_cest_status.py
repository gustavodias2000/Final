"""allow explicit CEST validation and reconciliation statuses

Revision ID: 20260927_0005
Revises: 20260926_0004
Create Date: 2026-09-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260927_0005"
down_revision = "20260926_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "audit_items",
        "cest_status",
        existing_type=sa.String(length=30),
        type_=sa.String(length=64),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "audit_items",
        "cest_status",
        existing_type=sa.String(length=64),
        type_=sa.String(length=30),
        existing_nullable=True,
    )
