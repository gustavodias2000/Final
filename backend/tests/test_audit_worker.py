from datetime import datetime, timedelta, timezone
import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Audit,
    AuditInputItem,
    AuditItem,
    CestReference,
    CestReferenceVersion,
    NCM,
    NcmReferenceVersion,
    Tenant,
)
from app.db.session import Base
from app.services.audit_worker import AuditWorker
from app.services.reference.cest_lookup import CestLookupResult, CestLookupStatus
from app.services.reference.fallback_lookup import FallbackReferenceLookup, LookupState, ReferenceAttempt


class FakeCestLookupClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def lookup(self, ncm: str) -> CestLookupResult:
        self.calls.append(ncm)
        return CestLookupResult(
            status=CestLookupStatus.FOUND,
            ncm=ncm,
            cest_codes=("01.001.00",),
            source_url=f"https://example.test/cest?ncm={ncm}",
            checked_at=datetime.now(timezone.utc),
            evidence="CEST 01.001.00",
        )


class AuditWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _create_audit(self, *, expired_lease: bool = False) -> Audit:
        db = self.Session()
        try:
            tenant = Tenant(id=uuid4(), nome="Empresa de teste")
            reference_version = NcmReferenceVersion(
                id=uuid4(),
                source_url="https://example.test/ncm",
                version=f"test-{uuid4()}",
                fetched_at=datetime.now(timezone.utc),
            )
            ncm = NCM(
                id=uuid4(),
                reference_version_id=reference_version.id,
                codigo="01012100",
                descricao="Cavalos reprodutores de raça pura",
            )
            audit = Audit(
                id=uuid4(),
                tenant_id=tenant.id,
                source_filename="produtos.xlsx",
                source_file_sha256="b" * 64,
                source_file_size_bytes=256,
                status="processing",
                total_produtos=1,
                processados=0,
                errors=[],
                worker_id="worker-encerrado" if expired_lease else None,
                lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1) if expired_lease else None,
            )
            input_item = AuditInputItem(
                id=uuid4(),
                audit_id=audit.id,
                row_number=1,
                codigo_produto="SKU-CAVALO",
                descricao="Cavalos reprodutores de raça pura",
                ncm_atual="00000000",
                cest_atual=None,
            )
            db.add_all([tenant, reference_version, ncm, audit, input_item])
            db.commit()
            return audit
        finally:
            db.close()

    def test_worker_completes_persisted_audit(self) -> None:
        audit = self._create_audit()
        worker = AuditWorker(self.Session, worker_id="worker-a", lease_seconds=60, max_attempts=3)

        self.assertTrue(worker.process_next())

        db = self.Session()
        try:
            persisted = db.get(Audit, audit.id)
            items = db.query(AuditItem).filter(AuditItem.audit_id == audit.id).all()
            self.assertEqual(persisted.status, "completed")
            self.assertEqual(persisted.processados, 1)
            self.assertEqual(persisted.attempt_count, 1)
            self.assertIsNone(persisted.worker_id)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].ncm_sugerido, "01012100")
        finally:
            db.close()

    def test_worker_recovers_an_expired_lease(self) -> None:
        audit = self._create_audit(expired_lease=True)
        worker = AuditWorker(self.Session, worker_id="worker-recuperador", lease_seconds=60, max_attempts=3)

        self.assertTrue(worker.process_next())

        db = self.Session()
        try:
            persisted = db.get(Audit, audit.id)
            self.assertEqual(persisted.status, "completed")
            self.assertEqual(persisted.attempt_count, 1)
            self.assertEqual(db.query(AuditItem).filter(AuditItem.audit_id == audit.id).count(), 1)
        finally:
            db.close()

    def test_worker_persists_unique_cest_suggestion_with_evidence(self) -> None:
        audit = self._create_audit()
        cest_client = FakeCestLookupClient()
        worker = AuditWorker(
            self.Session,
            worker_id="worker-cest",
            lease_seconds=60,
            max_attempts=3,
            cest_lookup_enabled=True,
            cest_lookup_factory=lambda: cest_client,
        )

        self.assertTrue(worker.process_next())

        db = self.Session()
        try:
            item = db.query(AuditItem).filter(AuditItem.audit_id == audit.id).one()
            self.assertEqual(cest_client.calls, ["01012100"])
            self.assertEqual(item.cest_sugerido, "01.001.00")
            self.assertEqual(item.cest_status, "found")
            self.assertEqual(item.cest_source_url, "https://example.test/cest?ncm=01012100")
            self.assertEqual(item.cest_evidence, "CEST 01.001.00")
            self.assertIn("CEST sugerido", item.motivo)
        finally:
            db.close()

    def test_worker_prefers_versioned_local_cest_catalog(self) -> None:
        audit = self._create_audit()
        db = self.Session()
        try:
            catalog = CestReferenceVersion(
                id=uuid4(),
                source_url="https://example.test/catalogo-cest",
                version="sha256:local-cest",
                fetched_at=datetime.now(timezone.utc),
            )
            entry = CestReference(
                id=uuid4(),
                reference_version_id=catalog.id,
                ncm_codigo="01012100",
                cest_codigo="01.001.00",
                descricao="Cavalos",
            )
            db.add_all([catalog, entry])
            db.commit()
        finally:
            db.close()

        worker = AuditWorker(self.Session, worker_id="worker-catalogo", lease_seconds=60, max_attempts=3)
        self.assertTrue(worker.process_next())

        db = self.Session()
        try:
            item = db.query(AuditItem).filter(AuditItem.audit_id == audit.id).one()
            self.assertEqual(item.cest_sugerido, "01.001.00")
            self.assertEqual(item.cest_status, "catalog_found")
            self.assertEqual(item.cest_source_url, "https://example.test/catalogo-cest")
            self.assertIn("sha256:local-cest", item.cest_evidence)
        finally:
            db.close()

    def test_worker_records_prefix_cest_rule_without_automatic_suggestion(self) -> None:
        audit = self._create_audit()
        db = self.Session()
        try:
            catalog = CestReferenceVersion(
                id=uuid4(),
                source_url="https://example.test/catalogo-cest",
                version="sha256:prefix-cest",
                fetched_at=datetime.now(timezone.utc),
            )
            entry = CestReference(
                id=uuid4(),
                reference_version_id=catalog.id,
                ncm_codigo="0101",
                cest_codigo="01.001.00",
                descricao="Regra ampla",
            )
            db.add_all([catalog, entry])
            db.commit()
        finally:
            db.close()

        worker = AuditWorker(self.Session, worker_id="worker-prefixo", lease_seconds=60, max_attempts=3)
        self.assertTrue(worker.process_next())

        db = self.Session()
        try:
            item = db.query(AuditItem).filter(AuditItem.audit_id == audit.id).one()
            self.assertIsNone(item.cest_sugerido)
            self.assertEqual(item.cest_status, "catalog_prefix_match")
            self.assertIn("regra NCM 0101", item.cest_evidence)
        finally:
            db.close()

    def test_worker_ranks_multiple_exact_cest_options_by_description(self) -> None:
        audit = self._create_audit()
        db = self.Session()
        try:
            catalog = CestReferenceVersion(
                id=uuid4(),
                source_url="https://example.test/catalogo-cest",
                version="sha256:ranked-cest",
                fetched_at=datetime.now(timezone.utc),
            )
            matching = CestReference(
                id=uuid4(),
                reference_version_id=catalog.id,
                ncm_codigo="01012100",
                cest_codigo="01.001.00",
                descricao="Cavalos reprodutores de raça pura",
            )
            unrelated = CestReference(
                id=uuid4(),
                reference_version_id=catalog.id,
                ncm_codigo="01012100",
                cest_codigo="01.002.00",
                descricao="Peças e acessórios para veículos automotores",
            )
            db.add_all([catalog, matching, unrelated])
            db.commit()
        finally:
            db.close()

        worker = AuditWorker(self.Session, worker_id="worker-ranking", lease_seconds=60, max_attempts=3)
        self.assertTrue(worker.process_next())

        db = self.Session()
        try:
            item = db.query(AuditItem).filter(AuditItem.audit_id == audit.id).one()
            self.assertEqual(item.cest_sugerido, "01.001.00")
            self.assertEqual(item.cest_status, "catalog_ranked")
            self.assertIn("Ranking por descrição", item.cest_evidence)
        finally:
            db.close()

    def test_worker_persists_external_reference_attempts(self) -> None:
        audit = self._create_audit()

        class ExternalProvider:
            def lookup(self, ncm: str) -> ReferenceAttempt:
                return ReferenceAttempt(
                    "tabelas_fiscais_api", LookupState.FOUND, "https://example.test/ncm/01012100", "OK", cest_codes=("01.001.00",)
                )

        class SecondaryProvider:
            def lookup(self, ncm: str) -> ReferenceAttempt:
                return ReferenceAttempt("ncm_api_br", LookupState.UNAVAILABLE)

        worker = AuditWorker(
            self.Session,
            worker_id="worker-external",
            lease_seconds=60,
            max_attempts=3,
            external_reference_lookup_enabled=True,
            reference_lookup_factory=lambda *_: FallbackReferenceLookup(
                (ExternalProvider(), SecondaryProvider()), sleep_fn=lambda _: None
            ),
        )
        self.assertTrue(worker.process_next())

        db = self.Session()
        try:
            item = db.query(AuditItem).filter(AuditItem.audit_id == audit.id).one()
            self.assertEqual(item.cest_sugerido, "01.001.00")
            self.assertEqual(item.reference_attempts[0]["source"], "tabelas_fiscais_api")
            self.assertEqual(item.cest_status, "tabelas_fiscais_api_found")
        finally:
            db.close()

    def test_worker_marks_audit_failed_after_last_attempt(self) -> None:
        db = self.Session()
        try:
            tenant = Tenant(id=uuid4(), nome="Empresa sem referência")
            audit = Audit(
                id=uuid4(),
                tenant_id=tenant.id,
                source_filename="produtos.xlsx",
                source_file_sha256="c" * 64,
                source_file_size_bytes=256,
                status="processing",
                total_produtos=1,
                processados=0,
                errors=[],
            )
            input_item = AuditInputItem(
                id=uuid4(),
                audit_id=audit.id,
                row_number=1,
                codigo_produto="SKU-SEM-BASE",
                descricao="Produto sem referência",
                ncm_atual=None,
                cest_atual=None,
            )
            db.add_all([tenant, audit, input_item])
            db.commit()
        finally:
            db.close()

        worker = AuditWorker(self.Session, worker_id="worker-falha", lease_seconds=60, max_attempts=1)
        self.assertTrue(worker.process_next())

        db = self.Session()
        try:
            persisted = db.get(Audit, audit.id)
            self.assertEqual(persisted.status, "failed")
            self.assertEqual(persisted.attempt_count, 1)
            self.assertTrue(persisted.errors)
            self.assertIsNone(persisted.worker_id)
        finally:
            db.close()
