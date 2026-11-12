"""Referências fixas versionadas no projeto: correlação de NCM extinto e sinônimos de varejo."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services.ncm_matcher import NcmMatcher, matching_text

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CORRELATION_SOURCE = "Tabela de Correlação NCM 2017×2022 (MDIC/Camex)"


@lru_cache(maxsize=1)
def correlation_map() -> dict[str, list[str]]:
    """Código extinto -> códigos novos, conforme a tabela oficial de correlação 2017×2022."""
    with open(DATA_DIR / "ncm_correlacao_2017_2022.json", encoding="utf-8") as file:
        return json.load(file)["mapa"]


@dataclass(frozen=True)
class Successors:
    codes: tuple[str, ...]
    # "correlacao" (tabela oficial) ou "desdobramento" (códigos atuais com o mesmo começo).
    origin: str


def successors(raw_code: str | None, matcher: NcmMatcher) -> Successors | None:
    """Códigos vigentes que substituem um NCM extinto.

    1. Tabela oficial de correlação 2017×2022; um destino que também deixou de existir é
       desdobrado de novo pelo passo 2.
    2. Desdobramento: códigos vigentes que começam como o extinto, sem os zeros finais
       (1901.20.00 -> 1901.20.10/20/90). É uma aproximação, não uma correlação oficial.
    """
    if not raw_code or len(raw_code) != 8 or not raw_code.isdigit() or matcher.find_by_code(raw_code):
        return None
    official = correlation_map().get(raw_code)
    if official:
        codes: list[str] = []
        for destination in official:
            codes += [destination] if matcher.find_by_code(destination) else _split(destination, matcher)
        codes = list(dict.fromkeys(codes))
        if codes:
            return Successors(tuple(codes), "correlacao")
    codes = _split(raw_code, matcher)
    return Successors(tuple(codes), "desdobramento") if codes else None


def _split(code: str, matcher: NcmMatcher) -> list[str]:
    prefix = code.rstrip("0")
    if len(prefix) < 6:
        prefix = code[:6]
    codes = matcher.codes_with_prefix(prefix)
    # 1905.90.10 extinto: nada começa com "1905901", mas a subposição 1905.90 continua.
    return codes or matcher.codes_with_prefix(code[:6])


@dataclass(frozen=True)
class SynonymHit:
    familia: str
    termo: str
    ncm: str


class SynonymDictionary:
    """Famílias de produtos de varejo -> NCM, pelo começo da descrição ("lasanha" -> 1902.20.00)."""

    def __init__(self, entries: list[dict[str, object]]) -> None:
        self._terms: dict[tuple[str, ...], tuple[str, str]] = {}
        for entry in entries:
            by_term = entry.get("ncm_por_termo") or {}
            for term in entry["termos"]:
                tokens = tuple(matching_text(term).split())
                if tokens:
                    self._terms[tokens] = (str(entry["familia"]), str(by_term.get(term, entry["ncm"])))
        self._longest = max((len(tokens) for tokens in self._terms), default=0)

    def lookup(self, descricao: str) -> SynonymHit | None:
        """Termo mais longo que coincide com o começo da descrição do produto."""
        tokens = matching_text(descricao).split()
        for size in range(min(self._longest, len(tokens)), 0, -1):
            hit = self._terms.get(tuple(tokens[:size]))
            if hit:
                return SynonymHit(familia=hit[0], termo=" ".join(tokens[:size]), ncm=hit[1])
        return None


@lru_cache(maxsize=1)
def synonym_dictionary() -> SynonymDictionary:
    with open(DATA_DIR / "ncm_sinonimos.json", encoding="utf-8") as file:
        return SynonymDictionary(json.load(file)["entradas"])
