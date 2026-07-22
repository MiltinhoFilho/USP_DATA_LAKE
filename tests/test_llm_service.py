import unittest
from unittest.mock import Mock, patch

import httpx

from src import llm_service


def config(**overrides):
    values = {
        "base_url": "http://ollama.local:11434",
        "model": "gemma3:4b",
        "timeout": 30,
        "max_context_chars": 300,
        "max_sources": 3,
        "temperature": 0.1,
        "num_predict": 96,
        "num_ctx": 2048,
        "keep_alive": "10m",
    }
    values.update(overrides)
    return llm_service.OllamaConfig(**values)


class ContextTests(unittest.TestCase):
    def test_deduplicates_text_groups_document_and_preserves_best_source(self):
        chunks = [
            {"id": 1, "documento_id": "doc-a", "titulo": "Principal", "texto": "evidência principal"},
            {"id": 2, "documento_id": "doc-a", "titulo": "Principal", "texto": "evidência complementar"},
            {"id": 3, "documento_id": "doc-b", "titulo": "Duplicada", "texto": "evidência principal"},
        ]
        context, selected = llm_service.prepare_context(chunks, config())
        self.assertEqual([item["id"] for item in selected], [1, 2])
        self.assertEqual(context.count("Principal"), 1)
        self.assertEqual(context.count("evidência principal"), 1)

    def test_respects_character_budget_without_discarding_first_source(self):
        chunks = [
            {"id": 1, "documento_id": "a", "titulo": "Melhor", "texto": "primeira evidência " * 30},
            {"id": 2, "documento_id": "b", "titulo": "Segunda", "texto": "segunda evidência " * 30},
        ]
        context, selected = llm_service.prepare_context(
            chunks, config(max_context_chars=120)
        )
        self.assertLessEqual(len(context), 120)
        self.assertEqual(selected[0]["id"], 1)
        self.assertIn("Melhor", context)


class OllamaClientTests(unittest.TestCase):
    def tearDown(self):
        llm_service._client = None

    def test_payload_is_short_deterministic_and_uses_chat_endpoint(self):
        response = Mock(status_code=200)
        response.json.return_value = {"message": {"content": "Resposta fiel"}}
        client = Mock()
        client.post.return_value = response
        with patch.object(llm_service, "get_http_client", return_value=client):
            answer = llm_service.generate_answer("Pergunta?", "Contexto", config())
        self.assertEqual(answer, "Resposta fiel")
        url, = client.post.call_args.args
        payload = client.post.call_args.kwargs["json"]
        self.assertEqual(url, "http://ollama.local:11434/api/chat")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["keep_alive"], "10m")
        self.assertEqual(payload["options"], {"temperature": 0.1, "num_predict": 96, "num_ctx": 2048})
        self.assertNotIn("http", payload["messages"][1]["content"])

    def test_timeout_is_controlled(self):
        client = Mock()
        client.post.side_effect = httpx.ReadTimeout("timeout")
        with patch.object(llm_service, "get_http_client", return_value=client):
            with self.assertRaises(llm_service.OllamaUnavailableError):
                llm_service.generate_answer("Pergunta?", "Contexto", config())


if __name__ == "__main__":
    unittest.main()
