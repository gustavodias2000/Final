"""Catálogo CEST local, versionado e importado explicitamente."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Protocol

import pandas as pd
import requests

from app.services.ncm_matcher import normalize_text


class CestCatalogError(RuntimeError):
    """O arquivo de referência CEST não possui registros utilizáveis."""


class JsonHttpResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class JsonHttpClient(Protocol):
    def get(self, url: str, *, timeout: float, headers: dict[str, str]) -> JsonHttpResponse: ...


@dataclass(frozen=True)
class CestCatalogEntry:
    ncm_codigo: str
    cest_codigo: str
    descricao: str | None


@dataclass(frozen=True)
class CestCatalog:
    entries: tuple[CestCatalogEntry, ...]
    source_url: str
    fetched_at: datetime
    version: str


def normalize_cest(value: object) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 6:
        digits = digits.zfill(7)
    if len(digits) != 7:
        return None
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:]}"


def normalize_ncm_prefix(value: object) -> str | None:
    """Normaliza NCM completo ou prefixo publicado nas tabelas CEST."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if 2 <= len(digits) <= 8 else None


def build_catalog(rows: Iterable[Mapping[str, object]], source_url: str) -> CestCatalog:
    entries: list[CestCatalogEntry] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        ncm = normalize_ncm_prefix(_get_value(row, "ncm", "ncm_codigo", "codigo_ncm"))
        cest = normalize_cest(_get_value(row, "cest", "cest_codigo", "codigo_cest"))
        descricao_value = _get_value(row, "descricao", "descrição", "descricao_cest")
        descricao = str(descricao_value).strip() if descricao_value is not None else None
        descricao = descricao if descricao and normalize_text(descricao) else None
        if not ncm or not cest or (ncm, cest) in seen:
            continue
        seen.add((ncm, cest))
        entries.append(CestCatalogEntry(ncm, cest, descricao))

    if not entries:
        raise CestCatalogError("O arquivo CEST não contém pares NCM/CEST válidos.")

    entries.sort(key=lambda item: (item.ncm_codigo, item.cest_codigo, item.descricao or ""))
    payload = [
        {"ncm": item.ncm_codigo, "cest": item.cest_codigo, "descricao": item.descricao}
        for item in entries
    ]
    version = f"sha256:{sha256(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()}"
    return CestCatalog(tuple(entries), source_url, datetime.now(timezone.utc), version)


def load_catalog_file(path: str | Path, source_url: str | None = None) -> CestCatalog:
    file_path = Path(path)
    if not file_path.is_file():
        raise CestCatalogError(f"Arquivo CEST não encontrado: {file_path}")
    if file_path.suffix.lower() == ".csv":
        frame = pd.read_csv(file_path, dtype=str, keep_default_na=False)
    elif file_path.suffix.lower() == ".xlsx":
        frame = pd.read_excel(file_path, dtype=str, keep_default_na=False)
    else:
        raise CestCatalogError("Use um arquivo CEST .csv ou .xlsx.")
    return build_catalog(frame.to_dict(orient="records"), source_url or file_path.resolve().as_uri())


def load_catalog_url(
    source_url: str,
    timeout_seconds: float,
    http_client: JsonHttpClient | None = None,
) -> CestCatalog:
    """Baixa e valida um catálogo JSON antes de qualquer gravação no banco."""
    client = http_client or requests.Session()
    try:
        response = client.get(
            source_url,
            timeout=timeout_seconds,
            headers={"Accept": "application/json", "User-Agent": "AuditorNCM/1.0"},
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise CestCatalogError("Não foi possível obter o catálogo CEST remoto.") from exc

    rows = payload.get("dados") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise CestCatalogError("Formato inesperado do catálogo CEST remoto.")
    return build_catalog(rows, source_url)


def _get_value(row: Mapping[str, object], *names: str) -> object | None:
    normalized = {normalize_text(key).replace(" ", "_"): value for key, value in row.items()}
    for name in names:
        value = normalized.get(normalize_text(name).replace(" ", "_"))
        if value not in (None, ""):
            return value
    return None
