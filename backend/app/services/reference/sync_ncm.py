"""Sincroniza uma versão imutável da referência NCM no PostgreSQL."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.models import NCM, NcmReferenceVersion
from app.db.session import SessionLocal, configure_database
from app.services.reference.ncm_catalog import NcmCatalog, SiscomexNcmCatalogClient


@dataclass(frozen=True)
class NcmSyncResult:
    version: str
    entries: int
    created: bool


def persist_catalog(
    catalog: NcmCatalog,
    session_factory: sessionmaker = SessionLocal,
) -> NcmSyncResult:
    """Persiste o catálogo uma única vez, identificado pelo hash do conteúdo."""
    db: Session = session_factory()
    try:
        existing = db.query(NcmReferenceVersion).filter(NcmReferenceVersion.version == catalog.version).first()
        if existing is not None:
            count = db.query(NCM).filter(NCM.reference_version_id == existing.id).count()
            return NcmSyncResult(version=existing.version, entries=count, created=False)

        version = NcmReferenceVersion(
            id=uuid4(),
            source_url=catalog.source_url,
            source_etag=catalog.source_etag,
            version=catalog.version,
            fetched_at=catalog.fetched_at,
        )
        db.add(version)
        db.flush()
        db.bulk_insert_mappings(
            NCM,
            [
                {
                    "id": uuid4(),
                    "reference_version_id": version.id,
                    "codigo": entry.codigo,
                    "descricao": entry.descricao,
                }
                for entry in catalog.entries
            ],
        )
        db.commit()
        return NcmSyncResult(version=version.version, entries=len(catalog.entries), created=True)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def sync_ncm(
    session_factory: sessionmaker = SessionLocal,
    client: SiscomexNcmCatalogClient | None = None,
) -> NcmSyncResult:
    catalog_client = client or SiscomexNcmCatalogClient(
        settings.siscomex_ncm_url,
        settings.external_request_timeout_seconds,
    )
    return persist_catalog(catalog_client.fetch(), session_factory)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza a referência NCM oficial no PostgreSQL.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Baixa e valida a referência sem gravar no banco.",
    )
    arguments = parser.parse_args()
    client = SiscomexNcmCatalogClient(
        settings.siscomex_ncm_url,
        settings.external_request_timeout_seconds,
    )
    catalog = client.fetch()
    if arguments.dry_run:
        print(f"Referência NCM validada: {catalog.version} ({len(catalog.entries)} registros).")
        return

    if not settings.database_url:
        raise RuntimeError("DATABASE_URL é obrigatória para gravar a referência NCM.")
    configure_database()
    result = persist_catalog(catalog)
    action = "criada" if result.created else "já existente"
    print(f"Referência NCM {action}: {result.version} ({result.entries} registros).")


if __name__ == "__main__":
    main()
