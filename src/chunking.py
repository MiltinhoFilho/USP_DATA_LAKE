"""Text chunking utilities for the transformation pipeline."""

from __future__ import annotations


DEFAULT_CHUNK_SIZE = 1200
DEFAULT_OVERLAP = 200


def criar_chunks(
    texto: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """Split text into fixed-size chunks with character overlap."""
    if chunk_size <= 0:
        raise ValueError("chunk_size deve ser maior que zero")
    if overlap < 0:
        raise ValueError("overlap nao pode ser negativo")
    if overlap >= chunk_size:
        raise ValueError("overlap deve ser menor que chunk_size")

    texto = texto.strip()
    if not texto:
        return []

    chunks: list[str] = []
    inicio = 0
    passo = chunk_size - overlap

    while inicio < len(texto):
        fim = inicio + chunk_size
        chunk = texto[inicio:fim].strip()
        if chunk:
            chunks.append(chunk)
        if fim >= len(texto):
            break
        inicio += passo

    return chunks
