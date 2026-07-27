
"""Load embeddings into Qdrant Gold vector storage."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable, Sequence

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "chunks_embeddings.jsonl"
DEFAULT_COLLECTION = "usp_news_embeddings"

load_dotenv(PROJECT_ROOT / ".env")


def get_collection_name() -> str:
    return os.getenv("QDRANT_COLLECTION", DEFAULT_COLLECTION)


def _load_qdrant_types():
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Dependencia ausente: instale qdrant-client com "
            "pip install -r requirements.txt"
        ) from error

    return QdrantClient, Distance, PointStruct, VectorParams


def get_qdrant_client():
    QdrantClient, _, _, _ = _load_qdrant_types()
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    api_key = os.getenv("QDRANT_API_KEY") or None
    return QdrantClient(url=url, api_key=api_key)


def _collection_exists(client, collection_name: str) -> bool:
    if hasattr(client, "collection_exists"):
        return bool(client.collection_exists(collection_name=collection_name))

    try:
        client.get_collection(collection_name=collection_name)
    except Exception:
        return False
    return True


def ensure_collection(
    client,
    vector_size: int,
    collection_name: str | None = None,
) -> str:
    _, Distance, _, VectorParams = _load_qdrant_types()
    collection_name = collection_name or get_collection_name()

    if not _collection_exists(client, collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
        )

    return collection_name


def _record_vector(record: dict, embedding: Sequence[float] | None) -> list[float]:
    vector = embedding if embedding is not None else record.get("embedding")
    if vector is None:
        raise ValueError("Registro sem embedding")
    return [float(value) for value in vector]


def _point_id(record: dict) -> int:
    raw_id = record.get("postgres_id") or record.get("id")
    if raw_id is None:
        raise ValueError(
            "Registro sem id/postgres_id; carregue os chunks no PostgreSQL antes"
        )
    return int(raw_id)


def _payload(record: dict, postgres_id: int) -> dict:
    payload = {
        "postgres_id": postgres_id,
        "documento_id": record.get("documento_id"),
        "chunk_id": record.get("chunk_id"),
        "titulo": record.get("titulo"),
        "url": record.get("url"),
        "categoria": record.get("categoria"),
        "source_object": record.get("source_object"),
    }
    for key in (
        "source_type",
        "source_objects",
        "lineage_id",
        "canonical_sha256",
        "schema_version",
    ):
        if record.get(key) is not None:
            payload[key] = record[key]
    return payload


def upsert_embeddings(
    records: Sequence[dict],
    embeddings: Sequence[Sequence[float]] | None = None,
    client=None,
    collection_name: str | None = None,
    batch_size: int = 64,
) -> int:
    """Upsert vectors into Qdrant using PostgreSQL ids as point ids."""
    if not records:
        return 0
    if embeddings is not None and len(embeddings) != len(records):
        raise ValueError("Quantidade de embeddings diferente dos registros")

    _, _, PointStruct, _ = _load_qdrant_types()
    client = client or get_qdrant_client()

    first_vector = _record_vector(
        records[0],
        embeddings[0] if embeddings is not None else None,
    )
    collection_name = ensure_collection(
        client,
        vector_size=len(first_vector),
        collection_name=collection_name,
    )

    points = []
    total = 0
    for index, record in enumerate(records):
        vector = (
            first_vector
            if index == 0
            else _record_vector(
                record,
                embeddings[index] if embeddings is not None else None,
            )
        )
        postgres_id = _point_id(record)
        points.append(
            PointStruct(
                id=postgres_id,
                vector=vector,
                payload=_payload(record, postgres_id),
            )
        )

        if len(points) >= batch_size:
            client.upsert(collection_name=collection_name, points=points, wait=True)
            total += len(points)
            points = []

    if points:
        client.upsert(collection_name=collection_name, points=points, wait=True)
        total += len(points)

    return total


def read_jsonl(input_path: Path) -> list[dict]:
    records: list[dict] = []
    with input_path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Carrega embeddings no Qdrant")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Arquivo JSONL com chunks e embeddings",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Colecao Qdrant (padrao: QDRANT_COLLECTION)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Tamanho do lote de upsert",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = read_jsonl(args.input)
    total = upsert_embeddings(
        records,
        collection_name=args.collection,
        batch_size=args.batch_size,
    )
    print(f"Embeddings carregados no Qdrant: {total} pontos.")


if __name__ == "__main__":
    main()
