"""Gera relatório preliminar ou final a partir de dados auditáveis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evaluation.metrics import (
    classification_metrics,
    latency_metrics,
    load_json,
    quality_metrics,
    retrieval_metrics,
    validate_ground_truth,
)


SCOPE_NOTICE = (
    "Os resultados apresentados são válidos apenas para o conjunto documental "
    "local utilizado no experimento. O corpus representa um recorte do Jornal "
    "da USP e não deve ser interpretado como uma avaliação de cobertura ou "
    "desempenho sobre todo o portal."
)


def load_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _format_metric(value: Any) -> str:
    if value is None:
        return "não calculável"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def build_report(ground_truth: dict[str, Any], results: list[dict[str, Any]], inventory: dict[str, Any]) -> str:
    cases = validate_ground_truth(ground_truth)
    approved = [case for case in cases if case["review_status"] == "approved"]
    summary = inventory["summary"]
    lines = [
        "# Relatório de avaliação da RAG",
        "",
        "## Escopo e objetivo",
        "",
        "Avaliar de forma reproduzível a decisão de evidência, a recuperação, a resposta e a latência no corpus local indexado.",
        "",
        f"> {SCOPE_NOTICE}",
        "",
        "## Inventário do corpus",
        "",
        f"- Chunks no PostgreSQL: {summary['postgres_rows']}",
        f"- Identidades documentais: {summary['document_ids']}",
        f"- URLs distintas: {summary['urls']}",
        f"- Objetos de origem: {summary['source_objects']}",
        "- Embeddings validados externamente ao benchmark: 663 vetores BGE-M3 no Qdrant.",
        "",
        "## Metodologia",
        "",
        f"O benchmark preliminar contém {len(cases)} casos: "
        f"{sum(case['categoria'] == 'json' for case in cases)} JSON, "
        f"{sum(case['categoria'] == 'pdf' for case in cases)} PDF e "
        f"{sum(case['categoria'] == 'fora_do_corpus' for case in cases)} negativos.",
        "Cada resposta positiva exige decisão aceita e recuperação da fonte esperada para ser classificada como TP.",
        "",
        "## Critérios de inclusão das perguntas",
        "",
        "Perguntas positivas usam apenas trechos diretamente indexados; perguntas negativas usam expressões distintivas confirmadas como ausentes nos 663 chunks. O único PDF recebe somente quatro perguntas não repetitivas.",
        "",
        "## Revisão humana do ground truth",
        "",
        f"Itens aprovados: {len(approved)} de {len(cases)}.",
        "",
        "| ID | Pergunta | Respondível | Documento esperado | Revisão |",
        "|---|---|---:|---|---|",
    ]
    for case in cases:
        lines.append(
            f"| {case['id']} | {case['pergunta']} | {'sim' if case['answerable'] else 'não'} | "
            f"{case.get('titulo_esperado') or 'recusa segura'} | {case['review_status']} |"
        )
    lines.extend(["", "## Resultados", ""])
    if len(approved) != len(cases):
        lines.extend([
            "**Relatório preliminar:** o ground truth ainda não foi integralmente aprovado.",
            "Accuracy, Precision, Recall, F1-score, métricas de recuperação e gráficos não são apresentados como resultados oficiais.",
            "",
            "### Matriz de confusão",
            "",
            "Não calculada: existem itens com revisão pendente.",
            "",
            "### Accuracy, Precision, Recall, F1-score, Specificity e Balanced Accuracy",
            "",
            "Não calculadas: existem itens com revisão pendente.",
            "",
            "### Métricas de recuperação",
            "",
            "Hit Rate@k, Recall@k, MRR e NDCG@3 não calculados nesta etapa preliminar.",
            "",
            "### Métricas de latência",
            "",
            "Não calculadas: a execução controlada ainda não foi autorizada.",
            "",
            "### Gráficos",
            "",
            "Não gerados: não existem resultados reais aprovados.",
        ])
    elif not results:
        lines.append("O ground truth está aprovado, mas ainda não existem resultados de execução.")
    else:
        classification = classification_metrics(cases, results)
        retrieval = retrieval_metrics(cases, results)
        lines.extend([
            "### Matriz de confusão e classificação",
            "",
            "| TP | TN | FP | FN | Total | Accuracy | Precision | Recall | F1 | Specificity | Balanced Accuracy | FPR | FNR |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            "| " + " | ".join(_format_metric(classification[key]) for key in (
                "TP", "TN", "FP", "FN", "total_avaliado", "accuracy", "precision",
                "recall", "f1_score", "specificity", "balanced_accuracy",
                "false_positive_rate", "false_negative_rate",
            )) + " |",
            "",
            "### Recuperação",
            "",
            "| Hit@1 | Hit@3 | Hit@5 | Recall@1 | Recall@3 | Recall@5 | MRR | NDCG@3 |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|",
            "| " + " | ".join(_format_metric(retrieval[key]) for key in (
                "hit_rate_at_1", "hit_rate_at_3", "hit_rate_at_5", "recall_at_1",
                "recall_at_3", "recall_at_5", "mrr", "ndcg_at_3",
            )) + " |",
            "",
            retrieval["ndcg_note"],
            "",
            "### Qualidade das respostas",
            "",
            "```json",
            json.dumps(quality_metrics(results), ensure_ascii=False, indent=2),
            "```",
            "",
            "### Latência",
            "",
            "As estatísticas são específicas do hardware local. O JSON completo de latências deve acompanhar o relatório final.",
            "",
            "```json",
            json.dumps(latency_metrics(results), ensure_ascii=False, indent=2),
            "```",
        ])
    lines.extend([
        "",
        "## Protocolo de qualidade das respostas",
        "",
        "Fidelidade, cobertura, ausência de informação não sustentada, fonte correta e clareza devem ser avaliadas manualmente em escala 0–2. O modelo avaliado não é usado como único juiz.",
        "",
        "## Limitações e ameaças à validade",
        "",
        "- O corpus é um recorte controlado, não uma amostra representativa de todo o portal.",
        "- Existe apenas um PDF; métricas por tipo possuem tamanhos muito diferentes.",
        "- O ground truth preliminar possui uma fonte relevante binária por caso.",
        "- Latências dependem do hardware, carga, cold start e estado do Ollama.",
        "- Perguntas negativas sintéticas medem recusa segura, mas não cobrem toda ambiguidade possível.",
        "",
        "## Conclusão",
        "",
        "Nenhuma conclusão quantitativa oficial deve ser publicada antes da revisão humana e da execução controlada.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, default=Path("evaluation/ground_truth.json"))
    parser.add_argument("--inventory", type=Path, default=Path("evaluation/corpus_inventory.json"))
    parser.add_argument("--results", type=Path, default=Path("evaluation/results/results.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/reports/report.md"))
    args = parser.parse_args()
    report = build_report(load_json(args.ground_truth), load_results(args.results), load_json(args.inventory))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Relatório salvo em {args.output}")


if __name__ == "__main__":
    main()
