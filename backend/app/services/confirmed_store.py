"""Gravação dos códigos confirmados da empresa (aprovação na revisão e importação)."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.db.models import NCM, ConfirmedClassification, NcmReferenceVersion
from app.services.confirmed_codes import product_code_key
from app.services.ncm_matcher import matching_text, normalize_ncm


@dataclass(frozen=True)
class ConfirmedInput:
    codigo_produto: str | None
    descricao: str
    ncm: str
    cest: str | None


def current_ncm_codes(db: Session) -> set[str]:
    """Códigos da versão mais recente da tabela NCM (vazio se nenhuma foi sincronizada)."""
    latest = db.query(NcmReferenceVersion.id).order_by(NcmReferenceVersion.fetched_at.desc()).limit(1).scalar()
    if latest is None:
        return set()
    return {code for (code,) in db.query(NCM.codigo).filter(NCM.reference_version_id == latest)}


def ncm_exists(db: Session, ncm: str) -> bool:
    latest = db.query(NcmReferenceVersion.id).order_by(NcmReferenceVersion.fetched_at.desc()).limit(1).scalar()
    query = db.query(func.count(NCM.id)).filter(NCM.codigo == ncm)
    if latest is not None:
        query = query.filter(NCM.reference_version_id == latest)
    return bool(query.scalar())


def upsert_confirmed(
    db: Session,
    tenant_id: UUID,
    entries: list[ConfirmedInput],
    origem: str,
    user_id: UUID | None,
) -> tuple[int, int]:
    """Cria ou atualiza códigos confirmados; devolve (criados, atualizados). Não faz commit.

    O produto é identificado pelo código (normalizado) ou, sem código, pela descrição normalizada.
    Os registros já existentes desses produtos são lidos numa consulta só, para não fazer uma ida
    ao banco por linha.
    """
    codes = {key for entry in entries if (key := product_code_key(entry.codigo_produto))}
    keys = {matching_text(entry.descricao) for entry in entries if not product_code_key(entry.codigo_produto)}
    existing = (
        db.query(ConfirmedClassification)
        .filter(
            ConfirmedClassification.tenant_id == tenant_id,
            or_(
                ConfirmedClassification.codigo_produto.in_(codes or {""}),
                and_(ConfirmedClassification.codigo_produto.is_(None), ConfirmedClassification.descricao_chave.in_(keys or {""})),
            ),
        )
        .all()
    )
    by_code = {row.codigo_produto: row for row in existing if row.codigo_produto}
    by_description = {row.descricao_chave: row for row in existing if not row.codigo_produto}
    created = updated = 0
    for entry in entries:
        ncm = normalize_ncm(entry.ncm)
        if not ncm:
            continue
        code = product_code_key(entry.codigo_produto)
        key = matching_text(entry.descricao)
        row = by_code.get(code) if code else by_description.get(key)
        if row is None:
            row = ConfirmedClassification(tenant_id=tenant_id, codigo_produto=code, created_by_user_id=user_id)
            db.add(row)
            if code:
                by_code[code] = row
            else:
                by_description[key] = row
            created += 1
        else:
            updated += 1
        row.descricao = entry.descricao
        row.descricao_chave = key
        row.ncm = ncm
        row.cest = entry.cest or None
        row.origem = origem
    return created, updated
