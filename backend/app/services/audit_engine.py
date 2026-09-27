"""Regras de domínio para auditoria de NCM.

Este módulo não conhece FastAPI, SQLAlchemy ou componentes visuais. Sua saída
é uma recomendação explicável, que deve ser revisada antes de qualquer uso
fiscal.
"""

from dataclasses import asdict, dataclass, replace
from typing import Callable, Iterable

from app.services.ncm_matcher import NcmMatcher, normalize_ncm, normalize_text


@dataclass(frozen=True)
class AuditPolicy:
    compatibility_score: float = 70.0
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

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class AuditEngine:
    """Executa a política de auditoria contra uma referência NCM indexada."""

    def __init__(self, base_ncm: Iterable[tuple[object, object]], policy: AuditPolicy | None = None):
        self.policy = policy or AuditPolicy()
        self.matcher = NcmMatcher(base_ncm)
        self._finding_cache: dict[tuple[str, str | None, str | None], AuditFinding] = {}

    def audit_product(self, product: ProductForAudit) -> AuditFinding:
        cache_key = (normalize_text(product.descricao), normalize_ncm(product.ncm_atual), product.cest_atual or None)
        cached = self._finding_cache.get(cache_key)
        if cached is not None:
            return replace(cached, codigo_produto=product.codigo_produto, descricao=product.descricao)

        finding = self._audit_product_uncached(product)
        self._finding_cache[cache_key] = finding
        return finding

    def _audit_product_uncached(self, product: ProductForAudit) -> AuditFinding:
        descricao = normalize_text(product.descricao)
        ncm_atual = normalize_ncm(product.ncm_atual)

        if not descricao:
            return self._without_suggestion(
                product,
                ncm_atual,
                0.0,
                "A descrição do produto está vazia ou inválida; não há base para sugerir NCM.",
            )

        current_reference = self.matcher.find_by_code(ncm_atual)
        if current_reference:
            current_score = self.matcher.score_against(descricao, current_reference)
            if current_score >= self.policy.compatibility_score:
                return self._without_suggestion(
                    product,
                    ncm_atual,
                    current_score,
                    "O NCM atual existe na referência e sua descrição é compatível com o produto.",
                )

        candidate = self.matcher.best_match(descricao)
        if candidate is None:
            return self._without_suggestion(
                product,
                ncm_atual,
                0.0,
                "A base de referência não possui descrição elegível para comparação.",
            )

        if candidate.score < self.policy.suggestion_score:
            return self._without_suggestion(
                product,
                ncm_atual,
                candidate.score,
                "A melhor correspondência encontrada não atingiu o limiar mínimo de confiança.",
            )

        if candidate.referencia.codigo == ncm_atual:
            return self._without_suggestion(
                product,
                ncm_atual,
                candidate.score,
                "O NCM atual foi a melhor correspondência, mas a descrição exige revisão humana.",
            )

        return AuditFinding(
            codigo_produto=product.codigo_produto,
            descricao=product.descricao,
            ncm_atual=ncm_atual,
            ncm_sugerido=candidate.referencia.codigo,
            cest_atual=product.cest_atual,
            cest_sugerido=None,
            score=round(candidate.score, 2),
            status="suggested",
            motivo="NCM sugerido pela maior similaridade textual acima do limiar de confiança; requer revisão humana.",
            fonte_referencia=self.policy.reference_source,
            versao_referencia=self.policy.reference_version,
        )

    def audit_products(
        self,
        products: Iterable[ProductForAudit],
        on_processed: Callable[[int], None] | None = None,
        progress_every: int = 1,
    ) -> list[AuditFinding]:
        if progress_every <= 0:
            raise ValueError("progress_every deve ser maior que zero.")

        findings: list[AuditFinding] = []
        for index, product in enumerate(products, start=1):
            findings.append(self.audit_product(product))
            if on_processed and index % progress_every == 0:
                on_processed(index)
        if on_processed and findings and len(findings) % progress_every:
            on_processed(len(findings))
        return findings

    def _without_suggestion(
        self,
        product: ProductForAudit,
        ncm_atual: str | None,
        score: float,
        motivo: str,
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
        )


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
