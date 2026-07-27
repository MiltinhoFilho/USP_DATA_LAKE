import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.silver import (
    SilverResult,
    SourceReference,
    compare_json_pdf,
    deduplicate_exact_blocks,
    reconcile_sources,
    transform_json,
    transform_pdf,
)


def _article(**overrides):
    article = {
        "titulo": "Pesquisa interdisciplinar",
        "autor": "Autora Exemplo",
        "data": "2026-07-23T10:00:00+00:00",
        "categoria": "Ciências",
        "conteudo": (
            "<h2>Pesquisa interdisciplinar</h2>"
            "<p>Primeiro parágrafo editorial.</p>"
            "<p>Segundo parágrafo editorial.</p>"
        ),
        "url": "https://jornal.usp.br/ciencias/pesquisa-interdisciplinar/",
    }
    article.update(overrides)
    return article


class SilverTests(unittest.TestCase):
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.json_path = self.directory / "usp_news_000001.json"
        self._write(_article())

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _write(self, article):
        self.json_path.write_text(
            json.dumps(article, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _pdf_result_from_json(self, json_result, **document_overrides):
        source_hash = json_result.document.sources[0].source_content_sha256
        pdf_source = SourceReference(
            source_type="pdf",
            object_name="usp_news_000001.pdf",
            binary_sha256="a" * 64,
            source_content_sha256=source_hash,
        )
        values = {
            "primary_source": "pdf",
            "sources": (pdf_source,),
            **document_overrides,
        }
        document = replace(json_result.document, **values)
        return SilverResult(
            document=document,
            promotable_to_golden=False,
            quality_issues=("pdf_requires_json_authority",),
        )

    def test_json_builds_complete_canonical_document(self):
        result = transform_json(self.json_path)
        document = result.document

        self.assertTrue(result.promotable_to_golden)
        self.assertEqual(result.quality_issues, ())
        self.assertEqual(document.schema_version, "1.0")
        self.assertEqual(document.document_id, "usp_news_000001")
        self.assertEqual(document.primary_source, "json")
        self.assertEqual(document.text.count("Pesquisa interdisciplinar"), 1)
        self.assertRegex(document.canonical_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(
            document.lineage_id,
            f"silver:usp_news_000001:{document.canonical_sha256[:16]}",
        )
        self.assertEqual(document.sources[0].source_type, "json")
        self.assertRegex(
            document.sources[0].source_content_sha256 or "",
            r"^[0-9a-f]{64}$",
        )

    def test_canonical_field_order_is_stable(self):
        keys = list(transform_json(self.json_path).document.to_dict())
        self.assertEqual(
            keys,
            [
                "schema_version",
                "document_id",
                "lineage_id",
                "title",
                "author",
                "published_at",
                "category",
                "url",
                "text",
                "canonical_sha256",
                "primary_source",
                "sources",
                "transformations",
            ],
        )

    def test_json_transformation_is_idempotent(self):
        first = transform_json(self.json_path)
        second = transform_json(self.json_path)
        self.assertEqual(first, second)

    def test_hash_changes_only_when_canonical_content_changes(self):
        first = transform_json(self.json_path).document.canonical_sha256
        article = _article(
            conteudo="<p>Conteúdo editorial efetivamente alterado.</p>"
        )
        self._write(article)
        second = transform_json(self.json_path).document.canonical_sha256
        self.assertNotEqual(first, second)

    def test_exact_duplicate_blocks_are_removed_preserving_order(self):
        text, removed = deduplicate_exact_blocks(
            "# Título\n\nPrimeiro.\n\nSegundo.\n\nPrimeiro."
        )
        self.assertEqual(removed, 1)
        self.assertEqual(text, "# Título\n\nPrimeiro.\n\nSegundo.")

    def test_boilerplate_is_removed_without_losing_editorial_text(self):
        self._write(
            _article(
                conteudo=(
                    '<a href="#main-content">Pular barra de compartilhamento</a>'
                    "<p>Texto editorial preservado.</p>"
                )
            )
        )
        result = transform_json(self.json_path)
        self.assertNotIn("Pular barra", result.document.text)
        self.assertIn("Texto editorial preservado.", result.document.text)
        self.assertTrue(result.promotable_to_golden)

    def test_invisible_format_characters_are_removed_from_editorial_text(self):
        self._write(
            _article(
                conteudo="<p>Texto com caractere\u200b invisível preservado.</p>"
            )
        )
        result = transform_json(self.json_path)

        self.assertNotIn("\u200b", result.document.text)
        self.assertIn("Texto com caractere invisível preservado.", result.document.text)

    def test_pdf_is_transformed_as_auditable_non_promotable_fallback(self):
        pdf_path = self.PROJECT_ROOT / "bronze" / "raw" / "usp_news_000001.pdf"
        json_path = pdf_path.with_suffix(".json")
        json_result = transform_json(json_path)
        result = transform_pdf(pdf_path)

        self.assertEqual(result.document.primary_source, "pdf")
        self.assertEqual(result.document.document_id, "usp_news_000001")
        self.assertIn("A cultura organizacional", result.document.text)
        self.assertFalse(result.promotable_to_golden)
        self.assertEqual(
            result.document.published_at,
            json_result.document.published_at,
        )
        self.assertEqual(result.document.category, json_result.document.category)
        self.assertNotIn("JORNAL DA USP — RECORTE ACADÊMICO", result.document.text)
        self.assertNotIn("Autor: Não informado", result.document.text)
        self.assertNotIn("URL original:", result.document.text)
        self.assertIn("pdf_requires_json_authority", result.quality_issues)

    def test_equivalent_pair_uses_json_and_records_both_sources(self):
        json_result = transform_json(self.json_path)
        pdf_result = self._pdf_result_from_json(json_result)
        with patch("src.silver.transform_pdf", return_value=pdf_result):
            result = reconcile_sources(self.json_path, "validacao.pdf")

        self.assertEqual(result.document.primary_source, "json")
        self.assertEqual(
            [source.source_type for source in result.document.sources],
            ["json", "pdf"],
        )
        self.assertIsNotNone(result.divergence)
        self.assertEqual(result.divergence.classification, "equivalent")
        self.assertTrue(result.divergence.source_hash_match)
        self.assertTrue(result.promotable_to_golden)

    def test_json_has_precedence_and_major_divergence_blocks_promotion(self):
        original_json = transform_json(self.json_path)
        stale_pdf = self._pdf_result_from_json(
            original_json,
            title="Título anterior no PDF",
            text="Conteúdo anterior no PDF.",
            sources=(
                SourceReference(
                    source_type="pdf",
                    object_name="usp_news_000001.pdf",
                    binary_sha256="b" * 64,
                    source_content_sha256="c" * 64,
                ),
            ),
        )
        changed = _article(
            titulo="Título atualizado no JSON",
            conteudo="<p>Conteúdo atualizado e autoritativo do JSON.</p>",
        )
        self._write(changed)

        with patch("src.silver.transform_pdf", return_value=stale_pdf):
            result = reconcile_sources(self.json_path, "validacao.pdf")

        self.assertEqual(result.document.title, "Título atualizado no JSON")
        self.assertIn("Conteúdo atualizado", result.document.text)
        self.assertEqual(result.divergence.classification, "major")
        self.assertFalse(result.divergence.source_hash_match)
        self.assertFalse(result.promotable_to_golden)
        self.assertIn("major_json_pdf_divergence", result.quality_issues)

    def test_deterministic_comparison_reports_metadata_and_length(self):
        json_result = transform_json(self.json_path)
        pdf_result = self._pdf_result_from_json(json_result)
        first = compare_json_pdf(json_result, pdf_result)
        second = compare_json_pdf(json_result, pdf_result)

        self.assertEqual(first, second)
        self.assertGreaterEqual(first.text_similarity, 0)
        self.assertLessEqual(first.text_similarity, 1)
        self.assertIsInstance(first.length_difference, int)

    def test_missing_required_metadata_blocks_golden_promotion(self):
        self._write(_article(data="", categoria=""))
        result = transform_json(self.json_path)
        self.assertFalse(result.promotable_to_golden)
        self.assertIn("missing_published_at", result.quality_issues)
        self.assertIn("missing_category", result.quality_issues)

    def test_empty_author_is_allowed_by_current_bronze_contract(self):
        self._write(_article(autor=""))
        result = transform_json(self.json_path)
        self.assertTrue(result.promotable_to_golden)
        self.assertEqual(result.document.author, "")


if __name__ == "__main__":
    unittest.main()
