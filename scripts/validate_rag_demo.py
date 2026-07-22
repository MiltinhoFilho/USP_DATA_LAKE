"""Validação E2E curta e sequencial para a demonstração da RAG."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen


API_URL = "http://localhost:8003/pergunta"
REPORT_PATH = Path(__file__).resolve().parents[1] / "data" / "rag_demo_report.json"
QUESTIONS = [
    ("json", "Quais são os riscos da gamificação no cotidiano?"),
    ("json", "O que a notícia explica sobre a verdadeira face da cultura de inovação?"),
    ("json", "Qual é o tema da exposição Ser Transformado na Biblioteca Sinhá Junqueira?"),
    ("pdf", "Quais são os quatro módulos do curso de organização financeira da USP?"),
    ("pdf", "Quais são os três pilares da metodologia SOFt?"),
    ("externa", "Qual foi o resultado do campeonato intergaláctico de xadrez quântico da USP?"),
    ("externa", "Quais missões tripuladas da USP chegaram a Marte em 2035?"),
    ("externa", "O que o acervo diz sobre criação de unicórnios na Lua?"),
]


def ask(question: str) -> dict:
    request = Request(
        API_URL,
        data=json.dumps({"pergunta": question, "top_k": 5}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=240) as response:
        payload = json.loads(response.read())
    return {
        "status_http": response.status,
        "tempo_cliente_s": round(time.perf_counter() - started, 3),
        **payload,
    }


def main() -> None:
    results = []
    for index, (kind, question) in enumerate(QUESTIONS, start=1):
        print(f"[{index}/8] {kind}: {question}", flush=True)
        result = {"tipo": kind, **ask(question)}
        expected_evidence = kind != "externa"
        result["aprovado"] = (
            result["status_http"] == 200
            and result.get("evidence_sufficient") is expected_evidence
            and result.get("ollama_skipped") is (not expected_evidence)
            and (bool(result.get("fontes")) if expected_evidence else not result.get("fontes"))
        )
        results.append(result)
    report = {
        "executado_em_utc": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "aprovados": sum(item["aprovado"] for item in results),
        "resultados": results,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"total": report["total"], "aprovados": report["aprovados"], "arquivo": str(REPORT_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
