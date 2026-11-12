"""Contratos da API de códigos confirmados."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ConfirmedCodeEntry(BaseModel):
    id: UUID
    codigo_produto: str | None = None
    descricao: str
    ncm: str
    cest: str | None = None
    origem: str = Field(description="aprovacao (decisão na revisão) ou importacao (planilha)")
    atualizado_em: datetime


class ConfirmedCodeList(BaseModel):
    total: int = Field(ge=0, description="Total de códigos confirmados da empresa, sem o filtro de busca")
    data: list[ConfirmedCodeEntry]


class ConfirmedCodeImportResult(BaseModel):
    importados: int = Field(ge=0)
    atualizados: int = Field(ge=0)
    ignorados: int = Field(ge=0)
    motivos_ignorados: list[str] = Field(default_factory=list, description="Até 20 linhas ignoradas e o motivo")
