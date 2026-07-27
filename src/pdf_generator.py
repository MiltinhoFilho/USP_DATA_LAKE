"""Geração offline e determinística de PDF a partir de um JSON Bronze."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import textwrap
import unicodedata
from typing import Any, Iterable
from urllib.parse import urlparse

from PyPDF2 import PdfReader

SOURCE_FIELDS = (
    "titulo",
    "autor",
    "data",
    "categoria",
    "conteudo_texto",
    "url",
)
SOURCE_NAME_PATTERN = re.compile(r"^(usp_news_(\d{6}))\.json$")
GENERATOR_NAME = "USP Data Lake - PDF Generator"
GENERATOR_VERSION = "usp-data-lake-pdf-generator/1.0"
MAX_LINES_PER_PAGE = 52
LINE_WIDTH = 92
SYMBOL_ENCODING = {"≈": 187}

_INVISIBLE_CHARACTERS = dict.fromkeys(
    map(ord, ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff")),
    None,
)
_TEXT_REPLACEMENTS = str.maketrans(
    {
        "\u00a0": " ",
        "\u202f": " ",
        "\ufb01": "fi",
    }
)


class PDFGeneratorError(RuntimeError):
    """Erro controlado durante geração ou validação de PDF."""


class SourceValidationError(PDFGeneratorError, ValueError):
    """O JSON-fonte ou sua identidade não atende ao contrato."""


class PDFValidationError(PDFGeneratorError, ValueError):
    """O PDF não corresponde ao JSON-fonte."""


@dataclass(frozen=True)
class CanonicalIdentity:
    """Identidade estável extraída do nome do JSON Bronze."""

    canonical_id: str
    source_index: str
    source_json: str
    source_pdf: str


@dataclass(frozen=True)
class PDFValidationResult:
    """Resultado verificável da validação de um PDF."""

    pdf_path: Path
    source_hash: str
    size_bytes: int
    page_count: int
    metadata: dict[str, str]
    extracted_text_chars: int


@dataclass(frozen=True)
class PDFGenerationResult:
    """Resultado da geração ou reutilização idempotente."""

    status: str
    pdf_path: Path
    identity: CanonicalIdentity
    validation: PDFValidationResult


@dataclass(frozen=True)
class PDFBatchResult:
    """Resultado de uma geração preparada integralmente antes da publicação."""

    generated: tuple[PDFGenerationResult, ...]


def extract_canonical_identity(source_path: str | Path) -> CanonicalIdentity:
    """Extrai a identidade canônica de ``usp_news_NNNNNN.json``."""
    filename = Path(source_path).name
    match = SOURCE_NAME_PATTERN.fullmatch(filename)
    if match is None:
        raise SourceValidationError(
            "Nome de JSON inválido; esperado usp_news_NNNNNN.json: "
            f"{filename!r}"
        )

    canonical_id, source_index = match.groups()
    return CanonicalIdentity(
        canonical_id=canonical_id,
        source_index=source_index,
        source_json=filename,
        source_pdf=f"{canonical_id}.pdf",
    )


def _validate_source_payload(payload: Any, source_path: Path) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise SourceValidationError(
            f"O JSON deve conter um objeto: {source_path}"
        )

    missing = [field for field in SOURCE_FIELDS if field not in payload]
    if missing:
        raise SourceValidationError(
            f"Campos ausentes em {source_path.name}: {', '.join(missing)}"
        )

    normalized: dict[str, str] = {}
    for field in SOURCE_FIELDS:
        value = payload[field]
        if not isinstance(value, str):
            raise SourceValidationError(
                f"O campo {field!r} deve ser string em {source_path.name}"
            )
        normalized[field] = value

    if not normalized["titulo"].strip():
        raise SourceValidationError(
            f"O campo 'titulo' não pode ser vazio em {source_path.name}"
        )
    if not normalized["conteudo_texto"].strip():
        raise SourceValidationError(
            f"O campo 'conteudo_texto' não pode ser vazio em {source_path.name}"
        )

    url = normalized["url"].strip()
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise SourceValidationError(
                f"URL inválida em {source_path.name}: {url!r}"
            )
    normalized["url"] = url
    return normalized


def load_source_json(source_path: str | Path) -> dict[str, str]:
    """Lê e valida um único JSON do corpus, sem modificar sua origem."""
    path = Path(source_path)
    extract_canonical_identity(path)
    if not path.is_file():
        raise SourceValidationError(f"JSON-fonte não encontrado: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as error:
        raise SourceValidationError(
            f"JSON-fonte não está codificado em UTF-8: {path}"
        ) from error
    except json.JSONDecodeError as error:
        raise SourceValidationError(
            f"JSON inválido em {path}: linha {error.lineno}, coluna {error.colno}"
        ) from error

    return _validate_source_payload(payload, path)


def calculate_source_hash(payload: dict[str, Any]) -> str:
    """Calcula SHA-256 da representação canônica dos seis campos-fonte."""
    canonical_payload: dict[str, str] = {}
    for field in SOURCE_FIELDS:
        if field not in payload:
            raise SourceValidationError(
                f"Não é possível calcular o hash: campo ausente {field!r}"
            )
        value = payload[field]
        if not isinstance(value, str):
            raise SourceValidationError(
                f"Não é possível calcular o hash: {field!r} deve ser string"
            )
        canonical_payload[field] = value

    serialized = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def normalize_text(value: str, *, field_name: str = "texto") -> str:
    """Normaliza texto e rejeita caracteres sem representação no renderer."""
    if not isinstance(value, str):
        raise SourceValidationError(f"O campo {field_name!r} deve ser string")

    text = unicodedata.normalize("NFC", value)
    text = text.translate(_INVISIBLE_CHARACTERS)
    text = text.translate(_TEXT_REPLACEMENTS)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    try:
        text.translate(str.maketrans({character: "" for character in SYMBOL_ENCODING})).encode(
            "cp1252"
        )
    except UnicodeEncodeError:
        for character in text:
            if character in SYMBOL_ENCODING:
                continue
            try:
                character.encode("cp1252")
            except UnicodeEncodeError as error:
                raise SourceValidationError(
                    "Geração interrompida para preservar o conteúdo: "
                    "o renderer PDF não representa o caractere "
                    f"{character!r} (U+{ord(character):04X}) "
                    f"no campo {field_name!r}. "
                    "Nenhum PDF será gerado e o texto de origem não será alterado."
                ) from error
        raise
    return text


def _wrap_visible_lines(lines: list[str]) -> list[str]:
    wrapped: list[str] = []
    for logical_line in lines:
        line = normalize_text(logical_line, field_name="conteudo_visivel")
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(
            textwrap.wrap(
                line,
                width=LINE_WIDTH,
                replace_whitespace=False,
                drop_whitespace=True,
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [""]
        )
    return wrapped


def _pdf_literal(value: str, *, field_name: str) -> bytes:
    normalized = normalize_text(value, field_name=field_name)
    try:
        encoded = normalized.encode("cp1252")
    except UnicodeEncodeError as error:
        raise SourceValidationError(
            f"Falha ao codificar o campo {field_name!r} para o PDF"
        ) from error
    return (
        encoded.replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
    )


def _pdf_line_commands(value: str) -> list[bytes]:
    """Codifica uma linha alternando WinAnsi e Symbol sem substituir Unicode."""
    normalized = normalize_text(value, field_name="conteudo_visivel")
    commands = [b"/F1 10 Tf"]
    winansi_buffer: list[str] = []

    def flush_winansi() -> None:
        if not winansi_buffer:
            return
        commands.append(
            b"("
            + _pdf_literal(
                "".join(winansi_buffer),
                field_name="conteudo_visivel",
            )
            + b") Tj"
        )
        winansi_buffer.clear()

    index = 0
    while index < len(normalized):
        character = normalized[index]
        symbol_code = SYMBOL_ENCODING.get(character)
        if symbol_code is None:
            winansi_buffer.append(character)
            index += 1
            continue
        symbol_bytes = bytearray()
        if winansi_buffer and winansi_buffer[-1] == " ":
            winansi_buffer.pop()
            symbol_bytes.append(32)
        flush_winansi()
        symbol_bytes.append(symbol_code)
        if index + 1 < len(normalized) and normalized[index + 1] == " ":
            symbol_bytes.append(32)
            index += 1
        commands.extend(
            (
                b"/F2 10 Tf",
                b"<" + bytes(symbol_bytes).hex().upper().encode("ascii") + b"> Tj",
                b"/F1 10 Tf",
            )
        )
        index += 1
    flush_winansi()
    commands.append(b"T*")
    return commands


def _pdf_metadata_string(value: str) -> bytes:
    encoded = b"\xfe\xff" + value.encode("utf-16-be")
    return b"<" + encoded.hex().upper().encode("ascii") + b">"


def _metadata_keywords(identity: CanonicalIdentity, source_hash: str) -> str:
    return (
        f"Canonical-ID={identity.canonical_id};"
        f"Source-JSON={identity.source_json};"
        f"Source-SHA256={source_hash};"
        "Source-Format=json;"
        "Corpus=Jornal-USP-PoC"
    )


def _visible_document_lines(payload: dict[str, str]) -> list[str]:
    title = normalize_text(payload["titulo"], field_name="titulo")
    content = normalize_text(
        payload["conteudo_texto"],
        field_name="conteudo_texto",
    )
    if not content:
        raise SourceValidationError("Conteúdo sem texto útil no JSON-fonte")

    author = normalize_text(payload["autor"], field_name="autor")
    date = normalize_text(payload["data"], field_name="data")
    category = normalize_text(payload["categoria"], field_name="categoria")
    url = normalize_text(payload["url"], field_name="url")

    lines = [
        title,
        "",
        f"Autor: {author or 'Não informado'}",
        f"Data: {date or 'Não informada'}",
        f"Categoria: {category or 'Não informada'}",
        f"URL original: {url or 'Não informada'}",
        "",
    ]
    lines.extend(content.splitlines())
    return _wrap_visible_lines(lines)


def _build_pdf_bytes(
    payload: dict[str, str],
    identity: CanonicalIdentity,
    source_hash: str,
) -> bytes:
    lines = _visible_document_lines(payload)
    pages = [
        lines[index : index + MAX_LINES_PER_PAGE]
        for index in range(0, len(lines), MAX_LINES_PER_PAGE)
    ] or [[]]

    font_id = 3 + 2 * len(pages)
    symbol_font_id = font_id + 1
    info_id = font_id + 2
    page_ids = [3 + 2 * index for index in range(len(pages))]
    title = normalize_text(payload["titulo"], field_name="titulo")
    author = normalize_text(payload["autor"], field_name="autor")
    subject = f"Source-URL: {normalize_text(payload['url'], field_name='url')}"
    keywords = _metadata_keywords(identity, source_hash)

    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            b"<< /Type /Pages /Count "
            + str(len(pages)).encode("ascii")
            + b" /Kids ["
            + b" ".join(f"{page_id} 0 R".encode("ascii") for page_id in page_ids)
            + b"] >>"
        ),
        font_id: (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
        symbol_font_id: (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Symbol >>"
        ),
        info_id: (
            b"<< /Title "
            + _pdf_metadata_string(title)
            + b" /Author "
            + _pdf_metadata_string(author)
            + b" /Subject "
            + _pdf_metadata_string(subject)
            + b" /Creator "
            + _pdf_metadata_string(GENERATOR_NAME)
            + b" /Producer "
            + _pdf_metadata_string(GENERATOR_VERSION)
            + b" /Keywords "
            + _pdf_metadata_string(keywords)
            + b" >>"
        ),
    }

    for index, page_lines in enumerate(pages):
        page_id = page_ids[index]
        content_id = page_id + 1
        commands = [b"BT /F1 10 Tf 50 790 Td 13 TL"]
        for line in page_lines:
            commands.extend(_pdf_line_commands(line))
        commands.append(b"ET")
        stream = b"\n".join(commands)
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_id} 0 R "
            f"/F2 {symbol_font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")
        objects[content_id] = (
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id in range(1, info_id + 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")

    xref = len(output)
    output.extend(f"xref\n0 {info_id + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {info_id + 1} /Root 1 0 R "
            f"/Info {info_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def _metadata_as_strings(reader: PdfReader) -> dict[str, str]:
    metadata = reader.metadata or {}
    return {
        str(key): "" if value is None else str(value)
        for key, value in metadata.items()
    }


def _validate_pdf(
    pdf_path: Path,
    source_path: Path,
    *,
    require_canonical_filename: bool,
) -> PDFValidationResult:
    identity = extract_canonical_identity(source_path)
    payload = load_source_json(source_path)
    source_hash = calculate_source_hash(payload)

    if require_canonical_filename and pdf_path.name != identity.source_pdf:
        raise PDFValidationError(
            f"Nome de PDF divergente; esperado {identity.source_pdf!r}: "
            f"{pdf_path.name!r}"
        )
    if not pdf_path.is_file():
        raise PDFValidationError(f"PDF não encontrado: {pdf_path}")
    size_bytes = pdf_path.stat().st_size
    if size_bytes <= 0:
        raise PDFValidationError(f"PDF vazio: {pdf_path}")
    if pdf_path.read_bytes()[:5] != b"%PDF-":
        raise PDFValidationError(f"Assinatura PDF inválida: {pdf_path}")

    try:
        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
        extracted_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        metadata = _metadata_as_strings(reader)
    except Exception as error:
        raise PDFValidationError(f"Não foi possível abrir o PDF: {pdf_path}") from error

    if page_count < 1:
        raise PDFValidationError(f"PDF sem páginas: {pdf_path}")
    if not extracted_text.strip():
        raise PDFValidationError(f"PDF sem texto extraível: {pdf_path}")

    expected_metadata = {
        "/Title": normalize_text(payload["titulo"], field_name="titulo"),
        "/Author": normalize_text(payload["autor"], field_name="autor"),
        "/Subject": f"Source-URL: {normalize_text(payload['url'], field_name='url')}",
        "/Creator": GENERATOR_NAME,
        "/Producer": GENERATOR_VERSION,
        "/Keywords": _metadata_keywords(identity, source_hash),
    }
    for key, expected in expected_metadata.items():
        if metadata.get(key) != expected:
            raise PDFValidationError(
                f"Metadado {key} divergente em {pdf_path.name}: "
                f"esperado {expected!r}, obtido {metadata.get(key)!r}"
            )

    compact_extracted_text = re.sub(r"\s+", "", extracted_text)
    visible_expectations = (
        normalize_text(payload["titulo"], field_name="titulo"),
    )
    for expected in visible_expectations:
        if expected and re.sub(r"\s+", "", expected) not in compact_extracted_text:
            raise PDFValidationError(
                f"Conteúdo obrigatório ausente no PDF: {expected!r}"
            )

    expected_url = normalize_text(payload["url"], field_name="url")
    if expected_url and re.sub(r"\s+", "", expected_url) not in compact_extracted_text:
        raise PDFValidationError(
            f"URL obrigatória ausente no PDF: {expected_url!r}"
        )

    return PDFValidationResult(
        pdf_path=pdf_path,
        source_hash=source_hash,
        size_bytes=size_bytes,
        page_count=page_count,
        metadata=metadata,
        extracted_text_chars=len(extracted_text),
    )


def validate_pdf_against_json(
    pdf_path: str | Path,
    source_path: str | Path,
) -> PDFValidationResult:
    """Valida assinatura, texto, identidade, metadados e hash do par."""
    return _validate_pdf(
        Path(pdf_path),
        Path(source_path),
        require_canonical_filename=True,
    )


def generate_pdf_from_json(
    source_path: str | Path,
    destination_path: str | Path | None = None,
    *,
    regenerate: bool = False,
) -> PDFGenerationResult:
    """Gera atomicamente um PDF ou reutiliza um par já válido."""
    source = Path(source_path)
    identity = extract_canonical_identity(source)
    payload = load_source_json(source)
    source_hash = calculate_source_hash(payload)
    destination = (
        Path(destination_path)
        if destination_path is not None
        else source.with_suffix(".pdf")
    )

    if destination.name != identity.source_pdf:
        raise SourceValidationError(
            f"O único nome permitido para o PDF é {identity.source_pdf!r}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() and not regenerate:
        try:
            validation = validate_pdf_against_json(destination, source)
        except PDFValidationError as error:
            raise FileExistsError(
                f"O PDF existente não corresponde ao JSON e não será sobrescrito: "
                f"{destination}. Use regenerate=True após revisar o conflito."
            ) from error
        return PDFGenerationResult(
            status="unchanged",
            pdf_path=destination,
            identity=identity,
            validation=validation,
        )

    pdf_bytes = _build_pdf_bytes(payload, identity, source_hash)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{identity.canonical_id}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary.write(pdf_bytes)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)

        _validate_pdf(
            temporary_path,
            source,
            require_canonical_filename=False,
        )
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    validation = validate_pdf_against_json(destination, source)
    return PDFGenerationResult(
        status="regenerated" if regenerate else "generated",
        pdf_path=destination,
        identity=identity,
        validation=validation,
    )


def generate_pdf_batch(
    source_paths: Iterable[str | Path],
    destination_directory: str | Path,
) -> PDFBatchResult:
    """Prepara e valida todo o lote antes de publicar, com rollback em falha."""
    sources = [Path(source) for source in source_paths]
    destination = Path(destination_directory)
    identities = [extract_canonical_identity(source) for source in sources]
    names = [identity.source_pdf for identity in identities]
    if len(names) != len(set(names)):
        raise SourceValidationError("O lote contém identidades PDF duplicadas")

    destination.mkdir(parents=True, exist_ok=True)
    published: list[Path] = []
    backups: dict[Path, Path] = {}
    with tempfile.TemporaryDirectory(
        prefix=".pdf-corpus-stage-",
        dir=destination.parent,
    ) as stage_name, tempfile.TemporaryDirectory(
        prefix=".pdf-corpus-backup-",
        dir=destination.parent,
    ) as backup_name:
        stage = Path(stage_name)
        backup = Path(backup_name)
        prepared: list[tuple[Path, CanonicalIdentity, PDFValidationResult]] = []
        for source, identity in zip(sources, identities):
            staged_path = stage / identity.source_pdf
            result = generate_pdf_from_json(source, staged_path)
            prepared.append((source, identity, result.validation))

        try:
            for source, identity, _ in prepared:
                staged_path = stage / identity.source_pdf
                final_path = destination / identity.source_pdf
                if final_path.exists() and final_path.read_bytes() == staged_path.read_bytes():
                    continue
                if final_path.exists():
                    backup_path = backup / identity.source_pdf
                    os.replace(final_path, backup_path)
                    backups[final_path] = backup_path
                os.replace(staged_path, final_path)
                published.append(final_path)
        except Exception:
            for final_path in reversed(published):
                final_path.unlink(missing_ok=True)
            for final_path, backup_path in backups.items():
                if backup_path.exists():
                    os.replace(backup_path, final_path)
            raise

        results: list[PDFGenerationResult] = []
        for source, identity, _ in prepared:
            final_path = destination / identity.source_pdf
            validation = validate_pdf_against_json(final_path, source)
            if final_path in backups:
                status = "regenerated"
            elif final_path in published:
                status = "generated"
            else:
                status = "unchanged"
            results.append(
                PDFGenerationResult(
                    status=status,
                    pdf_path=final_path,
                    identity=identity,
                    validation=validation,
                )
            )
    return PDFBatchResult(tuple(results))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera um único PDF offline a partir de um JSON Bronze."
    )
    parser.add_argument("source_json", type=Path)
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Regenera explicitamente o PDF canônico já existente.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = generate_pdf_from_json(
        args.source_json,
        regenerate=args.regenerate,
    )
    print(
        json.dumps(
            {
                "status": result.status,
                "pdf": str(result.pdf_path),
                "canonical_id": result.identity.canonical_id,
                "source_hash": result.validation.source_hash,
                "size_bytes": result.validation.size_bytes,
                "page_count": result.validation.page_count,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
