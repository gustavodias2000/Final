"""Códigos NCM confirmados pela empresa: importação por planilha, consulta e remoção."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.core.config import settings
from app.db.models import ConfirmedClassification, User
from app.schemas.confirmed_codes import ConfirmedCodeEntry, ConfirmedCodeImportResult, ConfirmedCodeList
from app.services.confirmed_codes import ORIGIN_IMPORT
from app.services.confirmed_store import ConfirmedInput, current_ncm_codes, upsert_confirmed
from app.services.excel_parser import parse_excel

router = APIRouter(prefix="/api/v1/confirmed-codes", tags=["Códigos confirmados"])
MAX_REPORTED_SKIPS = 20


@router.get("", response_model=ConfirmedCodeList)
def list_confirmed_codes(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConfirmedCodeList:
    base = db.query(ConfirmedClassification).filter(ConfirmedClassification.tenant_id == current_user.tenant_id)
    total = base.with_entities(func.count(ConfirmedClassification.id)).scalar() or 0
    query = base
    term = q.strip()
    if term:
        like = f"%{term}%"
        digits = "".join(char for char in term if char.isdigit())
        conditions = [ConfirmedClassification.descricao.ilike(like), ConfirmedClassification.codigo_produto.ilike(like)]
        if len(digits) >= 4:
            conditions.append(ConfirmedClassification.ncm.like(f"%{digits}%"))
        query = query.filter(or_(*conditions))
    rows = query.order_by(ConfirmedClassification.updated_at.desc(), ConfirmedClassification.id).limit(limit).all()
    return ConfirmedCodeList(total=total, data=[_to_entry(row) for row in rows])


@router.post("/import", response_model=ConfirmedCodeImportResult)
def import_confirmed_codes(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConfirmedCodeImportResult:
    """Importa uma planilha no mesmo modelo da auditoria; o NCM e o CEST informados são tidos como corretos."""
    filename = file.filename or "arquivo.xlsx"
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Envie um arquivo .xlsx.")

    spreadsheet = parse_excel(file.file, settings.max_upload_bytes)
    valid_codes = current_ncm_codes(db)
    entries: list[ConfirmedInput] = []
    skipped: list[str] = []
    for row_number, product in enumerate(spreadsheet.products, start=2):
        if not product.ncm_atual:
            skipped.append(f"Linha {row_number} ({product.descricao}): sem NCM.")
        elif valid_codes and product.ncm_atual not in valid_codes:
            skipped.append(f"Linha {row_number} ({product.descricao}): NCM {product.ncm_atual} não existe na tabela vigente.")
        else:
            entries.append(ConfirmedInput(product.codigo_produto, product.descricao, product.ncm_atual, product.cest_atual))

    created, updated = upsert_confirmed(db, current_user.tenant_id, entries, ORIGIN_IMPORT, current_user.id)
    db.commit()
    return ConfirmedCodeImportResult(
        importados=created,
        atualizados=updated,
        ignorados=len(skipped),
        motivos_ignorados=skipped[:MAX_REPORTED_SKIPS],
    )


@router.delete("/{code_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_confirmed_code(
    code_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    row = (
        db.query(ConfirmedClassification)
        .filter(ConfirmedClassification.id == code_id, ConfirmedClassification.tenant_id == current_user.tenant_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Código confirmado não encontrado.")
    db.delete(row)
    db.commit()


def _to_entry(row: ConfirmedClassification) -> ConfirmedCodeEntry:
    return ConfirmedCodeEntry(
        id=row.id,
        codigo_produto=row.codigo_produto,
        descricao=row.descricao,
        ncm=row.ncm,
        cest=row.cest,
        origem=row.origem,
        atualizado_em=row.updated_at,
    )
