"""API RAG para respostas extrativas sobre notícias da USP."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
import threading
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware 
from pydantic import BaseModel, Field

from src.llm_service import (
    close_http_client,
    LLMServiceError,
    OllamaInvalidResponseError,
    OllamaModelNotFoundError,
    OllamaUnavailableError,
    generate_answer,
    prepare_context,
)
from src.retriever import Retriever, evaluate_evidence

SERVICE_NAME = "rag-api"
NO_RESULTS_MESSAGE = (
    "Não encontrei informações suficientes sobre esse tema no conjunto de "
    "notícias atualmente indexado do Jornal da USP."
)

logger = logging.getLogger("uvicorn.error")
_initialization_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa recursos locais somente durante a vida da aplicação."""
    with _initialization_lock:
        if getattr(app.state, "retriever", None) is None:
            try:
                retriever = Retriever()
                retriever.initialize()
                app.state.retriever = retriever
                app.state.retriever_error = None

            except Exception as error:
                app.state.retriever = None
                app.state.retriever_error = "retriever_unavailable"
                logger.exception("Falha ao inicializar o Retriever: %s",error)

    try:
        yield
    finally:
        retriever = getattr(app.state, "retriever", None)
        if retriever is not None:
            try:
                retriever.close()
            except Exception:
                logger.warning("Falha controlada ao encerrar o Retriever")
        app.state.retriever = None
        close_http_client()

app = FastAPI(
    title="USP Data Lake - RAG API",
    description="API para realizar buscas semânticas nos dados do Data Lake.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PerguntaRequest(BaseModel):
    pergunta: str = Field(..., min_length=3, description="Pergunta do usuário")
    top_k: int = Field(default=5, ge=1, le=20, description="Número de fontes")


class FonteResponse(BaseModel):
    id: int | None = None
    titulo: str | None = None
    url: str | None = None
    texto: str | None = None
    score: float | None = None
    document_id: str | None = None
    chunk_id: int | str | None = None
    postgres_id: int | None = None
    source_type: str | None = None
    source_object: str | None = None


class PerguntaResponse(BaseModel):
    status: str
    service: str
    pergunta: str
    resposta: str
    fontes: list[FonteResponse]
    total_fontes: int
    evidence_sufficient: bool | None = None
    ollama_skipped: bool | None = None
    metrics: dict[str, float | int | bool | str] | None = None


@app.get("/")
def root() -> dict:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "message": "USP Data Lake - RAG API",
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": SERVICE_NAME}


def _derive_source_type(chunk: dict[str, Any]) -> str:
    """Deriva a origem sem alterar ou depender dos dados persistidos."""
    source_object = str(chunk.get("source_object") or "").lower()
    if source_object.endswith(".json"):
        return "json"
    if source_object.endswith(".pdf"):
        return "pdf"

    explicit_type = str(
        chunk.get("source_type") or chunk.get("origem") or chunk.get("tipo") or ""
    ).strip().lower()
    if explicit_type in {"json", "pdf"}:
        return explicit_type

    url = str(chunk.get("url") or "").lower().split("?", 1)[0]
    if url.endswith(".json"):
        return "json"
    if url.endswith(".pdf"):
        return "pdf"
    return "unknown"


def _fonte_from_chunk(chunk: dict[str, Any]) -> FonteResponse:
    postgres_id = chunk.get("postgres_id", chunk.get("id"))
    return FonteResponse(
        id=chunk.get("id"),
        titulo=chunk.get("titulo"),
        url=chunk.get("url"),
        texto=chunk.get("texto"),
        score=chunk.get("score"),
        document_id=chunk.get("document_id", chunk.get("documento_id")),
        chunk_id=chunk.get("chunk_id"),
        postgres_id=postgres_id,
        source_type=_derive_source_type(chunk),
        source_object=chunk.get("source_object"),
    )


def _get_retriever(request: Request) -> Retriever:
    retriever = getattr(request.app.state, "retriever", None)
    if retriever is None:
        raise HTTPException(
            status_code=503,
            detail="Serviço de recuperação temporariamente indisponível.",
        )
    return retriever


def _log_metrics(metrics: dict[str, float | int | str]) -> None:
    logger.info(
        "rag_request_metrics %s",
        json.dumps(metrics, ensure_ascii=True, sort_keys=True),
    )


def _log_evidence_diagnostics(evidence: Any) -> None:
    """Registra decisão e candidatos sem expor o conteúdo dos documentos."""
    summary = {
        "decision": evidence.decision,
        "reason": evidence.refusal_reason,
        "candidate_count": len(evidence.classified_sources),
        "context_source_count": len(evidence.context_sources),
        "public_source_count": len(evidence.public_sources),
    }
    logger.info(
        "rag_evidence_decision %s",
        json.dumps(summary, ensure_ascii=True, sort_keys=True),
    )

    inconsistent_candidates = 0
    for candidate in evidence.classified_sources:
        source_type = _derive_source_type(candidate)
        postgres_id = candidate.get("postgres_id", candidate.get("id"))
        if postgres_id is None:
            inconsistent_candidates += 1
        details = {
            "score_vector": candidate.get("score_vector"),
            "score_bm25": candidate.get("score_lexical"),
            "rank_vector": candidate.get("rank_vector"),
            "rank_lexical": candidate.get("rank_lexical"),
            "rank_hybrid": candidate.get("evidence_hybrid_rank"),
            "score_rrf": candidate.get("score_hybrid", candidate.get("score")),
            "covered_terms": candidate.get("evidence_terms_covered", []),
            "title": candidate.get("titulo"),
            "url": candidate.get("url"),
            "document_id": candidate.get("document_id", candidate.get("documento_id")),
            "chunk_id": candidate.get("chunk_id"),
            "postgres_id": postgres_id,
            "source_object": candidate.get("source_object"),
            "source_type": source_type,
            "evidence_class": candidate.get("evidence_class"),
            "decision": evidence.decision,
            "reason": evidence.refusal_reason,
        }
        logger.info(
            "rag_evidence_candidate %s",
            json.dumps(details, ensure_ascii=True, sort_keys=True),
        )

    if inconsistent_candidates:
        logger.warning(
            "rag_evidence_metadata_inconsistency count=%d",
            inconsistent_candidates,
        )


def _public_metrics(metrics: dict[str, Any]) -> dict[str, float | int | bool | str]:
    allowed = {
        "embedding_seconds", "qdrant_seconds", "postgres_seconds",
        "retriever_seconds", "evidence_check_seconds", "context_seconds",
        "ollama_seconds", "total_seconds", "context_chars", "source_count",
        "deduplicated_candidates", "evidence_decision", "refusal_reason",
    }
    return {key: value for key, value in metrics.items() if key in allowed}


@app.post("/pergunta", response_model=PerguntaResponse)
def pergunta(payload: PerguntaRequest, request: Request) -> PerguntaResponse:
    total_started = time.perf_counter()
    try:
        retriever = _get_retriever(request)
        chunks, metrics = retriever.search_with_metrics(
            question=payload.pergunta,
            top_k=payload.top_k,
        )
    except HTTPException:
        raise
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (ConnectionError, TimeoutError) as error:
        raise HTTPException(
            status_code=503,
            detail="Serviços de recuperação temporariamente indisponíveis.",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="Não foi possível consultar as notícias.",
        ) from error

    evidence = evaluate_evidence(payload.pergunta, chunks)
    metrics.update(evidence.metrics)
    _log_evidence_diagnostics(evidence)
    if not evidence.sufficient:
        fontes = [_fonte_from_chunk(chunk) for chunk in evidence.public_sources]
        metrics["context_seconds"] = 0.0
        metrics["context_chars"] = 0
        metrics["source_count"] = len(fontes)
        metrics["ollama_seconds"] = 0.0
        metrics["total_seconds"] = time.perf_counter() - total_started
        _log_metrics(metrics)
        return PerguntaResponse(
            status="ok",
            service=SERVICE_NAME,
            pergunta=payload.pergunta,
            resposta=NO_RESULTS_MESSAGE,
            fontes=fontes,
            total_fontes=len(fontes),
            evidence_sufficient=False,
            ollama_skipped=True,
            metrics=_public_metrics(metrics),
        )

    try:
        context_started = time.perf_counter()
        context, selected_chunks = prepare_context(evidence.context_sources)
        metrics["context_seconds"] = time.perf_counter() - context_started
        metrics["context_chars"] = len(context)
        metrics["source_count"] = len(selected_chunks)
        ollama_started = time.perf_counter()
        if not selected_chunks:
            answer = NO_RESULTS_MESSAGE
            metrics["ollama_seconds"] = 0.0
        else:
            answer = generate_answer(payload.pergunta, context)
            metrics["ollama_seconds"] = time.perf_counter() - ollama_started
    except OllamaModelNotFoundError as error:
        raise HTTPException(
            status_code=503,
            detail="O modelo configurado não está instalado no Ollama.",
        ) from error
    except OllamaUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "O modelo local de linguagem está indisponível. "
                "Verifique se o Ollama está em execução."
            ),
        ) from error
    except OllamaInvalidResponseError as error:
        raise HTTPException(
            status_code=502,
            detail="O modelo local de linguagem retornou uma resposta inválida.",
        ) from error
    except LLMServiceError as error:
        raise HTTPException(
            status_code=500,
            detail="Não foi possível configurar o modelo local de linguagem.",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="Não foi possível gerar a resposta.",
        ) from error

    fontes = [_fonte_from_chunk(chunk) for chunk in selected_chunks]
    metrics["total_seconds"] = time.perf_counter() - total_started
    _log_metrics(metrics)
    return PerguntaResponse(
        status="ok",
        service=SERVICE_NAME,
        pergunta=payload.pergunta,
        resposta=answer,
        fontes=fontes,
        total_fontes=len(fontes),
        evidence_sufficient=True,
        ollama_skipped=False,
        metrics=_public_metrics(metrics),
    )
