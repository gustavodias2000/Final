"""confirmed classifications per tenant and NCM options for extinct codes

Revision ID: 20261112_0008
Revises: 20261112_0007
Create Date: 2026-11-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261112_0008"
down_revision = "20261112_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "confirmed_classifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("codigo_produto", sa.String(length=255), nullable=True),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("descricao_chave", sa.Text(), nullable=False),
        sa.Column("ncm", sa.String(length=8), nullable=False),
        sa.Column("cest", sa.String(length=10), nullable=True),
        sa.Column("origem", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "codigo_produto", name="uq_confirmed_tenant_codigo"),
    )
    op.create_index("ix_confirmed_classifications_tenant_id", "confirmed_classifications", ["tenant_id"])
    op.create_index("ix_confirmed_classifications_descricao_chave", "confirmed_classifications", ["descricao_chave"])
    op.add_column(
        "audit_items",
        sa.Column("ncm_opcoes", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column("audit_items", sa.Column("ncm_escolhido", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_items", "ncm_escolhido")
    op.drop_column("audit_items", "ncm_opcoes")
    op.drop_index("ix_confirmed_classifications_descricao_chave", table_name="confirmed_classifications")
    op.drop_index("ix_confirmed_classifications_tenant_id", table_name="confirmed_classifications")
    op.drop_table("confirmed_classifications")
