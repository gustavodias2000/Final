"""persist CEST candidate options and the reviewer's chosen CEST

Revision ID: 20261111_0006
Revises: 20260927_0005
Create Date: 2026-11-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20261111_0006"
down_revision = "20260927_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_items",
        sa.Column("cest_candidates", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column("audit_items", sa.Column("cest_escolhido", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_items", "cest_escolhido")
    op.drop_column("audit_items", "cest_candidates")
