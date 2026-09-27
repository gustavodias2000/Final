"""Importa um catálogo CEST local em versão imutável."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.models import CestReference, CestReferenceVersion
from app.db.session import SessionLocal, configure_database
from app.services.reference.cest_catalog import CestCatalog, load_catalog_file


@dataclass(frozen=True)
class CestSyncResult:
    version: str
    entries: int
    created: bool


def persist_catalog(catalog: CestCatalog, session_factory: sessionmaker = SessionLocal) -> CestSyncResult:
    db: Session = session_factory()
    try:
        existing = db.query(CestReferenceVersion).filter(CestReferenceVersion.version == catalog.version).first()
        if existing is not None:
            count = db.query(CestReference).filter(CestReference.reference_version_id == existing.id).count()
            return CestSyncResult(existing.version, count, False)

        version = CestReferenceVersion(
            id=uuid4(), source_url=catalog.source_url, version=catalog.version, fetched_at=catalog.fetched_at
        )
        db.add(version)
        db.flush()
        db.bulk_insert_mappings(
            CestReference,
            [
                {
                    "id": uuid4(),
                    "reference_version_id": version.id,
                    "ncm_codigo": entry.ncm_codigo,
                    "cest_codigo": entry.cest_codigo,
                    "descricao": entry.descricao,
                }
                for entry in catalog.entries
            ],
        )
        db.commit()
        return CestSyncResult(version.version, len(catalog.entries), True)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa uma referência CEST .csv ou .xlsx.")
    parser.add_argument("file", type=Path, help="Arquivo com as colunas ncm e cest; descricao é opcional.")
    parser.add_argument("--source-url", help="URL ou identificação oficial da fonte do arquivo.")
    parser.add_argument("--dry-run", action="store_true", help="Valida sem gravar no banco.")
    arguments = parser.parse_args()
    catalog = load_catalog_file(arguments.file, arguments.source_url)
    if arguments.dry_run:
        print(f"Referência CEST validada: {catalog.version} ({len(catalog.entries)} registros).")
        return
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL é obrigatória para gravar a referência CEST.")
    configure_database()
    result = persist_catalog(catalog)
    action = "criada" if result.created else "já existente"
    print(f"Referência CEST {action}: {result.version} ({result.entries} registros).")


if __name__ == "__main__":
    main()
