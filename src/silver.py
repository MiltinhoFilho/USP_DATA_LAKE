"""Etapa Silver de transformação.

Este módulo não representa uma camada persistida. Ele transforma documentos da
camada Bronze em documentos canônicos elegíveis para promoção à camada Golden.

A transformação é determinística, não persiste Golden, não cria chunks e não
acessa serviços externos.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

from PyPDF2 import PdfReader

from src.pdf_generator import (
    GENERATOR_NAME,
    calculate_source_hash,
    extract_canonical_identity,
    load_source_json,
)
from src.transform import limpar_html_para_markdown, montar_texto_limpo


SILVER_SCHEMA_VERSION = "1.0"
MINOR_TEXT_SIMILARITY = 0.98
KNOWN_BOILERPLATES = (
    "pular barra de compartilhamento",
    "no ar veiculado pela rede usp de rádio",
)
INVISIBLE_FORMAT_CHARACTERS = {
    "\u200b",
    "\u200c",
    "\u200d",
    "\u2060",
    "\ufeff",
}


@dataclass(frozen=True)
class SourceReference:
    source_type: str
    object_name: str
    binary_sha256: str
    source_content_sha256: str | None = None


@dataclass(frozen=True)
class DivergenceReport:
    classification: str
    text_similarity: float
    length_difference: int
    length_ratio: float
    source_hash_match: bool | None
    metadata_differences: tuple[str, ...] = ()
    structural_differences: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalDocument:
    schema_version: str
    document_id: str
    lineage_id: str
    title: str
    author: str
    published_at: str
    category: str
    url: str
    text: str
    canonical_sha256: str
    primary_source: str
    sources: tuple[SourceReference, ...]
    transformations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SilverResult:
    document: CanonicalDocument
    promotable_to_golden: bool
    quality_issues: tuple[str, ...] = ()
    divergence: DivergenceReport | None = None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _semantic_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = "".join(
        character
        for character in value
        if character not in INVISIBLE_FORMAT_CHARACTERS
    )
    return re.sub(r"\s+", " ", value).strip()


def _remove_invisible_format_characters(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return "".join(
        character
        for character in value
        if character not in INVISIBLE_FORMAT_CHARACTERS
    )


def _remove_generated_pdf_header(
    extracted: str,
    metadata: dict[str, str],
    title: str,
    url: str,
) -> str:
    """Remove somente o cabeçalho conhecido dos PDFs produzidos pelo projeto."""
    if metadata.get("/Creator") != GENERATOR_NAME:
        return extracted

    lines = extracted.splitlines()
    if lines and _semantic_text(lines[0]).casefold() == (
        "jornal da usp — recorte acadêmico"
    ).casefold():
        lines.pop(0)

    title_key = _semantic_text(title).casefold()
    title_index = next(
        (
            index
            for index, line in enumerate(lines[:4])
            if _semantic_text(line).casefold() == title_key
        ),
        None,
    )
    if title_index is None:
        return "\n".join(lines).strip()

    index = title_index + 1
    while index < len(lines) and re.match(
        r"^\s*(Autor|Data|Categoria)\s*:",
        lines[index],
        flags=re.IGNORECASE,
    ):
        lines.pop(index)

    if index < len(lines) and re.match(
        r"^\s*URL original\s*:",
        lines[index],
        flags=re.IGNORECASE,
    ):
        first_url_part = lines.pop(index).split(":", 1)[1].strip()
        collected_url = first_url_part
        expected_url = re.sub(r"\s+", "", url)
        while (
            index < len(lines)
            and expected_url
            and re.sub(r"\s+", "", collected_url) != expected_url
        ):
            candidate = collected_url + lines[index].strip()
            if not expected_url.startswith(re.sub(r"\s+", "", candidate)):
                break
            collected_url = candidate
            lines.pop(index)

    return "\n".join(lines).strip()


def _paragraph_key(value: str) -> str:
    value = re.sub(r"^#{1,6}\s+", "", value.strip())
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"[*_`]+", "", value)
    return _semantic_text(value).casefold()


def deduplicate_exact_blocks(text: str) -> tuple[str, int]:
    """Remove blocos Markdown exatamente repetidos, preservando a primeira posição."""
    blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
    seen: set[str] = set()
    selected: list[str] = []
    removed = 0
    for block in blocks:
        key = _paragraph_key(block)
        if key and key in seen:
            removed += 1
            continue
        if key:
            seen.add(key)
        selected.append(block)
    return "\n\n".join(selected), removed


def _parse_pdf_keywords(value: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in value.split(";"):
        key, separator, content = item.partition("=")
        if separator and key.strip():
            parsed[key.strip()] = content.strip()
    return parsed


def _canonical_payload(
    *,
    document_id: str,
    title: str,
    author: str,
    published_at: str,
    category: str,
    url: str,
    text: str,
) -> dict[str, str]:
    return {
        "document_id": document_id,
        "title": title,
        "author": author,
        "published_at": published_at,
        "category": category,
        "url": url,
        "text": text,
    }


def _canonical_hash(payload: dict[str, str]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(serialized)


def _lineage_id(document_id: str, canonical_hash: str) -> str:
    return f"silver:{document_id}:{canonical_hash[:16]}"


def _quality_issues(payload: dict[str, str]) -> tuple[str, ...]:
    issues: list[str] = []
    for field_name in ("document_id", "title", "published_at", "category", "url", "text"):
        if not payload[field_name].strip():
            issues.append(f"missing_{field_name}")
    parsed_url = urlparse(payload["url"])
    if payload["url"] and (
        parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc
    ):
        issues.append("invalid_url")
    lowered = payload["text"].casefold()
    if any(boilerplate in lowered for boilerplate in KNOWN_BOILERPLATES):
        issues.append("known_boilerplate")
    if "\ufffd" in payload["text"]:
        issues.append("unicode_replacement_character")
    if any(
        unicodedata.category(character) == "Cc" and character not in "\n\t"
        for character in payload["text"]
    ):
        issues.append("invalid_control_character")
    return tuple(dict.fromkeys(issues))


def _build_document(
    payload: dict[str, str],
    *,
    primary_source: str,
    sources: tuple[SourceReference, ...],
    transformations: tuple[str, ...],
) -> CanonicalDocument:
    canonical_hash = _canonical_hash(payload)
    return CanonicalDocument(
        schema_version=SILVER_SCHEMA_VERSION,
        document_id=payload["document_id"],
        lineage_id=_lineage_id(payload["document_id"], canonical_hash),
        title=payload["title"],
        author=payload["author"],
        published_at=payload["published_at"],
        category=payload["category"],
        url=payload["url"],
        text=payload["text"],
        canonical_sha256=canonical_hash,
        primary_source=primary_source,
        sources=sources,
        transformations=transformations,
    )


def transform_json(source_path: str | Path) -> SilverResult:
    path = Path(source_path)
    article = load_source_json(path)
    identity = extract_canonical_identity(path)
    cleaned = montar_texto_limpo(article)
    text, duplicate_blocks = deduplicate_exact_blocks(cleaned)
    text = _remove_invisible_format_characters(text)
    payload = _canonical_payload(
        document_id=identity.canonical_id,
        title=_semantic_text(article["titulo"]),
        author=_semantic_text(article["autor"]),
        published_at=_semantic_text(article["data"]),
        category=_semantic_text(article["categoria"]),
        url=article["url"].strip(),
        text=text,
    )
    source = SourceReference(
        source_type="json",
        object_name=path.name,
        binary_sha256=_sha256_bytes(path.read_bytes()),
        source_content_sha256=calculate_source_hash(article),
    )
    transformations = [
        "html_to_markdown",
        "remove_confirmed_boilerplates",
        "normalize_unicode_nfkc",
        "remove_invisible_format_characters",
        "avoid_leading_title_duplication",
    ]
    if duplicate_blocks:
        transformations.append(f"deduplicate_exact_blocks:{duplicate_blocks}")
    issues = _quality_issues(payload)
    document = _build_document(
        payload,
        primary_source="json",
        sources=(source,),
        transformations=tuple(transformations),
    )
    return SilverResult(document, not issues, issues)


def transform_pdf(source_path: str | Path) -> SilverResult:
    path = Path(source_path)
    raw_bytes = path.read_bytes()
    reader = PdfReader(str(path))
    metadata = {str(key): str(value or "") for key, value in (reader.metadata or {}).items()}
    title = _semantic_text(metadata.get("/Title", "") or path.stem.replace("_", " ").title())
    author = _semantic_text(metadata.get("/Author", ""))
    subject = metadata.get("/Subject", "")
    url = subject.removeprefix("Source-URL: ").strip() if subject.startswith("Source-URL: ") else ""
    extracted = "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
    extracted_fields: dict[str, str] = {}
    for line in extracted.splitlines()[:12]:
        label, separator, value = line.partition(":")
        if separator and label.strip() in {"Autor", "Data", "Categoria"}:
            extracted_fields[label.strip()] = value.strip()
    extracted_author = extracted_fields.get("Autor", "")
    if extracted_author.casefold() == "não informado":
        extracted_author = ""
    if not author:
        author = _semantic_text(extracted_author)
    extracted = _remove_generated_pdf_header(extracted, metadata, title, url)
    text, duplicate_blocks = deduplicate_exact_blocks(extracted)
    text = _remove_invisible_format_characters(text)
    keywords = _parse_pdf_keywords(metadata.get("/Keywords", ""))
    document_id = keywords.get("Canonical-ID") or f"pdf_{path.stem}"
    payload = _canonical_payload(
        document_id=document_id,
        title=title,
        author=author,
        published_at=_semantic_text(extracted_fields.get("Data", "")),
        category=_semantic_text(extracted_fields.get("Categoria", "")),
        url=url,
        text=text,
    )
    source = SourceReference(
        source_type="pdf",
        object_name=path.name,
        binary_sha256=_sha256_bytes(raw_bytes),
        source_content_sha256=keywords.get("Source-SHA256") or None,
    )
    transformations = ["extract_pdf_text", "normalize_unicode_nfkc"]
    if duplicate_blocks:
        transformations.append(f"deduplicate_exact_blocks:{duplicate_blocks}")
    issues = list(_quality_issues(payload))
    if not keywords.get("Canonical-ID"):
        issues.append("pdf_without_canonical_identity")
    if not keywords.get("Source-SHA256"):
        issues.append("pdf_without_source_hash")
    issues.append("pdf_requires_json_authority")
    issues = list(dict.fromkeys(issues))
    document = _build_document(
        payload,
        primary_source="pdf",
        sources=(source,),
        transformations=tuple(transformations),
    )
    # PDF isolado é fallback auditável; não é promovido sem os metadados do JSON.
    return SilverResult(document, False, tuple(issues))


def compare_json_pdf(
    json_result: SilverResult,
    pdf_result: SilverResult,
) -> DivergenceReport:
    json_document = json_result.document
    pdf_document = pdf_result.document
    json_text = _semantic_text(json_document.text)
    pdf_text = _semantic_text(pdf_document.text)
    similarity = SequenceMatcher(None, json_text, pdf_text, autojunk=False).ratio()
    maximum_length = max(len(json_text), len(pdf_text), 1)
    length_difference = len(pdf_text) - len(json_text)
    length_ratio = min(len(json_text), len(pdf_text)) / maximum_length

    metadata_differences = []
    for field_name in ("title", "author", "published_at", "category", "url"):
        if _semantic_text(getattr(json_document, field_name)) != _semantic_text(
            getattr(pdf_document, field_name)
        ):
            metadata_differences.append(field_name)

    pdf_source_hash = pdf_document.sources[0].source_content_sha256
    json_source_hash = json_document.sources[0].source_content_sha256
    source_hash_match = (
        pdf_source_hash == json_source_hash if pdf_source_hash else None
    )
    structural_differences = []
    if json_document.document_id != pdf_document.document_id:
        structural_differences.append("document_id")
    if abs(length_difference) > max(200, int(len(json_text) * 0.02)):
        structural_differences.append("text_length")

    if source_hash_match is True and not metadata_differences:
        classification = "equivalent"
    elif (
        source_hash_match is not False
        and similarity >= MINOR_TEXT_SIMILARITY
        and not metadata_differences
    ):
        classification = "minor"
    else:
        classification = "major"
    return DivergenceReport(
        classification=classification,
        text_similarity=round(similarity, 6),
        length_difference=length_difference,
        length_ratio=round(length_ratio, 6),
        source_hash_match=source_hash_match,
        metadata_differences=tuple(metadata_differences),
        structural_differences=tuple(structural_differences),
    )


def reconcile_sources(
    json_path: str | Path,
    pdf_path: str | Path | None = None,
) -> SilverResult:
    """Reconcilia fontes sem persistir: JSON sempre possui precedência editorial."""
    json_result = transform_json(json_path)
    if pdf_path is None:
        return json_result

    pdf_result = transform_pdf(pdf_path)
    divergence = compare_json_pdf(json_result, pdf_result)
    document = json_result.document
    merged_document = CanonicalDocument(
        **{
            **document.to_dict(),
            "sources": document.sources + pdf_result.document.sources,
            "transformations": document.transformations + ("validate_against_pdf",),
        }
    )
    issues = list(json_result.quality_issues)
    if divergence.classification == "major":
        issues.append("major_json_pdf_divergence")
    return SilverResult(
        document=merged_document,
        promotable_to_golden=not issues,
        quality_issues=tuple(dict.fromkeys(issues)),
        divergence=divergence,
    )
