"""Regras de domínio para auditoria de NCM.

Este módulo não conhece FastAPI, SQLAlchemy ou componentes visuais. Sua saída
é uma recomendação explicável, que deve ser revisada antes de qualquer uso
fiscal.

Ordem das evidências, da mais forte para a mais fraca:
0. Código confirmado pela empresa (aprovado antes ou importado), pelo código do produto ou
   por descrição praticamente idêntica.
1. Produtos parecidos do próprio cadastro (CatalogIndex), quando concordam entre si.
2. Compatibilidade da descrição com o NCM atual na tabela oficial.
3. Semelhança da descrição com a tabela oficial, só como reserva quando o NCM atual não
   existe ou falta. Medida numa planilha real, ela quase nunca coincidia com o NCM informado,
   então não é usada para sugerir troca de um NCM válido.
"""

import re
from dataclasses import asdict, dataclass, field, replace
from typing import Callable, Iterable

from app.services.catalog_neighbors import CatalogConsensus, CatalogEntry, CatalogIndex, CatalogNeighbor
from app.services.confirmed_codes import ConfirmedCode, ConfirmedIndex, product_code_key
from app.services.ncm_matcher import NcmMatcher, normalize_ncm, normalize_text

NCM_VALID = "valid"
NCM_INVALID = "invalid"
NCM_MISSING = "missing"
SOURCE_CATALOG = "catalogo"
SOURCE_TABLE = "tabela"
SOURCE_CONFIRMED = "confirmado"


@dataclass(frozen=True)
class AuditPolicy:
    compatibility_score: float = 70.0
    # Sugestão pela tabela oficial quando o NCM atual não existe ou falta.
    suggestion_score: float = 70.0
    reference_source: str = "base_ncm"
    reference_version: str | None = None


@dataclass(frozen=True)
class ProductForAudit:
    codigo_produto: str
    descricao: str
    ncm_atual: str | None
    cest_atual: str | None


@dataclass(frozen=True)
class AuditFinding:
    codigo_produto: str
    descricao: str
    ncm_atual: str | None
    ncm_sugerido: str | None
    cest_atual: str | None
    cest_sugerido: str | None
    score: float
    status: str
    motivo: str
    fonte_referencia: str
    versao_referencia: str | None
    # valid: existe na tabela vigente; invalid: informado mas inexistente; missing: não informado.
    ncm_status: str = NCM_VALID
    # De onde veio a sugestão de NCM: "catalogo" (produtos parecidos) ou "tabela" (tabela oficial).
    ncm_fonte: str | None = None
    ncm_vizinhos: tuple[dict[str, object], ...] = field(default_factory=tuple)
    # NCM extinto: códigos vigentes da mesma subposição, para escolha na revisão.
    ncm_opcoes: tuple[dict[str, object], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["ncm_vizinhos"] = [dict(neighbor) for neighbor in self.ncm_vizinhos]
        data["ncm_opcoes"] = [dict(option) for option in self.ncm_opcoes]
        return data


def format_ncm(code: str | None) -> str:
    digits = re.sub(r"\D", "", code or "")
    return f"{digits[:4]}.{digits[4:6]}.{digits[6:8]}" if len(digits) == 8 else (code or "")


class AuditEngine:
    """Executa a política de auditoria contra uma referência NCM indexada."""

    def __init__(
        self,
        base_ncm: Iterable[tuple[object, object]],
        policy: AuditPolicy | None = None,
        confirmed: Iterable[ConfirmedCode] = (),
    ):
        self.policy = policy or AuditPolicy()
        self.matcher = NcmMatcher(base_ncm)
        self.confirmed = ConfirmedIndex(confirmed)
        self._finding_cache: dict[tuple[str, str | None, str | None, str | None], AuditFinding] = {}

    def audit_product(
        self,
        product: ProductForAudit,
        catalog: CatalogIndex | None = None,
        position: int | None = None,
    ) -> AuditFinding:
        # O código entra na chave só quando há um código confirmado para ele.
        code_key = product_code_key(product.codigo_produto) if self.confirmed.knows_code(product.codigo_produto) else None
        cache_key = (normalize_text(product.descricao), _raw_ncm(product.ncm_atual), product.cest_atual or None, code_key)
        cached = self._finding_cache.get(cache_key)
        if cached is not None:
            return replace(cached, codigo_produto=product.codigo_produto, descricao=product.descricao)

        neighbors = catalog.neighbors(product.descricao, exclude_position=position) if catalog else []
        consensus = catalog.consensus(neighbors) if catalog else None
        unanimous = catalog.consensus(neighbors, unanimous=True) if catalog else None
        finding = self._audit_product_uncached(product, neighbors, consensus, unanimous)
        self._finding_cache[cache_key] = finding
        return finding

    def build_catalog(self, products: list[ProductForAudit]) -> CatalogIndex:
        """Indexa os produtos do cadastro cujo NCM existe na tabela vigente."""
        entries = [
            CatalogEntry(position, product.codigo_produto, product.descricao, ncm)
            for position, product in enumerate(products)
            if (ncm := normalize_ncm(product.ncm_atual)) and self.matcher.find_by_code(ncm)
        ]
        return CatalogIndex(entries)

    def _audit_product_uncached(
        self,
        product: ProductForAudit,
        neighbors: list[CatalogNeighbor] | None = None,
        consensus: CatalogConsensus | None = None,
        unanimous: CatalogConsensus | None = None,
    ) -> AuditFinding:
        neighbors = neighbors or []
        descricao = normalize_text(product.descricao)
        ncm_atual = normalize_ncm(product.ncm_atual)
        current_reference = self.matcher.find_by_code(ncm_atual)
        ncm_status = NCM_VALID if current_reference else NCM_INVALID if _raw_ncm(product.ncm_atual) else NCM_MISSING
        context = {"ncm_status": ncm_status, "ncm_vizinhos": tuple(n.as_dict() for n in neighbors)}
        # A coluna guarda 8 dígitos; um código com outro tamanho aparece só no motivo.
        stored_ncm = ncm_atual

        if not descricao:
            return self._without_suggestion(
                product, stored_ncm, 0.0,
                "A descrição do produto está vazia ou inválida; não há base para sugerir NCM.", **context,
            )

        # 0. Código confirmado pela empresa.
        confirmed = self.confirmed.find(product.codigo_produto, product.descricao)
        if confirmed is not None and self.matcher.find_by_code(confirmed.code.ncm):
            return self._audit_confirmed(product, stored_ncm, ncm_status, confirmed, context)

        if ncm_status != NCM_VALID:
            return self._audit_unusable_ncm(product, stored_ncm, _raw_ncm(product.ncm_atual), ncm_status, consensus, context)

        # 1. Produtos parecidos do cadastro.
        if consensus is not None and consensus.ncm == ncm_atual:
            return self._without_suggestion(
                product, ncm_atual, consensus.best_score,
                f"NCM atual igual ao de {consensus.votes} de {consensus.neighbors} produtos parecidos do cadastro.",
                **context,
            )
        if unanimous is not None and unanimous.ncm != ncm_atual:
            return self._suggest(
                product, ncm_atual, unanimous.ncm, unanimous.best_score, SOURCE_CATALOG,
                f"Os {unanimous.votes} produtos mais parecidos do cadastro usam {format_ncm(unanimous.ncm)}; "
                f"este usa {format_ncm(ncm_atual)}. Confira qual está certo.",
                context,
            )

        # 2. Compatibilidade com a tabela oficial.
        current_score = self.matcher.score_against(descricao, current_reference)
        if current_score >= self.policy.compatibility_score:
            return self._without_suggestion(
                product, ncm_atual, current_score,
                "O NCM atual existe na referência e sua descrição é compatível com o produto.", **context,
            )

        return self._without_suggestion(
            product, ncm_atual, current_score,
            "O NCM atual existe na tabela vigente. A descrição não confirma esse código, e os produtos "
            "parecidos do cadastro não bastam para indicar outro com segurança.",
            **context,
        )

    def _audit_confirmed(self, product, stored_ncm, ncm_status, confirmed, context) -> AuditFinding:
        code = confirmed.code
        if code.ncm == stored_ncm:
            return replace(
                self._without_suggestion(
                    product, stored_ncm, confirmed.score,
                    f"NCM confirmado anteriormente ({confirmed.explanation()}).", **context,
                ),
                ncm_fonte=SOURCE_CONFIRMED,
            )
        # A origem da sugestão vem primeiro: é a frase que a fila mostra resumida.
        problem = {
            NCM_INVALID: f" Na planilha, o NCM {format_ncm(_raw_ncm(product.ncm_atual))} não existe na tabela NCM vigente.",
            NCM_MISSING: " Na planilha, o NCM não foi informado.",
            NCM_VALID: f" A planilha traz {format_ncm(stored_ncm)}.",
        }[ncm_status]
        return self._suggest(
            product, stored_ncm, code.ncm, confirmed.score, SOURCE_CONFIRMED,
            f"Código confirmado: NCM {format_ncm(code.ncm)} ({confirmed.explanation()}).{problem}",
            context,
        )

    def _audit_unusable_ncm(
        self,
        product: ProductForAudit,
        stored_ncm: str | None,
        raw_ncm: str | None,
        ncm_status: str,
        consensus: CatalogConsensus | None,
        context: dict[str, object],
    ) -> AuditFinding:
        problem = (
            f"NCM {format_ncm(raw_ncm)} não existe na tabela NCM vigente."
            if ncm_status == NCM_INVALID
            else "NCM não informado."
        )
        if consensus is not None:
            return self._suggest(
                product, stored_ncm, consensus.ncm, consensus.best_score, SOURCE_CATALOG,
                f"{problem} {consensus.votes} de {consensus.neighbors} produtos parecidos do cadastro usam "
                f"{format_ncm(consensus.ncm)}.",
                context,
            )
        # NCM extinto cuja subposição continua: os códigos atuais dela são os candidatos naturais.
        successors = self.matcher.codes_in_subheading(raw_ncm) if ncm_status == NCM_INVALID else []
        if len(successors) == 1:
            return self._suggest(
                product, stored_ncm, successors[0].codigo, 100.0, SOURCE_TABLE,
                f"{problem} A subposição {format_ncm(raw_ncm)[:7]} hoje tem um único código: "
                f"{format_ncm(successors[0].codigo)}.",
                context,
            )
        if successors:
            return replace(
                self._without_suggestion(
                    product, stored_ncm, 0.0,
                    f"{problem} A subposição {format_ncm(raw_ncm)[:7]} hoje se divide em {len(successors)} "
                    "códigos; escolha um na revisão.",
                    **context,
                ),
                status="pending_review",
                ncm_opcoes=tuple({"ncm": option.codigo, "descricao": option.descricao} for option in successors),
            )
        candidate = self.matcher.best_match(product.descricao)
        if candidate is not None and candidate.score >= self.policy.suggestion_score:
            return self._suggest(
                product, stored_ncm, candidate.referencia.codigo, candidate.score, SOURCE_TABLE,
                f"{problem} Sugestão pela semelhança da descrição com a tabela NCM; confira.",
                context,
            )
        # Sem sugestão, mas o item precisa de atenção: vai para a fila de revisão.
        return replace(
            self._without_suggestion(
                product, stored_ncm, candidate.score if candidate else 0.0,
                f"{problem} Não foi possível sugerir um código com segurança; corrija o NCM no cadastro de origem.",
                **context,
            ),
            status="pending_review",
        )

    def audit_products(
        self,
        products: Iterable[ProductForAudit],
        on_processed: Callable[[int], None] | None = None,
        progress_every: int = 1,
    ) -> list[AuditFinding]:
        if progress_every <= 0:
            raise ValueError("progress_every deve ser maior que zero.")

        product_list = list(products)
        catalog = self.build_catalog(product_list)
        findings: list[AuditFinding] = []
        for index, product in enumerate(product_list, start=1):
            findings.append(self.audit_product(product, catalog, position=index - 1))
            if on_processed and index % progress_every == 0:
                on_processed(index)
        if on_processed and findings and len(findings) % progress_every:
            on_processed(len(findings))
        return findings

    def _suggest(
        self,
        product: ProductForAudit,
        ncm_atual: str | None,
        ncm_sugerido: str,
        score: float,
        source: str,
        motivo: str,
        context: dict[str, object],
    ) -> AuditFinding:
        return AuditFinding(
            codigo_produto=product.codigo_produto,
            descricao=product.descricao,
            ncm_atual=ncm_atual,
            ncm_sugerido=ncm_sugerido,
            cest_atual=product.cest_atual,
            cest_sugerido=None,
            score=round(score, 2),
            status="suggested",
            motivo=motivo,
            fonte_referencia=self.policy.reference_source,
            versao_referencia=self.policy.reference_version,
            ncm_fonte=source,
            **context,
        )

    def _without_suggestion(
        self,
        product: ProductForAudit,
        ncm_atual: str | None,
        score: float,
        motivo: str,
        **context: object,
    ) -> AuditFinding:
        return AuditFinding(
            codigo_produto=product.codigo_produto,
            descricao=product.descricao,
            ncm_atual=ncm_atual,
            ncm_sugerido=None,
            cest_atual=product.cest_atual,
            cest_sugerido=None,
            score=round(score, 2),
            status="no_suggestion",
            motivo=motivo,
            fonte_referencia=self.policy.reference_source,
            versao_referencia=self.policy.reference_version,
            **context,
        )


def _raw_ncm(value: object) -> str | None:
    """Dígitos do NCM como vieram da planilha, mesmo que não formem um código válido."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits or None


def executar_auditoria(df, base_ncm: Iterable[tuple[object, object]]) -> list[dict[str, object]]:
    """Adaptador temporário entre o DataFrame de importação e o domínio."""
    products = (
        ProductForAudit(
            codigo_produto=_optional_text(row["codigo_produto"]) or "",
            descricao=_optional_text(row["descricao"]) or "",
            ncm_atual=_optional_text(row["ncm_atual"]),
            cest_atual=_optional_text(row["cest_atual"]),
        )
        for _, row in df.iterrows()
    )
    return [finding.as_dict() for finding in AuditEngine(base_ncm).audit_products(products)]


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text if text and text.lower() != "nan" else None
