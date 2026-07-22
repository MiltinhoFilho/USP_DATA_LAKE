"""Executor sequencial e retomável do benchmark contra a RAG API."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from evaluation.metrics import load_json, source_rank, validate_benchmark, validate_ground_truth


DEFAULT_API_URL = "http://localhost:8003/pergunta"


def load_completed(path: Path) -> set[str]:
    if not path.exists():
        return set()
    completed = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                item = json.loads(line)
                if item.get("completed"):
                    completed.add(str(item["id"]))
    return completed


def call_api(api_url: str, question: str, top_k: int, timeout: float) -> tuple[int, dict]:
    payload = json.dumps({"pergunta": question, "top_k": top_k}).encode("utf-8")
    request = Request(api_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return error.code, {"detail": body[:500]}
    except (URLError, TimeoutError) as error:
        return 0, {"detail": type(error).__name__}


def sanitize_sources(sources: list[dict]) -> list[dict]:
    allowed = {
        "id", "titulo", "url", "score", "document_id", "chunk_id",
        "postgres_id", "source_type", "source_object",
    }
    return [{key: value for key, value in source.items() if key in allowed} for source in sources]


def execute_case(case: dict, api_url: str, top_k: int, timeout: float) -> dict:
    started = time.perf_counter()
    status, response = call_api(api_url, case["pergunta"], top_k, timeout)
    wall_seconds = time.perf_counter() - started
    result = {
        "id": case["id"],
        "categoria": case["categoria"],
        "pergunta": case["pergunta"],
        "review_status": case["review_status"],
        "status_http": status,
        "resposta_gerada": response.get("resposta"),
        "evidence_sufficient": response.get("evidence_sufficient"),
        "ollama_skipped": response.get("ollama_skipped"),
        "refusal_reason": (response.get("metrics") or {}).get("refusal_reason"),
        "fontes": sanitize_sources(response.get("fontes") or []),
        "metrics": response.get("metrics") or {},
        "wall_seconds": wall_seconds,
        "human_evaluation": None,
        "completed": status == 200,
    }
    result["expected_source_rank"] = source_rank(case, result)
    if status != 200:
        result["error_type"] = response.get("detail")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=Path("evaluation/questions.json"))
    parser.add_argument("--ground-truth", type=Path, default=Path("evaluation/ground_truth.json"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/results/results.jsonl"))
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=420)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--allow-pending", action="store_true", help="Permite somente piloto preliminar; não libera métricas oficiais.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    questions = load_json(args.questions)
    truth = load_json(args.ground_truth)
    validate_benchmark(questions, truth)
    cases = validate_ground_truth(truth, require_approved=not args.allow_pending)
    if args.ids:
        requested = set(args.ids)
        cases = [case for case in cases if case["id"] in requested]
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit deve ser maior que zero")
        cases = cases[: args.limit]
    completed = load_completed(args.output)
    pending = [case for case in cases if case["id"] not in completed]
    print(f"Casos selecionados: {len(cases)}; concluídos: {len(completed)}; pendentes: {len(pending)}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as stream:
        for index, case in enumerate(pending, start=1):
            print(f"[{index}/{len(pending)}] {case['id']} — {case['categoria']}", flush=True)
            result = execute_case(case, args.api_url, args.top_k, args.timeout)
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            stream.flush()
            print(f"HTTP {result['status_http']} | {result['wall_seconds']:.2f}s", flush=True)
            if not result["completed"]:
                raise RuntimeError(f"execução interrompida em {case['id']}; use o checkpoint para retomar")


if __name__ == "__main__":
    main()
