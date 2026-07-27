import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from PyPDF2 import PdfReader

from src.pdf_generator import (
    PDFValidationError,
    SourceValidationError,
    calculate_source_hash,
    extract_canonical_identity,
    generate_pdf_batch,
    generate_pdf_from_json,
    load_source_json,
    normalize_text,
    validate_pdf_against_json,
)
from src.transform import _decode_pdf_bytes, transformar_documento


def _payload(**overrides):
    payload = {
        "titulo": "Título de teste",
        "autor": "Autora Exemplo",
        "data": "2026-07-23T10:00:00+00:00",
        "categoria": "Ciência",
        "conteudo_texto": (
            "Primeiro parágrafo com informação integral.\n\n"
            "Segundo parágrafo para validar a extração."
        ),
        "conteudo": "<p>HTML legado que não deve ser usado no PDF.</p>",
        "url": "https://jornal.usp.br/noticias/teste/",
    }
    payload.update(overrides)
    return payload


class PdfGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.source = self.directory / "usp_news_000001.json"
        self.source.write_text(
            json.dumps(_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _write_payload(self, payload):
        self.source.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_extracts_canonical_identity(self):
        identity = extract_canonical_identity(self.source)
        self.assertEqual(identity.canonical_id, "usp_news_000001")
        self.assertEqual(identity.source_index, "000001")
        self.assertEqual(identity.source_json, "usp_news_000001.json")
        self.assertEqual(identity.source_pdf, "usp_news_000001.pdf")

    def test_rejects_invalid_source_name(self):
        with self.assertRaisesRegex(SourceValidationError, "Nome de JSON inválido"):
            extract_canonical_identity("noticia-1.json")

    def test_canonical_hash_is_stable_across_json_formatting(self):
        first = calculate_source_hash(load_source_json(self.source))
        self.source.write_text(
            json.dumps(_payload(), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        second = calculate_source_hash(load_source_json(self.source))
        self.assertEqual(first, second)

    def test_hash_changes_when_source_content_changes(self):
        original = calculate_source_hash(load_source_json(self.source))
        changed = _payload(conteudo_texto="Conteúdo alterado.")
        self._write_payload(changed)
        self.assertNotEqual(
            original,
            calculate_source_hash(load_source_json(self.source)),
        )

    def test_normalizes_unicode_and_whitespace(self):
        value = "  cafe\u0301\u200b  \u202fﬁm\r\n\r\n\r\ntexto  "
        self.assertEqual(normalize_text(value), "café fim\n\ntexto")

    def test_preserves_approximation_symbol_without_replacement(self):
        self._write_payload(_payload(conteudo_texto="valor ≈ outro"))
        result = generate_pdf_from_json(self.source)
        reader = PdfReader(str(result.pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

        self.assertIn("valor ≈ outro", text)
        self.assertNotIn("�", text)

    def test_reports_unsupported_character_without_replacement(self):
        with self.assertRaisesRegex(
            SourceValidationError,
            r"preservar o conteúdo.*U\+1F600.*'conteudo_texto'.*Nenhum PDF será gerado",
        ):
            normalize_text("valor 😀 outro", field_name="conteudo_texto")

    def test_unsupported_character_does_not_create_partial_pdf(self):
        self._write_payload(_payload(conteudo_texto="valor 😀 outro"))

        with self.assertRaisesRegex(SourceValidationError, r"U\+1F600"):
            generate_pdf_from_json(self.source)

        self.assertFalse(self.source.with_suffix(".pdf").exists())
        self.assertEqual(list(self.directory.glob("*.tmp")), [])
        self.assertIn("😀", load_source_json(self.source)["conteudo_texto"])

    def test_rejects_empty_content(self):
        self._write_payload(_payload(conteudo_texto="  "))
        with self.assertRaisesRegex(SourceValidationError, "conteudo_texto.*vazio"):
            load_source_json(self.source)

    def test_generates_valid_extractable_pdf_with_metadata(self):
        result = generate_pdf_from_json(self.source)
        self.assertEqual(result.status, "generated")
        self.assertTrue(result.pdf_path.read_bytes().startswith(b"%PDF-"))
        self.assertGreater(result.validation.page_count, 0)
        reader = PdfReader(str(result.pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("Primeiro parágrafo", text)
        self.assertEqual(reader.metadata["/Title"], "Título de teste")
        self.assertEqual(reader.metadata["/Author"], "Autora Exemplo")
        self.assertEqual(
            reader.metadata["/Subject"],
            "Source-URL: https://jornal.usp.br/noticias/teste/",
        )
        self.assertIn(
            "Canonical-ID=usp_news_000001",
            reader.metadata["/Keywords"],
        )
        self.assertIn(
            "Source-JSON=usp_news_000001.json",
            reader.metadata["/Keywords"],
        )
        self.assertIn(
            f"Source-SHA256={result.validation.source_hash}",
            reader.metadata["/Keywords"],
        )
        self.assertIn("Source-Format=json", reader.metadata["/Keywords"])
        self.assertIn("Corpus=Jornal-USP-PoC", reader.metadata["/Keywords"])

    def test_body_excludes_internal_engineering_metadata(self):
        result = generate_pdf_from_json(self.source)
        reader = PdfReader(str(result.pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertNotIn("Identificador:", text)
        self.assertNotIn("usp_news_000001.json", text)
        self.assertNotIn(result.validation.source_hash, text)
        self.assertNotIn("Source-JSON", text)
        self.assertNotIn("Source-SHA256", text)
        self.assertNotIn(
            "Documento gerado a partir do JSON armazenado na camada Bronze",
            text,
        )
        self.assertNotIn("JORNAL DA USP — RECORTE ACADÊMICO", text)

    def test_visible_fields_and_editorial_body_remain_faithful(self):
        payload = load_source_json(self.source)
        result = generate_pdf_from_json(self.source)
        reader = PdfReader(str(result.pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        compact = lambda value: "".join(value.split())

        self.assertIn(payload["titulo"], text)
        self.assertIn(f"Autor: {payload['autor'] or 'Não informado'}", text)
        self.assertIn(f"Data: {payload['data']}", text)
        self.assertIn(f"Categoria: {payload['categoria']}", text)
        self.assertIn(compact(payload["url"]), compact(text))
        self.assertIn(
            compact(payload["conteudo_texto"]),
            compact(text),
        )

    def test_body_uses_only_conteudo_texto_without_html_fallback(self):
        self._write_payload(
            _payload(
                conteudo="<p>CONTEÚDO HTML PROIBIDO</p>",
                conteudo_texto="Conteúdo editorial canônico.",
            )
        )
        result = generate_pdf_from_json(self.source)
        text = "\n".join(
            page.extract_text() or ""
            for page in PdfReader(str(result.pdf_path)).pages
        )

        self.assertIn("Conteúdo editorial canônico.", text)
        self.assertNotIn("CONTEÚDO HTML PROIBIDO", text)

    def test_empty_author_is_preserved_in_metadata(self):
        self._write_payload(_payload(autor=""))
        result = generate_pdf_from_json(self.source)
        reader = PdfReader(str(result.pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertEqual(reader.metadata["/Author"], "")
        self.assertIn("Autor: Não informado", text)

    def test_accents_and_legitimate_question_mark_are_preserved(self):
        editorial_text = (
            "á à â ã é ê í ó ô õ ú ç — “texto” ‘teste’ … •\n\n"
            "Esta é uma pergunta legítima?"
        )
        self._write_payload(_payload(conteudo_texto=editorial_text))
        result = generate_pdf_from_json(self.source)
        reader = PdfReader(str(result.pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        for expected in (
            "á", "à", "â", "ã", "é", "ê", "í", "ó", "ô", "õ", "ú", "ç",
            "—", "“", "”", "‘", "’", "…", "•",
        ):
            self.assertIn(expected, text)
        self.assertEqual(text.count("?"), 1)
        self.assertNotIn("�", text)

    def test_generation_is_deterministic(self):
        first = generate_pdf_from_json(self.source)
        with tempfile.TemporaryDirectory() as second_directory:
            second_source = Path(second_directory) / self.source.name
            second_source.write_bytes(self.source.read_bytes())
            second = generate_pdf_from_json(second_source)
            self.assertEqual(
                first.pdf_path.read_bytes(),
                second.pdf_path.read_bytes(),
            )

    def test_validates_long_url_wrapped_across_pdf_lines(self):
        long_url = (
            "https://jornal.usp.br/articulistas/exemplo/"
            "uma-url-longa-que-precisa-ser-quebrada-durante-a-renderizacao/"
        )
        self._write_payload(_payload(url=long_url))
        result = generate_pdf_from_json(self.source)
        validation = validate_pdf_against_json(result.pdf_path, self.source)
        self.assertEqual(
            validation.metadata["/Subject"],
            f"Source-URL: {long_url}",
        )

    def test_validates_long_title_wrapped_across_pdf_lines(self):
        long_title = (
            "Da ideia ao impacto: pesquisa universitária constrói uma rede "
            "para transformar conhecimento em soluções para a sociedade"
        )
        self._write_payload(_payload(titulo=long_title))
        result = generate_pdf_from_json(self.source)
        validation = validate_pdf_against_json(result.pdf_path, self.source)

        self.assertEqual(validation.metadata["/Title"], long_title)

    def test_second_execution_is_idempotent(self):
        first = generate_pdf_from_json(self.source)
        first_bytes = first.pdf_path.read_bytes()
        second = generate_pdf_from_json(self.source)
        self.assertEqual(second.status, "unchanged")
        self.assertEqual(first_bytes, second.pdf_path.read_bytes())
        self.assertEqual(
            list(self.directory.glob("usp_news_000001*.pdf")),
            [self.directory / "usp_news_000001.pdf"],
        )

    def test_blocks_overwrite_when_existing_pdf_is_invalid(self):
        destination = self.source.with_suffix(".pdf")
        destination.write_bytes(b"%PDF-invalid")
        with self.assertRaisesRegex(FileExistsError, "não será sobrescrito"):
            generate_pdf_from_json(self.source)
        self.assertEqual(destination.read_bytes(), b"%PDF-invalid")

    def test_regenerates_only_with_explicit_option(self):
        destination = self.source.with_suffix(".pdf")
        destination.write_bytes(b"%PDF-invalid")
        result = generate_pdf_from_json(self.source, regenerate=True)
        self.assertEqual(result.status, "regenerated")
        self.assertGreater(result.validation.page_count, 0)

    def test_validation_detects_hash_divergence(self):
        result = generate_pdf_from_json(self.source)
        self._write_payload(_payload(conteudo_texto="Novo conteúdo."))
        with self.assertRaisesRegex(PDFValidationError, "Metadado /Keywords"):
            validate_pdf_against_json(result.pdf_path, self.source)

    def test_is_compatible_with_current_transform(self):
        result = generate_pdf_from_json(self.source)
        raw_bytes = result.pdf_path.read_bytes()
        document = _decode_pdf_bytes(raw_bytes, "raw/pdf/usp_news_000001.pdf")[0]
        records = transformar_documento(document)
        self.assertEqual(document.documento_id, "pdf_usp_news_000001")
        self.assertEqual(
            document.payload["url"],
            "https://jornal.usp.br/noticias/teste/",
        )
        self.assertTrue(records)
        self.assertTrue(all(record["texto"] for record in records))

    def test_generation_does_not_use_network_or_external_services(self):
        with patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("acesso externo não permitido"),
        ):
            result = generate_pdf_from_json(self.source)
        self.assertEqual(result.status, "generated")

    def test_temporary_file_is_removed_after_success(self):
        generate_pdf_from_json(self.source)
        self.assertEqual(list(self.directory.glob("*.tmp")), [])
        self.assertEqual(list(self.directory.glob(".*.tmp")), [])

    def test_batch_is_one_to_one_idempotent_and_selectively_regenerates(self):
        second_source = self.directory / "usp_news_000002.json"
        second_source.write_text(
            json.dumps(_payload(titulo="Segundo documento"), ensure_ascii=False),
            encoding="utf-8",
        )
        external_pdf = self.directory / "externo.pdf"
        external_pdf.write_bytes(b"%PDF-external")

        first = generate_pdf_batch(
            [self.source, second_source],
            self.directory,
        )
        self.assertEqual([item.status for item in first.generated], ["generated", "generated"])
        self.assertTrue(external_pdf.exists())

        hashes = {
            item.pdf_path.name: item.pdf_path.read_bytes()
            for item in first.generated
        }
        second = generate_pdf_batch(
            [self.source, second_source],
            self.directory,
        )
        self.assertEqual([item.status for item in second.generated], ["unchanged", "unchanged"])

        self._write_payload(_payload(conteudo_texto="Conteúdo atualizado."))
        third = generate_pdf_batch(
            [self.source, second_source],
            self.directory,
        )
        self.assertEqual([item.status for item in third.generated], ["regenerated", "unchanged"])
        self.assertNotEqual(
            hashes["usp_news_000001.pdf"],
            (self.directory / "usp_news_000001.pdf").read_bytes(),
        )
        self.assertEqual(
            hashes["usp_news_000002.pdf"],
            (self.directory / "usp_news_000002.pdf").read_bytes(),
        )
        self.assertEqual(list(self.directory.glob(".pdf-corpus-*")), [])

    def test_batch_preparation_failure_publishes_nothing(self):
        second_source = self.directory / "usp_news_000002.json"
        second_source.write_text(
            json.dumps(
                _payload(conteudo_texto="Caractere não suportado: 😀"),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(SourceValidationError, r"U\+1F600"):
            generate_pdf_batch(
                [self.source, second_source],
                self.directory,
            )

        self.assertFalse((self.directory / "usp_news_000001.pdf").exists())
        self.assertFalse((self.directory / "usp_news_000002.pdf").exists())
        self.assertEqual(list(self.directory.glob(".pdf-corpus-*")), [])


if __name__ == "__main__":
    unittest.main()
