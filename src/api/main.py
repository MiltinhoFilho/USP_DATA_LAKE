"""
Pipeline API: process Bronze data into Silver (chunks) and Gold (embeddings).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel, Field

from embedding import BGEM3Embedder
from postgres_loader import insert_chunks
from qdrant_loader import upsert_embeddings
from scraper import scrape_article
from transform import BronzeDocument, transformar_documento, _extract_text_from_pdf_bytes

app = FastAPI(
    title="USP Data Lake - Pipeline API",
    description="Aplicacao para processar dados Bronze em Silver e Gold.",
    version="1.0.0",
)


class SiteRequest(BaseModel):
    url: str = Field(..., description="URL do artigo a ser processado.")


class ProcessOptions(BaseModel):
    load_postgres: bool = Field(default=True, description="Carregar no PostgreSQL")
    load_qdrant: bool = Field(default=True, description="Carregar no Qdrant")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "pipeline-api"}


def _run_document_pipeline(document: BronzeDocument, options: ProcessOptions) -> dict:
    try:
        # 1. Transform (Document -> Chunks)
        records = transformar_documento(document)
        if not records:
            return {"message": "Documento não gerou chunks para processar."}

        postgres_count = 0
        if options.load_postgres:
            # 2. Load text chunks to PostgreSQL (Silver -> Gold Text)
            records_with_ids = insert_chunks(records)
            postgres_count = len(records_with_ids)
            records = records_with_ids

        qdrant_count = 0
        if options.load_qdrant:
            # 3. Create embeddings and load to Qdrant (Gold Vectors)
            embedder = BGEM3Embedder()
            embeddings = embedder.encode_texts((r["texto"] for r in records))
            qdrant_count = upsert_embeddings(records, embeddings)

        return {
            "message": "Pipeline executado com sucesso.",
            "documento_id": document.documento_id,
            "chunks_gerados": len(records),
            "chunks_carregados_postgres": postgres_count,
            "vetores_carregados_qdrant": qdrant_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no pipeline: {e}") from e


@app.post("/processar-site")
def processar_site(request: SiteRequest, options: ProcessOptions) -> dict:
    """
    Processa uma URL de notícia, extrai o conteúdo e o carrega para as camadas Gold.
    """
    try:
        article_data = scrape_article(request.url)
        document_id = Path(request.url).stem

        document = BronzeDocument(
            object_name=request.url,
            documento_id=document_id,
            payload=article_data,
        )

        return _run_document_pipeline(document, options)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/processar-pdf")
async def processar_pdf(file: UploadFile, options: ProcessOptions) -> dict:
    """
    Processa um arquivo PDF enviado, extrai o texto e o carrega para as camadas Gold.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nome do arquivo não encontrado.")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="O arquivo deve ser um PDF.")

    try:
        # Usar arquivo temporário para garantir compatibilidade
        with tempfile.NamedTemporaryFile(delete=True, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp.seek(0)
            pdf_bytes = Path(tmp.name).read_bytes()

        text = _extract_text_from_pdf_bytes(pdf_bytes, file.filename)
        document_id = Path(file.filename).stem
        document = BronzeDocument(
            object_name=file.filename,
            documento_id=document_id,
            payload={"titulo": document_id.replace("_", " ").title(), "conteudo": text},
        )

        return _run_document_pipeline(document, options)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e