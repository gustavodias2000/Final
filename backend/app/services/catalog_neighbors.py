"""Evidência vinda do próprio cadastro enviado: produtos parecidos e famílias de produtos.

A tabela NCM oficial tem descrições curtas e genéricas ("- Lapiseiras", "Outras") que pouco se
parecem com nomes de produto; o cadastro da empresa costuma ter vários itens da mesma família.

Semelhança: TF-IDF com cosseno, em que palavras raras pesam mais que as comuns ("lasanha" pesa
mais que "sadia" ou "600g") e a primeira palavra (o que o produto é) vale o dobro. Medido numa
planilha real de 3.700 itens, deixando cada item de fora do índice: com 5 vizinhos e votação
ponderada pela nota, a precisão fica em ~91% com 79% de cobertura, contra 53% de cobertura do
critério anterior (3 vizinhos por token_set_ratio).

Famílias: estatística "começo da descrição -> NCM" (2 primeiras palavras, depois a 1ª), também
calculada sem o próprio item.
"""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass

from app.services.ncm_matcher import matching_text

FIRST_WORD_BOOST = 2.0


@dataclass(frozen=True)
class CatalogNeighbor:
    codigo_produto: str
    descricao: str
    ncm: str
    score: float

    def as_dict(self) -> dict[str, object]:
        return {
            "codigo_produto": self.codigo_produto,
            "descricao": self.descricao,
            "ncm": self.ncm,
            "score": round(self.score, 1),
        }


@dataclass(frozen=True)
class CatalogConsensus:
    ncm: str
    votes: int
    neighbors: int
    best_score: float
    share: float


@dataclass(frozen=True)
class FamilyVote:
    """NCM mais usado pelos produtos do cadastro que começam com as mesmas palavras."""

    ncm: str
    key: str
    count: int
    total: int

    @property
    def share(self) -> float:
        return self.count / self.total if self.total else 0.0


@dataclass(frozen=True)
class CatalogEntry:
    position: int
    codigo_produto: str
    descricao: str
    ncm: str


@dataclass(frozen=True)
class ConsensusRule:
    min_best_score: float
    min_share: float
    min_votes: int = 2


# Para confirmar o NCM atual ou sugerir um NCM quando o atual não existe (~90% de precisão medida).
SUGGEST_RULE = ConsensusRule(min_best_score=40.0, min_share=0.6)
# Para alertar que um NCM válido diverge do cadastro (~95% de precisão medida).
ALERT_RULE = ConsensusRule(min_best_score=50.0, min_share=0.8)


class CatalogIndex:
    """Produtos do cadastro com NCM válido, para achar os mais parecidos e as famílias."""

    def __init__(self, entries: list[CatalogEntry], neighbors: int = 5, min_vote_score: float = 40.0) -> None:
        self.neighbors_limit = neighbors
        self.min_vote_score = min_vote_score
        self._entries: list[CatalogEntry] = []
        tokens_by_entry: list[list[str]] = []
        for entry in entries:
            tokens = matching_text(entry.descricao).split()
            if tokens:
                self._entries.append(entry)
                tokens_by_entry.append(tokens)

        document_frequency: Counter[str] = Counter()
        for tokens in tokens_by_entry:
            document_frequency.update(set(tokens))
        total = len(self._entries)
        self._idf = {
            token: math.log((total + 1) / (frequency + 1)) + 1 for token, frequency in document_frequency.items()
        }
        self._default_idf = math.log(total + 1) + 1

        # Índice invertido palavra -> [(entrada, peso normalizado)].
        self._postings: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for index, tokens in enumerate(tokens_by_entry):
            for token, weight in self._weights(tokens).items():
                self._postings[token].append((index, weight))

        self._family2: dict[str, Counter[str]] = defaultdict(Counter)
        self._family1: dict[str, Counter[str]] = defaultdict(Counter)
        self._position_keys: dict[int, tuple[str | None, str | None]] = {}
        for entry, tokens in zip(self._entries, tokens_by_entry):
            key1, key2 = _family_keys(tokens)
            self._position_keys[entry.position] = (key1, key2)
            self._family1[key1][entry.ncm] += 1
            if key2:
                self._family2[key2][entry.ncm] += 1
        self._ncm_by_position = {entry.position: entry.ncm for entry in self._entries}
        self._cache: dict[str, list[tuple[int, float]]] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def _weights(self, tokens: list[str]) -> dict[str, float]:
        weights: dict[str, float] = {}
        for position, token in enumerate(tokens):
            weight = self._idf.get(token, self._default_idf) * (FIRST_WORD_BOOST if position == 0 else 1.0)
            weights[token] = max(weights.get(token, 0.0), weight)
        norm = math.sqrt(sum(weight * weight for weight in weights.values()))
        return {token: weight / norm for token, weight in weights.items()} if norm else {}

    def neighbors(self, descricao: str, exclude_position: int | None = None) -> list[CatalogNeighbor]:
        query = matching_text(descricao)
        if not query or not self._entries:
            return []
        if query not in self._cache:
            scores: dict[int, float] = defaultdict(float)
            for token, weight in self._weights(query.split()).items():
                for index, entry_weight in self._postings.get(token, ()):
                    scores[index] += weight * entry_weight
            ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[: self.neighbors_limit + 1]
            self._cache[query] = [(index, min(100.0, score * 100)) for index, score in ranked]
        result: list[CatalogNeighbor] = []
        for index, score in self._cache[query]:
            entry = self._entries[index]
            if entry.position == exclude_position:
                continue
            result.append(CatalogNeighbor(entry.codigo_produto, entry.descricao, entry.ncm, score))
            if len(result) == self.neighbors_limit:
                break
        return result

    def consensus(self, neighbors: list[CatalogNeighbor], rule: ConsensusRule = SUGGEST_RULE) -> CatalogConsensus | None:
        """NCM com a maior parte do voto dos vizinhos, ponderado pela nota de semelhança."""
        if not neighbors or neighbors[0].score < rule.min_best_score:
            return None
        weights: dict[str, float] = defaultdict(float)
        counts: Counter[str] = Counter()
        for neighbor in neighbors:
            if neighbor.score >= self.min_vote_score:
                weights[neighbor.ncm] += neighbor.score
                counts[neighbor.ncm] += 1
        total = sum(weights.values())
        if not total:
            return None
        ncm, weight = max(weights.items(), key=lambda pair: pair[1])
        share = weight / total
        if share < rule.min_share or counts[ncm] < rule.min_votes:
            return None
        return CatalogConsensus(ncm, counts[ncm], sum(counts.values()), neighbors[0].score, share)

    def family(self, descricao: str, exclude_position: int | None = None) -> tuple[FamilyVote | None, FamilyVote | None]:
        """(voto pelas 2 primeiras palavras, voto pela 1ª palavra), sem contar o próprio item."""
        key1, key2 = _family_keys(matching_text(descricao).split())
        own = self._ncm_by_position.get(exclude_position) if exclude_position is not None else None
        return _vote(self._family2, key2, own), _vote(self._family1, key1, own)


def _family_keys(tokens: list[str]) -> tuple[str | None, str | None]:
    key1 = tokens[0] if tokens else None
    key2 = " ".join(tokens[:2]) if len(tokens) >= 2 else None
    return key1, key2


def _vote(table: dict[str, Counter[str]], key: str | None, own_ncm: str | None) -> FamilyVote | None:
    if not key or key not in table:
        return None
    counts = table[key].copy()
    if own_ncm is not None and counts.get(own_ncm):
        counts[own_ncm] -= 1
        if counts[own_ncm] <= 0:
            del counts[own_ncm]
    total = sum(counts.values())
    if not total:
        return None
    ncm, count = counts.most_common(1)[0]
    return FamilyVote(ncm, key, count, total)
