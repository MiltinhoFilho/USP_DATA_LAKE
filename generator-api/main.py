"""Data generation API: scrape Jornal da USP pages and ingest PDFs."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException, Query

from scraper import REQUEST_TIMEOUT, USER_AGENT, run as run_scraper
from upload_bronze import upload_bronze_files

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BRONZE_RAW_DIR = PROJECT_ROOT / "bronze" / "raw"

app = FastAPI(
    title="USP Data Lake - Generator API",
    description="Aplicacao de geracao/coleta de dados para a camada Bronze.",
    version="1.0.0",
)


def _safe_pdf_filename(url: str, filename: str | None) -> str:
    if filename:
        candidate = filename
    else:
        path_name = Path(urlparse(url).path).name or "documento.pdf"
        candidate = path_name

    candidate = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate).strip("._")
    if not candidate.lower().endswith(".pdf"):
        candidate = f"{candidate}.pdf"
    return candidate or "documento.pdf"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "generator-api"}


@app.get("/site")
def gerar_site(
    limit: int = Query(10, ge=1, le=500),
    max_pages: int | None = Query(None, ge=1),
    upload_minio: bool = Query(True),
) -> dict:
    """Scrape news from Jornal da USP and optionally upload Bronze files to MinIO."""
    try:
        articles = run_scraper(
            limit=limit,
            project_root=PROJECT_ROOT,
            max_pages=max_pages,
        )
        upload_summary = None
        if upload_minio:
            uploaded, failed = upload_bronze_files(BRONZE_RAW_DIR)
            upload_summary = {"uploaded": uploaded, "failed": failed}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return {
        "message": "Coleta de site concluida",
        "articles": len(articles),
        "bronze_dir": str(BRONZE_RAW_DIR),
        "upload_minio": upload_summary,
    }


@app.get("/pdf")
def gerar_pdf(
    url: str = Query(..., description="URL publica do arquivo PDF"),
    filename: str | None = Query(None),
    upload_minio: bool = Query(True),
) -> dict:
    """Download a PDF into Bronze and optionally upload it to MinIO."""
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise HTTPException(
            status_code=400,
            detail=f"Nao foi possivel baixar o PDF: {error}",
        ) from error

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" not in content_type and not urlparse(url).path.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="A URL informada nao parece apontar para um arquivo PDF.",
        )

    BRONZE_RAW_DIR.mkdir(parents=True, exist_ok=True)
    output_path = BRONZE_RAW_DIR / _safe_pdf_filename(url, filename)
    output_path.write_bytes(response.content)

    upload_summary = None
    if upload_minio:
        try:
            uploaded, failed = upload_bronze_files(BRONZE_RAW_DIR)
            upload_summary = {"uploaded": uploaded, "failed": failed}
        except Exception as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    return {
        "message": "PDF salvo na camada Bronze",
        "file": str(output_path),
        "bytes": len(response.content),
        "upload_minio": upload_summary,
    }