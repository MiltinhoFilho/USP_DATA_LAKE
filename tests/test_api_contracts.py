import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.generator_api import app as generator_app
from src.api.pipeline_api import app as pipeline_app


class GeneratorContractTests(unittest.TestCase):
    def test_health_contract(self):
        response = TestClient(generator_app).get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "generator-api"})

    def test_site_contract_without_real_scraping(self):
        with patch("src.api.generator_api.run", return_value=[{"url": "https://example"}]):
            response = TestClient(generator_app).get(
                "/site?limit=1&max_pages=1&upload_minio=false"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["service"], "generator-api")
        self.assertEqual(response.json()["data"]["articles"], 1)


class PipelineContractTests(unittest.TestCase):
    def test_health_contract(self):
        response = TestClient(pipeline_app).get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "pipeline-api"})

    def test_process_site_contract_without_reprocessing_gold(self):
        expected = {
            "message": "Nenhum documento novo para processar.",
        }
        with patch("src.api.pipeline_api._run_pipeline", return_value=expected):
            response = TestClient(pipeline_app).post(
                "/processar-site",
                json={"source": "minio", "limit": 1,
                      "load_postgres": True, "load_qdrant": True},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)

    def test_zero_limit_is_rejected_by_current_contract(self):
        response = TestClient(pipeline_app).post(
            "/processar-site",
            json={"source": "minio", "limit": 0,
                  "load_postgres": False, "load_qdrant": False},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
