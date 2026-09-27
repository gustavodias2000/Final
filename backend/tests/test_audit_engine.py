import unittest
from unittest.mock import patch

from rapidfuzz import process as rapidfuzz_process

from app.services.audit_engine import AuditEngine, ProductForAudit
from app.services.ncm_matcher import NcmMatcher, normalize_ncm, normalize_text


REFERENCE = [
    ("0901.21.00", "Café torrado não descafeinado, em grãos"),
    ("9405.10.00", "Lustres e aparelhos elétricos de iluminação"),
]


class AuditEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = AuditEngine(REFERENCE)

    def test_keeps_compatible_current_ncm_without_suggestion(self) -> None:
        result = self.engine.audit_product(
            ProductForAudit("SKU-1", "Café torrado em grãos", "0901.21.00", None)
        )

        self.assertEqual(result.status, "no_suggestion")
        self.assertIsNone(result.ncm_sugerido)
        self.assertGreaterEqual(result.score, 70)

    def test_suggests_a_different_ncm_when_current_one_is_incompatible(self) -> None:
        result = self.engine.audit_product(
            ProductForAudit("SKU-2", "Café torrado em grãos", "9405.10.00", None)
        )

        self.assertEqual(result.status, "suggested")
        self.assertEqual(result.ncm_sugerido, "09012100")

    def test_does_not_suggest_when_confidence_is_low(self) -> None:
        result = self.engine.audit_product(
            ProductForAudit("SKU-3", "xilofone artesanal", "9405.10.00", None)
        )

        self.assertEqual(result.status, "no_suggestion")
        self.assertIsNone(result.ncm_sugerido)

    def test_normalization_is_deterministic(self) -> None:
        self.assertEqual(normalize_ncm("0901.21.00"), "09012100")
        self.assertIsNone(normalize_ncm("9012100"))
        self.assertEqual(normalize_text("Café / Torrado"), "cafe torrado")


    def test_reuses_classification_for_equivalent_products(self) -> None:
        products = [
            ProductForAudit("SKU-4", "Cafe torrado em graos", "9405.10.00", None),
            ProductForAudit("SKU-5", "  cafe torrado em graos ", "94051000", None),
        ]

        with patch.object(
            self.engine,
            "_audit_product_uncached",
            wraps=self.engine._audit_product_uncached,
        ) as audit_uncached:
            findings = self.engine.audit_products(products)

        self.assertEqual(audit_uncached.call_count, 1)
        self.assertEqual([finding.codigo_produto for finding in findings], ["SKU-4", "SKU-5"])
        self.assertEqual(findings[1].descricao, "  cafe torrado em graos ")
        self.assertEqual(findings[0].ncm_sugerido, findings[1].ncm_sugerido)

    def test_reports_progress_by_configured_batches(self) -> None:
        products = [
            ProductForAudit(f"SKU-{index}", "Cafe torrado em graos", "9405.10.00", None)
            for index in range(1, 6)
        ]
        progress: list[int] = []

        self.engine.audit_products(products, on_processed=progress.append, progress_every=2)

        self.assertEqual(progress, [2, 4, 5])

    def test_caches_best_ncm_match_for_repeated_description(self) -> None:
        matcher = NcmMatcher(REFERENCE)

        with patch(
            "app.services.ncm_matcher.process.extractOne",
            wraps=rapidfuzz_process.extractOne,
        ) as extract_one:
            first = matcher.best_match("Cafe torrado em graos")
            second = matcher.best_match(" cafe torrado em graos ")

        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(extract_one.call_count, 1)


if __name__ == "__main__":
    unittest.main()
