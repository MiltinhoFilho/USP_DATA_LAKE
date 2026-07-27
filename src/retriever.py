"""Recuperação híbrida local sobre chunks do Jornal da USP."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math
import os
import re
import threading
import time
import unicodedata
from typing import Any, Iterable

from src.embedding import BGEM3Embedder
from src.postgres_loader import get_postgres_connection
from src.qdrant_loader import get_collection_name, get_qdrant_client

DEFAULT_TOP_K = 5
MIN_TOP_K = 1
MAX_TOP_K = 20
TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
QUERY_STOPWORDS = {
    "a", "as", "da", "das", "de", "do", "dos", "e", "em", "foi", "foram",
    "ha", "no", "nos", "o", "os", "pela", "pelo", "por", "qual", "que", "sao",
    "um", "uma", "mostra", "mostram", "revela", "revelam", "trata", "sobre", "estudos","abordados", "aparecem", "existem", "jornal", "mencionam", "noticias",
    "noticia", "publicou", "quais", "relacionadas", "pesquisas", "sobre", "qual", "quais", "apontam", "aponta", "oncologia", "pressao alta", "cursos", "curso"
    "tratam", "usp", "diz", "pesquisas", "saude", "educacao", "cursos", "estudos"  
     }

DOMAIN_SYNONYMS = {
    "usp": [
        "universidade",
        "universidade de sao paulo",
        "universidade de são paulo",
    ],

    "ia": [
        "inteligencia",
        "artificial",
        "inteligencia artificial",
    ],


    "inteligencia artificial": [
        "ia",
    ],

    "covid": [
        "covid19",
        "coronavirus",
    ],

    "pesquisa": [
        "estudo",
        "cientifico",
        "científica",
        "pesquisador",
        "pesquisadores",
    ],

    "docente": [
        "professor",
        "professora",
    ],

    "aluno": [
        "estudante",
        "graduando",
        "graduanda",
    ],

    "ribeirao preto": [
         "campus ribeirao preto",
    ],

    "esalq": [
        "escola superior de agricultura luiz de queiroz",
    ],

    "fmrp": [
    "faculdade de medicina de ribeirao preto",
    ],

    "iqsc": [
    "instituto de quimica de sao carlos",
    ],
}

def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RetrievalConfig:
    hybrid_enabled: bool = True
    lexical_enabled: bool = True
    initial_candidates: int = 20
    final_sources: int = 5
    max_chunks_per_source: int = 1
    vector_weight: float = 1.0
    lexical_weight: float = 2.0
    rrf_k: float = 60.0
    title_weight: float = 3.0
    category_weight: float = 1.5
    content_weight: float = 1.0
    author_weight: float = 0.5
    bm25_k1: float = 1.5
    bm25_b: float = 0.75

    @classmethod
    def from_env(cls) -> "RetrievalConfig":
        return cls(
            hybrid_enabled=_env_bool("RAG_HYBRID_ENABLED", True),
            lexical_enabled=_env_bool("RAG_LEXICAL_ENABLED", True),
            initial_candidates=max(1, int(os.getenv("RAG_INITIAL_CANDIDATES", "20"))),
            final_sources=max(1, int(os.getenv("RAG_FINAL_SOURCES", "5"))),
            max_chunks_per_source=max(1, int(os.getenv("RAG_MAX_CHUNKS_PER_SOURCE", "1"))),
            vector_weight=float(os.getenv("RAG_VECTOR_WEIGHT", "1.0")),
            lexical_weight=float(os.getenv("RAG_LEXICAL_WEIGHT", "2.0")),
            rrf_k=max(1.0, float(os.getenv("RAG_RRF_K", "60"))),
            title_weight=float(os.getenv("RAG_LEXICAL_TITLE_WEIGHT", "3.0")),
            category_weight=float(os.getenv("RAG_LEXICAL_CATEGORY_WEIGHT", "1.5")),
            content_weight=float(os.getenv("RAG_LEXICAL_CONTENT_WEIGHT", "1.0")),
            author_weight=float(os.getenv("RAG_LEXICAL_AUTHOR_WEIGHT", "0.5")),
            bm25_k1=max(0.01, float(os.getenv("RAG_BM25_K1", "1.5"))),
            bm25_b=min(1.0, max(0.0, float(os.getenv("RAG_BM25_B", "0.75")))),
        )


def tokenize(text: str) -> list[str]:
    """Normaliza acentos e pontuação, preservando siglas como IA como token ``ia``."""
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return TOKEN_PATTERN.findall(normalized.lower())


def tokenize_query(text: str) -> list[str]:
    """Remove apenas palavras de enquadramento, mantendo os termos temáticos."""
    return [term for term in tokenize(text) if term not in QUERY_STOPWORDS]



    """Normaliza acentos e pontuação, preservando siglas como IA como token ``ia``."""
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = "".join(
        char for char in normalized
        if not unicodedata.combining(char)
    )
    return TOKEN_PATTERN.findall(normalized.lower())


def tokenize_query(text: str) -> list[str]:
    """Remove apenas palavras de enquadramento, mantendo os termos temáticos."""
    return [
        term
        for term in tokenize(text)
        if term not in QUERY_STOPWORDS
    ]


def expand_query_terms(terms: Iterable[str]) -> list[str]:
    """
    Expande termos da consulta com equivalências específicas do domínio.

    Mantém os termos originais, adiciona os equivalentes configurados em
    DOMAIN_SYNONYMS e remove duplicatas preservando a ordem.
    """
    expanded: list[str] = []

    for term in terms:
        expanded.append(term)

        for synonym in DOMAIN_SYNONYMS.get(term, []):
            expanded.extend(tokenize(synonym))

    return list(dict.fromkeys(expanded))



def extract_query_terms(question: str) -> list[str]:
    """Retorna termos temáticos únicos, na ordem em que aparecem."""
    return list(dict.fromkeys(tokenize_query(question)))


@dataclass(frozen=True)
class EvidenceConfig:
    enabled: bool = True
    min_direct_sources: int = 1
    min_total_relevant_sources: int = 2
    min_query_term_coverage: float = 0.60
    min_lexical_matched_sources: int = 1
    allow_single_strong_source: bool = True
    single_strong_source_min_coverage: float = 0.80
    single_strong_source_require_title_match: bool = False
    single_strong_source_min_matched_terms: int = 2
    single_strong_source_max_lexical_rank: int = 3
    single_strong_source_allow_strong_partial: bool = True
    reject_all_weak: bool = True

    @classmethod
    def from_env(cls) -> "EvidenceConfig":
        return cls(
            enabled=_env_bool("RAG_EVIDENCE_CHECK_ENABLED", True),
            min_direct_sources=max(0, int(os.getenv("RAG_MIN_DIRECT_SOURCES", "1"))),
            min_total_relevant_sources=max(1, int(os.getenv("RAG_MIN_TOTAL_RELEVANT_SOURCES", "2"))),
            min_query_term_coverage=min(1.0, max(0.0, float(os.getenv("RAG_MIN_QUERY_TERM_COVERAGE", "0.60")))),
            min_lexical_matched_sources=max(0, int(os.getenv("RAG_MIN_LEXICAL_MATCHED_SOURCES", "1"))),
            allow_single_strong_source=_env_bool("RAG_ALLOW_SINGLE_STRONG_SOURCE", True),
            single_strong_source_min_coverage=min(1.0, max(0.0, float(os.getenv("RAG_SINGLE_STRONG_SOURCE_MIN_COVERAGE", "0.80")))),
            single_strong_source_require_title_match=_env_bool("RAG_SINGLE_STRONG_SOURCE_REQUIRE_TITLE_MATCH", False),
            single_strong_source_min_matched_terms=max(2, int(os.getenv("RAG_SINGLE_STRONG_SOURCE_MIN_MATCHED_TERMS", "2"))),
            single_strong_source_max_lexical_rank=max(1, int(os.getenv("RAG_SINGLE_STRONG_SOURCE_MAX_LEXICAL_RANK", "3"))),
            single_strong_source_allow_strong_partial=_env_bool("RAG_SINGLE_STRONG_SOURCE_ALLOW_STRONG_PARTIAL", True),
            reject_all_weak=_env_bool("RAG_REJECT_ALL_WEAK", True),
        )


@dataclass(frozen=True)
class EvidenceEvaluation:
    sufficient: bool
    decision: str
    refusal_reason: str
    query_terms: list[str]
    classified_sources: list[dict[str, Any]]
    context_sources: list[dict[str, Any]]
    public_sources: list[dict[str, Any]]
    metrics: dict[str, Any]


def _source_evidence(source: dict[str, Any], terms: list[str],
                     config: EvidenceConfig, hybrid_rank: int) -> dict[str, Any]:
    title_tokens = set(tokenize(str(source.get("titulo") or "")))
    text_tokens = set(tokenize(str(source.get("texto") or "")))
    combined = title_tokens | text_tokens
    covered = [term for term in terms if term in combined]
    title_covered = [term for term in terms if term in title_tokens]
    text_covered = [term for term in terms if term in text_tokens]
    coverage = len(covered) / len(terms) if terms else 0.0
    title_coverage = len(title_covered) / len(terms) if terms else 0.0
    text_coverage = len(text_covered) / len(terms) if terms else 0.0
    phrase = " ".join(terms)
    normalized_title = " ".join(tokenize(str(source.get("titulo") or "")))
    normalized_text = " ".join(tokenize(str(source.get("texto") or "")))
    exact_phrase = bool(phrase and (phrase in normalized_title or phrase in normalized_text))
    lexical = source.get("rank_lexical") is not None and float(source.get("score_lexical") or 0) > 0
    vector = source.get("rank_vector") is not None and float(source.get("score_vector") or 0) > 0

    strong_lexical = lexical and int(source["rank_lexical"]) <= 10
    strong_vector = vector and int(source["rank_vector"]) <= 5
    if coverage >= 0.999 and strong_lexical and (
        exact_phrase or title_coverage >= 0.999 or text_coverage >= 0.999
    ):
        classification = "direct"
    elif coverage >= 0.60 and (lexical or strong_vector):
        classification = "partial"
    elif not lexical and strong_vector and coverage > 0:
        classification = "partial"
    else:
        classification = "weak"

    # Uma partial forte precisa combinar cobertura temática e sinais de ranking.
    # Consultas de termo único permanecem fora desta exceção conservadora.
    distributed_strong = bool(
        len(terms) >= 4
        and len(covered) >= 4
        and coverage >= config.single_strong_source_min_coverage
        and strong_vector
        and lexical
        and int(source["rank_lexical"]) == 1
        and hybrid_rank == 1
    )
    strong_partial = bool(
        classification == "partial"
        and config.single_strong_source_allow_strong_partial
        and len(terms) >= 2
        and len(covered) >= config.single_strong_source_min_matched_terms
        and coverage >= config.single_strong_source_min_coverage
        and lexical
        and int(source["rank_lexical"]) <= config.single_strong_source_max_lexical_rank
        and hybrid_rank <= config.single_strong_source_max_lexical_rank
        and (
            exact_phrase
            or title_coverage >= config.single_strong_source_min_coverage
            or text_coverage >= config.single_strong_source_min_coverage
            or distributed_strong
        )
        and (
            strong_vector
            or exact_phrase
            or title_coverage >= config.single_strong_source_min_coverage
        )
    )

    enriched = dict(source)
    enriched["evidence_class"] = classification
    enriched["evidence_term_coverage"] = coverage
    enriched["evidence_title_coverage"] = title_coverage
    enriched["evidence_text_coverage"] = text_coverage
    enriched["evidence_exact_phrase"] = exact_phrase
    enriched["evidence_terms_covered"] = covered
    enriched["evidence_hybrid_rank"] = hybrid_rank
    enriched["evidence_strong_partial"] = strong_partial
    enriched["evidence_distributed_strong"] = distributed_strong
    return enriched


def evaluate_evidence(question: str, sources: list[dict[str, Any]],
                      config: EvidenceConfig | None = None) -> EvidenceEvaluation:
    """Avalia evidências sem LLM, usando cobertura lexical e sinais híbridos."""
    started = time.perf_counter()
    config = config or EvidenceConfig.from_env()
    terms = extract_query_terms(question)
    classified = [
        _source_evidence(source, terms, config, rank)
        for rank, source in enumerate(sources, start=1)
    ]
    direct = [source for source in classified if source["evidence_class"] == "direct"]
    partial = [source for source in classified if source["evidence_class"] == "partial"]
    strong_partial = [source for source in partial if source["evidence_strong_partial"]]
    weak_partial = [source for source in partial if not source["evidence_strong_partial"]]
    weak = [source for source in classified if source["evidence_class"] == "weak"]
    relevant = direct + partial
    defensible = direct + strong_partial
    covered_terms = set()
    for source in relevant:
        covered_terms.update(source["evidence_terms_covered"])
    term_coverage = len(covered_terms) / len(terms) if terms else 0.0
    lexical_matched = sum(source.get("rank_lexical") is not None for source in relevant)
    unique_urls = len({source.get("url") or source.get("documento_id") or source.get("id") for source in relevant})

    if not config.enabled:
        sufficient, decision, reason = True, "disabled", "evidence_check_disabled"
        context_sources = list(sources)
    elif not sources:
        sufficient, decision, reason = False, "refused", "no_results"
        context_sources = []
    elif config.reject_all_weak and len(weak) == len(classified):
        sufficient, decision, reason = False, "refused", "all_sources_weak"
        context_sources = []
    else:
        condition_a = (
            len(direct) >= config.min_direct_sources
            and len(defensible) >= config.min_total_relevant_sources
            and term_coverage >= config.min_query_term_coverage
            and lexical_matched >= config.min_lexical_matched_sources
        )
        strongest = direct[0] if direct else (strong_partial[0] if strong_partial else None)
        condition_b = bool(
            config.allow_single_strong_source and strongest
            and strongest["evidence_term_coverage"] >= config.single_strong_source_min_coverage
            and len(strongest["evidence_terms_covered"]) >= config.single_strong_source_min_matched_terms
            and (not config.single_strong_source_require_title_match
                 or strongest["evidence_title_coverage"] >= config.single_strong_source_min_coverage)
            and strongest.get("rank_lexical") is not None
            and int(strongest["rank_lexical"]) <= config.single_strong_source_max_lexical_rank
        )
        sufficient = condition_a or condition_b
        decision = "accepted" if sufficient else "refused"
        if sufficient:
            reason = "evidence_accepted"
        elif term_coverage < config.min_query_term_coverage:
            reason = "insufficient_term_coverage"
        elif len(direct) < config.min_direct_sources:
            reason = "insufficient_direct_sources"
        elif len(relevant) < config.min_total_relevant_sources:
            reason = "insufficient_relevant_sources"
        elif lexical_matched < config.min_lexical_matched_sources:
            reason = "ambiguous_matches"
        else:
            reason = "insufficient_relevant_sources"
        context_sources = defensible if sufficient else []

    # Na recusa, apenas evidências diretas defensáveis permanecem visíveis.
    public_sources = context_sources if sufficient else direct
    metrics = {
        "evidence_check_seconds": time.perf_counter() - started,
        "evidence_sufficient": sufficient,
        "evidence_decision": decision,
        "direct_sources_count": len(direct),
        "partial_sources_count": len(partial),
        "strong_partial_sources_count": len(strong_partial),
        "weak_partial_sources_count": len(weak_partial),
        "weak_sources_count": len(weak),
        "query_terms_count": len(terms),
        "query_terms_covered_count": len(covered_terms),
        "query_term_coverage": term_coverage,
        "lexical_matched_sources": lexical_matched,
        "relevant_unique_sources": unique_urls,
        "ollama_skipped": not sufficient,
        "refusal_reason": reason,
    }
    return EvidenceEvaluation(sufficient, decision, reason, terms, classified,
                              context_sources, public_sources, metrics)


class BM25Index:
    """BM25 Okapi local com TF ponderada por campo.

    Usa ``idf = log(1 + (N-df+0.5)/(df+0.5))`` e os parâmetros tradicionais
    ``k1=1.5`` e ``b=0.75``. O comprimento é a soma ponderada dos campos.
    """

    def __init__(self, documents: Iterable[dict[str, Any]], config: RetrievalConfig) -> None:
        self.config = config
        self.documents: dict[int, dict[str, Any]] = {}
        self.term_frequencies: dict[int, Counter[str]] = {}
        self.lengths: dict[int, float] = {}
        document_frequency: Counter[str] = Counter()
        fields = (("titulo", config.title_weight), ("categoria", config.category_weight),
                  ("texto", config.content_weight), ("autor", config.author_weight))
        for document in documents:
            identifier = int(document["id"])
            weighted: Counter[str] = Counter()
            length = 0.0
            for field, weight in fields:
                if weight <= 0:
                    continue
                tokens = tokenize(str(document.get(field) or ""))
                length += len(tokens) * weight
                for term, count in Counter(tokens).items():
                    weighted[term] += count * weight
            self.documents[identifier] = dict(document)
            self.term_frequencies[identifier] = weighted
            self.lengths[identifier] = length
            document_frequency.update(weighted.keys())
        self.size = len(self.documents)
        self.average_length = sum(self.lengths.values()) / self.size if self.size else 0.0
        self.idf = {term: math.log(1.0 + (self.size - df + 0.5) / (df + 0.5))
                    for term, df in document_frequency.items()}

    def search(self, question: str, limit: int) -> list[dict[str, Any]]:
        original_terms = tokenize_query(question)
        query_terms = expand_query_terms(original_terms)

        if not query_terms or not self.size or self.average_length <= 0:
            return []
        scores: list[tuple[float, int]] = []

        for identifier, frequencies in self.term_frequencies.items():
            score = 0.0
            length_ratio = self.lengths[identifier] / self.average_length
            for term in query_terms:
                tf = frequencies.get(term, 0.0)
                if tf <= 0:
                    continue
                denominator = tf + self.config.bm25_k1 * (
                    1.0 - self.config.bm25_b + self.config.bm25_b * length_ratio
                )
                if denominator > 0:
                    score += self.idf.get(term, 0.0) * tf * (self.config.bm25_k1 + 1.0) / denominator
            if score > 0:
                scores.append((score, identifier))
        scores.sort(key=lambda item: (-item[0], item[1]))
        results = []
        for rank, (score, identifier) in enumerate(scores[:limit], start=1):
            item = dict(self.documents[identifier])
            item.update(score_lexical=score, rank_lexical=rank)
            results.append(item)
        return results


def reciprocal_rank_fusion(vector_results: list[dict[str, Any]], lexical_results: list[dict[str, Any]],
                           config: RetrievalConfig) -> list[dict[str, Any]]:
    candidates: dict[int, dict[str, Any]] = {}
    for rank, result in enumerate(vector_results, start=1):
        item = candidates.setdefault(int(result["id"]), dict(result))
        item["rank_vector"] = rank
        item["score_vector"] = float(result.get("score_vector", result.get("score", 0.0)))
    for rank, result in enumerate(lexical_results, start=1):
        item = candidates.setdefault(int(result["id"]), dict(result))
        item["rank_lexical"] = rank
        item["score_lexical"] = float(result.get("score_lexical", 0.0))
    for item in candidates.values():
        vector_part = config.vector_weight / (config.rrf_k + item["rank_vector"]) if item.get("rank_vector") else 0.0
        lexical_part = config.lexical_weight / (config.rrf_k + item["rank_lexical"]) if item.get("rank_lexical") else 0.0
        item["score_hybrid"] = vector_part + lexical_part
        item["score"] = item["score_hybrid"]
    return sorted(candidates.values(), key=lambda item: (-item["score_hybrid"],
                  item.get("rank_vector", 10**9), item.get("rank_lexical", 10**9), int(item["id"])))


class Retriever:
    def __init__(self, embedder: Any | None = None, qdrant_client: Any | None = None,
                 collection_name: str | None = None, postgres_connection_factory: Any | None = None,
                 config: RetrievalConfig | None = None) -> None:
        self._embedder = embedder
        self._qdrant = qdrant_client
        self._collection = collection_name
        self._postgres_connection_factory = postgres_connection_factory or get_postgres_connection
        self.config = config or RetrievalConfig.from_env()
        self._embedding_lock = threading.Lock()
        self._lexical_lock = threading.Lock()
        self._lexical_index: BM25Index | None = None
        self.lexical_index_load_seconds = 0.0

    @property
    def embedder(self) -> Any:
        if self._embedder is None:
            self._embedder = BGEM3Embedder()
        return self._embedder

    @property
    def qdrant(self) -> Any:
        if self._qdrant is None:
            self._qdrant = get_qdrant_client()
        return self._qdrant

    @property
    def collection(self) -> str:
        if self._collection is None:
            self._collection = get_collection_name()
        return self._collection

    @staticmethod
    def _validate_top_k(top_k: int) -> int:
        if isinstance(top_k, bool) or not isinstance(top_k, int):
            raise TypeError("top_k deve ser um número inteiro")
        if not MIN_TOP_K <= top_k <= MAX_TOP_K:
            raise ValueError(f"top_k deve estar entre {MIN_TOP_K} e {MAX_TOP_K}")
        return top_k

    def _embed_question(self, question: str) -> list[float]:
        with self._embedding_lock:
            embeddings = self.embedder.encode_texts([question], show_progress_bar=False)
        return list(embeddings[0])

    def initialize(self) -> None:
        _ = self.embedder
        _ = self.qdrant
        _ = self.collection
        if self.config.lexical_enabled:
            self._initialize_lexical_index()

    def _initialize_lexical_index(self) -> None:
        if self._lexical_index is not None:
            return
        with self._lexical_lock:
            if self._lexical_index is not None:
                return
            started = time.perf_counter()
            self._lexical_index = BM25Index(self._fetch_all_chunks(), self.config)
            self.lexical_index_load_seconds = time.perf_counter() - started

    def close(self) -> None:
        close = getattr(self._qdrant, "close", None)
        if callable(close):
            close()

    def _search_qdrant(self, vector: list[float], limit: int) -> list[Any]:
        if hasattr(self.qdrant, "query_points"):
            return list(self.qdrant.query_points(collection_name=self.collection, query=vector,
                        limit=limit, with_payload=True).points)
        return list(self.qdrant.search(collection_name=self.collection, query_vector=vector,
                    limit=limit, with_payload=True))

    @staticmethod
    def _postgres_id(hit: Any) -> int:
        payload = getattr(hit, "payload", None) or {}
        point_id = payload.get("postgres_id", getattr(hit, "id", None))
        try:
            return int(point_id)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Resultado do Qdrant sem postgres_id válido: {point_id!r}") from error

    @staticmethod
    def _row_to_chunk(row: Any) -> dict[str, Any]:
        return {"id": int(row[0]), "documento_id": row[1], "chunk_id": row[2], "titulo": row[3],
                "texto": row[4], "url": row[5], "categoria": row[6], "autor": row[7],
                "data_publicacao": row[8], "source_object": row[9]}

    def _query_chunks(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        connection = self._postgres_connection_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                return [self._row_to_chunk(row) for row in cursor.fetchall()]
        finally:
            connection.close()

    def _fetch_all_chunks(self) -> list[dict[str, Any]]:
        return self._query_chunks("SELECT id, documento_id, chunk_id, titulo, texto, url, categoria, autor, data_publicacao, source_object FROM chunks ORDER BY id")

    def _fetch_chunks(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        if not ids:
            return {}
        chunks = self._query_chunks("SELECT id, documento_id, chunk_id, titulo, texto, url, categoria, autor, data_publicacao, source_object FROM chunks WHERE id = ANY(%s)", (ids,))
        return {chunk["id"]: chunk for chunk in chunks}

    @staticmethod
    def _source_key(item: dict[str, Any]) -> tuple[str, str]:
        if item.get("url"):
            return "url", str(item["url"])
        if item.get("documento_id"):
            return "documento", str(item["documento_id"])
        return "id", str(item["id"])

    def _deduplicate(self, results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        counts: defaultdict[tuple[str, str], int] = defaultdict(int)
        selected = []
        for result in results:
            key = self._source_key(result)
            if counts[key] >= self.config.max_chunks_per_source:
                continue
            counts[key] += 1
            selected.append(result)
            if len(selected) >= limit:
                break
        return selected

    def search(self, question: str, top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
        results, _ = self.search_with_metrics(question, top_k)
        return results

    def search_with_metrics(self, question: str, top_k: int = DEFAULT_TOP_K, *,
                            mode: str | None = None, deduplicate: bool = True) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        started = time.perf_counter()
        top_k = self._validate_top_k(top_k)
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question não pode ser vazia")
        requested_mode = mode or ("hybrid" if self.config.hybrid_enabled else "vector")
        if requested_mode not in {"vector", "lexical", "hybrid"}:
            raise ValueError("modo de recuperação inválido")
        candidate_limit = max(top_k, self.config.initial_candidates)
        metrics: dict[str, Any] = {"lexical_index_load_seconds": self.lexical_index_load_seconds,
            "embedding_seconds": 0.0, "qdrant_seconds": 0.0, "postgres_seconds": 0.0,
            "vector_search_seconds": 0.0, "lexical_search_seconds": 0.0,
            "fusion_seconds": 0.0, "deduplication_seconds": 0.0}
        vector_results: list[dict[str, Any]] = []
        if requested_mode in {"vector", "hybrid"}:
            phase = time.perf_counter(); embedding_started = time.perf_counter()
            vector = self._embed_question(question)
            metrics["embedding_seconds"] = time.perf_counter() - embedding_started
            qdrant_started = time.perf_counter(); hits = self._search_qdrant(vector, candidate_limit)
            metrics["qdrant_seconds"] = time.perf_counter() - qdrant_started
            ranked = [(self._postgres_id(hit), float(getattr(hit, "score", 0.0))) for hit in hits]
            pg_started = time.perf_counter(); chunks = self._fetch_chunks([item[0] for item in ranked])
            metrics["postgres_seconds"] = time.perf_counter() - pg_started
            for rank, (identifier, score) in enumerate(ranked, start=1):
                if identifier in chunks:
                    item = dict(chunks[identifier]); item.update(score=score, score_vector=score, rank_vector=rank)
                    vector_results.append(item)
            metrics["vector_search_seconds"] = time.perf_counter() - phase
        lexical_results: list[dict[str, Any]] = []
        if requested_mode in {"lexical", "hybrid"} and self.config.lexical_enabled:
            lexical_started = time.perf_counter()
            try:
                self._initialize_lexical_index()
                lexical_results = self._lexical_index.search(question, candidate_limit) if self._lexical_index else []
            except Exception:
                lexical_results = []
            metrics["lexical_search_seconds"] = time.perf_counter() - lexical_started
        effective_mode = requested_mode
        fusion_started = time.perf_counter()
        if requested_mode == "lexical":
            ranked_results = [dict(item, score=item["score_lexical"]) for item in lexical_results]
        elif requested_mode == "hybrid" and lexical_results:
            ranked_results = reciprocal_rank_fusion(vector_results, lexical_results, self.config)
        else:
            ranked_results = vector_results
            if requested_mode == "hybrid":
                effective_mode = "hybrid_fallback_vector"
        metrics["fusion_seconds"] = time.perf_counter() - fusion_started
        dedup_started = time.perf_counter()
        final_limit = min(top_k, self.config.final_sources)
        final = self._deduplicate(ranked_results, final_limit) if deduplicate else ranked_results[:final_limit]
        metrics["deduplication_seconds"] = time.perf_counter() - dedup_started
        metrics.update(vector_candidates=len(vector_results), lexical_candidates=len(lexical_results),
                       fused_candidates=len(ranked_results), deduplicated_candidates=len(final),
                       final_sources=len(final), retrieval_mode=effective_mode)
        metrics["total_retriever_seconds"] = time.perf_counter() - started
        metrics["retriever_seconds"] = metrics["total_retriever_seconds"]
        return final, metrics
