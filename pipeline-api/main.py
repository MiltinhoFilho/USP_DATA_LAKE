"""
Pipeline API: process Bronze data into Silver (chunks) and Gold (embeddings).
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from embedding import BGEM3Embedder
from postgres_loader import insert_chunks
from qdrant_loader import upsert_embeddings
from transform import run_transform

app = FastAPI(
    title="USP Data Lake - Pipeline API",
    description="Aplicacao para processar dados Bronze em Silver e Gold.",
    version="1.0.0",
)


class ProcessRequest(BaseModel):
    source: str = Field(default="minio", description="Origem: 'minio' ou 'local'")
    limit: int | None = Field(default=None, description="Limite de documentos")
    load_postgres: bool = Field(default=True, description="Carregar no PostgreSQL")
    load_qdrant: bool = Field(default=True, description="Carregar no Qdrant")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "pipeline-api"}


def _run_pipeline(
    request: ProcessRequest,
    extensions: set[str],
) -> dict:
    try:
        # 1. Transform (Bronze -> Silver)
        records = run_transform(
            source=request.source,
            limit=request.limit,
            extensions=extensions,
        )
        if not records:
            return {"message": "Nenhum documento novo para processar."}

        postgres_count = 0
        if request.load_postgres:
            # 2. Load text chunks to PostgreSQL (Silver -> Gold Text)
            records_with_ids = insert_chunks(records)
            postgres_count = len(records_with_ids)
            # Use records with postgres IDs for Qdrant
            records = records_with_ids

        qdrant_count = 0
        if request.load_qdrant:
            # 3. Create embeddings and load to Qdrant (Gold Vectors)
            embedder = BGEM3Embedder()
            embeddings = embedder.encode_texts(
                (record["texto"] for record in records),
            )
            qdrant_count = upsert_embeddings(records, embeddings)

        return {
            "message": "Pipeline executado com sucesso.",
            "documentos_processados": len(
                {record["documento_id"] for record in records}
            ),
            "chunks_gerados": len(records),
            "chunks_carregados_postgres": postgres_count,
            "vetores_carregados_qdrant": qdrant_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/processar-site")
def processar_site(request: ProcessRequest) -> dict:
    """
    Processa arquivos JSON (notícias de site) da camada Bronze para Gold.
    """
    return _run_pipeline(request, extensions={"json"})


@app.post("/processar-pdf")
def processar_pdf(request: ProcessRequest) -> dict:
    """
    Processa arquivos PDF da camada Bronze para Gold.
    """
    return _run_pipeline(request, extensions={"pdf"})