"""Fronteira explícita entre a transformação Silver e a Golden existente."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.chunking import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP, criar_chunks
from src.silver import SilverResult


def silver_to_golden_chunks(
    result: SilverResult,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[dict[str, Any]]:
    """Converte um documento Silver aprovado em registros de chunk da Golden."""
    if not result.promotable_to_golden:
        issues = ", ".join(result.quality_issues) or "quality_gate_rejected"
        raise ValueError(f"SilverResult não promovível para Golden: {issues}")

    document = result.document
    primary = next(
        (
            source
            for source in document.sources
            if source.source_type == document.primary_source
        ),
        document.sources[0] if document.sources else None,
    )
    source_object = primary.object_name if primary is not None else None
    source_objects = tuple(source.object_name for source in document.sources)
    sources = tuple(asdict(source) for source in document.sources)

    return [
        {
            "documento_id": document.document_id,
            "chunk_id": chunk_id,
            "texto": text,
            "titulo": document.title,
            "autor": document.author,
            "data_publicacao": document.published_at,
            "categoria": document.category,
            "url": document.url,
            "source_object": source_object,
            "source_type": document.primary_source,
            "source_objects": source_objects,
            "sources": sources,
            "lineage_id": document.lineage_id,
            "canonical_sha256": document.canonical_sha256,
            "schema_version": document.schema_version,
            "chunk_size": chunk_size,
            "overlap": overlap,
        }
        for chunk_id, text in enumerate(
            criar_chunks(
                document.text,
                chunk_size=chunk_size,
                overlap=overlap,
            ),
            start=1,
        )
    ]
