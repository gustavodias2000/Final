import unittest

from app.services.reference.cest_lookup import CestLookupClient, CestLookupStatus
from app.services.reference.ncm_catalog import SiscomexNcmCatalogClient


class FakeJsonResponse:
    headers = {"ETag": "catalog-v1"}

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {
            "Nomenclaturas": [
                {"Codigo": "0901.21.00", "Descricao": "Café torrado em grãos"},
                {"Codigo": "0901.21.00", "Descricao": "Registro duplicado"},
                {"Codigo": "invalido", "Descricao": "Ignorado"},
            ]
        }


class FakeJsonClient:
    def get(self, url, *, timeout, headers):
        self.url = url
        self.timeout = timeout
        self.headers = headers
        return FakeJsonResponse()


class FakeHtmlResponse:
    text = """
        <html><body><table><tr><td>CEST</td><td>01.001.00</td></tr>
        <tr><td>02.002.00</td></tr></table></body></html>
    """

    def raise_for_status(self) -> None:
        return None


class FakeHtmlClient:
    def __init__(self):
        self.calls = 0

    def get(self, url, *, timeout, headers):
        self.calls += 1
        self.url = url
        return FakeHtmlResponse()


class ReferenceServiceTests(unittest.TestCase):
    def test_catalog_is_normalized_deduplicated_and_versioned(self) -> None:
        client = FakeJsonClient()
        catalog = SiscomexNcmCatalogClient(
            "https://example.test/ncm", timeout_seconds=3, http_client=client
        ).fetch()

        self.assertEqual(catalog.matcher_pairs(), [("09012100", "Café torrado em grãos")])
        self.assertEqual(catalog.source_etag, "catalog-v1")
        self.assertTrue(catalog.version.startswith("sha256:"))
        self.assertEqual(client.headers["Accept"], "application/json")

    def test_cest_lookup_keeps_all_codes_and_uses_cache(self) -> None:
        client = FakeHtmlClient()
        lookup = CestLookupClient(
            "https://example.test/cest?ncm={ncm}",
            timeout_seconds=3,
            cache_ttl_seconds=60,
            http_client=client,
        )

        result = lookup.lookup("0901.21.00")
        cached = lookup.lookup("09012100")

        self.assertEqual(result.status, CestLookupStatus.FOUND)
        self.assertEqual(result.cest_codes, ("01.001.00", "02.002.00"))
        self.assertIsNone(result.suggested_cest)
        self.assertEqual(client.calls, 1)
        self.assertEqual(cached, result)

    def test_invalid_ncm_never_causes_external_request(self) -> None:
        client = FakeHtmlClient()
        lookup = CestLookupClient(
            "https://example.test/cest?ncm={ncm}",
            timeout_seconds=3,
            cache_ttl_seconds=60,
            http_client=client,
        )

        result = lookup.lookup("123")

        self.assertEqual(result.status, CestLookupStatus.INVALID_NCM)
        self.assertEqual(client.calls, 0)
