"""Executa perguntas reais, sem mocks, contra a RAG do recorte existente."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "data" / "rag_corpus_e2e_report.json"
API_URL = "http://localhost:8003/pergunta"

PDF_TITLE = "Como organizar as finanças e investir melhor? Serviço da USP abre inscrições para curso"
PDF_URL = "https://jornal.usp.br/universidade/como-organizar-as-financas-e-investir-melhor-servico-da-usp-abre-inscricoes-para-curso/"

QUESTIONS = [
    {"grupo": "json", "pergunta": "O que a notícia explica sobre a verdadeira face da cultura de inovação?", "titulo_esperado": "A verdadeira face da cultura de inovação", "origem_esperada": "json"},
    {"grupo": "json", "pergunta": "Qual foi o primeiro passo na internacionalização da Com-Arte?", "titulo_esperado": "O primeiro passo na internacionalização da Com-Arte", "origem_esperada": "json"},
    {"grupo": "json", "pergunta": "Como a alfabetização na idade certa mobiliza formações na Bahia?", "titulo_esperado": "Alfabetização na idade certa mobiliza formações na Bahia", "origem_esperada": "json"},
    {"grupo": "json", "pergunta": "Quais são os riscos da gamificação no cotidiano segundo a notícia?", "titulo_esperado": "Quando o jogo sai da tela: os riscos da gamificação no cotidiano", "origem_esperada": "json"},
    {"grupo": "json", "pergunta": "O que é o PET-Saúde Clima citado pela USP e Secretaria Municipal de Saúde?", "titulo_esperado": "USP e Secretaria Municipal de Saúde selecionam estudantes para o PET-Saúde Clima", "origem_esperada": "json"},
    {"grupo": "pdf", "pergunta": "Qual serviço da USP oferece a Jornada SOFt 2026?", "titulo_esperado": PDF_TITLE, "url_esperada": PDF_URL, "origem_esperada": "pdf"},
    {"grupo": "pdf", "pergunta": "Quando ocorre a Jornada SOFt 2026 e qual é o formato do curso?", "titulo_esperado": PDF_TITLE, "url_esperada": PDF_URL, "origem_esperada": "pdf"},
    {"grupo": "pdf", "pergunta": "Quais são os quatro módulos do curso de organização financeira da USP?", "titulo_esperado": PDF_TITLE, "url_esperada": PDF_URL, "origem_esperada": "pdf"},
    {"grupo": "pdf", "pergunta": "Quais são os três pilares da metodologia SOFt?", "titulo_esperado": PDF_TITLE, "url_esperada": PDF_URL, "origem_esperada": "pdf"},
    {"grupo": "pdf", "pergunta": "Como entrar em contato com o Serviço de Orientação Financeira da FEA?", "titulo_esperado": PDF_TITLE, "url_esperada": PDF_URL, "origem_esperada": "pdf"},
    {"grupo": "multidocumento", "pergunta": "Quais temas de educação aparecem nas notícias atualmente indexadas?", "origem_esperada": "json"},
    {"grupo": "multidocumento", "pergunta": "Que iniciativas de formação e orientação são mencionadas no recorte indexado?", "origem_esperada": "json/pdf"},
    {"grupo": "multidocumento", "pergunta": "Como as notícias relacionam universidade, comunidade e produção de conhecimento?", "origem_esperada": "json"},
    {"grupo": "multidocumento", "pergunta": "Quais ações de extensão e serviços à população aparecem no acervo indexado?", "origem_esperada": "json/pdf"},
    {"grupo": "multidocumento", "pergunta": "Quais iniciativas do recorte tratam de educação, saúde ou bem-estar?", "origem_esperada": "json/pdf"},
    {"grupo": "fora_do_recorte", "pergunta": "Quais missões tripuladas da USP chegaram ao planeta Marte em 2035?", "recusa_esperada": True},
    {"grupo": "fora_do_recorte", "pergunta": "Qual foi o resultado do campeonato intergaláctico de xadrez quântico da USP?", "recusa_esperada": True},
]


def call_api(question: str) -> dict:
    body = json.dumps({"pergunta": question, "top_k": 5}).encode("utf-8")
    request = Request(API_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=360) as response:
            payload = json.loads(response.read())
            status = response.status
    except HTTPError as error:
        status = error.code
        payload = json.loads(error.read())
    return {"status_http": status, "duracao_total_cliente_s": round(time.perf_counter() - started, 4), "payload": payload}


def main() -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    results = []
    for index, spec in enumerate(QUESTIONS, 1):
        print(f"[{index:02d}/{len(QUESTIONS)}] {spec['grupo']}: {spec['pergunta']}", flush=True)
        result = {**spec, **call_api(spec["pergunta"])}
        payload = result["payload"]
        sources = payload.get("fontes", []) if isinstance(payload, dict) else []
        result["fontes"] = sources
        result["total_fontes"] = payload.get("total_fontes") if isinstance(payload, dict) else None
        result["resposta"] = payload.get("resposta") if isinstance(payload, dict) else None
        result["evidence_sufficient"] = bool(sources)
        title_ok = not spec.get("titulo_esperado") or any(source.get("titulo") == spec["titulo_esperado"] for source in sources)
        url_ok = not spec.get("url_esperada") or any(source.get("url") == spec["url_esperada"] for source in sources)
        refusal_ok = not spec.get("recusa_esperada") or (not sources and "não encontrei informações suficientes" in (result["resposta"] or "").lower())
        result["correto"] = result["status_http"] == 200 and title_ok and url_ok and refusal_ok
        results.append(result)
    report = {"inicio_utc": started_at, "fim_utc": datetime.now(timezone.utc).isoformat(), "api": API_URL, "total": len(results), "aprovados": sum(item["correto"] for item in results), "resultados": results}
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"total": report["total"], "aprovados": report["aprovados"], "arquivo": str(REPORT_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
