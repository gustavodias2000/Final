"""initial tenant-aware audit schema

Revision ID: 20260922_0001
Revises:
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260922_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "tenants",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "users",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False, server_default="admin"),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_table(
        "ncm_reference_versions",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_etag", sa.String(length=255)),
        sa.Column("version", sa.String(length=80), nullable=False, unique=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ncm",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("reference_version_id", uuid_type, sa.ForeignKey("ncm_reference_versions.id"), nullable=False),
        sa.Column("codigo", sa.String(length=8), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.UniqueConstraint("reference_version_id", "codigo", name="uq_ncm_version_codigo"),
    )
    op.create_index("ix_ncm_reference_version_id", "ncm", ["reference_version_id"])
    op.create_index("ix_ncm_codigo", "ncm", ["codigo"])
    op.create_table(
        "audits",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("source_file_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_produtos", sa.Integer(), nullable=False),
        sa.Column("processados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("reference_version_id", uuid_type, sa.ForeignKey("ncm_reference_versions.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_audits_tenant_id", "audits", ["tenant_id"])
    op.create_index("ix_audits_status", "audits", ["status"])
    op.create_table(
        "audit_items",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("audit_id", uuid_type, sa.ForeignKey("audits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("codigo_produto", sa.String(length=255), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("ncm_atual", sa.String(length=8)),
        sa.Column("ncm_sugerido", sa.String(length=8)),
        sa.Column("cest_atual", sa.String(length=10)),
        sa.Column("cest_sugerido", sa.String(length=10)),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("fonte_referencia", sa.Text()),
        sa.Column("versao_referencia", sa.String(length=80)),
        sa.Column("cest_status", sa.String(length=30)),
        sa.Column("cest_source_url", sa.Text()),
        sa.Column("cest_evidence", sa.Text()),
        sa.Column("reviewed_by_user_id", uuid_type, sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_items_audit_id", "audit_items", ["audit_id"])
    op.create_index("ix_audit_items_status", "audit_items", ["status"])


def downgrade() -> None:
    op.drop_index("ix_audit_items_status", table_name="audit_items")
    op.drop_index("ix_audit_items_audit_id", table_name="audit_items")
    op.drop_table("audit_items")
    op.drop_index("ix_audits_status", table_name="audits")
    op.drop_index("ix_audits_tenant_id", table_name="audits")
    op.drop_table("audits")
    op.drop_index("ix_ncm_codigo", table_name="ncm")
    op.drop_index("ix_ncm_reference_version_id", table_name="ncm")
    op.drop_table("ncm")
    op.drop_table("ncm_reference_versions")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")
