"""Contratos públicos da API de auditorias.

Estes modelos são deliberadamente independentes dos modelos SQLAlchemy. Eles
definem o formato estável exposto ao frontend e a futuros consumidores da API.
"""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class AuditStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AuditItemStatus(str, Enum):
    SUGGESTED = "suggested"
    NO_SUGGESTION = "no_suggestion"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class AuditItemResponse(BaseModel):
    """Uma recomendação para um produto, ainda sujeita a revisão humana."""

    id: UUID
    codigo_produto: str = Field(description="Identificador informado no arquivo")
    descricao: str
    ncm_atual: str | None = None
    ncm_sugerido: str | None = None
    cest_atual: str | None = None
    cest_sugerido: str | None = None
    score: float = Field(ge=0, le=100)
    status: AuditItemStatus
    motivo: str
    fonte_referencia: str | None = None
    versao_referencia: str | None = None
    cest_status: str | None = None
    cest_source_url: str | None = None
    cest_evidence: str | None = None
    reference_attempts: list[dict[str, object]] = Field(default_factory=list)


class AuditItemReviewRequest(BaseModel):
    decision: ReviewDecision


class AuditSummary(BaseModel):
    total_produtos: int = Field(ge=0)
    itens_com_sugestao: int = Field(ge=0)
    itens_sem_sugestao: int = Field(ge=0)


class AuditProgress(BaseModel):
    processados: int = Field(ge=0)
    total: int = Field(ge=0)


class AuditUploadResponse(BaseModel):
    """Resposta uniforme do upload de uma auditoria."""

    audit_id: UUID
    status: AuditStatus
    arquivo: str
    resumo: AuditSummary
    data: list[AuditItemResponse]
    progresso: AuditProgress
    errors: list[str] = []


class ApiError(BaseModel):
    code: str
    message: str
    details: list[str] = []
