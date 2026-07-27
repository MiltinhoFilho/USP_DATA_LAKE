import json
from pathlib import Path
import tempfile
import unittest

from scripts.restructure_bronze_staging import (
    generate_staging,
    restructure_document,
)
from src.transform import extract_clean_text, refine_editorial_text


class EditorialTextTests(unittest.TestCase):
    def test_removes_non_editorial_elements(self):
        html = """
        <article><style>.x{color:red}</style><script>alert(1)</script>
        <noscript>ative scripts</noscript><nav>menu</nav>
        <p>Texto editorial.</p></article>
        """
        text = extract_clean_text(html)
        self.assertEqual(text, "Texto editorial.")

    def test_preserves_paragraphs(self):
        text = extract_clean_text("<article><p>Primeiro.</p><p>Segundo.</p></article>")
        self.assertEqual(text, "Primeiro.\n\nSegundo.")

    def test_preserves_headings_lists_and_links(self):
        text = extract_clean_text(
            '<article><h2>Seção</h2><ul><li>Um</li><li>Dois</li></ul>'
            '<p><a href="https://example.test">Referência</a></p></article>'
        )
        self.assertIn("## Seção", text)
        self.assertIn("- Um", text)
        self.assertIn("[Referência](https://example.test)", text)

    def test_images_are_removed_without_losing_caption_text(self):
        text = extract_clean_text(
            '<article><figure><img src="x"><figcaption>Legenda</figcaption>'
            "</figure></article>"
        )
        self.assertNotIn("src=", text)
        self.assertIn("Legenda", text)

    def test_preserves_unicode_accents_and_approximation(self):
        text = extract_clean_text("<p>São Paulo: valor ≈ outro.</p>")
        self.assertEqual(text, "São Paulo: valor ≈ outro.")

    def test_accepts_malformed_html_and_missing_entry_content(self):
        text = extract_clean_text("<main><h2>Título<p>Parágrafo incompleto")
        self.assertIn("Título", text)
        self.assertIn("Parágrafo incompleto", text)

    def test_empty_html_returns_empty_text(self):
        self.assertEqual(extract_clean_text(""), "")

    def test_non_string_is_rejected(self):
        with self.assertRaises(TypeError):
            extract_clean_text(None)  # type: ignore[arg-type]

    def test_long_paragraph_is_not_truncated(self):
        paragraph = "conteúdo " * 2000
        text = extract_clean_text(f"<p>{paragraph}</p>")
        self.assertGreater(len(text), 15000)
        self.assertTrue(text.endswith("conteúdo"))

    def test_restructure_preserves_original_and_metadata(self):
        source = {
            "titulo": "Título",
            "autor": "",
            "data": "2026-01-01",
            "categoria": "Ciências",
            "conteudo": "<p>Texto íntegro.</p>",
            "url": "https://example.test/noticia",
        }
        result = restructure_document(source, "usp_news_000001")
        self.assertEqual(result["conteudo"], source["conteudo"])
        self.assertEqual(result["conteudo_html"], source["conteudo"])
        self.assertEqual(result["conteudo_texto"], "Texto íntegro.")
        self.assertEqual(result["autor"], "")

    def test_restructure_is_deterministic_and_idempotent(self):
        source = {
            "titulo": "Título",
            "autor": "Autor",
            "data": "2026-01-01",
            "categoria": "USP",
            "conteudo": "<p>Texto.</p>",
            "url": "https://example.test",
        }
        first = restructure_document(source, "usp_news_000001")
        second = restructure_document(first, "usp_news_000001")
        self.assertEqual(first, second)

    def test_restructure_rejects_empty_content(self):
        with self.assertRaises(ValueError):
            restructure_document({"conteudo": ""}, "usp_news_000001")

    def test_duplicate_leading_title_is_removed(self):
        text = extract_clean_text(
            "<article><h2>Título da matéria</h2><p>Último parágrafo.</p></article>",
            title="Título da matéria",
        )
        self.assertEqual(text, "Último parágrafo.")

    def test_legitimate_internal_title_is_preserved(self):
        text = extract_clean_text(
            "<article><p>Introdução.</p><h2>Título da matéria</h2>"
            "<p>Final.</p></article>",
            title="Título da matéria",
        )
        self.assertIn("## Título da matéria", text)

    def test_duplicate_byline_is_removed(self):
        text = extract_clean_text(
            "<article><p>Por Maria da Silva</p><p>Notícia.</p></article>",
            author="Maria da Silva",
        )
        self.assertEqual(text, "Notícia.")

    def test_author_mentioned_legitimately_is_preserved(self):
        text = extract_clean_text(
            "<article><p>Notícia.</p><p>Maria da Silva explicou o estudo.</p>"
            "</article>",
            author="Maria da Silva",
        )
        self.assertIn("Maria da Silva explicou", text)

    def test_generic_opinion_notice_and_variation_are_removed(self):
        for notice in (
            "As opiniões expressas nos artigos publicados são de inteira "
            "responsabilidade de seus autores.",
            "As opiniões expressas nos artigos publicados no Jornal da USP "
            "são de inteira responsabilidade de seus autores e não refletem "
            "posições institucionais.",
        ):
            with self.subTest(notice=notice):
                refinement = refine_editorial_text(
                    f"Último parágrafo editorial.\n\n{notice}"
                )
                self.assertEqual(
                    refinement.text, "Último parágrafo editorial."
                )
                self.assertEqual(
                    refinement.removals[0].rule,
                    "generic_opinion_notice",
                )

    def test_generic_reuse_policy_is_removed(self):
        refinement = refine_editorial_text(
            "Último parágrafo.\n\n---\n\n"
            "## Política de uso\nA reprodução de matérias é livre. "
            "Para uso de arquivos de vídeo devem constar os créditos. "
            "Fotos devem ser creditadas."
        )
        self.assertEqual(refinement.text, "Último parágrafo.")
        self.assertEqual(
            {item.rule for item in refinement.removals},
            {"generic_reuse_credits", "generic_reuse_separator"},
        )

    def test_legitimate_photo_credit_is_preserved(self):
        text = refine_editorial_text(
            "Texto da notícia.\n\nFoto: Maria da Silva/USP Imagens"
        ).text
        self.assertTrue(text.endswith("Foto: Maria da Silva/USP Imagens"))

    def test_last_editorial_paragraph_is_preserved(self):
        text = extract_clean_text(
            "<p>Introdução.</p><p>Último parágrafo jornalístico.</p>"
        )
        self.assertTrue(text.endswith("Último parágrafo jornalístico."))

    def test_refinement_is_idempotent_and_deterministic(self):
        source = (
            "## Título\n\nTexto legítimo.\n\n"
            "As opiniões expressas nos artigos publicados são de inteira "
            "responsabilidade de seus autores."
        )
        first = refine_editorial_text(source, title="Título")
        second = refine_editorial_text(first.text, title="Título")
        repeated = refine_editorial_text(source, title="Título")
        self.assertEqual(first.text, second.text)
        self.assertEqual(first, repeated)

    def test_batch_of_one_hundred_uses_isolated_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            staging = root / "staging"
            reports = root / "reports"
            source.mkdir()
            for index in range(1, 101):
                payload = {
                    "titulo": f"Título {index}",
                    "autor": "" if index == 50 else "Autor",
                    "data": "2026-01-01",
                    "categoria": "USP",
                    "conteudo": f"<article><p>Texto {index}.</p></article>",
                    "url": f"https://example.test/{index}",
                }
                (source / f"usp_news_{index:06d}.json").write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )
            rows = generate_staging(source, staging, reports)
            self.assertEqual(len(rows), 100)
            self.assertEqual(len(list(staging.glob("*.json"))), 100)
            self.assertTrue(all(row["status"] == "APROVADO" for row in rows))


if __name__ == "__main__":
    unittest.main()
