from __future__ import annotations

import unittest

from evaluation.metrics import (
    classification_metrics,
    latency_metrics,
    load_json,
    quality_metrics,
    retrieval_metrics,
    validate_benchmark,
    validate_ground_truth,
)
from evaluation.report import build_report


def case(identifier: str, answerable: bool = True) -> dict:
    return {
        "id": identifier, "categoria": "json" if answerable else "fora_do_corpus",
        "pergunta": "Pergunta", "answerable": answerable,
        "source_type_esperado": "json" if answerable else None,
        "document_id_esperado": f"doc-{identifier}" if answerable else None,
        "titulo_esperado": "Título" if answerable else None,
        "url_esperada": f"https://example.test/{identifier}" if answerable else None,
        "source_object_esperado": f"raw/{identifier}.json" if answerable else None,
        "trecho_referencia": "Trecho" if answerable else None,
        "resposta_referencia": "Resposta", "evidence_sufficient_esperado": answerable,
        "ollama_skipped_esperado": not answerable, "observacao_origem": "Teste",
        "review_status": "approved", "human_evaluation": None,
    }


def result(item: dict, accepted: bool, rank: int | None = 1) -> dict:
    sources = []
    if rank is not None:
        sources = [{"document_id": f"wrong-{index}"} for index in range(rank - 1)]
        sources.append({"document_id": item["document_id_esperado"]})
    return {
        "id": item["id"], "categoria": item["categoria"], "status_http": 200,
        "evidence_sufficient": accepted, "ollama_skipped": not accepted,
        "fontes": sources, "metrics": {"total_seconds": 2.0},
    }


class EvaluationTests(unittest.TestCase):
    def test_repository_benchmark_loads_and_schema_is_valid(self):
        questions = load_json("evaluation/questions.json")
        truth = load_json("evaluation/ground_truth.json")
        validate_benchmark(questions, truth)
        cases = validate_ground_truth(truth)
        self.assertEqual(len(cases), 20)
        self.assertTrue(all(item["review_status"] == "pending" for item in cases))

    def test_missing_ground_truth_is_rejected(self):
        questions = {"questions": [{"id": "one"}]}
        truth = {"cases": [case("two")]}
        with self.assertRaisesRegex(ValueError, "benchmark inconsistente"):
            validate_benchmark(questions, truth)

    def test_unapproved_case_is_rejected_for_final_metrics(self):
        pending = case("one")
        pending["review_status"] = "pending"
        with self.assertRaisesRegex(ValueError, "ainda não possui revisão"):
            validate_ground_truth({"cases": [pending]}, require_approved=True)

    def test_confusion_matrix_and_metrics(self):
        tp, tn, fp, fn = case("tp"), case("tn", False), case("fp", False), case("fn")
        results = [result(tp, True), result(tn, False, None), result(fp, True, None), result(fn, False, None)]
        metrics = classification_metrics([tp, tn, fp, fn], results)
        self.assertEqual({key: metrics[key] for key in ("TP", "TN", "FP", "FN")}, {"TP": 1, "TN": 1, "FP": 1, "FN": 1})
        for key in ("accuracy", "precision", "recall", "f1_score", "specificity", "balanced_accuracy"):
            self.assertEqual(metrics[key], 0.5)

    def test_zero_divisions_are_reported_as_none(self):
        negative = case("negative", False)
        metrics = classification_metrics([negative], [result(negative, False, None)])
        self.assertIsNone(metrics["precision"])
        self.assertIsNone(metrics["recall"])
        self.assertIsNone(metrics["f1_score"])
        self.assertEqual(metrics["specificity"], 1.0)

    def test_hit_rate_recall_and_mrr(self):
        cases = [case("one"), case("two"), case("three")]
        results = [result(cases[0], True, 1), result(cases[1], True, 2), result(cases[2], True, None)]
        metrics = retrieval_metrics(cases, results)
        self.assertAlmostEqual(metrics["hit_rate_at_1"], 1 / 3)
        self.assertAlmostEqual(metrics["hit_rate_at_3"], 2 / 3)
        self.assertEqual(metrics["recall_at_3"], metrics["hit_rate_at_3"])
        self.assertEqual(metrics["mrr"], 0.5)
        self.assertIsNone(metrics["ndcg_at_3"])

    def test_latency_aggregation(self):
        items = [
            {"categoria": "json", "ollama_skipped": False, "metrics": {"total_seconds": 1.0}},
            {"categoria": "pdf", "ollama_skipped": False, "metrics": {"total_seconds": 3.0}},
            {"categoria": "fora_do_corpus", "ollama_skipped": True, "metrics": {"total_seconds": 2.0}},
        ]
        metrics = latency_metrics(items)
        self.assertEqual(metrics["all"]["total_seconds"]["mean"], 2.0)
        self.assertEqual(metrics["all"]["total_seconds"]["median"], 2.0)
        self.assertEqual(metrics["json"]["total_seconds"]["count"], 1)
        self.assertEqual(metrics["ollama_ignorado"]["total_seconds"]["max"], 2.0)

    def test_human_quality_requires_explicit_zero_to_two_scores(self):
        evaluation = {
            "fidelidade": 2, "cobertura": 1,
            "ausencia_de_informacao_nao_sustentada": 2,
            "fonte_correta": 2, "clareza": 1,
        }
        metrics = quality_metrics([{"id": "one", "human_evaluation": evaluation}])
        self.assertEqual(metrics["total_avaliado_por_humano"], 1)
        self.assertEqual(metrics["media_por_criterio"]["fidelidade"], 2.0)
        invalid = dict(evaluation, clareza=3)
        with self.assertRaisesRegex(ValueError, "nota clareza inválida"):
            quality_metrics([{"id": "bad", "human_evaluation": invalid}])

    def test_preliminary_report_does_not_claim_metrics(self):
        pending = case("pending")
        pending["review_status"] = "pending"
        inventory = {"summary": {"postgres_rows": 663, "document_ids": 111, "urls": 110, "source_objects": 102}}
        report = build_report({"cases": [pending]}, [], inventory)
        self.assertIn("Relatório preliminar", report)
        self.assertIn("não são apresentados como resultados oficiais", report)
        self.assertIn("recorte do Jornal da USP", report)
        self.assertIn("### Matriz de confusão", report)
        self.assertIn("### Métricas de recuperação", report)
        self.assertIn("Não gerados: não existem resultados reais", report)


if __name__ == "__main__":
    unittest.main()
