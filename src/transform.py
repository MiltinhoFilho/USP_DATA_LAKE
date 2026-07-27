"""Read Bronze JSON or PDF from MinIO/local, clean text, and create text chunks."""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import html
import io
import json
import re
import unicodedata
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

KNOWN_BOILERPLATE_PATTERNS = (
    re.compile(
        r"(?im)^\[Pular barra de compartilhamento\]\(\s*#main-content\s*\)\s*$"
    ),
    re.compile(
        r"(?ims)"
        r"^\s*---\s*\n+"
        r"\*\*Jornal da USP no Ar\*\*\s*\n+"
        r"\[Jornal da USP no Ar\]\("
        r"https?://jornal\.usp\.br/editorias/radio-usp/jornal-da-usp-no-ar/"
        r"\)\s+no ar veiculado pela Rede USP de Rádio,.*\Z"
    ),
)


@dataclass(frozen=True)
class BronzeDocument:
    object_name: str
    documento_id: str
    payload: dict


@dataclass(frozen=True)
class EditorialRemoval:
    """Bloco não editorial removido de uma extremidade do texto."""

    rule: str
    reason: str
    text: str


@dataclass(frozen=True)
class EditorialRefinement:
    """Resultado auditável do refinamento editorial."""

    original_text: str
    text: str
    removals: tuple[EditorialRemoval, ...]


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


def _remove_known_boilerplates(markdown: str) -> str:
    """Remove somente resíduos institucionais confirmados no corpus auditado."""
    cleaned = markdown
    for pattern in KNOWN_BOILERPLATE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned


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
    return _normalize_markdown(_remove_known_boilerplates(markdown))


def _editorial_key(value: str) -> str:
    """Normaliza títulos, autores e blocos Markdown para comparação."""
    value = re.sub(r"^#{1,6}\s+", "", value.strip())
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = value.replace("\\", "").replace("*", "")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        character
        for character in value
        if not unicodedata.combining(character)
    )
    value = re.sub(r"[^\w]+", " ", value.casefold())
    return re.sub(r"\s+", " ", value).strip()


def _split_editorial_blocks(value: str) -> list[str]:
    return [
        block.strip()
        for block in re.split(r"\n[ \t]*\n+", value)
        if block.strip()
    ]


def remove_duplicate_leading_title(
    blocks: list[str],
    title: str,
) -> tuple[list[str], EditorialRemoval | None]:
    """Remove somente o primeiro bloco quando ele repete o título documental."""
    if not blocks or not title.strip():
        return blocks, None
    candidate = _editorial_key(blocks[0])
    expected = _editorial_key(title)
    if not candidate or not expected:
        return blocks, None
    equivalent = candidate == expected or (
        SequenceMatcher(None, candidate, expected, autojunk=False).ratio() >= 0.97
        and set(candidate.split()) == set(expected.split())
    )
    if not equivalent:
        return blocks, None
    removal = EditorialRemoval(
        rule="duplicate_leading_title",
        reason="primeiro bloco repete o campo titulo",
        text=blocks[0],
    )
    return blocks[1:], removal


def remove_duplicate_byline(
    blocks: list[str],
    author: str,
) -> tuple[list[str], EditorialRemoval | None]:
    """Remove byline inicial somente quando ela coincide com o campo autor."""
    if not blocks or not author.strip():
        return blocks, None
    author_key = _editorial_key(author)
    for index, block in enumerate(blocks[:3]):
        first_line = block.splitlines()[0].strip()
        if not re.match(r"(?i)^por(?:\s|:)", first_line):
            continue
        byline_key = _editorial_key(
            re.sub(r"(?i)^por(?:\s|:)+", "", first_line)
        )
        if author_key and (
            author_key == byline_key
            or author_key in byline_key
            or byline_key in author_key
        ):
            removal = EditorialRemoval(
                rule="duplicate_byline",
                reason="byline inicial repete o campo autor",
                text=block,
            )
            return blocks[:index] + blocks[index + 1 :], removal
    return blocks, None


def remove_generic_editorial_notices(
    blocks: list[str],
) -> tuple[list[str], tuple[EditorialRemoval, ...]]:
    """Remove avisos institucionais genéricos apenas da cauda do artigo."""
    removals: list[EditorialRemoval] = []
    while blocks:
        key = _editorial_key(blocks[-1])
        opinion_notice = (
            "opinioes expressas nos artigos publicados" in key
            and "inteira responsabilidade de seus autores" in key
        )
        if not opinion_notice:
            break
        removals.append(
            EditorialRemoval(
                rule="generic_opinion_notice",
                reason="aviso institucional genérico após o artigo",
                text=blocks.pop(),
            )
        )
    return blocks, tuple(removals)


def remove_generic_reuse_credits(
    blocks: list[str],
) -> tuple[list[str], tuple[EditorialRemoval, ...]]:
    """Remove política geral de reutilização somente quando terminal."""
    removals: list[EditorialRemoval] = []
    if not blocks:
        return blocks, ()
    key = _editorial_key(blocks[-1])
    reuse_notice = (
        "politica de uso" in key
        and "reproducao de materias" in key
        and (
            "arquivos de video" in key
            or "fotos devem ser creditadas" in key
        )
    )
    if reuse_notice:
        removals.append(
            EditorialRemoval(
                rule="generic_reuse_credits",
                reason="política institucional geral após o artigo",
                text=blocks.pop(),
            )
        )
        if blocks and re.fullmatch(r"[-_*\\\s]+", blocks[-1]):
            removals.append(
                EditorialRemoval(
                    rule="generic_reuse_separator",
                    reason="separador do bloco institucional removido",
                    text=blocks.pop(),
                )
            )
    return blocks, tuple(removals)


def refine_editorial_text(
    text: str,
    *,
    title: str = "",
    author: str = "",
) -> EditorialRefinement:
    """Refina somente duplicações e avisos comprovados nas extremidades."""
    original = text.strip()
    blocks = _split_editorial_blocks(original)
    removals: list[EditorialRemoval] = []

    blocks, removal = remove_duplicate_leading_title(blocks, title)
    if removal is not None:
        removals.append(removal)
    blocks, removal = remove_duplicate_byline(blocks, author)
    if removal is not None:
        removals.append(removal)
    blocks, removed = remove_generic_editorial_notices(blocks)
    removals.extend(removed)
    blocks, removed = remove_generic_reuse_credits(blocks)
    removals.extend(removed)

    refined = "\n\n".join(blocks).strip()
    return EditorialRefinement(original, refined, tuple(removals))


def extract_clean_text(
    html_text: str,
    *,
    title: str = "",
    author: str = "",
) -> str:
    """Extrai texto editorial legível sem modificar o HTML de origem.

    O contrato público reutiliza a limpeza consolidada da etapa Silver:
    elementos não editoriais são removidos e parágrafos, subtítulos, listas,
    links e Unicode são preservados em Markdown legível.
    """
    if not isinstance(html_text, str):
        raise TypeError("html_text deve ser uma string")
    clean_text = limpar_html_para_markdown(html_text)
    return refine_editorial_text(
        clean_text,
        title=title,
        author=author,
    ).text


def _clean_plain_value(value: object) -> str:
    if value is None:
        return ""
    return _normalize_markdown(str(value))


def _comparable_heading(value: str) -> str:
    value = re.sub(r"^#{1,6}\s+", "", value.strip())
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = unicodedata.normalize("NFKC", value)
    value = "".join(
        character
        for character in value
        if unicodedata.category(character) != "Cf"
    )
    return re.sub(r"\s+", " ", value).strip().casefold()


def _body_starts_with_title(content: str, title: str) -> bool:
    """Detecta o título entre as primeiras linhas editoriais do JSON."""
    expected = _comparable_heading(title)
    if not expected:
        return False
    initial_lines = [line for line in content.splitlines() if line.strip()][:3]
    return any(_comparable_heading(line) == expected for line in initial_lines)


def montar_texto_limpo(article: dict, *, preserve_external_pdf: bool = False) -> str:
    titulo = _clean_plain_value(article.get("titulo"))
    conteudo = limpar_html_para_markdown(str(article.get("conteudo") or ""))

    parts = []
    if titulo and (
        preserve_external_pdf
        or not _body_starts_with_title(conteudo, titulo)
    ):
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
    texto_limpo = montar_texto_limpo(
        article,
        preserve_external_pdf=Path(document.object_name).suffix.lower() == ".pdf",
    )
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
