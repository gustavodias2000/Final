"""persist NCM validity, suggestion source and similar catalog products

Revision ID: 20261112_0007
Revises: 20261111_0006
Create Date: 2026-11-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20261112_0007"
down_revision = "20261111_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # valid / invalid / missing; vazio nas auditorias feitas antes desta versão.
    op.add_column("audit_items", sa.Column("ncm_status", sa.String(length=20), nullable=True))
    # catalogo (produtos parecidos) / tabela (tabela NCM oficial).
    op.add_column("audit_items", sa.Column("ncm_fonte", sa.String(length=20), nullable=True))
    op.add_column(
        "audit_items",
        sa.Column("ncm_vizinhos", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )


def downgrade() -> None:
    op.drop_column("audit_items", "ncm_vizinhos")
    op.drop_column("audit_items", "ncm_fonte")
    op.drop_column("audit_items", "ncm_status")
