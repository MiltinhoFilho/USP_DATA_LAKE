"""Reconstrói a Golden em recursos paralelos sem tocar a versão oficial."""

from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import time

from qdrant_client.models import Distance, VectorParams

from src.embedding import BGEM3Embedder
from src.golden_adapter import silver_to_golden_chunks
from src.postgres_loader import get_postgres_connection
from src.qdrant_loader import get_qdrant_client, upsert_embeddings
from src.silver import transform_json


TABLE = "chunks_sprint_27"
COLLECTION = "usp_news_embeddings_sprint_27"
ROOT = Path(__file__).resolve().parent.parent
BRONZE = ROOT / "bronze" / "raw"


def build_records() -> list[dict]:
    records: list[dict] = []
    for index in range(1, 101):
        result = transform_json(BRONZE / f"usp_news_{index:06d}.json")
        records.extend(silver_to_golden_chunks(result))
    if len({record["documento_id"] for record in records}) != 100:
        raise RuntimeError("Quantidade de documentos canônicos diferente de 100")
    if len({(record["documento_id"], record["chunk_id"]) for record in records}) != len(records):
        raise RuntimeError("Chaves de chunk duplicadas")
    return records


def create_staging_table(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", (TABLE,))
        if cursor.fetchone()[0] is not None:
            raise RuntimeError(f"Tabela de staging já existe: {TABLE}")
        cursor.execute(
            f"""
            CREATE TABLE {TABLE} (
                id SERIAL PRIMARY KEY,
                documento_id VARCHAR(255) NOT NULL,
                chunk_id INTEGER NOT NULL,
                texto TEXT NOT NULL,
                titulo TEXT,
                autor TEXT,
                data_publicacao TEXT,
                categoria TEXT,
                url TEXT,
                source_object TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (documento_id, chunk_id)
            )
            """
        )
    connection.commit()


def load_staging_postgres(records: list[dict]) -> list[dict]:
    connection = get_postgres_connection()
    try:
        create_staging_table(connection)
        enriched = []
        with connection.cursor() as cursor:
            for record in records:
                cursor.execute(
                    f"""
                    INSERT INTO {TABLE} (
                        documento_id, chunk_id, texto, titulo, autor,
                        data_publicacao, categoria, url, source_object
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        record["documento_id"],
                        record["chunk_id"],
                        record["texto"],
                        record.get("titulo"),
                        record.get("autor"),
                        record.get("data_publicacao"),
                        record.get("categoria"),
                        record.get("url"),
                        record.get("source_object"),
                    ),
                )
                item = dict(record)
                item["id"] = item["postgres_id"] = int(cursor.fetchone()[0])
                enriched.append(item)
        connection.commit()
        return enriched
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    started = time.perf_counter()
    records = build_records()
    model = BGEM3Embedder(device="cpu")
    embedding_started = time.perf_counter()
    vectors = model.encode_texts(
        (record["texto"] for record in records),
        batch_size=8,
    )
    embedding_seconds = time.perf_counter() - embedding_started
    dimensions = {len(vector) for vector in vectors}
    if dimensions != {1024}:
        raise RuntimeError(f"Dimensões vetoriais inválidas: {dimensions}")
    if not all(all(math.isfinite(float(value)) for value in vector) for vector in vectors):
        raise RuntimeError("Embedding contém NaN ou infinito")

    client = get_qdrant_client()
    if client.collection_exists(COLLECTION):
        raise RuntimeError(f"Coleção de staging já existe: {COLLECTION}")

    enriched = load_staging_postgres(records)
    try:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )
        loaded = upsert_embeddings(
            enriched,
            embeddings=vectors,
            client=client,
            collection_name=COLLECTION,
        )
    except Exception:
        connection = get_postgres_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP TABLE IF EXISTS {TABLE}")
            connection.commit()
        finally:
            connection.close()
        if client.collection_exists(COLLECTION):
            client.delete_collection(COLLECTION)
        raise
    finally:
        client.close()

    print(
        json.dumps(
            {
                "documents": len({record["documento_id"] for record in enriched}),
                "chunks": len(enriched),
                "vectors": loaded,
                "dimension": model.dimension,
                "embedding_seconds": round(embedding_seconds, 3),
                "total_seconds": round(time.perf_counter() - started, 3),
                "chunks_per_document": dict(Counter(r["documento_id"] for r in enriched)),
                "table": TABLE,
                "collection": COLLECTION,
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
