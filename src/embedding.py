"""Embedding generation with the BGE-M3 model."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "chunks.jsonl"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "chunks_embeddings.jsonl"
DEFAULT_MODEL_NAME = "BAAI/bge-m3"

load_dotenv(PROJECT_ROOT / ".env")


def get_embedding_model_name() -> str:
    return os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL_NAME)


class BGEM3Embedder:
    """Small wrapper around SentenceTransformer for BGE-M3 embeddings."""

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        normalize_embeddings: bool = True,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name or get_embedding_model_name()
        self.normalize_embeddings = normalize_embeddings
        offline = os.getenv("HF_HUB_OFFLINE", "").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.model = SentenceTransformer(
            self.model_name,
            device=device,
            local_files_only=offline,
        )

    @property
    def dimension(self) -> int:
        dimension = self.model.get_sentence_embedding_dimension()
        if dimension is None:
            raise RuntimeError("Nao foi possivel detectar a dimensao do modelo")
        return int(dimension)

    def encode_texts(
        self,
        texts: Iterable[str],
        batch_size: int = 16,
        show_progress_bar: bool = True,
    ) -> list[list[float]]:
        text_list = list(texts)
        if not text_list:
            return []

        vectors = self.model.encode(
            text_list,
            batch_size=batch_size,
            normalize_embeddings=self.normalize_embeddings,
            show_progress_bar=show_progress_bar,
        )

        if hasattr(vectors, "tolist"):
            return vectors.tolist()

        return [list(vector) for vector in vectors]


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


def embed_records(
    records: list[dict],
    embedder: BGEM3Embedder,
    batch_size: int = 16,
    text_key: str = "texto",
) -> list[dict]:
    texts = [str(record.get(text_key) or "") for record in records]
    vectors = embedder.encode_texts(texts, batch_size=batch_size)

    if len(vectors) != len(records):
        raise RuntimeError(
            "Quantidade de embeddings diferente da quantidade de registros"
        )

    enriched_records: list[dict] = []
    for record, vector in zip(records, vectors):
        enriched = dict(record)
        enriched["embedding"] = vector
        enriched_records.append(enriched)

    return enriched_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera embeddings BGE-M3")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Arquivo JSONL com chunks textuais",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Arquivo JSONL com embeddings",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Modelo SentenceTransformer (padrao: BAAI/bge-m3)",
    )
    parser.add_argument(
        "--device",
        default=os.getenv("EMBEDDING_DEVICE"),
        help="Dispositivo do SentenceTransformer, como cpu ou cuda",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="Tamanho do lote para vetorizacao",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = read_jsonl(args.input)
    embedder = BGEM3Embedder(model_name=args.model, device=args.device)
    enriched_records = embed_records(
        records,
        embedder=embedder,
        batch_size=args.batch_size,
    )
    count = write_jsonl(enriched_records, args.output)
    print(
        f"Embeddings BGE-M3 salvos em {args.output}: "
        f"{count} registros, dimensao {embedder.dimension}."
    )


if __name__ == "__main__":
    main()
