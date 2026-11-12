import unittest
from unittest.mock import patch

from rapidfuzz import process as rapidfuzz_process

from app.services.audit_engine import AuditEngine, ProductForAudit
from app.services.confirmed_codes import ConfirmedCode
from app.services.catalog_neighbors import CatalogEntry, CatalogIndex
from app.services.ncm_matcher import NcmMatcher, matching_text, normalize_ncm, normalize_text


REFERENCE = [
    ("0901.21.00", "Café torrado não descafeinado, em grãos"),
    ("9405.10.00", "Lustres e aparelhos elétricos de iluminação"),
    ("9608.40.00", "- Lapiseiras"),
    ("3215.11.00", "-- Pretas"),
    ("1902.19.00", "-- Outras massas alimentícias"),
    ("1902.11.00", "-- Que contenham ovos"),
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

    def test_does_not_replace_a_valid_ncm_by_table_similarity_alone(self) -> None:
        # Medido numa planilha real, a semelhança com a tabela quase nunca coincidia com o NCM
        # informado; trocar um código válido só por ela gerava centenas de sugestões erradas.
        result = self.engine.audit_product(
            ProductForAudit("SKU-2", "Café torrado em grãos", "9405.10.00", None)
        )

        self.assertEqual(result.status, "no_suggestion")
        self.assertIsNone(result.ncm_sugerido)
        self.assertEqual(result.ncm_status, "valid")

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


class NcmValidityAndCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = AuditEngine(REFERENCE)

    def test_invalid_ncm_is_reported_and_suggested_from_the_table_by_the_main_word(self) -> None:
        # "Pretas" cabe inteira no nome do produto, mas o produto é uma lapiseira.
        [result] = self.engine.audit_products([
            ProductForAudit("7891360582045", "LAPISEIRA FABER-CASTELL POLY TEEN 0,7 PRETA", "9999.99.99", None),
        ])

        self.assertEqual(result.ncm_status, "invalid")
        self.assertEqual(result.ncm_atual, "99999999")
        self.assertEqual(result.ncm_sugerido, "96084000")
        self.assertEqual(result.ncm_fonte, "tabela")
        self.assertEqual(result.status, "suggested")
        self.assertIn("9999.99.99 não existe na tabela NCM vigente", result.motivo)

    def test_invalid_ncm_without_a_safe_suggestion_goes_to_review(self) -> None:
        [result] = self.engine.audit_products([ProductForAudit("SKU-1", "Xilofone artesanal", "9999.99.99", None)])

        self.assertEqual(result.status, "pending_review")
        self.assertIsNone(result.ncm_sugerido)
        self.assertIn("corrija o NCM no cadastro de origem", result.motivo)

    def test_missing_ncm_is_reported_as_missing(self) -> None:
        [result] = self.engine.audit_products([ProductForAudit("SKU-1", "Xilofone artesanal", None, None)])

        self.assertEqual(result.ncm_status, "missing")
        self.assertIn("o NCM não foi informado", result.motivo)

    def test_invalid_ncm_takes_the_ncm_shared_by_similar_catalog_products(self) -> None:
        findings = self.engine.audit_products([
            ProductForAudit("A", "MACARRAO CRISTAL ESPAGUETE 500G", "1902.19.00", None),
            ProductForAudit("B", "MACARRAO CRISTAL PENNE 500G", "1902.19.00", None),
            ProductForAudit("C", "MACARRAO CRISTAL PARAFUSO 500G", "1902.19.00", None),
            ProductForAudit("D", "MACARRAO CRISTAL TALHARIM 500G", "9999.99.99", None),
        ])

        result = findings[3]
        self.assertEqual(result.ncm_sugerido, "19021900")
        self.assertEqual(result.ncm_fonte, "catalogo")
        self.assertIn("3 de 3 produtos parecidos do cadastro usam 1902.19.00", result.motivo)
        self.assertEqual(len(result.ncm_vizinhos), 3)
        self.assertNotIn("D", [neighbor["codigo_produto"] for neighbor in result.ncm_vizinhos])

    def test_valid_ncm_is_flagged_only_when_all_similar_products_disagree(self) -> None:
        unanimous = self.engine.audit_products([
            ProductForAudit("A", "MAIONESE QUERO SACHE 200G", "1902.19.00", None),
            ProductForAudit("B", "MAIONESE QUERO SACHE 700G", "1902.19.00", None),
            ProductForAudit("C", "MAIONESE QUERO 270G", "1902.19.00", None),
            ProductForAudit("D", "MAIONESE QUERO SACHE 1KG", "1902.11.00", None),
        ])[3]
        split = AuditEngine(REFERENCE).audit_products([
            ProductForAudit("A", "LEITE CONDENSADO MOCOCA 395G", "1902.19.00", None),
            ProductForAudit("B", "LEITE CONDENSADO PIRACANJUBA 395G", "1902.11.00", None),
            ProductForAudit("C", "LEITE CONDENSADO ITALAC 395G", "1902.19.00", None),
            ProductForAudit("D", "LEITE CONDENSADO EMBARE 395G", "1902.11.00", None),
        ])[3]

        self.assertEqual(unanimous.status, "suggested")
        self.assertEqual(unanimous.ncm_sugerido, "19021900")
        self.assertIn("Confira qual está certo", unanimous.motivo)
        self.assertEqual(split.status, "no_suggestion")
        self.assertIsNone(split.ncm_sugerido)

    def test_valid_ncm_shared_by_similar_products_is_confirmed(self) -> None:
        result = self.engine.audit_products([
            ProductForAudit("A", "MACARRAO CRISTAL ESPAGUETE 500G", "1902.19.00", None),
            ProductForAudit("B", "MACARRAO CRISTAL PENNE 500G", "1902.19.00", None),
            ProductForAudit("C", "MACARRAO CRISTAL PARAFUSO 500G", "1902.19.00", None),
        ])[0]

        self.assertEqual(result.status, "no_suggestion")
        self.assertIn("NCM atual igual ao de 2 de 2 produtos parecidos", result.motivo)

    def test_matching_text_drops_plural_numbers_measures_and_connectors(self) -> None:
        self.assertEqual(matching_text("LAPISEIRAS FABER-CASTELL 0,7 MM para escola"), "lapiseira faber castell escola")
        self.assertEqual(matching_text("Pães de queijo"), "pao queijo")


if __name__ == "__main__":
    unittest.main()


class ConfirmedCodesAndExtinctNcmTests(unittest.TestCase):
    REFERENCE = [
        ("2009.61.00", "-- Com valor Brix não superior a 30"),
        ("2202.99.00", "-- Outras"),
        ("1905.90.90", "Outros"),
        ("1901.20.10", "Massa para a preparação de pão, sem adição de grãos ou sementes integrais, congelada"),
        ("1901.20.20", "Massa para a preparação de pão, com adição de grãos ou sementes integrais, congelada"),
        ("1901.20.90", "Outras"),
        ("0402.99.00", "-- Outros"),
        ("0402.91.00", "-- Sem adição de açúcar"),
    ]
    CONFIRMED = [
        ConfirmedCode("7898953148220", "SUCO PRATS UVA 900ML", "20096100", "importacao"),
        ConfirmedCode("9051", "MANE PELADO E BOLOS DE PEDAÇO", "19059090", "aprovacao"),
    ]

    def audit(self, *products: ProductForAudit):
        return AuditEngine(self.REFERENCE, confirmed=self.CONFIRMED).audit_products(list(products))

    def test_product_is_recognized_by_its_ean_even_with_a_leading_zero(self) -> None:
        [result] = self.audit(ProductForAudit("07898953148220", "SUCO UVA INTEGRAL 900", None, None))

        self.assertEqual(result.status, "suggested")
        self.assertEqual(result.ncm_sugerido, "20096100")
        self.assertEqual(result.ncm_fonte, "confirmado")
        self.assertTrue(result.motivo.startswith("Código confirmado: NCM 2009.61.00"))
        self.assertIn("o NCM não foi informado", result.motivo)
        self.assertIn("importado como código confirmado, reconhecido pelo código do produto", result.motivo)

    def test_product_without_known_code_is_recognized_by_an_almost_identical_description(self) -> None:
        [result] = self.audit(ProductForAudit("OUTRO-COD", "Mané pelado e bolos de pedaco", "9999.99.99", None))

        self.assertEqual(result.ncm_sugerido, "19059090")
        self.assertIn("9999.99.99 não existe", result.motivo)
        self.assertIn("por descrição praticamente idêntica", result.motivo)

    def test_a_description_that_only_contains_a_confirmed_one_is_not_recognized(self) -> None:
        engine = AuditEngine(self.REFERENCE, confirmed=[ConfirmedCode(None, "SUCO UVA", "20096100", "importacao")])

        [result] = engine.audit_products([ProductForAudit("X", "SUCO UVA PRATS 900ML", None, None)])

        self.assertNotEqual(result.ncm_fonte, "confirmado")

    def test_confirmed_code_equal_to_the_current_one_is_reported_as_confirmed(self) -> None:
        [result] = self.audit(ProductForAudit("7898953148220", "SUCO PRATS UVA 900ML", "2009.61.00", None))

        self.assertEqual(result.status, "no_suggestion")
        self.assertEqual(result.ncm_fonte, "confirmado")
        self.assertIn("NCM confirmado anteriormente", result.motivo)

    def test_confirmed_code_beats_a_different_valid_ncm_in_the_spreadsheet(self) -> None:
        [result] = self.audit(ProductForAudit("7898953148220", "SUCO PRATS UVA 900ML", "2202.99.00", None))

        self.assertEqual(result.status, "suggested")
        self.assertEqual(result.ncm_sugerido, "20096100")
        self.assertIn("A planilha traz 2202.99.00", result.motivo)

    def test_extinct_ncm_lists_the_current_codes_of_its_subheading(self) -> None:
        [result] = self.audit(ProductForAudit("7896533710935", "MISTURA PARA MANE PELADO EMEGE", "1901.20.00", None))

        self.assertEqual(result.status, "pending_review")
        self.assertIsNone(result.ncm_sugerido)
        self.assertEqual([option["ncm"] for option in result.ncm_opcoes], ["19012010", "19012020", "19012090"])
        self.assertIn("O NCM 1901.20.00 não existe mais e hoje se divide em 3 códigos", result.motivo)

    def test_extinct_ncm_with_a_single_current_code_in_its_subheading_is_suggested(self) -> None:
        engine = AuditEngine([("1905.90.90", "Outros")])

        [result] = engine.audit_products([ProductForAudit("SKU", "Xilofone", "1905.90.10", None)])

        self.assertEqual(result.ncm_sugerido, "19059090")
        self.assertIn("o único código atual que começa como ele é 1905.90.90", result.motivo)


class PhaseOneEvidenceTests(unittest.TestCase):
    """Casos reais de uma planilha de supermercado que ficavam sem sugestão."""

    REFERENCE = [
        ("3402.50.00", "- Preparações acondicionadas para venda a retalho"),
        ("3402.90.31", "Preparações tensoativas"),
        ("1902.20.00", "- Massas alimentícias recheadas (mesmo cozidas ou preparadas de outro modo)"),
        ("1902.19.00", "-- Outras"),
        ("1509.20.00", "- Azeite de oliva extra virgem"),
        ("1509.30.00", "- Azeite de oliva virgem"),
        ("1509.40.00", "- Outros azeites de oliva virgens"),
        ("2103.90.11", "Maionese"),
        ("2103.90.19", "Outros"),
    ]

    def test_extinct_code_follows_the_official_correlation_table(self) -> None:
        [result] = AuditEngine(self.REFERENCE).audit_products([
            ProductForAudit("7896241900093", "LAVA ROUPAS KLIP ORIGINAL 1L", "3402.20.00", None),
        ])

        self.assertEqual(result.ncm_sugerido, "34025000")
        self.assertEqual(result.ncm_fonte, "correlacao")
        self.assertEqual(result.ncm_status, "invalid")
        self.assertIn("Tabela de Correlação NCM 2017×2022", result.motivo)

    def test_extinct_code_with_several_successors_offers_them_as_options(self) -> None:
        [result] = AuditEngine(self.REFERENCE).audit_products([
            ProductForAudit("1", "PRODUTO QUALQUER", "1509.10.00", None),
        ])

        self.assertEqual(result.status, "pending_review")
        self.assertEqual([option["ncm"] for option in result.ncm_opcoes], ["15092000", "15093000", "15094000"])
        self.assertEqual(result.ncm_fonte, "correlacao")

    def test_retail_synonym_classifies_a_product_the_table_does_not_name(self) -> None:
        [result] = AuditEngine(self.REFERENCE).audit_products([
            ProductForAudit("7891515475703", "LASANHA SADIA BOLONHESA", "9999.99.99", None),
        ])

        self.assertEqual(result.ncm_sugerido, "19022000")
        self.assertEqual(result.ncm_fonte, "sinonimo")
        self.assertTrue(result.motivo.startswith('"lasanha" é da família'))

    def test_valid_ncm_diverging_from_its_whole_family_is_flagged(self) -> None:
        products = [ProductForAudit(str(index), f"MAIONESE MARCA{index} {index}00G", "2103.90.11", None) for index in range(10)]
        products.append(ProductForAudit("X", "MAIONESE BAG VIGOR 1KG", "2103.90.19", None))

        result = AuditEngine(self.REFERENCE).audit_products(products)[-1]

        self.assertEqual(result.status, "suggested")
        self.assertEqual(result.ncm_sugerido, "21039011")
        self.assertIn(result.ncm_fonte, {"catalogo", "familia"})
        self.assertIn("Confira qual está certo", result.motivo)

    def test_rare_words_weigh_more_than_brands_when_finding_similar_products(self) -> None:
        index = CatalogIndex([
            CatalogEntry(0, "A", "LASANHA SEARA 600G", "19022000"),
            CatalogEntry(1, "B", "PIZZA SADIA CALABRESA", "19059090"),
            CatalogEntry(2, "C", "PRESUNTO SADIA", "16024100"),
            CatalogEntry(3, "D", "NUGGETS SADIA", "16023220"),
        ])

        [best, *_] = index.neighbors("LASANHA SADIA BOLONHESA")

        self.assertEqual(best.ncm, "19022000")

    def test_reference_files_ship_with_the_project(self) -> None:
        from app.services.ncm_references import correlation_map, synonym_dictionary

        self.assertEqual(correlation_map()["34022000"], ["34025000"])
        self.assertEqual(synonym_dictionary().lookup("LIMPADOR VEJA MULTI USO").ncm, "34025000")
