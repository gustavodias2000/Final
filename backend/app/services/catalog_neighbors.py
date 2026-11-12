"""Produtos parecidos dentro do próprio cadastro enviado.

A tabela NCM oficial tem descrições curtas e genéricas ("- Lapiseiras", "Outras") que pouco
se parecem com nomes de produto. O cadastro da empresa, ao contrário, costuma ter vários itens
da mesma família. Medido numa planilha real de 3.700 itens, o NCM do produto mais parecido do
cadastro coincidiu com o NCM informado em 77,5% dos casos; quando 2 dos 3 mais parecidos
concordavam (com nota de pelo menos 85), em 89,9%. A comparação direta com a tabela oficial
acertava 2,9%.
"""

from collections import Counter
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from app.services.ncm_matcher import matching_text


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


@dataclass(frozen=True)
class CatalogEntry:
    position: int
    codigo_produto: str
    descricao: str
    ncm: str


class CatalogIndex:
    """Índice dos produtos do cadastro que têm NCM válido, para achar os mais parecidos."""

    def __init__(
        self,
        entries: list[CatalogEntry],
        neighbors: int = 3,
        min_best_score: float = 85.0,
        min_votes: int = 2,
        min_vote_score: float = 70.0,
    ) -> None:
        self.neighbors_limit = neighbors
        self.min_best_score = min_best_score
        self.min_votes = min_votes
        self.min_vote_score = min_vote_score
        self._entries = [entry for entry in entries if matching_text(entry.descricao)]
        self._texts = [matching_text(entry.descricao) for entry in self._entries]
        self._cache: dict[str, list[tuple[int, float]]] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def neighbors(self, descricao: str, exclude_position: int | None = None) -> list[CatalogNeighbor]:
        query = matching_text(descricao)
        if not query or not self._entries:
            return []
        if query not in self._cache:
            # Um a mais que o necessário, para poder descartar o próprio produto.
            found = process.extract(query, self._texts, scorer=fuzz.token_set_ratio, limit=self.neighbors_limit + 1)
            self._cache[query] = [(index, float(score)) for _, score, index in found]
        result: list[CatalogNeighbor] = []
        for index, score in self._cache[query]:
            entry = self._entries[index]
            if entry.position == exclude_position:
                continue
            result.append(CatalogNeighbor(entry.codigo_produto, entry.descricao, entry.ncm, score))
            if len(result) == self.neighbors_limit:
                break
        return result

    def consensus(self, neighbors: list[CatalogNeighbor], unanimous: bool = False) -> CatalogConsensus | None:
        """NCM em que a maioria dos vizinhos concorda, se a semelhança for alta o bastante.

        Com unanimous=True, todos os vizinhos precisam concordar. É o que se exige para sugerir
        trocar um NCM válido: se o próprio cadastro classifica a mesma família de vários jeitos,
        a maioria simples manda cada item trocar para o código do outro.
        """
        if not neighbors or neighbors[0].score < self.min_best_score:
            return None
        votes = Counter(neighbor.ncm for neighbor in neighbors if neighbor.score >= self.min_vote_score)
        if not votes:
            return None
        ncm, count = votes.most_common(1)[0]
        if count < self.min_votes or (unanimous and count < len(neighbors)):
            return None
        return CatalogConsensus(ncm=ncm, votes=count, neighbors=len(neighbors), best_score=neighbors[0].score)
