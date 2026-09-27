"""add versioned CEST catalog

Revision ID: 20260926_0003
Revises: 20260923_0002
Create Date: 2026-09-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260926_0003"
down_revision = "20260923_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "cest_reference_versions",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False, unique=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "cest_references",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "reference_version_id",
            uuid_type,
            sa.ForeignKey("cest_reference_versions.id"),
            nullable=False,
        ),
        sa.Column("ncm_codigo", sa.String(length=8), nullable=False),
        sa.Column("cest_codigo", sa.String(length=10), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "reference_version_id",
            "ncm_codigo",
            "cest_codigo",
            name="uq_cest_reference_ncm_code",
        ),
    )
    op.create_index("ix_cest_references_reference_version_id", "cest_references", ["reference_version_id"])
    op.create_index("ix_cest_references_ncm_codigo", "cest_references", ["ncm_codigo"])


def downgrade() -> None:
    op.drop_index("ix_cest_references_ncm_codigo", table_name="cest_references")
    op.drop_index("ix_cest_references_reference_version_id", table_name="cest_references")
    op.drop_table("cest_references")
    op.drop_table("cest_reference_versions")
