from io import BytesIO
import unittest

import pandas as pd

from app.services.excel_parser import SpreadsheetValidationError, parse_excel


def excel_file(rows: list[dict[str, str]]) -> BytesIO:
    content = BytesIO()
    pd.DataFrame(rows).to_excel(content, index=False)
    content.seek(0)
    return content


class ExcelParserTests(unittest.TestCase):
    def test_accepts_normalized_headers_and_preserves_codes_as_text(self) -> None:
        parsed = parse_excel(
            excel_file(
                [
                    {
                        "Código Produto": "SKU-01",
                        "Descrição": "Café torrado",
                        "NCM Atual": "0901.21.00",
                        "CEST Atual": "01.001.00",
                    }
                ]
            ),
            max_bytes=1_000_000,
        )

        self.assertEqual(parsed.total_rows, 1)
        self.assertEqual(parsed.products[0].codigo_produto, "SKU-01")
        self.assertEqual(parsed.products[0].ncm_atual, "09012100")

    def test_reports_row_errors_without_silent_partial_import(self) -> None:
        with self.assertRaises(SpreadsheetValidationError) as raised:
            parse_excel(
                excel_file(
                    [
                        {
                            "codigo_produto": "",
                            "descricao": "Produto",
                            "ncm_atual": "123",
                            "cest_atual": "invalido",
                        }
                    ]
                ),
                max_bytes=1_000_000,
            )

        messages = [error.display() for error in raised.exception.errors]
        self.assertEqual(len(messages), 3)
        self.assertTrue(any("codigo_produto" in message for message in messages))
        self.assertTrue(any("ncm_atual" in message for message in messages))
        self.assertTrue(any("cest_atual" in message for message in messages))

    def test_normalizes_unformatted_cest_and_restores_leading_zero(self) -> None:
        parsed = parse_excel(
            excel_file(
                [
                    {
                        "codigo_produto": "SKU-01",
                        "descricao": "Produto",
                        "ncm_atual": "09012100",
                        "cest_atual": "123456",
                    }
                ]
            ),
            max_bytes=1_000_000,
        )

        self.assertEqual(parsed.products[0].cest_atual, "01.234.56")

    def test_treats_erp_blank_cest_placeholder_as_empty(self) -> None:
        parsed = parse_excel(
            excel_file(
                [
                    {
                        "codigo_produto": "SKU-01",
                        "descricao": "Produto",
                        "ncm_atual": "09012100",
                        "cest_atual": "  .   .  ",
                    }
                ]
            ),
            max_bytes=1_000_000,
        )

        self.assertIsNone(parsed.products[0].cest_atual)
if __name__ == "__main__":
    unittest.main()
