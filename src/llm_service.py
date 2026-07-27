"""Integração local com Ollama para geração de respostas da RAG."""

from __future__ import annotations

import os
from dataclasses import dataclass
import threading
from typing import Any

import httpx

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gemma3:4b" 
DEFAULT_OLLAMA_TIMEOUT = 120
DEFAULT_MAX_CONTEXT_CHARS = 6000
DEFAULT_MAX_SOURCES = 3
DEFAULT_TEMPERATURE = 0.1
DEFAULT_NUM_PREDICT = 96
DEFAULT_NUM_CTX = 2048
DEFAULT_KEEP_ALIVE = "10m"

SYSTEM_PROMPT = """Você responde perguntas sobre notícias do Jornal da USP.
Responda somente com base no contexto fornecido.
Não use conhecimento externo e não invente informações, títulos, URLs ou fontes.
Se o contexto não for suficiente, informe isso claramente.
Responda em português brasileiro de forma clara, objetiva e didática.
Não repita URLs no texto da resposta, não exponha raciocínio interno e preserve nomes, números, datas e listas."""

_client: httpx.Client | None = None
_client_lock = threading.Lock()


class LLMServiceError(RuntimeError):
    """Erro controlado do serviço local de linguagem."""


class OllamaUnavailableError(LLMServiceError):
    """O Ollama não está acessível ou excedeu o timeout."""


class OllamaModelNotFoundError(LLMServiceError):
    """O modelo configurado não está instalado."""


class OllamaInvalidResponseError(LLMServiceError):
    """O Ollama retornou uma resposta sem conteúdo utilizável."""


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str
    model: str
    timeout: float
    max_context_chars: int
    max_sources: int
    temperature: float = DEFAULT_TEMPERATURE
    num_predict: int = DEFAULT_NUM_PREDICT
    num_ctx: int = DEFAULT_NUM_CTX
    keep_alive: str = DEFAULT_KEEP_ALIVE


def _positive_number(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as error:
        raise LLMServiceError(f"Configuração inválida para {name}") from error
    if value <= 0:
        raise LLMServiceError(f"Configuração inválida para {name}")
    return value


def get_ollama_config() -> OllamaConfig:
    base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/")
    model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip()
    if not base_url or not model:
        raise LLMServiceError("Configuração do Ollama incompleta")
    return OllamaConfig(
        base_url=base_url,
        model=model,
        timeout=float(_positive_number("OLLAMA_TIMEOUT", DEFAULT_OLLAMA_TIMEOUT)),
        max_context_chars=_positive_number(
            "RAG_MAX_CONTEXT_CHARS", DEFAULT_MAX_CONTEXT_CHARS
        ),
        max_sources=_positive_number("RAG_MAX_SOURCES", DEFAULT_MAX_SOURCES),
        temperature=float(os.getenv("OLLAMA_TEMPERATURE", str(DEFAULT_TEMPERATURE))),
        num_predict=_positive_number("OLLAMA_NUM_PREDICT", DEFAULT_NUM_PREDICT),
        num_ctx=_positive_number("OLLAMA_NUM_CTX", DEFAULT_NUM_CTX),
        keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", DEFAULT_KEEP_ALIVE).strip() or DEFAULT_KEEP_ALIVE,
    )


def get_http_client() -> httpx.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client()
    return _client


def close_http_client() -> None:
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None


def _chunk_identity(chunk: dict[str, Any], text: str) -> tuple[str, str]:
    del chunk
    return ("text", " ".join(text.casefold().split()))


def _document_identity(chunk: dict[str, Any]) -> str:
    return str(chunk.get("documento_id") or chunk.get("url") or chunk.get("id"))


def _safe_truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    shortened = text[:limit].rstrip()
    boundary = max(shortened.rfind(". "), shortened.rfind("\n"), shortened.rfind(" "))
    return shortened[:boundary].rstrip() if boundary >= limit // 2 else shortened


def prepare_context(
    chunks: list[dict[str, Any]],
    config: OllamaConfig | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Filtra chunks e monta contexto limitado, preservando relevância."""
    config = config or get_ollama_config()
    groups: dict[str, list[tuple[dict[str, Any], str]]] = {}
    group_order: list[str] = []
    identities: set[tuple[str, str]] = set()

    for chunk in chunks:
        text_value = chunk.get("texto")
        if not isinstance(text_value, str) or not text_value.strip():
            continue
        text = text_value.strip()
        identity = _chunk_identity(chunk, text)
        if identity in identities:
            continue
        identities.add(identity)
        document = _document_identity(chunk)
        if document not in groups:
            if len(group_order) >= config.max_sources:
                continue
            groups[document] = []
            group_order.append(document)
        groups[document].append((chunk, text))

    blocks: list[str] = []
    selected: list[dict[str, Any]] = []
    current_length = 0
    for source_number, document in enumerate(group_order, start=1):
        entries = groups[document]
        separator = "\n\n" if blocks else ""
        prefix = f"[{source_number}] {entries[0][0].get('titulo') or 'Sem título'}\n"
        available = config.max_context_chars - current_length - len(separator) - len(prefix)
        if available <= 0:
            break
        parts: list[str] = []
        parts_length = 0
        for chunk, text in entries:
            part_separator = "\n" if parts else ""
            remaining = available - parts_length - len(part_separator)
            if remaining <= 0:
                break
            content = _safe_truncate(text, remaining)
            if content:
                parts.append(content)
                selected.append(chunk)
                parts_length += len(part_separator) + len(content)
            if len(content) < len(text):
                break
        if parts:
            block = prefix + "\n".join(parts)
            blocks.append(block)
            current_length += len(separator) + len(block)

    return "\n\n".join(blocks), selected


def generate_answer(
    question: str,
    context: str,
    config: OllamaConfig | None = None,
) -> str:
    """Solicita ao Ollama uma resposta não streaming baseada no contexto."""
    config = config or get_ollama_config()
    url = f"{config.base_url}/api/chat"
    payload = {
        "model": config.model,
        "stream": False,
        "keep_alive": config.keep_alive,
        "options": {
            "temperature": config.temperature,
            "num_predict": config.num_predict,
            "num_ctx": config.num_ctx,
        },
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"PERGUNTA:\n{question}\n\nCONTEXTO:\n{context}"
                    "\n\nResponda somente à pergunta."
                ),
            },
        ],
    }

    try:
        response = get_http_client().post(url, json=payload, timeout=config.timeout)
    except (httpx.ConnectError, httpx.TimeoutException) as error:
        raise OllamaUnavailableError from error
    except httpx.RequestError as error:
        raise OllamaUnavailableError from error

    if response.status_code == 404:
        raise OllamaModelNotFoundError
    if response.status_code >= 500:
        raise OllamaUnavailableError
    if response.status_code >= 400:
        response_text = response.text.casefold()
        if "model" in response_text and (
            "not found" in response_text or "não encontrado" in response_text
        ):
            raise OllamaModelNotFoundError
        raise OllamaUnavailableError

    try:
        content = response.json().get("message", {}).get("content")
    except (TypeError, ValueError) as error:
        raise OllamaInvalidResponseError from error
    if not isinstance(content, str) or not content.strip():
        raise OllamaInvalidResponseError
    return content.strip()
