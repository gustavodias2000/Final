from datetime import datetime, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import NCM, NcmReferenceVersion
from app.db.session import Base
from app.services.reference.ncm_catalog import NcmCatalog, NcmCatalogEntry
from app.services.reference.sync_ncm import persist_catalog


class NcmSyncTests(unittest.TestCase):
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

    def test_persists_an_immutable_catalog_and_skips_the_same_version(self) -> None:
        catalog = NcmCatalog(
            entries=(
                NcmCatalogEntry(codigo="09012100", descricao="Café torrado"),
                NcmCatalogEntry(codigo="01012100", descricao="Cavalos reprodutores"),
            ),
            source_url="https://example.test/ncm",
            fetched_at=datetime.now(timezone.utc),
            version="sha256:test-catalog",
            source_etag="etag-test",
        )

        created = persist_catalog(catalog, self.Session)
        repeated = persist_catalog(catalog, self.Session)

        self.assertTrue(created.created)
        self.assertEqual(created.entries, 2)
        self.assertFalse(repeated.created)
        self.assertEqual(repeated.entries, 2)

        db = self.Session()
        try:
            self.assertEqual(db.query(NcmReferenceVersion).count(), 1)
            self.assertEqual(db.query(NCM).count(), 2)
        finally:
            db.close()
