"""Read Bronze JSON or PDF from MinIO/local, clean text, and create text chunks."""

from __future__ import annotations

import argparse
import html
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from bs4 import BeautifulSoup, Comment
from markdownify import markdownify as html_to_markdown

from src.chunking import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP, criar_chunks
from src.minio_client import get_bucket_name, get_minio_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCAL_BRONZE_DIR = PROJECT_ROOT / "bronze" / "raw"
DEFAULT_CHUNKS_OUTPUT = PROJECT_ROOT / "data" / "chunks.jsonl"

MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "â€“", "â€”", "â€˜", "â€™", "â€œ", "â€�")

NOISE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "form",
    "nav",
    "footer",
    "header",
    "aside",
    ".sharedaddy",
    ".jp-relatedposts",
    ".post-navigation",
    ".navigation",
    ".newsletter",
    ".elementor-share-buttons-wrapper",
    ".addtoany_share_save_container",
)

NOISE_LINE_PATTERNS = (
    r"^compartilhe:?$",
    r"^leia tamb[eé]m:?$",
    r"^veja tamb[eé]m:?$",
    r"^ou[cç]a:?$",
    r"^publicidade$",
)


@dataclass(frozen=True)
class BronzeDocument:
    object_name: str
    documento_id: str
    payload: dict


def _document_id_from_object(object_name: str) -> str:
    return Path(object_name).stem


def _decode_json_object(raw_bytes: bytes, object_name: str) -> list[BronzeDocument]:
    payload = json.loads(raw_bytes.decode("utf-8"))
    base_id = _document_id_from_object(object_name)

    if isinstance(payload, list):
        return [
            BronzeDocument(
                object_name=object_name,
                documento_id=f"{base_id}_{index:06d}",
                payload=item,
            )
            for index, item in enumerate(payload, start=1)
            if isinstance(item, dict)
        ]

    if isinstance(payload, dict):
        return [
            BronzeDocument(
                object_name=object_name,
                documento_id=base_id,
                payload=payload,
            )
        ]

    return []


def _extract_text_from_pdf_bytes(raw_bytes: bytes, object_name: str) -> str:
    if not raw_bytes:
        raise RuntimeError(f"PDF vazio: {object_name}")
    if not raw_bytes.startswith(b"%PDF-"):
        raise RuntimeError(f"Conteudo sem assinatura PDF: {object_name}")
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(io.BytesIO(raw_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(pages).strip()
        if not text:
            raise RuntimeError(f"PDF sem texto extraível: {object_name}")
        return text
    except Exception as error:
        raise RuntimeError(
            f"Falha ao extrair texto do PDF {object_name}: {error}"
        ) from error


def _decode_pdf_bytes(raw_bytes: bytes, object_name: str) -> list[BronzeDocument]:
    text = _extract_text_from_pdf_bytes(raw_bytes, object_name)
    from PyPDF2 import PdfReader

    metadata = PdfReader(io.BytesIO(raw_bytes)).metadata or {}
    title = str(metadata.get("/Title") or Path(object_name).stem.replace("_", " ").title())
    subject = str(metadata.get("/Subject") or "")
    source_url = subject.removeprefix("Source-URL: ").strip() if subject.startswith("Source-URL: ") else ""
    return [
        BronzeDocument(
            object_name=object_name,
            documento_id=f"pdf_{_document_id_from_object(object_name)}",
            payload={
                "titulo": title,
                "conteudo": text,
                "autor": "",
                "data": "",
                "categoria": "",
                "url": source_url,
            },
        )
    ]


def iter_minio_documents(
    prefix: str = "raw/",
    limit: int | None = None,
    bucket_name: str | None = None,
    extensions: set[str] | None = None,
) -> Iterator[BronzeDocument]:
    """Yield Bronze JSON/PDF documents stored in MinIO."""
    client = get_minio_client()
    bucket_name = bucket_name or get_bucket_name()
    extensions = extensions or {"json", "pdf"}

    if not client.bucket_exists(bucket_name):
        raise RuntimeError(f"Bucket MinIO '{bucket_name}' nao encontrado")

    yielded = 0
    objects = client.list_objects(bucket_name, prefix=prefix, recursive=True)
    for obj in objects:
        if limit is not None and yielded >= limit:
            break
        suffix = obj.object_name.lower().split(".")[-1]
        if suffix not in extensions:
            continue

        response = client.get_object(bucket_name, obj.object_name)
        try:
            raw_bytes = response.read()
            if suffix == "json":
                documents = _decode_json_object(raw_bytes, obj.object_name)
            else:
                documents = _decode_pdf_bytes(raw_bytes, obj.object_name)
        finally:
            response.close()
            response.release_conn()

        for document in documents:
            if limit is not None and yielded >= limit:
                break
            yielded += 1
            yield document


def iter_local_documents(
    bronze_dir: Path = DEFAULT_LOCAL_BRONZE_DIR,
    limit: int | None = None,
    extensions: set[str] | None = None,
) -> Iterator[BronzeDocument]:
    """Yield local Bronze JSON files for development and validation."""
    extensions = extensions or {"json", "pdf"}
    yielded = 0
    for file_path in sorted(bronze_dir.glob("*")):
        suffix = file_path.suffix.lower().lstrip(".")
        if suffix not in extensions:
            continue
        if limit is not None and yielded >= limit:
            break

        raw_bytes = file_path.read_bytes()
        if file_path.suffix.lower() == ".json":
            documents = _decode_json_object(raw_bytes, file_path.name)
        else:
            documents = _decode_pdf_bytes(raw_bytes, file_path.name)
        for document in documents:
            if limit is not None and yielded >= limit:
                break
            yielded += 1
            yield document


def _is_noise_line(line: str) -> bool:
    lowered = line.strip().lower()
    return any(re.match(pattern, lowered) for pattern in NOISE_LINE_PATTERNS)


def _mojibake_score(text: str) -> int:
    return sum(text.count(marker) for marker in MOJIBAKE_MARKERS)


def _repair_mojibake(text: str) -> str:
    """Fix common UTF-8 text that was decoded as Latin-1/Windows-1252."""
    if not text or not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text

    best_text = text
    best_score = _mojibake_score(text)
    for encoding in ("latin1", "cp1252"):
        try:
            candidate = text.encode(encoding).decode("utf-8")
        except UnicodeError:
            continue

        candidate_score = _mojibake_score(candidate)
        if candidate_score < best_score:
            best_text = candidate
            best_score = candidate_score

    return best_text


def _normalize_markdown(text: str) -> str:
    text = html.unescape(text)
    text = _repair_mojibake(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"!\[[^\]]*]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)]\(\s*(?:#|javascript:[^)]+)\)", r"\1", text, flags=re.I)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    lines: list[str] = []
    previous_blank = False
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            if not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        previous_blank = False
        if _is_noise_line(cleaned):
            continue
        lines.append(cleaned)

    cleaned_text = "\n".join(lines).strip()
    return _repair_mojibake(re.sub(r"\n{3,}", "\n\n", cleaned_text))


def limpar_html_para_markdown(html_text: str) -> str:
    """Remove common page noise and convert the article body to Markdown."""
    if not html_text:
        return ""

    soup = BeautifulSoup(html_text, "html.parser")
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for selector in NOISE_SELECTORS:
        for element in soup.select(selector):
            element.decompose()

    markdown = html_to_markdown(
        str(soup),
        heading_style="ATX",
        bullets="-",
        strip=("img",),
    )
    return _normalize_markdown(markdown)


def _clean_plain_value(value: object) -> str:
    if value is None:
        return ""
    return _normalize_markdown(str(value))


def montar_texto_limpo(article: dict) -> str:
    titulo = _clean_plain_value(article.get("titulo"))
    conteudo = limpar_html_para_markdown(str(article.get("conteudo") or ""))

    parts = []
    if titulo:
        parts.append(f"# {titulo}")
    if conteudo:
        parts.append(conteudo)

    return "\n\n".join(parts).strip()


def transformar_documento(
    document: BronzeDocument,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[dict]:
    article = document.payload
    texto_limpo = montar_texto_limpo(article)
    chunks = criar_chunks(texto_limpo, chunk_size=chunk_size, overlap=overlap)

    records: list[dict] = []
    for chunk_id, texto in enumerate(chunks, start=1):
        records.append(
            {
                "documento_id": document.documento_id,
                "chunk_id": chunk_id,
                "texto": texto,
                "titulo": _clean_plain_value(article.get("titulo")),
                "autor": _clean_plain_value(article.get("autor")),
                "data_publicacao": _clean_plain_value(article.get("data")),
                "categoria": _clean_plain_value(article.get("categoria")),
                "url": _clean_plain_value(article.get("url")),
                "source_object": document.object_name,
                "chunk_size": chunk_size,
                "overlap": overlap,
            }
        )

    return records


def iter_bronze_documents(
    source: str,
    prefix: str,
    local_bronze_dir: Path,
    limit: int | None,
    bucket_name: str | None = None,
    extensions: set[str] | None = None,
) -> Iterable[BronzeDocument]:
    if source == "minio":
        return iter_minio_documents(
            prefix=prefix,
            limit=limit,
            bucket_name=bucket_name,
            extensions=extensions,
        )
    if source == "local":
        return iter_local_documents(
            bronze_dir=local_bronze_dir,
            limit=limit,
            extensions=extensions,
        )
    raise ValueError("source deve ser 'minio' ou 'local'")


def run_transform(
    source: str = "minio",
    prefix: str = "raw/",
    local_bronze_dir: Path = DEFAULT_LOCAL_BRONZE_DIR,
    limit: int | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    bucket_name: str | None = None,
    extensions: set[str] | None = None,
) -> list[dict]:
    records: list[dict] = []
    documents = iter_bronze_documents(
        source=source,
        prefix=prefix,
        local_bronze_dir=local_bronze_dir,
        limit=limit,
        bucket_name=bucket_name,
        extensions=extensions,
    )

    document_count = 0
    for document in documents:
        document_count += 1
        records.extend(
            transformar_documento(
                document,
                chunk_size=chunk_size,
                overlap=overlap,
            )
        )

    print(
        f"Transformacao concluida: {document_count} documentos, "
        f"{len(records)} chunks."
    )
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
    parser = argparse.ArgumentParser(
        description="Transforma Bronze MinIO em chunks limpos"
    )
    parser.add_argument(
        "--source",
        choices=("minio", "local"),
        default="minio",
        help="Origem dos JSONs Bronze",
    )
    parser.add_argument(
        "--prefix",
        default="raw/",
        help="Prefixo dos objetos no bucket Bronze",
    )
    parser.add_argument(
        "--bucket",
        default=None,
        help="Bucket MinIO (padrao: MINIO_BUCKET)",
    )
    parser.add_argument(
        "--local-bronze-dir",
        type=Path,
        default=DEFAULT_LOCAL_BRONZE_DIR,
        help="Diretorio local usado com --source local",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limite de documentos para transformar",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="Tamanho maximo dos chunks",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=DEFAULT_OVERLAP,
        help="Sobreposicao entre chunks",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CHUNKS_OUTPUT,
        help="Arquivo JSONL de saida para os chunks",
    )
    parser.add_argument(
        "--no-output",
        action="store_true",
        help="Nao grava JSONL local",
    )
    parser.add_argument(
        "--load-postgres",
        action="store_true",
        help="Carrega chunks textuais no PostgreSQL",
    )
    parser.add_argument(
        "--load-qdrant",
        action="store_true",
        help="Gera embeddings BGE-M3 e carrega vetores no Qdrant",
    )
    parser.add_argument(
        "--load-gold",
        action="store_true",
        help="Atalho para --load-postgres --load-qdrant",
    )
    parser.add_argument(
        "--embedding-model",
        default=None,
        help="Modelo SentenceTransformer para embeddings",
    )
    parser.add_argument(
        "--embedding-device",
        default=None,
        help="Dispositivo do SentenceTransformer, como cpu ou cuda",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=16,
        help="Tamanho do lote para embeddings",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_postgres = args.load_postgres or args.load_gold or args.load_qdrant
    load_qdrant = args.load_qdrant or args.load_gold

    records = run_transform(
        source=args.source,
        prefix=args.prefix,
        local_bronze_dir=args.local_bronze_dir,
        limit=args.limit,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        bucket_name=args.bucket,
    )

    if load_postgres:
        from postgres_loader import insert_chunks

        records = insert_chunks(records)
        print(f"Chunks carregados no PostgreSQL: {len(records)} registros.")

    if not args.no_output:
        count = write_jsonl(records, args.output)
        print(f"Chunks salvos em {args.output} ({count} registros).")

    if load_qdrant:
        from embedding import BGEM3Embedder
        from qdrant_loader import upsert_embeddings

        embedder = BGEM3Embedder(
            model_name=args.embedding_model,
            device=args.embedding_device,
        )
        embeddings = embedder.encode_texts(
            (record["texto"] for record in records),
            batch_size=args.embedding_batch_size,
        )
        total = upsert_embeddings(records, embeddings=embeddings)
        print(
            f"Embeddings carregados no Qdrant: {total} pontos "
            f"({embedder.dimension} dimensoes)."
        )


if __name__ == "__main__":
    main()
