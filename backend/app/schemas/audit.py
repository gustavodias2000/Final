"""Contratos públicos da API de auditorias.

Estes modelos são deliberadamente independentes dos modelos SQLAlchemy. Eles
definem o formato estável exposto ao frontend e a futuros consumidores da API.
"""

from datetime import datetime
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


class CestCandidate(BaseModel):
    """Uma opção de CEST elegível para o NCM, segundo o catálogo versionado."""

    cest: str
    descricao: str | None = None
    score: float | None = Field(default=None, ge=0, le=100, description="Similaridade com a descrição do produto")


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
    cest_candidates: list[CestCandidate] = Field(default_factory=list)
    cest_escolhido: str | None = Field(default=None, description="CEST escolhido na revisão entre as opções")
    ncm_status: str | None = Field(default=None, description="valid, invalid ou missing; vazio em auditorias antigas")
    ncm_fonte: str | None = Field(default=None, description="catalogo ou tabela: de onde veio a sugestão de NCM")
    ncm_vizinhos: list[dict[str, object]] = Field(
        default_factory=list,
        description="Produtos parecidos do mesmo cadastro usados como evidência",
    )
    ncm_opcoes: list[dict[str, object]] = Field(
        default_factory=list,
        description="NCM extinto: códigos vigentes da mesma subposição, para escolha na revisão",
    )
    ncm_escolhido: str | None = Field(default=None, description="NCM escolhido na revisão entre as opções")


class AuditItemReviewRequest(BaseModel):
    decision: ReviewDecision
    cest_escolhido: str | None = Field(
        default=None,
        description="Somente na aprovação: um dos CESTs listados em cest_candidates.",
    )
    ncm_escolhido: str | None = Field(
        default=None,
        description="Somente na aprovação: um dos NCMs listados em ncm_opcoes (NCM extinto).",
    )


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
    iniciada_em: datetime | None = Field(
        default=None,
        description="Quando um worker começou a analisar; vazio enquanto a auditoria espera na fila.",
    )
    errors: list[str] = []


class AuditHistoryEntry(BaseModel):
    """Uma auditoria anterior, sem os itens, para a lista de histórico."""

    audit_id: UUID
    arquivo: str
    status: AuditStatus
    criada_em: datetime
    concluida_em: datetime | None = None
    total_produtos: int = Field(ge=0)
    pendentes: int = Field(ge=0)
    aprovados: int = Field(ge=0)
    rejeitados: int = Field(ge=0)
    sem_sugestao: int = Field(ge=0)


class ApiError(BaseModel):
    code: str
    message: str
    details: list[str] = []
