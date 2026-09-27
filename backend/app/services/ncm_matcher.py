"""Matching textual entre produtos e a base de referência NCM."""

from dataclasses import dataclass
import re
import unicodedata
from typing import Iterable

from rapidfuzz import fuzz, process


def normalize_text(value: object) -> str:
    """Padroniza texto sem perder a semântica das palavras."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9]+", " ", text)).strip().lower()


def normalize_ncm(value: object) -> str | None:
    """Aceita apenas NCMs com oito dígitos; não inventa zeros à esquerda."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if len(digits) == 8 else None


@dataclass(frozen=True)
class NcmReference:
    codigo: str
    descricao: str
    descricao_normalizada: str


@dataclass(frozen=True)
class NcmMatch:
    referencia: NcmReference
    score: float


class NcmMatcher:
    """Índice imutável da referência NCM utilizado durante uma auditoria."""

    def __init__(self, base_ncm: Iterable[tuple[object, object]]):
        referencias: list[NcmReference] = []
        por_codigo: dict[str, NcmReference] = {}

        for codigo, descricao in base_ncm:
            codigo_normalizado = normalize_ncm(codigo)
            descricao_normalizada = normalize_text(descricao)
            if not codigo_normalizado or not descricao_normalizada:
                continue

            referencia = NcmReference(
                codigo=codigo_normalizado,
                descricao=str(descricao).strip(),
                descricao_normalizada=descricao_normalizada,
            )
            if codigo_normalizado not in por_codigo:
                referencias.append(referencia)
                por_codigo[codigo_normalizado] = referencia

        self._referencias = referencias
        self._por_codigo = por_codigo
        self._descricoes = [referencia.descricao_normalizada for referencia in referencias]
        self._best_match_cache: dict[str, NcmMatch | None] = {}
        self._score_cache: dict[tuple[str, str], float] = {}

    def find_by_code(self, codigo: object) -> NcmReference | None:
        codigo_normalizado = normalize_ncm(codigo)
        return self._por_codigo.get(codigo_normalizado) if codigo_normalizado else None

    def score_against(self, descricao: object, referencia: NcmReference) -> float:
        descricao_normalizada = normalize_text(descricao)
        if not descricao_normalizada:
            return 0.0
        key = (descricao_normalizada, referencia.codigo)
        if key not in self._score_cache:
            self._score_cache[key] = float(fuzz.token_set_ratio(descricao_normalizada, referencia.descricao_normalizada))
        return self._score_cache[key]

    def best_match(self, descricao: object) -> NcmMatch | None:
        descricao_normalizada = normalize_text(descricao)
        if not descricao_normalizada or not self._referencias:
            return None

        if descricao_normalizada in self._best_match_cache:
            return self._best_match_cache[descricao_normalizada]

        result = process.extractOne(
            descricao_normalizada,
            self._descricoes,
            scorer=fuzz.token_set_ratio,
        )
        if result is None:
            self._best_match_cache[descricao_normalizada] = None
            return None

        _, score, index = result
        match = NcmMatch(referencia=self._referencias[index], score=float(score))
        self._best_match_cache[descricao_normalizada] = match
        return match
