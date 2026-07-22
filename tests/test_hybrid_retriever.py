import unittest
from unittest.mock import Mock

from src.retriever import BM25Index, RetrievalConfig, Retriever, reciprocal_rank_fusion, tokenize, tokenize_query


def doc(identifier, title, text, url=None):
    return {"id": identifier, "documento_id": f"doc-{identifier}", "chunk_id": 1,
            "titulo": title, "texto": text, "url": url or f"https://example/{identifier}",
            "categoria": "", "autor": "", "data_publicacao": "2026-01-01"}


class BM25Tests(unittest.TestCase):
    def setUp(self):
        self.config = RetrievalConfig()
        self.docs = [doc(1, "Inteligência Artificial na USP", "pesquisa aplicada"),
                     doc(2, "Pesquisa aplicada", "inteligencia artificial na usp"),
                     doc(3, "Saúde", "pesquisa médica")]

    def test_tokenization_normalizes_accents_and_preserves_ia(self):
        self.assertEqual(tokenize("Inteligência, IA!"), ["inteligencia", "ia"])
        self.assertEqual(tokenize_query("Quais pesquisas da USP tratam de IA?"), ["ia"])

    def test_empty_query_and_no_match_return_empty(self):
        index = BM25Index(self.docs, self.config)
        self.assertEqual(index.search("", 5), [])
        self.assertEqual(index.search("termo-inexistente", 5), [])

    def test_bm25_is_positive_deterministic_and_title_has_more_weight(self):
        index = BM25Index(self.docs, self.config)
        first = index.search("inteligência artificial", 5)
        self.assertGreater(first[0]["score_lexical"], 0)
        self.assertEqual([x["id"] for x in first], [x["id"] for x in index.search("inteligência artificial", 5)])
        self.assertEqual(first[0]["id"], 1)


class FusionTests(unittest.TestCase):
    def test_rrf_vector_only_lexical_only_both_and_weights(self):
        config = RetrievalConfig(rrf_k=60, vector_weight=1, lexical_weight=2)
        vector = [dict(doc(1, "A", ""), score_vector=.9), dict(doc(2, "B", ""), score_vector=.8)]
        lexical = [dict(doc(2, "B", ""), score_lexical=4), dict(doc(3, "C", ""), score_lexical=3)]
        result = reciprocal_rank_fusion(vector, lexical, config)
        by_id = {x["id"]: x for x in result}
        self.assertEqual(result[0]["id"], 2)
        self.assertIsNone(by_id[1].get("rank_lexical"))
        self.assertIsNone(by_id[3].get("rank_vector"))
        self.assertAlmostEqual(by_id[2]["score_hybrid"], 1 / 62 + 2 / 61)
        self.assertEqual(result, reciprocal_rank_fusion(vector, lexical, config))


class RetrieverHybridTests(unittest.TestCase):
    def test_row_conversion_preserves_source_object(self):
        row = (1, "doc", 2, "Título", "Texto", "https://jornal.usp.br/x/", "cat", "autor", "2026-01-01", "raw/pdf/x.pdf")
        self.assertEqual(Retriever._row_to_chunk(row)["source_object"], "raw/pdf/x.pdf")

    def setUp(self):
        self.docs = [doc(1, "IA na USP", "inteligência artificial", "https://same"),
                     doc(2, "IA na USP", "algoritmos", "https://same"),
                     doc(3, "Saúde", "medicina", "https://other")]

    def make_retriever(self, config=None):
        retriever = Retriever(embedder=Mock(), qdrant_client=Mock(), collection_name="test",
                              postgres_connection_factory=Mock(), config=config or RetrievalConfig())
        retriever._fetch_all_chunks = Mock(return_value=self.docs)
        return retriever

    def test_index_built_once_and_reused(self):
        retriever = self.make_retriever(); retriever._initialize_lexical_index()
        first = retriever._lexical_index; retriever._initialize_lexical_index()
        self.assertIs(first, retriever._lexical_index)
        retriever._fetch_all_chunks.assert_called_once()

    def test_deduplication_by_url_and_limit(self):
        retriever = self.make_retriever(RetrievalConfig(max_chunks_per_source=1))
        self.assertEqual([x["id"] for x in retriever._deduplicate(self.docs, 5)], [1, 3])

    def test_lexical_mode_avoids_embedding_qdrant_and_ollama(self):
        retriever = self.make_retriever()
        results, metrics = retriever.search_with_metrics("inteligência artificial", 5, mode="lexical")
        self.assertEqual(results[0]["id"], 1)
        self.assertEqual(metrics["retrieval_mode"], "lexical")
        retriever._embedder.encode_texts.assert_not_called()
        retriever._qdrant.query_points.assert_not_called()

    def test_hybrid_fallback_and_hybrid_disabled(self):
        for config, expected in [(RetrievalConfig(lexical_enabled=False), "hybrid_fallback_vector"),
                                 (RetrievalConfig(hybrid_enabled=False, lexical_enabled=False), "vector")]:
            retriever = self.make_retriever(config)
            retriever._embed_question = Mock(return_value=[.1])
            hit = Mock(id=3, score=.8, payload={"postgres_id": 3})
            retriever._search_qdrant = Mock(return_value=[hit])
            retriever._fetch_chunks = Mock(return_value={3: self.docs[2]})
            results, metrics = retriever.search_with_metrics("saúde", 5)
            self.assertEqual(results[0]["score"], .8)
            self.assertEqual(metrics["retrieval_mode"], expected)


if __name__ == "__main__":
    unittest.main()
