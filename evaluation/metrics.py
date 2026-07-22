"""Validação e métricas auditáveis do benchmark da RAG."""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any, Iterable


REQUIRED_CASE_FIELDS = {
    "id", "categoria", "pergunta", "answerable", "source_type_esperado",
    "document_id_esperado", "titulo_esperado", "url_esperada",
    "source_object_esperado", "trecho_referencia", "resposta_referencia",
    "evidence_sufficient_esperado", "ollama_skipped_esperado",
    "observacao_origem", "review_status",
}
LATENCY_FIELDS = (
    "embedding_seconds", "qdrant_seconds", "postgres_seconds",
    "retriever_seconds", "evidence_check_seconds", "ollama_seconds",
    "total_seconds",
)
QUALITY_FIELDS = (
    "fidelidade", "cobertura", "ausencia_de_informacao_nao_sustentada",
    "fonte_correta", "clareza",
)


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path} deve conter um objeto JSON")
    return value


def validate_ground_truth(document: dict[str, Any], *, require_approved: bool = False) -> list[dict[str, Any]]:
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("ground_truth deve conter uma lista não vazia em cases")
    identifiers: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"case {index} não é um objeto")
        missing = REQUIRED_CASE_FIELDS - set(case)
        if missing:
            raise ValueError(f"case {case.get('id', index)!r} sem campos: {sorted(missing)}")
        identifier = str(case["id"])
        if identifier in identifiers:
            raise ValueError(f"id duplicado: {identifier}")
        identifiers.add(identifier)
        if case["review_status"] not in {"pending", "approved", "rejected"}:
            raise ValueError(f"review_status inválido em {identifier}")
        if require_approved and case["review_status"] != "approved":
            raise ValueError(f"case {identifier} ainda não possui revisão aprovada")
        if case["answerable"]:
            required_truth = (
                "source_type_esperado", "document_id_esperado", "titulo_esperado",
                "url_esperada", "source_object_esperado", "trecho_referencia",
                "resposta_referencia",
            )
            if any(not case.get(field) for field in required_truth):
                raise ValueError(f"case respondível {identifier} sem ground truth completo")
    return cases


def validate_benchmark(questions: dict[str, Any], ground_truth: dict[str, Any]) -> None:
    cases = validate_ground_truth(ground_truth)
    question_items = questions.get("questions")
    if not isinstance(question_items, list) or not question_items:
        raise ValueError("questions deve conter uma lista não vazia")
    question_ids = {str(item.get("id")) for item in question_items if isinstance(item, dict)}
    truth_ids = {str(case["id"]) for case in cases}
    if question_ids != truth_ids:
        missing_truth = sorted(question_ids - truth_ids)
        missing_question = sorted(truth_ids - question_ids)
        raise ValueError(
            f"benchmark inconsistente; sem ground truth={missing_truth}, "
            f"sem pergunta={missing_question}"
        )


def source_rank(case: dict[str, Any], result: dict[str, Any]) -> int | None:
    expected = {
        "document_id": case.get("document_id_esperado"),
        "url": case.get("url_esperada"),
        "source_object": case.get("source_object_esperado"),
    }
    for rank, source in enumerate(result.get("fontes") or [], start=1):
        if any(value and source.get(key) == value for key, value in expected.items()):
            return rank
    return None


def classify(case: dict[str, Any], result: dict[str, Any]) -> str:
    if case.get("review_status") != "approved":
        raise ValueError(f"case {case.get('id')} ainda não está aprovado")
    if int(result.get("status_http", 0)) != 200:
        raise ValueError(f"case {case.get('id')} sem resposta HTTP 200")
    accepted = result.get("evidence_sufficient") is True
    if case["answerable"]:
        return "TP" if accepted and source_rank(case, result) is not None else "FN"
    return "FP" if accepted else "TN"


def _safe_divide(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def classification_metrics(cases: Iterable[dict[str, Any]], results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    result_map = {str(item["id"]): item for item in results}
    counts = {label: 0 for label in ("TP", "TN", "FP", "FN")}
    for case in cases:
        if case.get("review_status") != "approved":
            continue
        result = result_map.get(str(case["id"]))
        if result is None:
            raise ValueError(f"resultado ausente para {case['id']}")
        counts[classify(case, result)] += 1
    total = sum(counts.values())
    precision = _safe_divide(counts["TP"], counts["TP"] + counts["FP"])
    recall = _safe_divide(counts["TP"], counts["TP"] + counts["FN"])
    specificity = _safe_divide(counts["TN"], counts["TN"] + counts["FP"])
    f1 = None if precision is None or recall is None or precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {
        **counts,
        "total_avaliado": total,
        "accuracy": _safe_divide(counts["TP"] + counts["TN"], total),
        "precision": precision,
        "recall": recall,
        "f1_score": f1,
        "specificity": specificity,
        "balanced_accuracy": None if recall is None or specificity is None else (recall + specificity) / 2,
        "false_positive_rate": _safe_divide(counts["FP"], counts["FP"] + counts["TN"]),
        "false_negative_rate": _safe_divide(counts["FN"], counts["FN"] + counts["TP"]),
    }


def retrieval_metrics(cases: Iterable[dict[str, Any]], results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    result_map = {str(item["id"]): item for item in results}
    ranks = []
    for case in cases:
        if case.get("review_status") == "approved" and case["answerable"]:
            result = result_map.get(str(case["id"]))
            if result is None:
                raise ValueError(f"resultado ausente para {case['id']}")
            ranks.append(source_rank(case, result))
    total = len(ranks)
    output: dict[str, Any] = {"total_respondiveis": total}
    for k in (1, 3, 5):
        value = _safe_divide(sum(rank is not None and rank <= k for rank in ranks), total)
        output[f"hit_rate_at_{k}"] = value
        output[f"recall_at_{k}"] = value
    output["mrr"] = _safe_divide(sum(1 / rank for rank in ranks if rank), total)
    output["ndcg_at_3"] = None
    output["ndcg_note"] = "Não calculado: o benchmark preliminar possui uma fonte relevante binária por caso."
    return output


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize_values(values: Iterable[float]) -> dict[str, float | int | None]:
    numbers = [float(value) for value in values]
    if not numbers:
        return {key: None for key in ("mean", "median", "min", "max", "stdev", "p50", "p90", "p95")} | {"count": 0}
    return {
        "count": len(numbers),
        "mean": statistics.fmean(numbers),
        "median": statistics.median(numbers),
        "min": min(numbers),
        "max": max(numbers),
        "stdev": statistics.pstdev(numbers),
        "p50": percentile(numbers, 0.50),
        "p90": percentile(numbers, 0.90),
        "p95": percentile(numbers, 0.95),
    }


def latency_metrics(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(results)
    groups: dict[str, list[dict[str, Any]]] = {"all": items}
    for category in ("json", "pdf", "fora_do_corpus"):
        groups[category] = [item for item in items if item.get("categoria") == category]
    groups["ollama_executado"] = [item for item in items if item.get("ollama_skipped") is False]
    groups["ollama_ignorado"] = [item for item in items if item.get("ollama_skipped") is True]
    return {
        group: {
            field: summarize_values(
                item.get("metrics", {}).get(field)
                for item in group_items
                if item.get("metrics", {}).get(field) is not None
            )
            for field in LATENCY_FIELDS
        }
        for group, group_items in groups.items()
    }


def quality_metrics(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    evaluations = []
    for result in results:
        evaluation = result.get("human_evaluation")
        if evaluation is None:
            continue
        if not isinstance(evaluation, dict):
            raise ValueError(f"avaliação humana inválida em {result.get('id')}")
        scores = {}
        for field in QUALITY_FIELDS:
            value = evaluation.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value not in {0, 1, 2}:
                raise ValueError(f"nota {field} inválida em {result.get('id')}")
            scores[field] = value
        evaluations.append(scores)
    return {
        "total_avaliado_por_humano": len(evaluations),
        "media_por_criterio": {
            field: _safe_divide(sum(item[field] for item in evaluations), len(evaluations))
            for field in QUALITY_FIELDS
        },
    }
