import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome = Column(String(255), nullable=False)
    ativo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    username = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="admin")
    ativo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    tenant = relationship("Tenant")


class NcmReferenceVersion(Base):
    __tablename__ = "ncm_reference_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_url = Column(Text, nullable=False)
    source_etag = Column(String(255), nullable=True)
    version = Column(String(80), nullable=False, unique=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NCM(Base):
    __tablename__ = "ncm"
    __table_args__ = (UniqueConstraint("reference_version_id", "codigo", name="uq_ncm_version_codigo"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference_version_id = Column(
        UUID(as_uuid=True), ForeignKey("ncm_reference_versions.id"), nullable=False, index=True
    )
    codigo = Column(String(8), nullable=False, index=True)
    descricao = Column(Text, nullable=False)

    reference_version = relationship("NcmReferenceVersion")


class CestReferenceVersion(Base):
    __tablename__ = "cest_reference_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_url = Column(Text, nullable=False)
    version = Column(String(80), nullable=False, unique=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CestReference(Base):
    __tablename__ = "cest_references"
    __table_args__ = (
        UniqueConstraint("reference_version_id", "ncm_codigo", "cest_codigo", name="uq_cest_reference_ncm_code"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference_version_id = Column(
        UUID(as_uuid=True), ForeignKey("cest_reference_versions.id"), nullable=False, index=True
    )
    ncm_codigo = Column(String(8), nullable=False, index=True)
    cest_codigo = Column(String(10), nullable=False)
    descricao = Column(Text, nullable=True)

    reference_version = relationship("CestReferenceVersion")


class Audit(Base):
    __tablename__ = "audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    source_filename = Column(String(512), nullable=False)
    source_file_sha256 = Column(String(64), nullable=False)
    source_file_size_bytes = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, index=True)
    total_produtos = Column(Integer, nullable=False)
    processados = Column(Integer, nullable=False, default=0)
    errors = Column(JSON, nullable=False, default=list)
    reference_version_id = Column(UUID(as_uuid=True), ForeignKey("ncm_reference_versions.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    worker_id = Column(String(120), nullable=True, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)

    tenant = relationship("Tenant")
    reference_version = relationship("NcmReferenceVersion")
    items = relationship("AuditItem", cascade="all, delete-orphan")
    input_items = relationship("AuditInputItem", cascade="all, delete-orphan")


class AuditInputItem(Base):
    """Linha normalizada da planilha, disponível para workers independentes."""

    __tablename__ = "audit_input_items"
    __table_args__ = (UniqueConstraint("audit_id", "row_number", name="uq_audit_input_row"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_id = Column(UUID(as_uuid=True), ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number = Column(Integer, nullable=False)
    codigo_produto = Column(String(255), nullable=False)
    descricao = Column(Text, nullable=False)
    ncm_atual = Column(String(8), nullable=True)
    cest_atual = Column(String(10), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    audit = relationship("Audit", back_populates="input_items")


class AuditItem(Base):
    __tablename__ = "audit_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_id = Column(UUID(as_uuid=True), ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True)
    codigo_produto = Column(String(255), nullable=False)
    descricao = Column(Text, nullable=False)
    ncm_atual = Column(String(8), nullable=True)
    ncm_sugerido = Column(String(8), nullable=True)
    cest_atual = Column(String(10), nullable=True)
    cest_sugerido = Column(String(10), nullable=True)
    score = Column(Float, nullable=False)
    status = Column(String(30), nullable=False, index=True)
    motivo = Column(Text, nullable=False)
    fonte_referencia = Column(Text, nullable=True)
    versao_referencia = Column(String(80), nullable=True)
    cest_status = Column(String(30), nullable=True)
    cest_source_url = Column(Text, nullable=True)
    cest_evidence = Column(Text, nullable=True)
    reference_attempts = Column(JSON, nullable=False, default=list)
    reviewed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    audit = relationship("Audit", back_populates="items")
    reviewed_by = relationship("User")
