from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import audit, auth
from app.api.dependencies import get_db
from app.core.config import settings
from app.db.session import configure_database
from app.schemas.audit import ApiError
from app.services.excel_parser import SpreadsheetValidationError


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate()
    configure_database()
    yield


app = FastAPI(title=settings.project_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# A auditoria completa vem com todos os itens e evidências; comprimida, chega bem mais rápido.
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(audit.router)


@app.exception_handler(SpreadsheetValidationError)
def spreadsheet_validation_error(_: Request, exc: SpreadsheetValidationError) -> JSONResponse:
    payload = ApiError(
        code="invalid_spreadsheet",
        message="A planilha não passou na validação.",
        details=[error.display() for error in exc.errors],
    )
    return JSONResponse(status_code=422, content=payload.model_dump())


@app.get("/health", tags=["Operação"])
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


# Diferente de /health (usado pela Render para saber se o processo está vivo), este
# consulta o banco. Chamado de tempos em tempos, mantém a API e o Supabase acordados.
@app.get("/health/db", tags=["Operação"])
def health_db(db: Session = Depends(get_db)) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "unreachable"})
    return JSONResponse(content={"status": "ok", "database": "ok"})


@app.get("/", tags=["Operação"])
def read_root() -> dict[str, str]:
    return {"service": settings.project_name, "status": "online"}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
