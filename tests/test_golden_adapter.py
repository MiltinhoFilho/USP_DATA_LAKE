from dataclasses import replace
from pathlib import Path
import unittest

from src.golden_adapter import silver_to_golden_chunks
from src.qdrant_loader import _payload
from src.silver import reconcile_sources, transform_json


class GoldenAdapterTests(unittest.TestCase):
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    BRONZE = PROJECT_ROOT / "bronze" / "raw"

    def test_rejects_non_promotable_silver_result(self):
        approved = transform_json(self.BRONZE / "usp_news_000001.json")
        rejected = replace(
            approved,
            promotable_to_golden=False,
            quality_issues=("major_json_pdf_divergence",),
        )

        with self.assertRaisesRegex(ValueError, "major_json_pdf_divergence"):
            silver_to_golden_chunks(rejected)

    def test_maps_canonical_document_and_preserves_both_sources(self):
        result = reconcile_sources(
            self.BRONZE / "usp_news_000001.json",
            self.BRONZE / "usp_news_000001.pdf",
        )
        chunks = silver_to_golden_chunks(result)

        self.assertTrue(chunks)
        self.assertEqual(
            [chunk["chunk_id"] for chunk in chunks],
            list(range(1, len(chunks) + 1)),
        )
        self.assertTrue(all(chunk["documento_id"] == "usp_news_000001" for chunk in chunks))
        self.assertTrue(all(chunk["source_object"] == "usp_news_000001.json" for chunk in chunks))
        self.assertTrue(all(chunk["source_type"] == "json" for chunk in chunks))
        self.assertTrue(
            all(
                chunk["source_objects"]
                == ("usp_news_000001.json", "usp_news_000001.pdf")
                for chunk in chunks
            )
        )
        self.assertTrue(all(chunk["lineage_id"] for chunk in chunks))
        self.assertTrue(all(chunk["canonical_sha256"] for chunk in chunks))

    def test_is_deterministic_and_does_not_duplicate_json_and_pdf(self):
        result = reconcile_sources(
            self.BRONZE / "usp_news_000053.json",
            self.BRONZE / "usp_news_000053.pdf",
        )

        first = silver_to_golden_chunks(result)
        second = silver_to_golden_chunks(result)

        self.assertEqual(first, second)
        self.assertEqual(
            len({(chunk["documento_id"], chunk["chunk_id"]) for chunk in first}),
            len(first),
        )
        self.assertTrue(any("≈" in chunk["texto"] for chunk in first))

    def test_qdrant_payload_preserves_available_lineage(self):
        result = reconcile_sources(
            self.BRONZE / "usp_news_000001.json",
            self.BRONZE / "usp_news_000001.pdf",
        )
        chunk = silver_to_golden_chunks(result)[0]
        payload = _payload(chunk, postgres_id=42)

        self.assertEqual(payload["postgres_id"], 42)
        self.assertEqual(payload["source_type"], "json")
        self.assertEqual(
            payload["source_objects"],
            ("usp_news_000001.json", "usp_news_000001.pdf"),
        )
        self.assertEqual(payload["lineage_id"], chunk["lineage_id"])
        self.assertEqual(payload["canonical_sha256"], chunk["canonical_sha256"])


if __name__ == "__main__":
    unittest.main()
