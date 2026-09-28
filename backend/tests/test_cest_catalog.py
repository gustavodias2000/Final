from datetime import datetime, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import CestReference, CestReferenceVersion
from app.db.session import Base
from app.services.reference.cest_catalog import CestCatalog, CestCatalogEntry, build_catalog, load_catalog_url
from app.services.reference.sync_cest import persist_catalog


class CestCatalogTests(unittest.TestCase):
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

    def test_build_catalog_normalizes_and_deduplicates_rows(self) -> None:
        catalog = build_catalog(
            [
                {"NCM": "0901.21.00", "CEST": "100100", "Descricao": "Cafe"},
                {"ncm_codigo": "09012100", "cest_codigo": "01.001.00", "descricao": "Duplicado"},
                {"ncm": "invalido", "cest": "01.001.00"},
            ],
            "https://example.test/cest",
        )

        self.assertEqual(len(catalog.entries), 1)
        self.assertEqual(catalog.entries[0].ncm_codigo, "09012100")
        self.assertEqual(catalog.entries[0].cest_codigo, "01.001.00")
        self.assertTrue(catalog.version.startswith("sha256:"))

    def test_build_catalog_accepts_a_partial_ncm_rule(self) -> None:
        catalog = build_catalog(
            [{"ncm": "2710.19.3", "cest": "06.005.00", "descricao": "Oleos lubrificantes"}],
            "https://example.test/cest",
        )

        self.assertEqual(catalog.entries[0].ncm_codigo, "2710193")
        self.assertEqual(catalog.entries[0].cest_codigo, "06.005.00")

    def test_load_catalog_url_accepts_tabelas_fiscais_download_format(self) -> None:
        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "gerado_em": "2026-09-24T01:32:12Z",
                    "total": 2,
                    "dados": [
                        {"ncm": "9608.40.00", "cest": "19.030.00"},
                        {"ncm": "2202.10.00", "cest": "03.007.00"},
                    ],
                }

        class FakeClient:
            def get(self, url: str, *, timeout: float, headers: dict[str, str]) -> FakeResponse:
                self.url = url
                self.timeout = timeout
                self.headers = headers
                return FakeResponse()

        client = FakeClient()
        catalog = load_catalog_url("https://example.test/cest_ncm.json", 12.0, client)

        self.assertEqual(len(catalog.entries), 2)
        self.assertEqual(catalog.entries[0].cest_codigo, "03.007.00")
        self.assertEqual(client.headers["Accept"], "application/json")

    def test_persists_immutable_catalog_once(self) -> None:
        catalog = CestCatalog(
            entries=(CestCatalogEntry("09012100", "01.001.00", "Cafe"),),
            source_url="https://example.test/cest",
            fetched_at=datetime.now(timezone.utc),
            version="sha256:test-cest-catalog",
        )

        created = persist_catalog(catalog, self.Session)
        repeated = persist_catalog(catalog, self.Session)

        self.assertTrue(created.created)
        self.assertFalse(repeated.created)
        db = self.Session()
        try:
            self.assertEqual(db.query(CestReferenceVersion).count(), 1)
            self.assertEqual(db.query(CestReference).count(), 1)
        finally:
            db.close()
