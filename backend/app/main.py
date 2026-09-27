from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import audit, auth
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


@app.get("/", tags=["Operação"])
def read_root() -> dict[str, str]:
    return {"service": settings.project_name, "status": "online"}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
