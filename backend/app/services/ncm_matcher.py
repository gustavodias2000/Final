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


# Palavras e medidas que não ajudam a reconhecer o produto e só diluem a comparação.
_STOPWORDS = frozenset(
    "de da do das dos para com sem e ou a o as os em no na nos nas por "
    "p c x un und cx pc pct kg g ml l mm cm m".split()
)
# (final do plural, troca, tamanho mínimo da palavra): "pães" -> "pão", "animais" -> "animal".
_PLURAL_ENDINGS = (
    ("oes", "ao", 4), ("aes", "ao", 4), ("ais", "al", 6), ("eis", "el", 6),
    ("ois", "ol", 6), ("uis", "ul", 6), ("ns", "m", 5),
)


def _singular(token: str) -> str:
    """Reduz o plural mais comum em português ("lapiseiras" -> "lapiseira")."""
    for ending, replacement, min_length in _PLURAL_ENDINGS:
        if token.endswith(ending) and len(token) >= min_length:
            return token[: -len(ending)] + replacement
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        return token[:-1]
    return token


def matching_text(value: object) -> str:
    """Texto usado para comparar descrições: sem acentos, números soltos, medidas,
    palavras de ligação e plural. "LAPISEIRA FABER-CASTELL 0,7" -> "lapiseira faber castell"."""
    tokens = (
        _singular(token)
        for token in normalize_text(value).split()
        if len(token) > 1 and not token.isdigit() and token not in _STOPWORDS
    )
    return " ".join(tokens)


def normalize_ncm(value: object) -> str | None:
    """Aceita apenas NCMs com oito dígitos; não inventa zeros à esquerda."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if len(digits) == 8 else None


@dataclass(frozen=True)
class NcmReference:
    codigo: str
    descricao: str
    descricao_normalizada: str
    descricao_busca: str = ""


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
                descricao_busca=matching_text(descricao),
            )
            if codigo_normalizado not in por_codigo:
                por_codigo[codigo_normalizado] = referencia
                if referencia.descricao_busca:
                    referencias.append(referencia)

        self._referencias = referencias
        self._por_codigo = por_codigo
        # Códigos atuais por subposição (6 dígitos), para indicar o substituto de um NCM extinto.
        self._por_subposicao: dict[str, list[NcmReference]] = {}
        for referencia in por_codigo.values():
            self._por_subposicao.setdefault(referencia.codigo[:6], []).append(referencia)
        self._descricoes = [referencia.descricao_busca for referencia in referencias]
        # Índice palavra -> referências que a contêm, para exigir a palavra principal do produto.
        self._por_palavra: dict[str, list[int]] = {}
        for index, referencia in enumerate(referencias):
            for palavra in set(referencia.descricao_busca.split()):
                self._por_palavra.setdefault(palavra, []).append(index)
        self._best_match_cache: dict[str, NcmMatch | None] = {}
        self._score_cache: dict[tuple[str, str], float] = {}

    def find_by_code(self, codigo: object) -> NcmReference | None:
        codigo_normalizado = normalize_ncm(codigo)
        return self._por_codigo.get(codigo_normalizado) if codigo_normalizado else None

    def codes_in_subheading(self, codigo: object) -> list[NcmReference]:
        """Códigos vigentes com os mesmos 6 primeiros dígitos (mesma subposição)."""
        digits = re.sub(r"\D", "", str(codigo or ""))
        if len(digits) < 6:
            return []
        return sorted(self._por_subposicao.get(digits[:6], []), key=lambda referencia: referencia.codigo)

    def score_against(self, descricao: object, referencia: NcmReference) -> float:
        descricao_busca = matching_text(descricao)
        if not descricao_busca or not referencia.descricao_busca:
            return 0.0
        key = (descricao_busca, referencia.codigo)
        if key not in self._score_cache:
            self._score_cache[key] = float(fuzz.token_set_ratio(descricao_busca, referencia.descricao_busca))
        return self._score_cache[key]

    def best_match(self, descricao: object) -> NcmMatch | None:
        """Melhor código da tabela entre os que contêm a palavra principal do produto.

        Nomes de produto começam pelo que o produto é ("LAPISEIRA ...", "LEITE ..."). Sem essa
        exigência, descrições curtas da tabela como "- Pretas" ou "Outras" ganhavam nota máxima
        só por ter todas as suas palavras dentro do nome do produto.
        """
        descricao_busca = matching_text(descricao)
        if not descricao_busca or not self._referencias:
            return None

        if descricao_busca in self._best_match_cache:
            return self._best_match_cache[descricao_busca]

        indices = self._por_palavra.get(descricao_busca.split()[0], [])
        result = process.extractOne(
            descricao_busca,
            [self._descricoes[index] for index in indices],
            scorer=fuzz.token_set_ratio,
        ) if indices else None
        if result is None:
            self._best_match_cache[descricao_busca] = None
            return None

        _, score, position = result
        match = NcmMatch(referencia=self._referencias[indices[position]], score=float(score))
        self._best_match_cache[descricao_busca] = match
        return match
