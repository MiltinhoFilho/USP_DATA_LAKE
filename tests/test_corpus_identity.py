import unittest
from unittest.mock import MagicMock

from src.postgres_loader import normalize_document_url, resolve_document_id_collisions


class CorpusIdentityTests(unittest.TestCase):
    def connection_with(self, rows):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = rows
        return connection

    def test_normalizes_fragment_and_tracking_without_network(self):
        self.assertEqual(
            normalize_document_url("HTTPS://JORNAL.USP.BR/noticia/?utm_source=x&id=1#parte"),
            "https://jornal.usp.br/noticia/?id=1",
        )

    def test_same_document_id_and_url_is_preserved(self):
        record = {"documento_id": "usp_news_000001", "chunk_id": 1,
                  "url": "https://jornal.usp.br/noticia/", "source_object": "raw/a.json"}
        records, collisions = resolve_document_id_collisions(
            [record], self.connection_with([("usp_news_000001", record["url"])])
        )
        self.assertEqual(records[0]["documento_id"], "usp_news_000001")
        self.assertEqual(collisions, [])

    def test_reused_sequential_id_is_remapped_deterministically(self):
        record = {"documento_id": "usp_news_000001", "chunk_id": 1,
                  "url": "https://jornal.usp.br/noticia-nova/", "source_object": "raw/a.json"}
        connection = self.connection_with([
            ("usp_news_000001", "https://jornal.usp.br/noticia-antiga/")
        ])
        first, collisions = resolve_document_id_collisions([record], connection)
        second, _ = resolve_document_id_collisions([record], self.connection_with([
            ("usp_news_000001", "https://jornal.usp.br/noticia-antiga/")
        ]))
        self.assertRegex(first[0]["documento_id"], r"^site_[0-9a-f]{16}$")
        self.assertEqual(first[0]["documento_id"], second[0]["documento_id"])
        self.assertEqual(len(collisions), 1)


if __name__ == "__main__":
    unittest.main()
