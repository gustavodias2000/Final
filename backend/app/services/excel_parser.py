"""Validação do arquivo Excel de entrada da auditoria."""

from dataclasses import dataclass
from hashlib import sha256
from io import BufferedIOBase, BytesIO
import re
import unicodedata

import pandas as pd

from app.services.audit_engine import ProductForAudit
from app.services.ncm_matcher import normalize_ncm

REQUIRED_COLUMNS = ("codigo_produto", "descricao", "ncm_atual", "cest_atual")
CEST_PATTERN = re.compile(r"^\d{2}\.\d{3}\.\d{2}$")
MAX_REPORTED_ERRORS = 100


@dataclass(frozen=True)
class SpreadsheetError:
    row: int | None
    field: str | None
    message: str

    def display(self) -> str:
        location = f"Linha {self.row}" if self.row else "Arquivo"
        field = f" ({self.field})" if self.field else ""
        return f"{location}{field}: {self.message}"


class SpreadsheetValidationError(ValueError):
    def __init__(self, errors: list[SpreadsheetError]):
        self.errors = errors
        super().__init__("Planilha inválida.")


@dataclass(frozen=True)
class ParsedSpreadsheet:
    products: tuple[ProductForAudit, ...]
    total_rows: int
    source_sha256: str
    source_size_bytes: int


def parse_excel(file: BufferedIOBase, max_bytes: int) -> ParsedSpreadsheet:
    size = _validate_size(file, max_bytes)
    try:
        content = file.read()
        dataframe = pd.read_excel(BytesIO(content), dtype=str, keep_default_na=False)
    except Exception as exc:
        raise SpreadsheetValidationError(
            [SpreadsheetError(None, None, "Não foi possível ler um arquivo Excel válido.")]
        ) from exc

    dataframe.columns = [_normalize_header(column) for column in dataframe.columns]
    missing = [column for column in REQUIRED_COLUMNS if column not in dataframe.columns]
    if missing:
        raise SpreadsheetValidationError(
            [SpreadsheetError(None, column, "Coluna obrigatória ausente.") for column in missing]
        )

    products: list[ProductForAudit] = []
    errors: list[SpreadsheetError] = []
    for index, row in dataframe.loc[:, list(REQUIRED_COLUMNS)].iterrows():
        row_number = int(index) + 2
        product, row_errors = _parse_row(row_number, row.to_dict())
        if row_errors:
            errors.extend(row_errors)
            if len(errors) >= MAX_REPORTED_ERRORS:
                errors.append(SpreadsheetError(None, None, "Limite de erros exibidos atingido."))
                break
        elif product:
            products.append(product)

    if errors:
        raise SpreadsheetValidationError(errors[: MAX_REPORTED_ERRORS + 1])
    if not products:
        raise SpreadsheetValidationError([SpreadsheetError(None, None, "A planilha não contém produtos.")])

    return ParsedSpreadsheet(
        products=tuple(products),
        total_rows=len(products),
        source_sha256=sha256(content).hexdigest(),
        source_size_bytes=size,
    )


def _validate_size(file: BufferedIOBase, max_bytes: int) -> int:
    try:
        file.seek(0, 2)
        size = file.tell()
        file.seek(0)
    except (AttributeError, OSError) as exc:
        raise SpreadsheetValidationError([SpreadsheetError(None, None, "Não foi possível validar o arquivo.")]) from exc

    if size > max_bytes:
        raise SpreadsheetValidationError(
            [SpreadsheetError(None, None, f"Arquivo excede o limite de {max_bytes} bytes.")]
        )
    return size


def _parse_row(row_number: int, row: dict[str, object]) -> tuple[ProductForAudit | None, list[SpreadsheetError]]:
    codigo = _text(row["codigo_produto"])
    descricao = _text(row["descricao"])
    ncm_informado = _text(row["ncm_atual"])
    ncm = normalize_ncm(ncm_informado)
    cest = _normalize_cest(_text(row["cest_atual"]))
    errors: list[SpreadsheetError] = []

    if not codigo:
        errors.append(SpreadsheetError(row_number, "codigo_produto", "Valor obrigatório."))
    if not descricao:
        errors.append(SpreadsheetError(row_number, "descricao", "Valor obrigatório."))
    if ncm_informado and not ncm:
        errors.append(SpreadsheetError(row_number, "ncm_atual", "Deve conter 8 dígitos."))
    if _text(row["cest_atual"]) and cest is None:
        errors.append(SpreadsheetError(row_number, "cest_atual", "Use o formato 00.000.00."))

    if errors:
        return None, errors
    return ProductForAudit(codigo, descricao, ncm, cest or None), []


def _normalize_cest(value: str) -> str | None:
    """Aceita CEST pontuado ou apenas numérico, sem perder zeros à esquerda."""
    if not value:
        return ""
    # Alguns ERPs exportam campos vazios como "  .   .  ". Isso não é um
    # CEST informado e deve ter o mesmo tratamento de uma célula em branco.
    if re.fullmatch(r"[.\s]+", value):
        return ""
    if CEST_PATTERN.fullmatch(value):
        return value

    digits = re.sub(r"\D", "", value)
    if len(digits) > 7 or not digits or re.search(r"[A-Za-z]", value):
        return None
    digits = digits.zfill(7)
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:]}"


def _normalize_header(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", normalized).strip("_").lower()
    return normalized


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""
