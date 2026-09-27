"""Consulta CEST com cache efêmero e resultado que preserva proveniência."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from time import monotonic
from typing import Protocol

import requests
from bs4 import BeautifulSoup

from app.services.ncm_matcher import normalize_ncm

CEST_PATTERN = re.compile(r"\b\d{2}\.\d{3}\.\d{2}\b")


class CestLookupStatus(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    INVALID_NCM = "invalid_ncm"
    UNAVAILABLE = "unavailable"


class HtmlHttpResponse(Protocol):
    text: str

    def raise_for_status(self) -> None: ...


class HtmlHttpClient(Protocol):
    def get(self, url: str, *, timeout: float, headers: dict[str, str]) -> HtmlHttpResponse: ...


@dataclass(frozen=True)
class CestLookupResult:
    status: CestLookupStatus
    ncm: str | None
    cest_codes: tuple[str, ...]
    source_url: str | None
    checked_at: datetime
    evidence: str | None

    @property
    def suggested_cest(self) -> str | None:
        """Só sugere CEST quando a fonte apresenta exatamente um código."""
        return self.cest_codes[0] if len(self.cest_codes) == 1 else None


@dataclass
class _CacheEntry:
    expires_at: float
    result: CestLookupResult


class CestLookupClient:
    def __init__(
        self,
        url_template: str,
        timeout_seconds: float,
        cache_ttl_seconds: int,
        http_client: HtmlHttpClient | None = None,
    ):
        self.url_template = url_template
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.http_client = http_client or requests.Session()
        self._cache: dict[str, _CacheEntry] = {}

    def lookup(self, ncm: object) -> CestLookupResult:
        codigo = normalize_ncm(ncm)
        if not codigo:
            return self._result(CestLookupStatus.INVALID_NCM, None, (), None, None)

        cached = self._cache.get(codigo)
        if cached and cached.expires_at > monotonic():
            return cached.result

        formatted_ncm = f"{codigo[:4]}.{codigo[4:6]}.{codigo[6:]}"
        source_url = self.url_template.format(ncm=formatted_ncm)
        try:
            response = self.http_client.get(
                source_url,
                timeout=self.timeout_seconds,
                headers={"User-Agent": "AuditorNCM/1.0", "Accept": "text/html"},
            )
            response.raise_for_status()
        except requests.RequestException:
            return self._result(CestLookupStatus.UNAVAILABLE, codigo, (), source_url, None)

        text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
        codes = tuple(sorted(set(CEST_PATTERN.findall(text))))
        status = CestLookupStatus.FOUND if codes else CestLookupStatus.NOT_FOUND
        result = self._result(status, codigo, codes, source_url, text[:500] or None)
        self._cache[codigo] = _CacheEntry(monotonic() + self.cache_ttl_seconds, result)
        return result

    @staticmethod
    def _result(
        status: CestLookupStatus,
        ncm: str | None,
        codes: tuple[str, ...],
        source_url: str | None,
        evidence: str | None,
    ) -> CestLookupResult:
        return CestLookupResult(
            status=status,
            ncm=ncm,
            cest_codes=codes,
            source_url=source_url,
            checked_at=datetime.now(timezone.utc),
            evidence=evidence,
        )
