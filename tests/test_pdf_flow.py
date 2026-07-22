import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import src.api.generator_api as generator_api
import src.api.pipeline_api as pipeline_api
from src.transform import _decode_pdf_bytes, _extract_text_from_pdf_bytes, transformar_documento
from src.upload_bronze import upload_bronze_file


class PdfGeneratorTests(unittest.TestCase):
    def test_invalid_url_is_rejected(self):
        response = TestClient(generator_api.app).get("/pdf", params={"url": "arquivo.pdf"})
        self.assertEqual(response.status_code, 422)

    def test_html_news_generates_and_uploads_only_the_pdf(self):
        response = MagicMock()
        response.content = b"<html></html>"
        article_text = "Texto válido da notícia para geração e extração do PDF. " * 4
        response.text = ("<html><head><meta property='og:title' content='Noticia teste'></head>"
                         f"<body><main><div class='entry-content'>{article_text}</div></main></body></html>")
        response.apparent_encoding = "utf-8"
        response.headers = {"content-type": "text/html"}
        response.raise_for_status.return_value = None
        uploaded = {"bucket": "bronze", "object_key": "raw/pdf/noticia.pdf",
                    "size_bytes": 100, "content_type": "application/pdf"}
        with patch.object(generator_api.requests, "get", return_value=response), \
             patch.object(generator_api, "upload_bronze_file", return_value=uploaded) as upload:
            result = TestClient(generator_api.app).get(
                "/pdf", params={"url": "https://jornal.usp.br/noticia/", "filename": "noticia.pdf",
                                "upload_minio": "true"})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["data"]["uploaded"])
        upload.assert_called_once()
        generated_path = upload.call_args.args[0]
        self.assertTrue(generated_path.read_bytes().startswith(b"%PDF-"))
        generated_path.unlink(missing_ok=True)

    def test_upload_uses_pdf_prefix_and_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty.pdf"
            empty.write_bytes(b"")
            with self.assertRaises(ValueError):
                upload_bronze_file(empty)

            valid = Path(directory) / "valid.pdf"
            valid.write_bytes(b"%PDF-test")
            client = MagicMock()
            client.stat_object.return_value = MagicMock(size=9, content_type="application/pdf")
            with patch("src.upload_bronze.get_minio_client", return_value=client), \
                 patch("src.upload_bronze.ensure_bucket", return_value="bronze"), \
                 patch("src.upload_bronze.upload_file") as upload:
                result = upload_bronze_file(valid)
            self.assertEqual(result["object_key"], "raw/pdf/valid.pdf")
            upload.assert_called_once_with(valid, "raw/pdf/valid.pdf", client=client, bucket_name="bronze")


class PdfPipelineTests(unittest.TestCase):
    def setUp(self):
        self.pdf = generator_api._build_text_pdf(
            "Titulo PDF", "https://jornal.usp.br/noticia/", "Texto extraido do PDF para gerar chunks."
        )

    def test_signature_and_extraction_validation(self):
        with self.assertRaisesRegex(RuntimeError, "PDF vazio"):
            _extract_text_from_pdf_bytes(b"", "empty.pdf")
        with self.assertRaisesRegex(RuntimeError, "assinatura PDF"):
            _extract_text_from_pdf_bytes(b"nao-pdf", "invalid.pdf")
        self.assertIn("Texto extraido", _extract_text_from_pdf_bytes(self.pdf, "valid.pdf"))

    def test_valid_pdf_preserves_metadata_and_generates_chunks(self):
        document = _decode_pdf_bytes(self.pdf, "raw/pdf/valid.pdf")[0]
        records = transformar_documento(document)
        self.assertTrue(records)
        self.assertEqual(document.documento_id, "pdf_valid")
        self.assertEqual(records[0]["url"], "https://jornal.usp.br/noticia/")

    def test_process_pdf_uses_same_recursive_prefix_without_persistence(self):
        record = {"documento_id": "pdf_valid", "chunk_id": 1, "texto": "texto",
                  "titulo": "Titulo", "source_object": "raw/pdf/valid.pdf"}
        with patch.object(pipeline_api, "run_transform", return_value=[record]) as transform, \
             patch.object(pipeline_api, "insert_chunks") as postgres, \
             patch.object(pipeline_api, "upsert_embeddings") as qdrant:
            response = TestClient(pipeline_api.app).post(
                "/processar-pdf",
                json={"source": "minio", "limit": 1, "load_postgres": False, "load_qdrant": False},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["chunks_gerados"], 1)
        self.assertEqual(transform.call_args.kwargs["prefix"], "raw/pdf/")
        self.assertEqual(transform.call_args.kwargs["extensions"], {"pdf"})
        postgres.assert_not_called()
        qdrant.assert_not_called()

    def test_pdf_alias_and_openapi_remain_available(self):
        with patch.object(pipeline_api, "run_transform", return_value=[]):
            response = TestClient(pipeline_api.app).post(
                "/pdf", json={"source": "minio", "limit": 1,
                              "load_postgres": False, "load_qdrant": False})
        self.assertEqual(response.status_code, 200)
        schema = pipeline_api.app.openapi()
        self.assertIn("/processar-pdf", schema["paths"])
        self.assertTrue(schema["paths"]["/pdf"]["post"]["deprecated"])


if __name__ == "__main__":
    unittest.main()
