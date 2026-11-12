"""Códigos NCM confirmados pela empresa, usados como a evidência mais forte da auditoria.

Vêm de duas fontes: itens aprovados na revisão e planilhas importadas como "códigos
confirmados". Um produto é reconhecido pelo código (código interno ou EAN) ou, sem código
conhecido, por uma descrição praticamente idêntica.
"""

import re
from dataclasses import dataclass
from typing import Iterable

from rapidfuzz import fuzz, process

from app.services.ncm_matcher import matching_text

ORIGIN_APPROVAL = "aprovacao"
ORIGIN_IMPORT = "importacao"


def product_code_key(value: object) -> str | None:
    """Chave do código do produto: sem espaços; EAN sem zeros à esquerda (GTIN-13 = GTIN-14)."""
    text = re.sub(r"\s+", "", str(value or "")).upper()
    if not text:
        return None
    if text.isdigit():
        return text.lstrip("0") or "0"
    return text


@dataclass(frozen=True)
class ConfirmedCode:
    codigo_produto: str | None
    descricao: str
    ncm: str
    origem: str


@dataclass(frozen=True)
class ConfirmedMatch:
    code: ConfirmedCode
    # "codigo" (código do produto igual) ou "descricao" (descrição praticamente idêntica).
    by: str
    score: float

    def explanation(self) -> str:
        origin = "aprovado numa revisão anterior" if self.code.origem == ORIGIN_APPROVAL else "importado como código confirmado"
        how = "pelo código do produto" if self.by == "codigo" else "por descrição praticamente idêntica"
        return f"{origin}, reconhecido {how}"


class ConfirmedIndex:
    def __init__(self, codes: Iterable[ConfirmedCode] = (), min_description_score: float = 92.0) -> None:
        self.min_description_score = min_description_score
        self._by_code: dict[str, ConfirmedCode] = {}
        described: list[ConfirmedCode] = []
        for code in codes:
            key = product_code_key(code.codigo_produto)
            if key:
                self._by_code[key] = code
            if matching_text(code.descricao):
                described.append(code)
        self._described = described
        self._texts = [matching_text(code.descricao) for code in described]
        self._cache: dict[str, ConfirmedMatch | None] = {}

    def __len__(self) -> int:
        return len(self._by_code) + len(self._described)

    def knows_code(self, codigo_produto: object) -> bool:
        key = product_code_key(codigo_produto)
        return bool(key and key in self._by_code)

    def find(self, codigo_produto: object, descricao: object) -> ConfirmedMatch | None:
        key = product_code_key(codigo_produto)
        if key and key in self._by_code:
            return ConfirmedMatch(self._by_code[key], "codigo", 100.0)
        query = matching_text(descricao)
        if not query or not self._texts:
            return None
        if query not in self._cache:
            # ratio compara o texto inteiro: "suco uva" não casa com "suco uva prats" por estar contido nele.
            found = process.extractOne(query, self._texts, scorer=fuzz.ratio)
            self._cache[query] = (
                ConfirmedMatch(self._described[found[2]], "descricao", float(found[1]))
                if found and found[1] >= self.min_description_score
                else None
            )
        return self._cache[query]
