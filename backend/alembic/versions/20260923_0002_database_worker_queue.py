"""persist audit input and worker leases

Revision ID: 20260923_0002
Revises: 20260922_0001
Create Date: 2026-09-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260923_0002"
down_revision = "20260922_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.add_column("audits", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audits", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audits", sa.Column("worker_id", sa.String(length=120), nullable=True))
    op.add_column(
        "audits",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_audits_lease_expires_at", "audits", ["lease_expires_at"])
    op.create_index("ix_audits_worker_id", "audits", ["worker_id"])
    op.create_table(
        "audit_input_items",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("audit_id", uuid_type, sa.ForeignKey("audits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("codigo_produto", sa.String(length=255), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("ncm_atual", sa.String(length=8), nullable=True),
        sa.Column("cest_atual", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("audit_id", "row_number", name="uq_audit_input_row"),
    )
    op.create_index("ix_audit_input_items_audit_id", "audit_input_items", ["audit_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_input_items_audit_id", table_name="audit_input_items")
    op.drop_table("audit_input_items")
    op.drop_index("ix_audits_worker_id", table_name="audits")
    op.drop_index("ix_audits_lease_expires_at", table_name="audits")
    op.drop_column("audits", "attempt_count")
    op.drop_column("audits", "worker_id")
    op.drop_column("audits", "lease_expires_at")
    op.drop_column("audits", "processing_started_at")
