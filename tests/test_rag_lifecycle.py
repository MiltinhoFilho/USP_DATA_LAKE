"""Testes unitários da vida útil e do cache da RAG API."""

from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import src.api.rag_api as rag_api
from src.retriever import Retriever, evaluate_evidence


EXPECTED_RESPONSE_FIELDS = {
    "status",
    "service",
    "pergunta",
    "resposta",
    "fontes",
    "total_fontes",
    "evidence_sufficient",
    "ollama_skipped",
    "metrics",
}


class FakeRetriever:
    instances = 0
    initialize_calls = 0
    close_calls = 0

    def __init__(self) -> None:
        type(self).instances += 1

    def initialize(self) -> None:
        type(self).initialize_calls += 1

    def close(self) -> None:
        type(self).close_calls += 1

    def search_with_metrics(self, question: str, top_k: int):
        return (
            [
                {
                    "id": 7,
                    "titulo": question,
                    "url": "https://jornal.usp.br/noticia",
                    "texto": question,
                    "score": 0.91,
                    "score_vector": 0.91,
                    "score_lexical": 4.0,
                    "score_hybrid": 0.04,
                    "rank_vector": 1,
                    "rank_lexical": 1,
                    "documento_id": "documento-7",
                    "chunk_id": 2,
                    "source_object": "raw/noticia.json",
                }
            ],
            {
                "embedding_seconds": 0.1,
                "qdrant_seconds": 0.2,
                "postgres_seconds": 0.3,
                "retriever_seconds": 0.6,
            },
        )


class RagLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeRetriever.instances = 0
        FakeRetriever.initialize_calls = 0
        FakeRetriever.close_calls = 0

    def test_import_and_openapi_do_not_initialize_retriever(self):
        with patch.object(rag_api, "Retriever", FakeRetriever):
            schema = rag_api.app.openapi()

        self.assertIn("/pergunta", schema["paths"])
        self.assertEqual(FakeRetriever.instances, 0)
        self.assertEqual(FakeRetriever.initialize_calls, 0)

    def test_retriever_is_created_once_and_reused(self):
        with (
            patch.object(rag_api, "Retriever", FakeRetriever),
            patch.object(
                rag_api,
                "prepare_context",
                side_effect=lambda chunks: ("contexto", chunks),
            ),
            patch.object(rag_api, "generate_answer", return_value="Resposta"),
            TestClient(rag_api.app) as client,
        ):
            first = client.post(
                "/pergunta", json={"pergunta": "Pergunta um", "top_k": 5}
            )
            second = client.post(
                "/pergunta", json={"pergunta": "Pergunta dois", "top_k": 5}
            )

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(FakeRetriever.instances, 1)
            self.assertEqual(FakeRetriever.initialize_calls, 1)
            self.assertEqual(set(first.json()), EXPECTED_RESPONSE_FIELDS)
            self.assertEqual(first.json()["fontes"][0]["score"], 0.91)
            self.assertEqual(
                set(first.json()["fontes"][0]),
                {
                    "id", "titulo", "url", "texto", "score", "document_id",
                    "chunk_id", "postgres_id", "source_type", "source_object",
                },
            )
            self.assertEqual(first.json()["fontes"][0]["document_id"], "documento-7")
            self.assertEqual(first.json()["fontes"][0]["postgres_id"], 7)
            self.assertEqual(first.json()["fontes"][0]["source_type"], "json")

        self.assertEqual(FakeRetriever.close_calls, 1)

    def test_source_metadata_is_optional_and_source_type_is_deterministic(self):
        old_contract = rag_api._fonte_from_chunk(
            {
                "id": 1,
                "titulo": "Título",
                "url": "https://example.test/noticia",
                "texto": "Texto",
                "score": 0.5,
            }
        ).model_dump()
        self.assertEqual(old_contract["id"], 1)
        self.assertEqual(old_contract["titulo"], "Título")
        self.assertEqual(old_contract["url"], "https://example.test/noticia")
        self.assertEqual(old_contract["texto"], "Texto")
        self.assertEqual(old_contract["score"], 0.5)
        self.assertIsNone(old_contract["document_id"])
        self.assertIsNone(old_contract["chunk_id"])
        self.assertEqual(old_contract["postgres_id"], 1)
        self.assertEqual(old_contract["source_type"], "unknown")
        self.assertIsNone(old_contract["source_object"])

        self.assertEqual(
            rag_api._derive_source_type({"source_object": "raw/item.JSON"}),
            "json",
        )
        self.assertEqual(
            rag_api._derive_source_type({"source_object": "raw/pdf/item.pdf"}),
            "pdf",
        )
        self.assertEqual(
            rag_api._derive_source_type({"url": "https://example.test/item.pdf?v=1"}),
            "pdf",
        )

    def test_openapi_exposes_old_and_optional_source_fields(self):
        properties = rag_api.app.openapi()["components"]["schemas"]["FonteResponse"][
            "properties"
        ]
        self.assertEqual(
            set(properties),
            {
                "id", "titulo", "url", "texto", "score", "document_id",
                "chunk_id", "postgres_id", "source_type", "source_object",
            },
        )

    def test_diagnostic_logging_does_not_change_evidence_or_log_text(self):
        source = {
            "id": 10,
            "documento_id": "doc-10",
            "chunk_id": 3,
            "titulo": "Cultura de inovação",
            "url": "https://example.test/inovacao",
            "texto": "Cultura de inovação gera novas ideias.",
            "score": 0.05,
            "score_vector": 0.8,
            "score_lexical": 9.0,
            "score_hybrid": 0.05,
            "rank_vector": 1,
            "rank_lexical": 1,
            "source_object": "raw/inovacao.json",
        }
        evidence = evaluate_evidence("Cultura de inovação gera novas ideias", [source])
        before = evidence.classified_sources.copy()
        with self.assertLogs("uvicorn.error", level="DEBUG") as captured:
            rag_api._log_evidence_diagnostics(evidence)

        self.assertEqual(evidence.classified_sources, before)
        output = "\n".join(captured.output)
        self.assertIn("rag_evidence_decision", output)
        self.assertIn("rag_evidence_candidate", output)
        self.assertIn('"source_type": "json"', output)
        self.assertNotIn(source["texto"], output)

    def test_startup_failure_returns_controlled_503(self):
        class BrokenRetriever:
            def initialize(self):
                raise RuntimeError("internal-secret")

        with (
            patch.object(rag_api, "Retriever", BrokenRetriever),
            TestClient(rag_api.app) as client,
        ):
            response = client.post(
                "/pergunta",
                json={"pergunta": "Pergunta válida", "top_k": 5},
            )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("internal-secret", response.text)

    def test_no_evidence_is_limited_to_currently_indexed_corpus(self):
        class EmptyRetriever(FakeRetriever):
            def search_with_metrics(self, question: str, top_k: int):
                return [], {"retriever_seconds": 0.01}

        with (
            patch.object(rag_api, "Retriever", EmptyRetriever),
            patch.object(rag_api, "generate_answer") as ollama,
            TestClient(rag_api.app) as client,
        ):
            response = client.post(
                "/pergunta", json={"pergunta": "Tema ausente", "top_k": 5}
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("conjunto de notícias atualmente indexado", response.json()["resposta"])
        self.assertEqual(response.json()["fontes"], [])
        ollama.assert_not_called()

    def test_weak_non_empty_evidence_skips_ollama(self):
        class WeakRetriever(FakeRetriever):
            def search_with_metrics(self, question: str, top_k: int):
                return ([{
                    "id": 8,
                    "titulo": "Assunto sem relação",
                    "url": "https://jornal.usp.br/assunto",
                    "texto": "Conteúdo distante da pergunta.",
                    "score": 0.03,
                    "score_hybrid": 0.03,
                    "score_vector": 0.5,
                    "rank_vector": 9,
                    "score_lexical": 0.0,
                    "rank_lexical": None,
                }], {"retriever_seconds": 0.01})

        with (
            patch.object(rag_api, "Retriever", WeakRetriever),
            patch.object(rag_api, "prepare_context") as context,
            patch.object(rag_api, "generate_answer") as ollama,
            TestClient(rag_api.app) as client,
        ):
            response = client.post(
                "/pergunta",
                json={"pergunta": "Transferência de tecnologia", "top_k": 5},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fontes"], [])
        self.assertEqual(response.json()["total_fontes"], 0)
        self.assertFalse(response.json()["evidence_sufficient"])
        self.assertTrue(response.json()["ollama_skipped"])
        context.assert_not_called()
        ollama.assert_not_called()

    def test_single_strong_source_calls_ollama_and_excludes_weak_sources(self):
        class StrongAndWeakRetriever(FakeRetriever):
            def search_with_metrics(self, question: str, top_k: int):
                strong = {
                    "id": 400,
                    "titulo": "Bolsa Familia reduziu hospitalizacoes e aumentou empregabilidade",
                    "url": "https://jornal.usp.br/bolsa-familia",
                    "texto": "Bolsa Familia reduziu hospitalizacoes e aumentou empregabilidade.",
                    "score": 0.05,
                    "score_vector": 0.78,
                    "score_lexical": 60.0,
                    "score_hybrid": 0.05,
                    "rank_vector": 1,
                    "rank_lexical": 1,
                }
                weak = {
                    "id": 999,
                    "titulo": "Assunto distante",
                    "url": "https://jornal.usp.br/distante",
                    "texto": "Conteudo sem relacao.",
                    "score": 0.01,
                    "score_vector": 0.3,
                    "score_lexical": 0.0,
                    "score_hybrid": 0.01,
                    "rank_vector": 9,
                    "rank_lexical": None,
                }
                return [strong, weak], {"retriever_seconds": 0.01}

        question = "Bolsa Familia reduziu hospitalizacoes e aumentou empregabilidade"
        with (
            patch.object(rag_api, "Retriever", StrongAndWeakRetriever),
            patch.object(
                rag_api,
                "prepare_context",
                side_effect=lambda chunks: ("contexto", chunks),
            ) as context,
            patch.object(rag_api, "generate_answer", return_value="Resposta") as ollama,
            TestClient(rag_api.app) as client,
        ):
            response = client.post(
                "/pergunta", json={"pergunta": question, "top_k": 5}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_fontes"], 1)
        self.assertEqual(response.json()["fontes"][0]["id"], 400)
        self.assertTrue(response.json()["evidence_sufficient"])
        self.assertFalse(response.json()["ollama_skipped"])
        selected = context.call_args.args[0]
        self.assertEqual([item["id"] for item in selected], [400])
        ollama.assert_called_once()

    def test_embedding_lock_serializes_encoder_use(self):
        class ConcurrentEmbedder:
            active = 0
            maximum = 0

            def encode_texts(self, texts, show_progress_bar=False):
                type(self).active += 1
                type(self).maximum = max(type(self).maximum, type(self).active)
                time.sleep(0.03)
                type(self).active -= 1
                return [[0.1, 0.2]]

        retriever = Retriever(
            embedder=ConcurrentEmbedder(),
            qdrant_client=SimpleNamespace(),
            collection_name="test",
            postgres_connection_factory=MagicMock(),
        )
        threads = [
            threading.Thread(target=retriever._embed_question, args=("pergunta",))
            for _ in range(4)
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(ConcurrentEmbedder.maximum, 1)


if __name__ == "__main__":
    unittest.main()
