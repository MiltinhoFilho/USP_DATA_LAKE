import hashlib
import json
from pathlib import Path
import unittest

from bs4 import BeautifulSoup

from src.scraper import extract_content_html
from src.transform import (
    BronzeDocument,
    limpar_html_para_markdown,
    montar_texto_limpo,
    transformar_documento,
)


def _article(**overrides):
    article = {
        "titulo": "Título editorial",
        "autor": "Autora",
        "data": "2026-07-23T10:00:00+00:00",
        "categoria": "Ciências",
        "conteudo": "<p>Conteúdo editorial integral e relevante.</p>",
        "url": "https://jornal.usp.br/ciencias/titulo-editorial/",
    }
    article.update(overrides)
    return article


class BronzeBoilerplateTests(unittest.TestCase):
    def test_removes_skip_share_link_and_preserves_editorial_content(self):
        content = (
            '<a href="#main-content">Pular barra de compartilhamento</a>'
            "<h2>Título editorial</h2>"
            "<p>Conteúdo editorial integral e relevante.</p>"
        )

        cleaned = limpar_html_para_markdown(content)

        self.assertNotIn("Pular barra de compartilhamento", cleaned)
        self.assertIn("Título editorial", cleaned)
        self.assertIn("Conteúdo editorial integral e relevante.", cleaned)

    def test_removes_only_confirmed_trailing_radio_boilerplate(self):
        content = (
            "<p>A notícia menciona legitimamente o Jornal da USP no Ar.</p>"
            "<hr>"
            "<p><strong>Jornal da USP no Ar</strong></p>"
            '<p><a href="https://jornal.usp.br/editorias/radio-usp/'
            'jornal-da-usp-no-ar/">Jornal da USP no Ar</a> no ar veiculado '
            "pela Rede USP de Rádio, de segunda a sexta-feira: programação "
            "institucional e informações para sintonizar.</p>"
        )

        cleaned = limpar_html_para_markdown(content)

        self.assertIn(
            "A notícia menciona legitimamente o Jornal da USP no Ar.",
            cleaned,
        )
        self.assertNotIn("programação institucional", cleaned)
        self.assertNotIn("informações para sintonizar", cleaned)

    def test_removes_standalone_ad_label_but_preserves_editorial_word(self):
        content = (
            "<p>Publicidade</p>"
            "<p>A pesquisa discute publicidade e economia.</p>"
        )

        cleaned = limpar_html_para_markdown(content)

        self.assertNotIn("\nPublicidade\n", f"\n{cleaned}\n")
        self.assertIn("A pesquisa discute publicidade e economia.", cleaned)


class BronzeTitleTests(unittest.TestCase):
    def test_does_not_prepend_title_already_at_body_start(self):
        text = montar_texto_limpo(
            _article(
                conteudo=(
                    "<h2>Título editorial</h2>"
                    "<p>Conteúdo editorial integral e relevante.</p>"
                )
            )
        )

        self.assertEqual(text.count("Título editorial"), 1)
        self.assertTrue(text.startswith("## Título editorial"))

    def test_ignores_invisible_format_character_when_comparing_title(self):
        text = montar_texto_limpo(
            _article(
                titulo="Título editorial\u200b",
                conteudo=(
                    "<h2>Título editorial</h2>"
                    "<p>Conteúdo editorial integral e relevante.</p>"
                ),
            )
        )

        self.assertFalse(text.startswith("# Título editorial\u200b"))
        self.assertEqual(text.count("Título editorial"), 1)

    def test_prepends_title_when_body_does_not_start_with_it(self):
        text = montar_texto_limpo(_article())

        self.assertTrue(text.startswith("# Título editorial\n\n"))
        self.assertEqual(text.count("Título editorial"), 1)

    def test_external_pdf_keeps_existing_title_behavior(self):
        document = BronzeDocument(
            object_name="raw/pdf/externo.pdf",
            documento_id="pdf_externo",
            payload=_article(
                conteudo=(
                    "<h2>Título editorial</h2>"
                    "<p>Texto extraído do PDF externo.</p>"
                )
            ),
        )

        records = transformar_documento(document)
        transformed = "\n".join(record["texto"] for record in records)

        self.assertTrue(transformed.startswith("# Título editorial"))
        self.assertEqual(transformed.count("Título editorial"), 2)


class BronzeMetadataCorrectionTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent / "bronze" / "raw"

    def _load(self, index):
        return json.loads(
            (self.ROOT / f"usp_news_{index:06d}.json").read_text(
                encoding="utf-8"
            )
        )

    def test_only_proven_author_migrations_are_corrected(self):
        expected = {
            1: ("Marcelo Caldeira Pedroso", "Artigos"),
            24: ("Carlos Eduardo Lins da Silva", "Rádio USP"),
            31: ("Danilo Silva Guimarães", "Artigos"),
            50: ("Janice Theodoro da Silva", "Artigos"),
        }

        for index, (author, category) in expected.items():
            with self.subTest(index=index):
                article = self._load(index)
                self.assertEqual(article["autor"], author)
                self.assertEqual(article["categoria"], category)

    def test_equivalent_campus_category_is_normalized(self):
        self.assertEqual(
            self._load(71)["categoria"],
            "Campus Ribeirão Preto",
        )

    def test_editorial_bodies_of_corrected_metadata_remain_unchanged(self):
        expected_hashes = {
            1: "1d82aebc8cf878006dfbe9240cc134ace49805547e9ed5b2d83564700d72ef99",
            24: "e81ba059b3960fb28c698e1bd997f018f053857d68ced384a125b85dbf997f9c",
            31: "4f0a44c26bb777e5d61c8d80f40eafa62fb2317a75e1afaf156be774134f4f4c",
            50: "5f734865c15238c34b38ac0503f93bf9433ded4aafbef5b73a7a5f6b5a598b28",
            71: "ed5cf2356c1596e82b3e885c4b4a20990ebd7c066cca181b2e704a7021612f44",
        }

        for index, expected_hash in expected_hashes.items():
            with self.subTest(index=index):
                body = self._load(index)["conteudo"].encode("utf-8")
                self.assertEqual(hashlib.sha256(body).hexdigest(), expected_hash)


class BronzeShortDocumentTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent / "bronze" / "raw"

    def test_short_trailing_entry_content_falls_back_to_complete_main(self):
        soup = BeautifulSoup(
            (
                "<main><section><p>"
                + ("Conteúdo editorial completo. " * 12)
                + "</p></section><div class='entry-content'>"
                "<p>Mais informações: contato@example.test</p>"
                "<p>Crédito editorial.</p></div></main>"
            ),
            "html.parser",
        )

        extracted = extract_content_html(soup)

        self.assertIn("Conteúdo editorial completo.", extracted)
        self.assertIn("Mais informações:", extracted)
        self.assertGreater(
            len(BeautifulSoup(extracted, "html.parser").get_text(strip=True)),
            200,
        )

    def test_fragmented_elementor_article_combines_editorial_widgets(self):
        soup = BeautifulSoup(
            (
                "<main><div class='elementor'>"
                "<div class='elementor-widget-heading'>"
                "<div class='elementor-widget-container'>"
                "<h2>Notícia completa</h2></div></div>"
                "<div class='elementor-widget-text-editor'>"
                "<div class='elementor-widget-container'><p>"
                + ("Corpo editorial preservado. " * 12)
                + "</p></div></div>"
                "<div class='elementor-widget-text-editor'>"
                "<div class='elementor-widget-container'>"
                "<div class='entry-content'><p>Mais informações.</p></div>"
                "</div></div></div></main>"
            ),
            "html.parser",
        )

        extracted = extract_content_html(soup)

        self.assertIn("<h2>Notícia completa</h2>", extracted)
        self.assertIn("Corpo editorial preservado.", extracted)
        self.assertIn("Mais informações.", extracted)
        self.assertNotIn("<main", extracted)

    def test_000065_contains_complete_recovered_editorial_sections(self):
        article = json.loads(
            (self.ROOT / "usp_news_000065.json").read_text(encoding="utf-8")
        )
        text = BeautifulSoup(article["conteudo"], "html.parser").get_text(
            " ",
            strip=True,
        )

        self.assertGreater(len(text), 5_000)
        self.assertIn("No início da pandemia de covid-19", text)
        self.assertIn("Como funcionou o acompanhamento", text)
        self.assertIn("quatro momentos principais", text)
        self.assertIn("Carlos Roberto Ribeiro Carvalho", text)
        self.assertIn("Mais informações: laura.sampaio@hc.fm.usp.br", text)


if __name__ == "__main__":
    unittest.main()
