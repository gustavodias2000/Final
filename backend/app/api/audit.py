from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.core.config import settings
from app.db.models import Audit, AuditInputItem, AuditItem, User
from app.schemas.audit import (
    AuditItemResponse,
    AuditItemReviewRequest,
    AuditProgress,
    AuditStatus,
    AuditSummary,
    AuditUploadResponse,
)
from app.services.excel_parser import parse_excel

router = APIRouter(prefix="/api/v1/audits", tags=["Auditorias"])
INPUT_INSERT_BATCH_SIZE = 500


@router.post("/upload", response_model=AuditUploadResponse, status_code=status.HTTP_202_ACCEPTED)
def upload(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuditUploadResponse:
    filename = file.filename or "arquivo-sem-nome.xlsx"
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Envie um arquivo .xlsx.")

    spreadsheet = parse_excel(file.file, settings.max_upload_bytes)
    audit = Audit(
        tenant_id=current_user.tenant_id,
        source_filename=filename,
        source_file_sha256=spreadsheet.source_sha256,
        source_file_size_bytes=spreadsheet.source_size_bytes,
        status=AuditStatus.PROCESSING.value,
        total_produtos=spreadsheet.total_rows,
        processados=0,
        errors=[],
    )
    db.add(audit)
    db.flush()
    _persist_input_items(db, audit.id, spreadsheet.products)
    db.commit()
    db.refresh(audit)
    return _to_response(audit, [])


@router.get("/latest", response_model=AuditUploadResponse)
def get_latest_audit(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuditUploadResponse:
    """Recupera a auditoria mais recente do tenant para retomar o dashboard."""
    audit = (
        db.query(Audit)
        .filter(Audit.tenant_id == current_user.tenant_id)
        .order_by(Audit.created_at.desc())
        .first()
    )
    if audit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhuma auditoria encontrada.")
    return _to_response(audit, audit.items)


def _persist_input_items(db: Session, audit_id: UUID, products: tuple) -> None:
    """Persiste uploads grandes em lotes, compatíveis com poolers PostgreSQL."""
    mappings = [
        {
            "id": uuid4(),
            "audit_id": audit_id,
            "row_number": row_number,
            "codigo_produto": product.codigo_produto,
            "descricao": product.descricao,
            "ncm_atual": product.ncm_atual,
            "cest_atual": product.cest_atual,
        }
        for row_number, product in enumerate(products, start=1)
    ]
    for start in range(0, len(mappings), INPUT_INSERT_BATCH_SIZE):
        db.bulk_insert_mappings(AuditInputItem, mappings[start : start + INPUT_INSERT_BATCH_SIZE])


@router.get("/{audit_id}", response_model=AuditUploadResponse)
def get_audit(
    audit_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuditUploadResponse:
    audit = _get_tenant_audit(db, audit_id, current_user.tenant_id)
    return _to_response(audit, audit.items)


@router.post("/{audit_id}/items/{item_id}/review", response_model=AuditItemResponse)
def review_audit_item(
    audit_id: UUID,
    item_id: UUID,
    request: AuditItemReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuditItemResponse:
    _get_tenant_audit(db, audit_id, current_user.tenant_id)
    item = db.query(AuditItem).filter(AuditItem.id == item_id, AuditItem.audit_id == audit_id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item de auditoria não encontrado.")
    if item.status not in {"suggested", "pending_review"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Item não está disponível para revisão.")

    item.status = request.decision.value
    item.reviewed_by_user_id = current_user.id
    item.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return _to_item_response(item)


def _get_tenant_audit(db: Session, audit_id: UUID, tenant_id: UUID) -> Audit:
    audit = db.query(Audit).filter(Audit.id == audit_id, Audit.tenant_id == tenant_id).first()
    if audit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auditoria não encontrada.")
    return audit


def _to_response(audit: Audit, items: list[AuditItem]) -> AuditUploadResponse:
    responses = [_to_item_response(item) for item in items]
    suggestions = sum(item.status.value == "suggested" for item in responses)
    return AuditUploadResponse(
        audit_id=audit.id,
        status=AuditStatus(audit.status),
        arquivo=audit.source_filename,
        resumo=AuditSummary(
            total_produtos=audit.total_produtos,
            itens_com_sugestao=suggestions,
            itens_sem_sugestao=sum(item.status.value == "no_suggestion" for item in responses),
        ),
        data=responses,
        progresso=AuditProgress(processados=audit.processados, total=audit.total_produtos),
        errors=audit.errors or [],
    )


def _to_item_response(item: AuditItem) -> AuditItemResponse:
    return AuditItemResponse(
        id=item.id,
        codigo_produto=item.codigo_produto,
        descricao=item.descricao,
        ncm_atual=item.ncm_atual,
        ncm_sugerido=item.ncm_sugerido,
        cest_atual=item.cest_atual,
        cest_sugerido=item.cest_sugerido,
        score=item.score,
        status=item.status,
        motivo=item.motivo,
        fonte_referencia=item.fonte_referencia,
        versao_referencia=item.versao_referencia,
        cest_status=item.cest_status,
        cest_source_url=item.cest_source_url,
        cest_evidence=item.cest_evidence,
        reference_attempts=item.reference_attempts or [],
    )
