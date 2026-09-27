"""Cadeia resiliente de consulta de referências NCM/CEST por código exato."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import monotonic, sleep
from typing import Callable, Protocol
from urllib.parse import quote

import requests

from app.services.ncm_matcher import normalize_ncm
from app.services.reference.cest_catalog import normalize_cest


class LookupState(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class ReferenceAttempt:
    source: str
    state: LookupState
    source_url: str | None = None
    detail: str | None = None
    ncm_description: str | None = None
    cest_codes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "state": self.state.value,
            "source_url": self.source_url,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ReferenceLookupResult:
    ncm: str
    attempt: ReferenceAttempt
    attempts: tuple[ReferenceAttempt, ...]


class ExactNcmProvider(Protocol):
    def lookup(self, ncm: str) -> ReferenceAttempt: ...


class TabelasFiscaisProvider:
    name = "tabelas_fiscais_api"

    def __init__(self, base_url: str, timeout_seconds: float, http_client=None):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client or requests.Session()

    def lookup(self, ncm: str) -> ReferenceAttempt:
        url = f"{self.base_url}/ncm/{ncm}"
        try:
            response = self.http_client.get(url, timeout=self.timeout_seconds, headers={"Accept": "application/json"})
            if response.status_code == 404:
                return ReferenceAttempt(self.name, LookupState.NOT_FOUND, url, "NCM não localizado na fonte.")
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return ReferenceAttempt(self.name, LookupState.UNAVAILABLE, url, "Falha técnica na consulta.")

        if not isinstance(payload, dict):
            return ReferenceAttempt(self.name, LookupState.UNAVAILABLE, url, "Resposta inválida da fonte.")
        cests = tuple(
            sorted(
                {
                    normalized
                    for item in payload.get("cest", [])
                    if isinstance(item, dict)
                    for normalized in [normalize_cest(item.get("cest"))]
                    if normalized
                }
            )
        )
        return ReferenceAttempt(
            self.name,
            LookupState.FOUND,
            url,
            "Consulta concluída.",
            str(payload.get("descricao") or "").strip() or None,
            cests,
        )


class NcmApiProvider:
    name = "ncm_api_br"

    def __init__(self, base_url: str, api_key: str, timeout_seconds: float, http_client=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client or requests.Session()

    def lookup(self, ncm: str) -> ReferenceAttempt:
        if not self.api_key:
            return ReferenceAttempt(self.name, LookupState.UNAVAILABLE, detail="NCM_API_KEY não configurada.")
        url = f"{self.base_url}/ncm/{ncm}"
        try:
            response = self.http_client.get(
                url,
                timeout=self.timeout_seconds,
                headers={"Accept": "application/json", "X-API-Key": self.api_key},
            )
            if response.status_code == 404:
                return ReferenceAttempt(self.name, LookupState.NOT_FOUND, url, "NCM não localizado na fonte.")
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return ReferenceAttempt(self.name, LookupState.UNAVAILABLE, url, "Falha técnica na consulta.")
        if not isinstance(payload, dict):
            return ReferenceAttempt(self.name, LookupState.UNAVAILABLE, url, "Resposta inválida da fonte.")
        return ReferenceAttempt(
            self.name,
            LookupState.PARTIAL,
            url,
            "NCM validado; esta fonte não é usada como referência CEST.",
            str(payload.get("descricao") or "").strip() or None,
        )


class AzxManualProvider:
    name = "azx_consulta_manual"
    url = "https://azxcontabilidade.com.br/ferramentas/consulta-cest-ncm"

    def lookup(self, ncm: str) -> ReferenceAttempt:
        return ReferenceAttempt(
            self.name,
            LookupState.MANUAL_REVIEW,
            f"{self.url}?q={quote(ncm)}",
            "Fonte sem API pública documentada; consulta manual necessária.",
        )


class LocalCatalogProvider:
    name = "siscomex_catalogo_local"

    def __init__(self, cest_by_ncm: dict[str, tuple[str, ...]], source_url: str | None, version: str | None):
        self.cest_by_ncm = cest_by_ncm
        self.source_url = source_url
        self.version = version

    def lookup(self, ncm: str) -> ReferenceAttempt:
        if not self.version:
            return ReferenceAttempt(self.name, LookupState.UNAVAILABLE, detail="Catálogo CEST local indisponível.")
        candidates = tuple(sorted(set(self.cest_by_ncm.get(ncm, ()))))
        detail = f"Catálogo local CEST {self.version or 'sem versão'}"
        if candidates:
            return ReferenceAttempt(self.name, LookupState.FOUND, self.source_url, detail, cest_codes=candidates)
        return ReferenceAttempt(self.name, LookupState.NOT_FOUND, self.source_url, detail)


class FallbackReferenceLookup:
    """Executa a ordem de fontes e reinicia após indisponibilidade técnica total."""

    def __init__(
        self,
        providers: tuple[ExactNcmProvider, ...],
        retry_seconds: int = 70,
        full_retry_seconds: int = 120,
        max_cycles: int = 3,
        require_cest: bool = False,
        sleep_fn: Callable[[float], None] = sleep,
        clock_fn: Callable[[], float] = monotonic,
    ):
        if len(providers) < 2:
            raise ValueError("A cadeia requer Tabelas Fiscais e NCM.api.br.")
        self.providers = providers
        self.retry_seconds = retry_seconds
        self.full_retry_seconds = full_retry_seconds
        self.max_cycles = max_cycles
        self.require_cest = require_cest
        self.sleep_fn = sleep_fn
        self.clock_fn = clock_fn

    def lookup(self, ncm: object) -> ReferenceLookupResult:
        return self._lookup_two_stage(ncm)

        normalized_ncm = normalize_ncm(ncm)
        if not normalized_ncm:
            invalid = ReferenceAttempt("router", LookupState.NOT_FOUND, detail="NCM inválido.")
            return ReferenceLookupResult("", invalid, (invalid,))

        attempts: list[ReferenceAttempt] = []
        preferred: ReferenceAttempt | None = None
        for cycle in range(self.max_cycles):
            for provider in self.providers:
                attempt = provider.lookup(normalized_ncm)
                attempts.append(attempt)
                if attempt.state is LookupState.FOUND:
                    return ReferenceLookupResult(normalized_ncm, attempt, tuple(attempts))
                if attempt.state is LookupState.NOT_FOUND:
                    return ReferenceLookupResult(normalized_ncm, preferred or attempt, tuple(attempts))
                if attempt.state is LookupState.PARTIAL:
                    preferred = preferred or attempt
            if preferred is not None and not self.require_cest:
                return ReferenceLookupResult(normalized_ncm, preferred, tuple(attempts))
            if cycle < self.max_cycles - 1:
                self.sleep_fn(self.retry_seconds)

        unavailable = preferred or ReferenceAttempt("router", LookupState.UNAVAILABLE, detail="Fontes indisponíveis.")
        return ReferenceLookupResult(normalized_ncm, unavailable, tuple(attempts))

    def _lookup_two_stage(self, ncm: object) -> ReferenceLookupResult:
        normalized_ncm = normalize_ncm(ncm)
        if not normalized_ncm:
            invalid = ReferenceAttempt("router", LookupState.NOT_FOUND, detail="NCM inválido.")
            return ReferenceLookupResult("", invalid, (invalid,))

        attempts: list[ReferenceAttempt] = []
        preferred: ReferenceAttempt | None = None
        primary, secondary, *fallbacks = self.providers

        for cycle in range(self.max_cycles):
            first_failure_at = self.clock_fn()
            first = primary.lookup(normalized_ncm)
            attempts.append(first)
            if first.state is not LookupState.UNAVAILABLE:
                return ReferenceLookupResult(normalized_ncm, first, tuple(attempts))

            second = secondary.lookup(normalized_ncm)
            attempts.append(second)
            if second.state in {LookupState.FOUND, LookupState.NOT_FOUND}:
                return ReferenceLookupResult(normalized_ncm, second, tuple(attempts))
            if second.state is LookupState.PARTIAL:
                preferred = second
                fallback_result = self._consult_fallbacks(normalized_ncm, fallbacks, attempts, preferred)
                return ReferenceLookupResult(normalized_ncm, fallback_result, tuple(attempts))

            self._wait_from(first_failure_at, self.retry_seconds)

            second_primary_failure_at = self.clock_fn()
            retry_primary = primary.lookup(normalized_ncm)
            attempts.append(retry_primary)
            if retry_primary.state is not LookupState.UNAVAILABLE:
                return ReferenceLookupResult(normalized_ncm, retry_primary, tuple(attempts))

            retry_secondary = secondary.lookup(normalized_ncm)
            attempts.append(retry_secondary)
            if retry_secondary.state in {LookupState.FOUND, LookupState.NOT_FOUND}:
                return ReferenceLookupResult(normalized_ncm, retry_secondary, tuple(attempts))
            if retry_secondary.state is LookupState.PARTIAL:
                preferred = retry_secondary

            fallback_result = self._consult_fallbacks(normalized_ncm, fallbacks, attempts, preferred)
            if fallback_result.state is LookupState.FOUND:
                return ReferenceLookupResult(normalized_ncm, fallback_result, tuple(attempts))
            preferred = preferred or fallback_result

            if cycle < self.max_cycles - 1:
                self._wait_from(second_primary_failure_at, self.full_retry_seconds)

        final = preferred or ReferenceAttempt("router", LookupState.UNAVAILABLE, detail="Fontes indisponíveis.")
        return ReferenceLookupResult(normalized_ncm, final, tuple(attempts))

    @staticmethod
    def _consult_fallbacks(
        ncm: str,
        providers: list[ExactNcmProvider],
        attempts: list[ReferenceAttempt],
        preferred: ReferenceAttempt | None,
    ) -> ReferenceAttempt:
        fallback_result = preferred
        for provider in providers:
            attempt = provider.lookup(ncm)
            attempts.append(attempt)
            if attempt.state is LookupState.FOUND:
                return attempt
            if attempt.state is LookupState.NOT_FOUND:
                fallback_result = fallback_result or attempt
        return fallback_result or ReferenceAttempt("router", LookupState.UNAVAILABLE, detail="Fontes indisponíveis.")

    def _wait_from(self, start: float, seconds: int) -> None:
        self.sleep_fn(max(0, seconds - (self.clock_fn() - start)))
