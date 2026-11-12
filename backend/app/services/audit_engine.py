"""Regras de domínio para auditoria de NCM.

Este módulo não conhece FastAPI, SQLAlchemy ou componentes visuais. Sua saída
é uma recomendação explicável, que deve ser revisada antes de qualquer uso
fiscal.

Ordem das evidências, da mais forte para a mais fraca (medida numa planilha real de 3.700
itens, deixando cada item fora das próprias evidências):

NCM informado que existe na tabela vigente:
  0. Código confirmado pela empresa (aprovado antes ou importado).
  1. Produtos parecidos do cadastro, com voto de pelo menos 80% (alerta só com ~95% de precisão).
  2. Família do cadastro: produtos que começam com as mesmas palavras, com 90% de concordância.
  3. Compatibilidade da descrição com o próprio código na tabela oficial.
  A semelhança com a tabela oficial nunca troca um NCM válido: medida, ela quase nunca
  coincidia com o NCM informado.

NCM informado que não existe (extinto ou fictício) ou que falta:
  0. Código confirmado pela empresa.
  1. Tabela oficial de correlação 2017×2022 (ou desdobramento do código nos códigos atuais).
     Com um único destino, ele é a sugestão; com vários, as próximas evidências escolhem entre
     eles e, sem escolha segura, a pessoa escolhe na revisão.
  2. Dicionário de famílias de varejo (lasanha -> massas recheadas, limpador -> tensoativos).
  3. Produtos parecidos e famílias do cadastro (~90% de precisão).
  4. Palavras da descrição dos códigos candidatos, quando o código extinto tem sucessores.
  5. Semelhança com a tabela oficial (confiança baixa).
"""

import re
from dataclasses import asdict, dataclass, field, replace
from typing import Callable, Iterable

from app.services.catalog_neighbors import (
    ALERT_RULE,
    SUGGEST_RULE,
    CatalogEntry,
    CatalogIndex,
    CatalogNeighbor,
    FamilyVote,
)
from app.services.confirmed_codes import ConfirmedCode, ConfirmedIndex, product_code_key
from app.services.ncm_matcher import NcmMatcher, normalize_ncm, normalize_text
from app.services.ncm_references import CORRELATION_SOURCE, Successors, successors, synonym_dictionary

NCM_VALID = "valid"
NCM_INVALID = "invalid"
NCM_MISSING = "missing"
SOURCE_CONFIRMED = "confirmado"
SOURCE_CORRELATION = "correlacao"
SOURCE_SYNONYM = "sinonimo"
SOURCE_CATALOG = "catalogo"
SOURCE_FAMILY = "familia"
SOURCE_TABLE = "tabela"


@dataclass(frozen=True)
class AuditPolicy:
    compatibility_score: float = 70.0
    # Sugestão pela semelhança com a tabela oficial quando o NCM atual não existe ou falta.
    suggestion_score: float = 70.0
    # Família do cadastro (começo da descrição): exemplos mínimos e concordância.
    family2_min_count: int = 3
    family1_min_count: int = 5
    family_suggest_share: float = 0.7
    family1_suggest_share: float = 0.8
    family_alert_share: float = 0.9
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
    # De onde veio a sugestão (ou a confirmação) de NCM: confirmado, correlacao, sinonimo,
    # catalogo, familia ou tabela.
    ncm_fonte: str | None = None
    ncm_vizinhos: tuple[dict[str, object], ...] = field(default_factory=tuple)
    # NCM extinto: códigos vigentes que o substituem, para escolha na revisão.
    ncm_opcoes: tuple[dict[str, object], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["ncm_vizinhos"] = [dict(neighbor) for neighbor in self.ncm_vizinhos]
        data["ncm_opcoes"] = [dict(option) for option in self.ncm_opcoes]
        return data


@dataclass(frozen=True)
class _Evidence:
    """Evidência do cadastro calculada uma vez por produto."""

    neighbors: list[CatalogNeighbor]
    catalog: CatalogIndex | None
    position: int | None


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
        self.synonyms = synonym_dictionary()
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
        finding = self._audit_product_uncached(product, _Evidence(neighbors, catalog, position))
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

    # ------------------------------------------------------------------ decisão

    def _audit_product_uncached(self, product: ProductForAudit, evidence: _Evidence | None = None) -> AuditFinding:
        evidence = evidence or _Evidence([], None, None)
        descricao = normalize_text(product.descricao)
        ncm_atual = normalize_ncm(product.ncm_atual)
        current_reference = self.matcher.find_by_code(ncm_atual)
        raw_ncm = _raw_ncm(product.ncm_atual)
        ncm_status = NCM_VALID if current_reference else NCM_INVALID if raw_ncm else NCM_MISSING
        context = {"ncm_status": ncm_status, "ncm_vizinhos": tuple(n.as_dict() for n in evidence.neighbors)}

        if not descricao:
            return self._without_suggestion(
                product, ncm_atual, 0.0,
                "A descrição do produto está vazia ou inválida; não há base para sugerir NCM.", **context,
            )

        confirmed = self.confirmed.find(product.codigo_produto, product.descricao)
        if confirmed is not None and self.matcher.find_by_code(confirmed.code.ncm):
            return self._audit_confirmed(product, ncm_atual, ncm_status, confirmed, context)

        if ncm_status != NCM_VALID:
            return self._audit_unusable_ncm(product, ncm_atual, raw_ncm, ncm_status, evidence, context)
        return self._audit_valid_ncm(product, ncm_atual, current_reference, evidence, context)

    def _audit_valid_ncm(self, product, ncm_atual, current_reference, evidence, context) -> AuditFinding:
        catalog = evidence.catalog
        # 1. Produtos parecidos do cadastro.
        if catalog is not None:
            agreement = catalog.consensus(evidence.neighbors, SUGGEST_RULE)
            if agreement is not None and agreement.ncm == ncm_atual:
                return self._without_suggestion(
                    product, ncm_atual, agreement.share * 100,
                    f"NCM atual igual ao de {agreement.votes} de {agreement.neighbors} produtos parecidos do cadastro.",
                    ncm_fonte=SOURCE_CATALOG, **context,
                )
            alert = catalog.consensus(evidence.neighbors, ALERT_RULE)
            if alert is not None and alert.ncm != ncm_atual:
                return self._suggest(
                    product, ncm_atual, alert.ncm, alert.share * 100, SOURCE_CATALOG,
                    f"{alert.votes} de {alert.neighbors} produtos parecidos do cadastro usam {format_ncm(alert.ncm)}; "
                    f"este usa {format_ncm(ncm_atual)}. Confira qual está certo.",
                    context,
                )
            # 2. Família do cadastro (começo da descrição).
            family = self._family(product, evidence, alert_mode=True)
            if family is not None:
                if family.ncm == ncm_atual:
                    return self._without_suggestion(
                        product, ncm_atual, family.share * 100,
                        f"NCM atual igual ao de {family.count} de {family.total} produtos do cadastro que começam "
                        f"com \"{family.key}\".",
                        ncm_fonte=SOURCE_FAMILY, **context,
                    )
                return self._suggest(
                    product, ncm_atual, family.ncm, family.share * 100, SOURCE_FAMILY,
                    f"{family.count} de {family.total} produtos do cadastro que começam com \"{family.key}\" usam "
                    f"{format_ncm(family.ncm)}; este usa {format_ncm(ncm_atual)}. Confira qual está certo.",
                    context,
                )

        # 3. Compatibilidade com a tabela oficial.
        current_score = self.matcher.score_against(product.descricao, current_reference)
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

    def _audit_unusable_ncm(self, product, stored_ncm, raw_ncm, ncm_status, evidence, context) -> AuditFinding:
        problem = (
            f"Na planilha, o NCM {format_ncm(raw_ncm)} não existe na tabela NCM vigente."
            if ncm_status == NCM_INVALID
            else "Na planilha, o NCM não foi informado."
        )
        found = successors(raw_ncm, self.matcher) if ncm_status == NCM_INVALID else None
        allowed = set(found.codes) if found else None
        options = tuple(
            {"ncm": code, "descricao": reference.descricao if (reference := self.matcher.find_by_code(code)) else None}
            for code in (found.codes if found and len(found.codes) > 1 else ())
        )
        lineage = _lineage(raw_ncm, found)

        # 1. Correlação com um único destino.
        if found and len(found.codes) == 1:
            source = SOURCE_CORRELATION if found.origin == "correlacao" else SOURCE_TABLE
            return self._suggest(product, stored_ncm, found.codes[0], 95.0, source, lineage, context)

        def accept(code: str | None) -> bool:
            return bool(code) and self.matcher.find_by_code(code) is not None and (allowed is None or code in allowed)

        def suggest(code: str, score: float, source: str, reason: str) -> AuditFinding:
            prefix = f"{lineage} " if options else ""
            tail = "" if options else f" {problem}"
            return replace(
                self._suggest(product, stored_ncm, code, score, source, f"{prefix}{reason}{tail}", context),
                ncm_opcoes=options,
            )

        # 2. Dicionário de famílias de varejo.
        synonym = self.synonyms.lookup(product.descricao)
        if synonym is not None and accept(synonym.ncm):
            return suggest(
                synonym.ncm, 85.0, SOURCE_SYNONYM,
                f"\"{synonym.termo}\" é da família {synonym.familia}: NCM {format_ncm(synonym.ncm)}.",
            )

        # 3. Produtos parecidos e famílias do cadastro.
        if evidence.catalog is not None:
            consensus = evidence.catalog.consensus(evidence.neighbors, SUGGEST_RULE)
            if consensus is not None and accept(consensus.ncm):
                return suggest(
                    consensus.ncm, consensus.share * 100, SOURCE_CATALOG,
                    f"{consensus.votes} de {consensus.neighbors} produtos parecidos do cadastro usam "
                    f"{format_ncm(consensus.ncm)}.",
                )
            family = self._family(product, evidence, alert_mode=False)
            if family is not None and accept(family.ncm):
                return suggest(
                    family.ncm, family.share * 100, SOURCE_FAMILY,
                    f"{family.count} de {family.total} produtos do cadastro que começam com \"{family.key}\" usam "
                    f"{format_ncm(family.ncm)}.",
                )

        # 4. Palavras da descrição dos códigos candidatos.
        if found and len(found.codes) > 1:
            words = set(_matching_tokens(product.descricao))
            scored = sorted(((len(words & self.matcher.leaf_words(code)), code) for code in found.codes), reverse=True)
            if scored[0][0] > 0 and scored[0][0] > scored[1][0]:
                code = scored[0][1]
                return suggest(
                    code, 60.0, SOURCE_TABLE,
                    f"A descrição do código {format_ncm(code)} é a que mais se parece com a do produto.",
                )

        # 5. Semelhança com a tabela oficial (confiança baixa).
        candidate = self.matcher.best_match(product.descricao)
        if candidate is not None and candidate.score >= self.policy.suggestion_score and accept(candidate.referencia.codigo):
            return suggest(
                candidate.referencia.codigo, min(candidate.score, 60.0), SOURCE_TABLE,
                "Sugestão pela semelhança da descrição com a tabela NCM (confiança baixa); confira.",
            )

        if options:
            return replace(
                self._without_suggestion(
                    product, stored_ncm, 0.0, f"{lineage} Escolha um na revisão.", **context,
                ),
                status="pending_review",
                ncm_opcoes=options,
                ncm_fonte=SOURCE_CORRELATION if found and found.origin == "correlacao" else None,
            )
        return replace(
            self._without_suggestion(
                product, stored_ncm, 0.0,
                f"{problem} Não foi possível sugerir um código com segurança; corrija o NCM no cadastro de origem.",
                **context,
            ),
            status="pending_review",
        )

    def _family(self, product: ProductForAudit, evidence: _Evidence, alert_mode: bool) -> FamilyVote | None:
        if evidence.catalog is None:
            return None
        by_two, by_one = evidence.catalog.family(product.descricao, exclude_position=evidence.position)
        policy = self.policy
        two_share = policy.family_alert_share if alert_mode else policy.family_suggest_share
        one_share = policy.family_alert_share if alert_mode else policy.family1_suggest_share
        if by_two is not None and by_two.total >= policy.family2_min_count and by_two.share >= two_share:
            return by_two
        if by_one is not None and by_one.total >= policy.family1_min_count and by_one.share >= one_share:
            return by_one
        return None

    def _audit_confirmed(self, product, stored_ncm, ncm_status, confirmed, context) -> AuditFinding:
        code = confirmed.code
        if code.ncm == stored_ncm:
            return self._without_suggestion(
                product, stored_ncm, confirmed.score,
                f"NCM confirmado anteriormente ({confirmed.explanation()}).",
                ncm_fonte=SOURCE_CONFIRMED, **context,
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


def _lineage(raw_ncm: str | None, found: Successors | None) -> str:
    """Frase que explica de onde vêm os códigos que substituem um NCM extinto."""
    if not found:
        return ""
    count = len(found.codes)
    target = format_ncm(found.codes[0]) if count == 1 else f"{count} códigos"
    if found.origin == "correlacao":
        return f"O NCM {format_ncm(raw_ncm)} foi extinto e, pela {CORRELATION_SOURCE}, corresponde hoje a {target}."
    if count == 1:
        return f"O NCM {format_ncm(raw_ncm)} não existe mais; o único código atual que começa como ele é {target}."
    return f"O NCM {format_ncm(raw_ncm)} não existe mais e hoje se divide em {target}."


def _matching_tokens(value: object) -> list[str]:
    from app.services.ncm_matcher import matching_text

    return matching_text(value).split()


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
