"""Worker de auditorias executado fora do processo web.

O banco é a fila: cada worker recebe uma concessão temporária (lease) antes de
processar uma auditoria. Se ele encerrar inesperadamente, outro worker poderá
retomar o trabalho quando a lease expirar.
"""

from __future__ import annotations

import os
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker
from rapidfuzz import fuzz

from app.core.config import settings
from app.db.models import (
    Audit,
    AuditInputItem,
    AuditItem,
    CestReference,
    CestReferenceVersion,
    NCM,
    NcmReferenceVersion,
)
from app.db.session import SessionLocal, configure_database
from app.services.audit_engine import AuditEngine, AuditPolicy, ProductForAudit
from app.services.ncm_matcher import normalize_ncm, normalize_text
from app.services.reference.cest_lookup import CestLookupClient, CestLookupResult
from app.services.reference.fallback_lookup import (
    AzxManualProvider,
    FallbackReferenceLookup,
    LocalCatalogProvider,
    NcmApiProvider,
    ReferenceLookupResult,
    TabelasFiscaisProvider,
)


RESULT_INSERT_BATCH_SIZE = 500


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuditWorker:
    def __init__(
        self,
        session_factory: sessionmaker = SessionLocal,
        worker_id: str | None = None,
        lease_seconds: int | None = None,
        max_attempts: int | None = None,
        progress_batch_size: int | None = None,
        cest_lookup_enabled: bool | None = None,
        cest_lookup_factory: Callable[[], CestLookupClient] | None = None,
        external_reference_lookup_enabled: bool | None = None,
        reference_lookup_factory: Callable[
            [dict[str, tuple[str, ...]], str | None, str | None], FallbackReferenceLookup
        ] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.lease_seconds = lease_seconds or settings.audit_worker_lease_seconds
        self.max_attempts = max_attempts or settings.audit_worker_max_attempts
        self.progress_batch_size = progress_batch_size or settings.audit_worker_progress_batch_size
        self.cest_lookup_enabled = (
            settings.cest_lookup_enabled if cest_lookup_enabled is None else cest_lookup_enabled
        )
        self.cest_lookup_factory = cest_lookup_factory or self._build_cest_lookup_client
        self.external_reference_lookup_enabled = (
            settings.external_reference_lookup_enabled
            if external_reference_lookup_enabled is None
            else external_reference_lookup_enabled
        )
        self.reference_lookup_factory = reference_lookup_factory or self._build_reference_lookup

    def process_next(self) -> bool:
        audit_id = self._claim_next()
        if audit_id is None:
            return False

        try:
            findings = self._run_audit(audit_id)
            self._complete(audit_id, findings)
        except Exception:
            self._fail_or_release(audit_id)
        return True

    def run_forever(self, sleep: Callable[[float], None] = time.sleep) -> None:
        while True:
            if not self.process_next():
                sleep(settings.audit_worker_poll_interval_seconds)

    def _claim_next(self) -> UUID | None:
        db = self.session_factory()
        try:
            now = _now()
            audit = (
                db.query(Audit)
                .filter(
                    Audit.status == "processing",
                    (Audit.worker_id.is_(None)) | (Audit.lease_expires_at < now),
                )
                .order_by(Audit.created_at.asc())
                .with_for_update(skip_locked=True)
                .first()
            )
            if audit is None:
                return None

            audit.worker_id = self.worker_id
            audit.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            audit.processing_started_at = audit.processing_started_at or now
            audit.attempt_count += 1
            db.commit()
            return audit.id
        finally:
            db.close()

    def _run_audit(self, audit_id: UUID) -> list[dict[str, object]]:
        db = self.session_factory()
        try:
            reference_version = (
                db.query(NcmReferenceVersion).order_by(NcmReferenceVersion.fetched_at.desc()).first()
            )
            if reference_version is None:
                raise RuntimeError("Referência NCM indisponível.")

            reference = (
                db.query(NCM.codigo, NCM.descricao)
                .filter(NCM.reference_version_id == reference_version.id)
                .all()
            )
            if not reference:
                raise RuntimeError("Referência NCM indisponível.")

            cest_version = (
                db.query(CestReferenceVersion).order_by(CestReferenceVersion.fetched_at.desc()).first()
            )
            cest_by_ncm: dict[str, tuple[str, ...]] = {}
            cest_rules: dict[str, tuple[tuple[str, str | None], ...]] = {}
            if cest_version is not None:
                for ncm_codigo, cest_codigo, descricao in (
                    db.query(CestReference.ncm_codigo, CestReference.cest_codigo, CestReference.descricao)
                    .filter(CestReference.reference_version_id == cest_version.id)
                    .all()
                ):
                    cest_by_ncm[ncm_codigo] = tuple((*cest_by_ncm.get(ncm_codigo, ()), cest_codigo))
                    cest_rules[ncm_codigo] = tuple((*cest_rules.get(ncm_codigo, ()), (cest_codigo, descricao)))

            inputs = (
                db.query(AuditInputItem)
                .filter(AuditInputItem.audit_id == audit_id)
                .order_by(AuditInputItem.row_number.asc())
                .all()
            )
            if not inputs:
                raise RuntimeError("Entrada da auditoria indisponível.")

            db.query(Audit).filter(Audit.id == audit_id, Audit.worker_id == self.worker_id).update(
                {Audit.reference_version_id: reference_version.id}, synchronize_session=False
            )
            db.commit()
            policy = AuditPolicy(
                reference_source=reference_version.source_url,
                reference_version=reference_version.version,
            )
            products = tuple(
                ProductForAudit(
                    codigo_produto=item.codigo_produto,
                    descricao=item.descricao,
                    ncm_atual=item.ncm_atual,
                    cest_atual=item.cest_atual,
                )
                for item in inputs
            )
            findings = AuditEngine(reference, policy).audit_products(
                products,
                on_processed=lambda n: self._progress(audit_id, n),
                progress_every=self.progress_batch_size,
            )
            results = [finding.as_dict() for finding in findings]
            if cest_version is not None:
                self._enrich_cest_catalog_results(results, cest_rules, cest_version)
            if self.external_reference_lookup_enabled:
                self._enrich_external_reference_results(
                    results,
                    cest_by_ncm,
                    cest_version.source_url if cest_version else None,
                    cest_version.version if cest_version else None,
                )
            if self.cest_lookup_enabled:
                self._enrich_cest_results(results)
            return results
        finally:
            db.close()

    @staticmethod
    def _build_cest_lookup_client() -> CestLookupClient:
        return CestLookupClient(
            settings.cest_lookup_url_template,
            timeout_seconds=settings.external_request_timeout_seconds,
            cache_ttl_seconds=settings.cest_cache_ttl_seconds,
        )

    @staticmethod
    def _build_reference_lookup(
        cest_by_ncm: dict[str, tuple[str, ...]], source_url: str | None, version: str | None
    ) -> FallbackReferenceLookup:
        return FallbackReferenceLookup(
            (
                TabelasFiscaisProvider(
                    settings.tabelas_fiscais_api_base_url,
                    settings.external_request_timeout_seconds,
                ),
                NcmApiProvider(
                    settings.ncm_api_base_url,
                    settings.ncm_api_key,
                    settings.external_request_timeout_seconds,
                ),
                AzxManualProvider(),
                LocalCatalogProvider(cest_by_ncm, source_url, version),
            ),
            retry_seconds=settings.external_reference_retry_seconds,
            full_retry_seconds=settings.external_reference_full_retry_seconds,
            max_cycles=settings.external_reference_max_cycles,
            require_cest=True,
        )

    def _enrich_external_reference_results(
        self,
        results: list[dict[str, object]],
        cest_by_ncm: dict[str, tuple[str, ...]],
        source_url: str | None,
        version: str | None,
    ) -> None:
        """Consulta a cadeia externa uma vez por NCM sem sobrescrever catálogo local válido."""
        lookup = self.reference_lookup_factory(cest_by_ncm, source_url, version)
        resolved: dict[str, ReferenceLookupResult] = {}
        for result in results:
            if result.get("cest_status") not in (None, "catalog_not_found"):
                continue
            ncm = normalize_ncm(result.get("ncm_sugerido") or result.get("ncm_atual"))
            if not ncm:
                continue
            outcome = resolved.get(ncm)
            if outcome is None:
                if len(resolved) >= settings.external_reference_lookup_max_unique_ncms:
                    result["cest_status"] = "external_lookup_limit"
                    continue
                outcome = lookup.lookup(ncm)
                resolved[ncm] = outcome
            self._apply_external_reference_result(result, outcome)

    @staticmethod
    def _apply_external_reference_result(
        result: dict[str, object], outcome: ReferenceLookupResult
    ) -> None:
        attempt = outcome.attempt
        result["reference_attempts"] = [entry.as_dict() for entry in outcome.attempts]
        result["cest_source_url"] = attempt.source_url
        result["cest_evidence"] = attempt.detail
        result["cest_status"] = f"{attempt.source}_{attempt.state.value}"
        if len(attempt.cest_codes) != 1 or attempt.cest_codes[0] == result.get("cest_atual"):
            return
        result["cest_sugerido"] = attempt.cest_codes[0]
        if result["status"] == "no_suggestion":
            result["status"] = "suggested"
        result["motivo"] = (
            f"{result['motivo']} CEST sugerido pela fonte {attempt.source}; requer revisão humana."
        )

    def _enrich_cest_results(self, results: list[dict[str, object]]) -> None:
        """Registra evidência CEST uma vez por NCM, sem escolher entre opções ambíguas."""
        lookup_client = self.cest_lookup_factory()
        lookups: dict[str, CestLookupResult] = {}

        for result in results:
            if result.get("cest_status"):
                continue
            ncm = normalize_ncm(result.get("ncm_sugerido") or result.get("ncm_atual"))
            if not ncm:
                continue

            lookup = lookups.get(ncm)
            if lookup is None:
                if len(lookups) >= settings.cest_lookup_max_unique_ncms:
                    result["cest_status"] = "not_checked_limit"
                    continue
                lookup = lookup_client.lookup(ncm)
                lookups[ncm] = lookup

            result["cest_status"] = lookup.status.value
            result["cest_source_url"] = lookup.source_url
            result["cest_evidence"] = lookup.evidence
            suggested_cest = lookup.suggested_cest
            if suggested_cest and suggested_cest != result.get("cest_atual"):
                result["cest_sugerido"] = suggested_cest
                if result["status"] == "no_suggestion":
                    result["status"] = "suggested"
                result["motivo"] = (
                    f"{result['motivo']} CEST sugerido porque a fonte consultada retornou uma única opção; "
                    "requer revisão humana."
                )

    @staticmethod
    def _enrich_cest_catalog_results(
        results: list[dict[str, object]],
        cest_rules: dict[str, tuple[tuple[str, str | None], ...]],
        version: CestReferenceVersion,
    ) -> None:
        """Usa regras CEST exatas ou por prefixo, sem sugerir por correspondência ampla."""
        for result in results:
            ncm = normalize_ncm(result.get("ncm_sugerido") or result.get("ncm_atual"))
            if not ncm:
                continue
            matching_prefixes = [prefix for prefix in cest_rules if ncm.startswith(prefix)]
            longest_prefix_length = max((len(prefix) for prefix in matching_prefixes), default=0)
            matched_rules = [
                rule
                for prefix in matching_prefixes
                if len(prefix) == longest_prefix_length
                for rule in cest_rules[prefix]
            ]
            candidates = tuple(
                sorted(
                    {
                        cest for cest, _ in matched_rules
                    }
                )
            )
            if not candidates:
                result["cest_status"] = "catalog_not_found"
                result["cest_source_url"] = version.source_url
                result["cest_evidence"] = f"Catalogo CEST {version.version}: nenhum CEST para NCM {ncm}."
                continue

            is_prefix_match = longest_prefix_length < len(ncm)
            ranked_candidates = AuditWorker._rank_cest_candidates(result.get("descricao"), matched_rules)
            result["cest_status"] = (
                "catalog_prefix_match"
                if is_prefix_match
                else "catalog_found" if len(candidates) == 1 else "catalog_multiple"
            )
            result["cest_source_url"] = version.source_url
            ranking_evidence = (
                " Ranking por descrição: "
                + ", ".join(f"{cest} ({score:.1f})" for cest, score in ranked_candidates)
                if ranked_candidates
                else ""
            )
            result["cest_evidence"] = (
                f"Catalogo CEST {version.version}; regra NCM {ncm[:longest_prefix_length]}; "
                f"NCM consultado {ncm}; opcoes: {', '.join(candidates)}.{ranking_evidence}"
            )
            if not is_prefix_match and len(candidates) == 1 and candidates[0] != result.get("cest_atual"):
                result["cest_sugerido"] = candidates[0]
                if result["status"] == "no_suggestion":
                    result["status"] = "suggested"
                result["motivo"] = (
                    f"{result['motivo']} CEST sugerido pelo catalogo local versionado; requer revisao humana."
                )
            elif not is_prefix_match and len(candidates) > 1:
                selected = AuditWorker._select_ranked_cest(ranked_candidates)
                if selected and selected != result.get("cest_atual"):
                    result["cest_sugerido"] = selected
                    result["cest_status"] = "catalog_ranked"
                    if result["status"] == "no_suggestion":
                        result["status"] = "suggested"
                    result["motivo"] = (
                        f"{result['motivo']} CEST selecionado entre opções da mesma NCM por similaridade "
                        "da descrição; requer revisão humana."
                    )

    @staticmethod
    def _rank_cest_candidates(
        product_description: object, candidates: list[tuple[str, str | None]]
    ) -> list[tuple[str, float]]:
        product = normalize_text(product_description)
        if not product:
            return []
        scores: dict[str, float] = {}
        for cest, reference_description in candidates:
            reference = normalize_text(reference_description)
            if reference:
                scores[cest] = max(scores.get(cest, 0.0), float(fuzz.token_set_ratio(product, reference)))
        return sorted(scores.items(), key=lambda item: (-item[1], item[0]))

    @staticmethod
    def _select_ranked_cest(ranked_candidates: list[tuple[str, float]]) -> str | None:
        if not ranked_candidates:
            return None
        best_code, best_score = ranked_candidates[0]
        second_score = ranked_candidates[1][1] if len(ranked_candidates) > 1 else 0.0
        if (
            best_score >= settings.cest_candidate_score_threshold
            and best_score - second_score >= settings.cest_candidate_score_margin
        ):
            return best_code
        return None

    def _progress(self, audit_id: UUID, processed: int) -> None:
        db = self.session_factory()
        try:
            db.query(Audit).filter(
                Audit.id == audit_id,
                Audit.status == "processing",
                Audit.worker_id == self.worker_id,
            ).update(
                {
                    Audit.processados: processed,
                    Audit.lease_expires_at: _now() + timedelta(seconds=self.lease_seconds),
                },
                synchronize_session=False,
            )
            db.commit()
        finally:
            db.close()

    def _complete(self, audit_id: UUID, results: list[dict[str, object]]) -> None:
        db = self.session_factory()
        try:
            audit = (
                db.query(Audit)
                .filter(Audit.id == audit_id, Audit.status == "processing", Audit.worker_id == self.worker_id)
                .with_for_update()
                .first()
            )
            if audit is None:
                return

            db.query(AuditItem).filter(AuditItem.audit_id == audit_id).delete(synchronize_session=False)
            mappings = [
                {
                    "audit_id": audit_id,
                    "codigo_produto": result["codigo_produto"],
                    "descricao": result["descricao"],
                    "ncm_atual": result["ncm_atual"],
                    "ncm_sugerido": result["ncm_sugerido"],
                    "cest_atual": result["cest_atual"],
                    "cest_sugerido": result["cest_sugerido"],
                    "score": result["score"],
                    "status": result["status"],
                    "motivo": result["motivo"],
                    "fonte_referencia": result["fonte_referencia"],
                    "versao_referencia": result["versao_referencia"],
                    "cest_status": result.get("cest_status"),
                    "cest_source_url": result.get("cest_source_url"),
                    "cest_evidence": result.get("cest_evidence"),
                    "reference_attempts": result.get("reference_attempts", []),
                }
                for result in results
            ]
            for start in range(0, len(mappings), RESULT_INSERT_BATCH_SIZE):
                db.bulk_insert_mappings(AuditItem, mappings[start : start + RESULT_INSERT_BATCH_SIZE])
            audit.status = "completed"
            audit.processados = len(results)
            audit.completed_at = _now()
            audit.worker_id = None
            audit.lease_expires_at = None
            audit.errors = []
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _fail_or_release(self, audit_id: UUID) -> None:
        db = self.session_factory()
        try:
            audit = (
                db.query(Audit)
                .filter(Audit.id == audit_id, Audit.status == "processing", Audit.worker_id == self.worker_id)
                .first()
            )
            if audit is None:
                return

            audit.worker_id = None
            audit.lease_expires_at = None
            if audit.attempt_count >= self.max_attempts:
                audit.status = "failed"
                audit.errors = ["A auditoria não pôde ser concluída após novas tentativas."]
                audit.completed_at = _now()
            db.commit()
        finally:
            db.close()


def main() -> None:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL é obrigatória para executar o worker.")
    configure_database()
    AuditWorker().run_forever()


if __name__ == "__main__":
    main()
