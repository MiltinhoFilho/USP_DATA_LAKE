"""Gera e valida JSONs editoriais em staging sem alterar a camada Bronze."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.transform import (
    extract_clean_text,
    limpar_html_para_markdown,
    refine_editorial_text,
)


DEFAULT_SOURCE = PROJECT_ROOT / "bronze" / "raw"
DEFAULT_STAGING = PROJECT_ROOT / "data" / "sprint_2_8_staging" / "json"
DEFAULT_REPORTS = PROJECT_ROOT / "reports" / "sprint_2_8"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def restructure_document(source: dict[str, Any], document_id: str) -> dict[str, Any]:
    """Preserva o contrato legado e adiciona representações HTML/texto."""
    if not isinstance(source, dict):
        raise TypeError("O JSON-fonte deve conter um objeto")
    original_html = source.get("conteudo")
    if not isinstance(original_html, str) or not original_html.strip():
        raise ValueError(f"{document_id}: campo 'conteudo' ausente ou vazio")

    structured = dict(source)
    structured["document_id"] = document_id
    structured["conteudo_html"] = original_html
    structured["conteudo_texto"] = extract_clean_text(
        original_html,
        title=str(source.get("titulo") or ""),
        author=str(source.get("autor") or ""),
    )
    if not structured["conteudo_texto"].strip():
        raise ValueError(f"{document_id}: extração textual vazia")
    return structured


def _paragraph_count(text: str) -> int:
    return len([block for block in text.split("\n\n") if block.strip()])


def generate_staging(
    source_dir: Path = DEFAULT_SOURCE,
    staging_dir: Path = DEFAULT_STAGING,
    reports_dir: Path = DEFAULT_REPORTS,
) -> list[dict[str, Any]]:
    """Gera 100 documentos em staging e relatórios de validação."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    validations: list[dict[str, Any]] = []
    refinements: list[dict[str, Any]] = []

    expected_names = [f"usp_news_{index:06d}.json" for index in range(1, 101)]
    actual_names = sorted(path.name for path in source_dir.glob("usp_news_*.json"))
    if actual_names != expected_names:
        raise RuntimeError("A origem não contém a sequência JSON 000001–000100")

    for name in expected_names:
        source_path = source_dir / name
        document_id = source_path.stem
        source = json.loads(source_path.read_text(encoding="utf-8"))
        structured = restructure_document(source, document_id)
        clean_before = limpar_html_para_markdown(source["conteudo"])
        refinement = refine_editorial_text(
            clean_before,
            title=str(source.get("titulo") or ""),
            author=str(source.get("autor") or ""),
        )
        destination = staging_dir / name
        destination.write_text(
            json.dumps(structured, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        reloaded = json.loads(destination.read_text(encoding="utf-8"))
        html_equal = reloaded["conteudo_html"] == source["conteudo"]
        legacy_equal = reloaded["conteudo"] == source["conteudo"]
        metadata_equal = all(
            reloaded.get(field) == source.get(field)
            for field in ("titulo", "autor", "data", "categoria", "url")
        )
        validations.append(
            {
                "document_id": document_id,
                "file": name,
                "valid_json": True,
                "nonempty_text": bool(reloaded["conteudo_texto"].strip()),
                "html_equal": html_equal,
                "legacy_content_equal": legacy_equal,
                "metadata_equal": metadata_equal,
                "original_html_sha256": _sha256_text(source["conteudo"]),
                "staging_html_sha256": _sha256_text(reloaded["conteudo_html"]),
                "text_chars": len(reloaded["conteudo_texto"]),
                "paragraphs": _paragraph_count(reloaded["conteudo_texto"]),
                "replacement_characters": reloaded["conteudo_texto"].count("\ufffd"),
                "status": (
                    "APROVADO"
                    if html_equal
                    and legacy_equal
                    and metadata_equal
                    and bool(reloaded["conteudo_texto"].strip())
                    else "REPROVADO"
                ),
            }
        )
        refinements.append(
            {
                "document_id": document_id,
                "title": source.get("titulo", ""),
                "author": source.get("autor", ""),
                "characters_before": len(refinement.original_text),
                "characters_after": len(refinement.text),
                "removed_characters": (
                    len(refinement.original_text) - len(refinement.text)
                ),
                "removed_blocks": [
                    {
                        "rule": removal.rule,
                        "reason": removal.reason,
                        "text": removal.text,
                    }
                    for removal in refinement.removals
                ],
                "first_excerpt_before": refinement.original_text[:500],
                "first_excerpt_after": refinement.text[:500],
                "last_excerpt_before": refinement.original_text[-500:],
                "last_excerpt_after": refinement.text[-500:],
                "status": "APROVADO" if refinement.text else "REPROVADO",
            }
        )

    if len(validations) != 100 or any(row["status"] != "APROVADO" for row in validations):
        raise RuntimeError("Validação do staging editorial falhou")
    if len({row["document_id"] for row in validations}) != 100:
        raise RuntimeError("IDs duplicados no staging editorial")

    (reports_dir / "json_validation.json").write_text(
        json.dumps({"items": validations}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (reports_dir / "json_validation.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as output:
        writer = csv.DictWriter(output, fieldnames=validations[0].keys())
        writer.writeheader()
        writer.writerows(validations)
    (reports_dir / "editorial_refinement.json").write_text(
        json.dumps({"items": refinements}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    refinement_rows = [
        {
            **{key: value for key, value in row.items() if key != "removed_blocks"},
            "removed_blocks": json.dumps(
                row["removed_blocks"], ensure_ascii=False
            ),
        }
        for row in refinements
    ]
    with (reports_dir / "editorial_refinement.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as output:
        writer = csv.DictWriter(output, fieldnames=refinement_rows[0].keys())
        writer.writeheader()
        writer.writerows(refinement_rows)
    return validations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estrutura JSONs Bronze em staging editorial isolado"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = generate_staging(args.source, args.staging, args.reports)
    print(
        json.dumps(
            {
                "documents": len(rows),
                "approved": sum(row["status"] == "APROVADO" for row in rows),
                "html_preserved": sum(row["html_equal"] for row in rows),
                "text_nonempty": sum(row["nonempty_text"] for row in rows),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
