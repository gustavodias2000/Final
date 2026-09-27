"""Sessão SQLAlchemy inicializada somente depois de validar o ambiente."""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

Base = declarative_base()
SessionLocal = sessionmaker(autoflush=False, autocommit=False)
_engine: Engine | None = None


def configure_database() -> Engine:
    """Configura o pool uma única vez, após a validação de Settings."""
    global _engine

    if _engine is None:
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
        SessionLocal.configure(bind=_engine)

    return _engine
