"""Cliente da referência NCM oficial, com catálogo versionado em memória."""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Protocol

import requests

from app.services.ncm_matcher import normalize_ncm, normalize_text


class ReferenceSyncError(RuntimeError):
    """A referência externa não pôde ser obtida ou validada."""


class JsonHttpResponse(Protocol):
    headers: dict[str, str]

    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class JsonHttpClient(Protocol):
    def get(self, url: str, *, timeout: float, headers: dict[str, str]) -> JsonHttpResponse: ...


@dataclass(frozen=True)
class NcmCatalogEntry:
    codigo: str
    descricao: str


@dataclass(frozen=True)
class NcmCatalog:
    entries: tuple[NcmCatalogEntry, ...]
    source_url: str
    fetched_at: datetime
    version: str
    source_etag: str | None

    def matcher_pairs(self) -> list[tuple[str, str]]:
        return [(entry.codigo, entry.descricao) for entry in self.entries]


class SiscomexNcmCatalogClient:
    """Baixa e valida o JSON NCM sem persistir ou alterar a base local."""

    def __init__(
        self,
        source_url: str,
        timeout_seconds: float,
        http_client: JsonHttpClient | None = None,
    ):
        self.source_url = source_url
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client or requests.Session()

    def fetch(self) -> NcmCatalog:
        try:
            response = self.http_client.get(
                self.source_url,
                timeout=self.timeout_seconds,
                headers={"Accept": "application/json", "User-Agent": "AuditorNCM/1.0"},
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ReferenceSyncError("Não foi possível obter a referência NCM oficial.") from exc

        entries = self._parse_entries(payload)
        if not entries:
            raise ReferenceSyncError("A referência NCM recebida não contém registros válidos.")

        canonical_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        version = f"sha256:{sha256(canonical_payload.encode('utf-8')).hexdigest()}"
        headers = getattr(response, "headers", {}) or {}

        return NcmCatalog(
            entries=tuple(entries),
            source_url=self.source_url,
            fetched_at=datetime.now(timezone.utc),
            version=version,
            source_etag=headers.get("ETag"),
        )

    @staticmethod
    def _parse_entries(payload: Any) -> list[NcmCatalogEntry]:
        raw_entries = payload.get("Nomenclaturas", []) if isinstance(payload, dict) else payload
        if not isinstance(raw_entries, list):
            raise ReferenceSyncError("Formato inesperado da referência NCM.")

        entries: list[NcmCatalogEntry] = []
        seen_codes: set[str] = set()
        for raw in raw_entries:
            if not isinstance(raw, dict):
                continue
            codigo = normalize_ncm(raw.get("Codigo") or raw.get("codigo") or raw.get("NCM"))
            descricao = str(raw.get("Descricao") or raw.get("descricao") or "").strip()
            if not codigo or not normalize_text(descricao) or codigo in seen_codes:
                continue
            seen_codes.add(codigo)
            entries.append(NcmCatalogEntry(codigo=codigo, descricao=descricao))

        return entries
