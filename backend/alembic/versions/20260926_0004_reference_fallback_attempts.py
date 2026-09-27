"""persist external reference fallback attempts

Revision ID: 20260926_0004
Revises: 20260926_0003
Create Date: 2026-09-26
"""

from alembic import op
import sqlalchemy as sa


revision = "20260926_0004"
down_revision = "20260926_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_items",
        sa.Column("reference_attempts", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )


def downgrade() -> None:
    op.drop_column("audit_items", "reference_attempts")
