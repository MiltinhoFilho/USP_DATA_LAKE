"""Exporta inventário somente leitura do PostgreSQL para JSON."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from src.postgres_loader import get_postgres_connection


QUERY = """
SELECT documento_id, titulo, url, source_object, categoria, COUNT(*) AS chunks
FROM chunks
GROUP BY documento_id, titulo, url, source_object, categoria
ORDER BY titulo, documento_id
"""


def source_type(source_object: str | None) -> str:
    value = (source_object or "").lower()
    if value.endswith(".json"):
        return "json"
    if value.endswith(".pdf"):
        return "pdf"
    return "unknown"


def build_inventory() -> dict:
    connection = get_postgres_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(QUERY)
            rows = cursor.fetchall()
    finally:
        connection.close()
    documents = [
        {
            "document_id": row[0], "titulo": row[1], "url": row[2],
            "source_object": row[3], "source_type": source_type(row[3]),
            "categoria": row[4] or "(sem categoria)", "chunks": int(row[5]),
        }
        for row in rows
    ]
    categories = Counter(document["categoria"] for document in documents)
    origins = Counter(document["source_type"] for document in documents)
    return {
        "scope": "Recorte local indexado do Jornal da USP",
        "limitations": "Não representa cobertura integral nem amostra estatística de todo o portal.",
        "summary": {
            "postgres_rows": sum(document["chunks"] for document in documents),
            "document_ids": len({document["document_id"] for document in documents}),
            "urls": len({document["url"] for document in documents}),
            "source_objects": len({document["source_object"] for document in documents}),
            "documents_by_source_type": dict(sorted(origins.items())),
            "documents_by_category": dict(sorted(categories.items())),
        },
        "documents": documents,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evaluation/corpus_inventory.json"))
    args = parser.parse_args()
    inventory = build_inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Inventário salvo em {args.output}: {len(inventory['documents'])} documentos")


if __name__ == "__main__":
    main()
