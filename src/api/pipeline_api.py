"""
Pipeline API: process Bronze data into Silver (chunks) and Gold (embeddings).
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.embedding import BGEM3Embedder
from src.minio_client import get_pdf_prefix
from src.postgres_loader import insert_chunks, resolve_document_id_collisions
from src.qdrant_loader import upsert_embeddings
from src.transform import run_transform

app = FastAPI(
    title="USP Data Lake - Pipeline API",
    description="Aplicacao para processar dados Bronze em Silver e Gold.",
    version="1.0.0",
)


class ProcessRequest(BaseModel):
    source: str = Field(
        default="minio",
        pattern="^(minio|local)$",
        description="Origem: 'minio' ou 'local'",
    )
    limit: int | None = Field(default=None, ge=1, description="Limite de documentos")
    load_postgres: bool = Field(default=True, description="Carregar no PostgreSQL")
    load_qdrant: bool = Field(default=True, description="Carregar no Qdrant")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "pipeline-api"}


def _run_pipeline(
    request: ProcessRequest,
    extensions: set[str],
    prefix: str = "raw/",
) -> dict:
    try:
        # 1. Transform (Bronze -> Silver)
        records = run_transform(
            source=request.source,
            limit=request.limit,
            extensions=extensions,
            prefix=prefix,
        )
        if not records:
            return {"message": "Nenhum documento novo para processar."}

        postgres_count = 0
        postgres_new_count = 0
        identity_collisions: list[dict] = []
        if request.load_postgres:
            records, identity_collisions = resolve_document_id_collisions(records)
            # 2. Load text chunks to PostgreSQL (Silver -> Gold Text)
            records_with_ids = insert_chunks(records)
            postgres_count = len(records_with_ids)
            postgres_new_count = sum(
                1 for record in records_with_ids if record.get("_inserted", True)
            )
            # Use records with postgres IDs for Qdrant
            records = records_with_ids

        qdrant_count = 0
        qdrant_new_count = 0
        if request.load_qdrant:
            # 3. Create embeddings and load to Qdrant (Gold Vectors)
            embedder = BGEM3Embedder()
            embeddings = embedder.encode_texts(
                (record["texto"] for record in records),
            )
            qdrant_count = upsert_embeddings(records, embeddings)
            qdrant_new_count = postgres_new_count

        already_processed = bool(request.load_postgres and postgres_new_count == 0)
        return {
            "message": (
                "Documento reprocessado de forma idempotente; nenhum item novo criado."
                if already_processed
                else "Pipeline executado com sucesso."
            ),
            "documentos_processados": len(
                {record["documento_id"] for record in records}
            ),
            "chunks_gerados": len(records),
            "chunks_carregados_postgres": postgres_count,
            "chunks_novos_postgres": postgres_new_count,
            "vetores_carregados_qdrant": qdrant_count,
            "vetores_novos_qdrant": qdrant_new_count,
            "caracteres_processados": sum(len(record["texto"]) for record in records),
            "objetos_processados": sorted({record["source_object"] for record in records}),
            "modo_persistencia": bool(request.load_postgres or request.load_qdrant),
            "documentos_remapeados": identity_collisions,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/processar-site")
def processar_site(request: ProcessRequest) -> dict:
    """
    Processa arquivos JSON (notícias de site) da camada Bronze para Gold.
    """
    return _run_pipeline(request, extensions={"json"})


@app.post("/site", deprecated=True)
def processar_site_alias(request: ProcessRequest) -> dict:
    """Alias compatível de /processar-site."""
    return processar_site(request)


@app.post("/processar-pdf")
def processar_pdf(request: ProcessRequest) -> dict:
    """
    Processa arquivos PDF da camada Bronze para Gold.
    """
    return _run_pipeline(request, extensions={"pdf"}, prefix=get_pdf_prefix())


@app.post("/pdf", deprecated=True)
def processar_pdf_alias(request: ProcessRequest) -> dict:
    """Alias compatível de /processar-pdf."""
    return processar_pdf(request)
