from __future__ import annotations

import re
import textwrap
from pathlib import Path
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException, Query

from bs4 import BeautifulSoup

from src.scraper import REQUEST_TIMEOUT, USER_AGENT, extract_content_html, extract_title, run
from src.upload_bronze import upload_bronze_file, upload_bronze_files

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BRONZE_RAW_DIR = PROJECT_ROOT / "bronze" / "raw"

app = FastAPI(
    title="USP Data Lake - Generator API",
    description="API para coletar dados e armazená-los na camada Bronze.",
    version="1.0.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "generator-api"}


def _response(message: str, data: dict) -> dict:
    return {
        "status": "ok",
        "service": "generator-api",
        "message": message,
        "data": data,
    }


def _safe_pdf_filename(url: str, filename: str | None) -> str:
    candidate = filename or Path(urlparse(url).path).name or "documento.pdf"
    candidate = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate).strip("._")
    if not candidate:
        candidate = "documento.pdf"
    if not candidate.lower().endswith(".pdf"):
        candidate = f"{candidate}.pdf"
    return candidate


def _pdf_string(value: str) -> bytes:
    encoded = value.encode("cp1252", errors="replace")
    return encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _build_text_pdf(title: str, source_url: str, text: str) -> bytes:
    """Gera um PDF textual simples e extraível, sem dependência adicional."""
    logical_lines = [title, source_url, ""]
    logical_lines.extend(text.splitlines())
    lines: list[str] = []
    for line in logical_lines:
        cleaned = re.sub(r"\s+", " ", line).strip()
        lines.extend(textwrap.wrap(cleaned, width=92) or [""])

    pages = [lines[index:index + 54] for index in range(0, len(lines), 54)] or [[title]]
    font_id = 3 + 2 * len(pages)
    info_id = font_id + 1
    page_ids = [3 + 2 * index for index in range(len(pages))]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Count " + str(len(pages)).encode() + b" /Kids [" +
           b" ".join(f"{page_id} 0 R".encode() for page_id in page_ids) + b"] >>",
        font_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        info_id: b"<< /Title (" + _pdf_string(title) + b") /Subject (Source-URL: " +
                 _pdf_string(source_url) + b") >>",
    }

    for index, page_lines in enumerate(pages):
        page_id = page_ids[index]
        content_id = page_id + 1
        commands = [b"BT /F1 10 Tf 50 790 Td 13 TL"]
        commands.extend(b"(" + _pdf_string(line) + b") Tj T*" for line in page_lines)
        commands.append(b"ET")
        stream = b"\n".join(commands)
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode()
        objects[content_id] = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id in range(1, info_id + 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode())
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {info_id + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {info_id + 1} /Root 1 0 R /Info {info_id} 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


@app.get("/site")
def gerar_site(
    limit: int = Query(10, ge=1, le=500),
    max_pages: int | None = Query(None, ge=1, le=100),
    upload_minio: bool = Query(False),
) -> dict:
    try:
        articles = run(
            limit=limit,
            project_root=PROJECT_ROOT,
            max_pages=max_pages,
        )

        upload_summary = None
        if upload_minio:
            uploaded, failed = upload_bronze_files(BRONZE_RAW_DIR)
            upload_summary = {"uploaded": uploaded, "failed": failed}

        return _response(
            message="Coleta de site concluída.",
            data={
                "articles": len(articles),
                "bronze_dir": str(BRONZE_RAW_DIR),
                "upload_minio": upload_summary,
            },
        )
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.get("/pdf")
def gerar_pdf(
    url: str = Query(..., min_length=1, description="URL pública de PDF ou notícia"),
    filename: str | None = Query(None, min_length=1, max_length=255),
    upload_minio: bool = Query(False),
) -> dict:
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise HTTPException(status_code=422, detail="Informe uma URL HTTP ou HTTPS válida.")

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
            detail=f"Não foi possível baixar o PDF: {error}",
        ) from error

    content_type = response.headers.get("content-type", "").lower()
    if response.content.startswith(b"%PDF-"):
        pdf_bytes = response.content
        title = Path(parsed_url.path).stem or "documento"
    elif "html" in content_type or "jornal.usp.br" in parsed_url.netloc.lower():
        response.encoding = response.apparent_encoding or "utf-8"
        soup = BeautifulSoup(response.text, "lxml")
        title = extract_title(soup).strip()
        content_html = extract_content_html(soup)
        article_text = BeautifulSoup(content_html, "lxml").get_text("\n", strip=True)
        if not title or not article_text:
            raise HTTPException(status_code=400, detail="A notícia não possui texto suficiente para gerar PDF.")
        pdf_bytes = _build_text_pdf(title, url, article_text)
    else:
        raise HTTPException(status_code=400, detail="A URL não contém um PDF nem uma notícia HTML válida.")

    if not pdf_bytes.startswith(b"%PDF-") or len(pdf_bytes) == 0:
        raise HTTPException(status_code=500, detail="O conteúdo PDF gerado é inválido.")

    output_path = BRONZE_RAW_DIR / _safe_pdf_filename(url, filename)
    try:
        BRONZE_RAW_DIR.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(pdf_bytes)

        upload_summary = {"uploaded": False}
        if upload_minio:
            uploaded_object = upload_bronze_file(output_path)
            upload_summary = {"uploaded": True, **uploaded_object}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return _response(
        message="PDF salvo na camada Bronze.",
        data={
            "file": str(output_path),
            "filename": output_path.name,
            "url": url,
            "bytes": len(pdf_bytes),
            "bucket": upload_summary.get("bucket"),
            "object_key": upload_summary.get("object_key"),
            "uploaded": upload_summary["uploaded"],
            "upload_minio": upload_summary,
        },
    )
