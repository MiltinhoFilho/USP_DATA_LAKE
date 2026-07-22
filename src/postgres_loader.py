"""Load textual chunks into PostgreSQL Gold storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "chunks.jsonl"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "chunks_postgres.jsonl"

load_dotenv(PROJECT_ROOT / ".env")

CREATE_CHUNKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chunks (
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
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_CHUNKS_UNIQUE_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_documento_chunk
ON chunks (documento_id, chunk_id);
"""

INSERT_CHUNK_SQL = """
INSERT INTO chunks (
    documento_id,
    chunk_id,
    texto,
    titulo,
    autor,
    data_publicacao,
    categoria,
    url,
    source_object
)
VALUES (
    %(documento_id)s,
    %(chunk_id)s,
    %(texto)s,
    %(titulo)s,
    %(autor)s,
    %(data_publicacao)s,
    %(categoria)s,
    %(url)s,
    %(source_object)s
)
ON CONFLICT (documento_id, chunk_id)
DO UPDATE SET
    texto = EXCLUDED.texto,
    titulo = EXCLUDED.titulo,
    autor = EXCLUDED.autor,
    data_publicacao = EXCLUDED.data_publicacao,
    categoria = EXCLUDED.categoria,
    url = EXCLUDED.url,
    source_object = EXCLUDED.source_object,
    updated_at = NOW()
RETURNING id, (created_at = updated_at) AS inserted;
"""


def _load_psycopg():
    try:
        import psycopg
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Dependencia ausente: instale psycopg[binary] com "
            "pip install -r requirements.txt"
        ) from error
    return psycopg


def get_postgres_connection():
    psycopg = _load_psycopg()
    dsn = os.getenv("POSTGRES_DSN")
    if dsn:
        return psycopg.connect(dsn)

    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "usp_data_lake"),
        user=os.getenv("POSTGRES_USER", "usp"),
        password=os.getenv("POSTGRES_PASSWORD", "usp123"),
    )


def ensure_chunks_table(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(CREATE_CHUNKS_TABLE_SQL)
        cursor.execute(CREATE_CHUNKS_UNIQUE_INDEX_SQL)


def _chunk_params(record: dict) -> dict:
    return {
        "documento_id": str(record["documento_id"]),
        "chunk_id": int(record["chunk_id"]),
        "texto": str(record["texto"]),
        "titulo": record.get("titulo"),
        "autor": record.get("autor"),
        "data_publicacao": record.get("data_publicacao"),
        "categoria": record.get("categoria"),
        "url": record.get("url"),
        "source_object": record.get("source_object"),
    }


def normalize_document_url(url: str) -> str:
    """Normaliza uma URL já conhecida, sem acessar ou descobrir endereços."""
    parts = urlsplit(str(url or "").strip())
    query = urlencode([
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ])
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", query, "")
    )


def resolve_document_id_collisions(
    records: Iterable[dict], connection=None
) -> tuple[list[dict], list[dict]]:
    """Impede que um nome sequencial reutilizado sobrescreva outra notícia."""
    records = [dict(record) for record in records]
    if not records:
        return records, []

    own_connection = connection is None
    connection = connection or get_postgres_connection()
    document_ids = sorted({str(record["documento_id"]) for record in records})
    existing: dict[str, set[str]] = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT documento_id, url FROM chunks WHERE documento_id = ANY(%s)",
                (document_ids,),
            )
            for document_id, url in cursor.fetchall():
                existing.setdefault(str(document_id), set()).add(
                    normalize_document_url(str(url or ""))
                )
    finally:
        if own_connection:
            connection.close()

    seen: set[tuple[str, str]] = set()
    collisions: list[dict] = []
    for record in records:
        original_id = str(record["documento_id"])
        normalized_url = normalize_document_url(str(record.get("url") or ""))
        known_urls = existing.get(original_id, set())
        if known_urls and normalized_url not in known_urls:
            identity = normalized_url or str(record.get("source_object") or original_id)
            resolved_id = (
                f"site_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
            )
            record["documento_id"] = resolved_id
            key = (original_id, resolved_id)
            if key not in seen:
                seen.add(key)
                collisions.append({
                    "original_documento_id": original_id,
                    "resolved_documento_id": resolved_id,
                    "url": normalized_url,
                })

    return records, collisions


def insert_chunks(records: Iterable[dict], connection=None) -> list[dict]:
    """Insert/update chunks and return records enriched with PostgreSQL ids."""
    own_connection = connection is None
    connection = connection or get_postgres_connection()
    enriched_records: list[dict] = []

    try:
        ensure_chunks_table(connection)
        with connection.cursor() as cursor:
            for record in records:
                cursor.execute(INSERT_CHUNK_SQL, _chunk_params(record))
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("PostgreSQL nao retornou id do chunk")

                postgres_id = int(row[0])
                enriched = dict(record)
                enriched["id"] = postgres_id
                enriched["postgres_id"] = postgres_id
                enriched["_inserted"] = bool(row[1])
                enriched_records.append(enriched)

        if own_connection:
            connection.commit()
    except Exception:
        if own_connection:
            connection.rollback()
        raise
    finally:
        if own_connection:
            connection.close()

    return enriched_records


def read_jsonl(input_path: Path) -> list[dict]:
    records: list[dict] = []
    with input_path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(records: Iterable[dict], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Carrega chunks no PostgreSQL")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Arquivo JSONL com chunks",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Arquivo JSONL enriquecido com id/postgres_id",
    )
    parser.add_argument(
        "--no-output",
        action="store_true",
        help="Nao grava JSONL enriquecido",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = read_jsonl(args.input)
    loaded = insert_chunks(records)
    print(f"Chunks carregados no PostgreSQL: {len(loaded)} registros.")
    if not args.no_output:
        count = write_jsonl(loaded, args.output)
        print(f"Chunks com IDs salvos em {args.output}: {count} registros.")


if __name__ == "__main__":
    main()
