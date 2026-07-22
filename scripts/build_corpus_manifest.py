"""Gera manifesto somente leitura do recorte já existente no USP Data Lake."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PyPDF2 import PdfReader

from src.minio_client import get_bucket_name, get_minio_client
from src.postgres_loader import get_postgres_connection, resolve_document_id_collisions
from src.qdrant_loader import get_collection_name, get_qdrant_client
from src.transform import (
    _decode_json_object,
    _decode_pdf_bytes,
    montar_texto_limpo,
    transformar_documento,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "data" / "recorte_manifest.json"


def build_manifest() -> dict:
    minio = get_minio_client()
    bucket = get_bucket_name()
    objects: list[dict] = []
    all_records: list[dict] = []

    for item in minio.list_objects(bucket, recursive=True):
        response = minio.get_object(bucket, item.object_name)
        try:
            raw = response.read()
        finally:
            response.close()
            response.release_conn()

        kind = "pdf" if item.object_name.lower().endswith(".pdf") else "json"
        error = ""
        documents = []
        pages = None
        try:
            if kind == "pdf":
                pages = len(PdfReader(io.BytesIO(raw)).pages)
                documents = _decode_pdf_bytes(raw, item.object_name)
            else:
                documents = _decode_json_object(raw, item.object_name)
        except Exception as exc:
            error = str(exc)

        for document in documents:
            records = transformar_documento(document)
            all_records.extend(records)
            objects.append({
                "documento_id": document.documento_id,
                "tipo": kind,
                "titulo": document.payload.get("titulo") or "",
                "url": document.payload.get("url") or "",
                "nome_arquivo": Path(item.object_name).name,
                "bucket": bucket,
                "object_key": item.object_name,
                "source_object": item.object_name,
                "tamanho": int(item.size),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "data_coleta": document.payload.get("data") or "",
                "paginas": pages,
                "caracteres": len(montar_texto_limpo(document.payload)),
                "chunks": len(records),
                "erro": error,
            })

    resolved_records, collisions = resolve_document_id_collisions(all_records)
    resolved_by_source = {
        record["source_object"]: record["documento_id"] for record in resolved_records
    }

    with get_postgres_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT documento_id, count(*) FROM chunks GROUP BY documento_id")
            postgres_counts = {str(row[0]): int(row[1]) for row in cursor.fetchall()}

    qdrant = get_qdrant_client()
    qdrant_counts: dict[str, int] = {}
    offset = None
    while True:
        points, offset = qdrant.scroll(
            get_collection_name(), limit=256, offset=offset,
            with_payload=True, with_vectors=False,
        )
        for point in points:
            document_id = str((point.payload or {}).get("documento_id") or "")
            qdrant_counts[document_id] = qdrant_counts.get(document_id, 0) + 1
        if offset is None:
            break

    for item in objects:
        resolved_id = resolved_by_source.get(item["source_object"], item["documento_id"])
        item["documento_id_resolvido"] = resolved_id
        item["status_postgresql"] = postgres_counts.get(resolved_id, 0)
        item["status_qdrant"] = qdrant_counts.get(resolved_id, 0)

    return {
        "escopo": "Somente objetos já existentes no MinIO Bronze",
        "bucket": bucket,
        "documentos": objects,
        "colisoes_identidade": collisions,
        "resumo": {
            "objetos": len(objects),
            "json": sum(item["tipo"] == "json" for item in objects),
            "pdf": sum(item["tipo"] == "pdf" for item in objects),
            "urls_distintas": len({item["url"] for item in objects if item["url"]}),
            "caracteres": sum(item["caracteres"] for item in objects),
            "chunks": sum(item["chunks"] for item in objects),
            "erros": sum(bool(item["erro"]) for item in objects),
        },
    }


def main() -> None:
    manifest = build_manifest()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest["resumo"], ensure_ascii=False))
    print(f"Manifesto salvo em {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
