# APIs

## Generator API — porta 8001

- `GET /health` → `{"status":"ok","service":"generator-api"}`
- `GET /site?limit=1&max_pages=1&upload_minio=false`
- `GET /pdf?url=https://exemplo/documento.pdf&upload_minio=false`

`/site` coleta notícias em JSON; `/pdf` salva um PDF na Bronze. Erros de validação
retornam 422 e falhas controladas de coleta retornam 4xx/5xx.

## Pipeline API — porta 8002

- `GET /health`
- `POST /processar-site`
- `POST /processar-pdf`

Payload:

```json
{"source":"minio","limit":1,"load_postgres":true,"load_qdrant":true}
```

`source` aceita `minio` ou `local`; `limit` deve ser nulo ou inteiro ≥1. Cargas Gold
são idempotentes por documento/chunk. Aliases `/site` e `/pdf` estão depreciados.

## RAG API — porta 8003

- `GET /`
- `GET /health`
- `POST /pergunta`

```json
{"pergunta":"Quais pesquisas da USP tratam de inteligência artificial?","top_k":5}
```

Resposta:

```json
{
  "status": "ok",
  "service": "rag-api",
  "pergunta": "Quais são os quatro módulos do curso de organização financeira da USP?",
  "resposta": "Os quatro módulos do curso são: Habilidade financeira, Planejamento financeiro, Investimentos e Crédito e Endividamento.",
  "fontes": [
    {
      "id": 6246,
      "titulo": "Como organizar as finanças e investir melhor? Serviço da USP abre inscrições para curso",
      "url": "https://jornal.usp.br/universidade/como-organizar-as-financas-e-investir-melhor-servico-da-usp-abre-inscricoes-para-curso/",
      "texto": "Trecho recuperado do documento...",
      "score": 0.04841188524590164,
      "document_id": "identificador-do-documento",
      "chunk_id": 2,
      "postgres_id": 6246,
      "source_type": "pdf",
      "source_object": "raw/pdf/arquivo.pdf"
    }
  ],
  "total_fontes": 1,
  "evidence_sufficient": true,
  "ollama_skipped": false,
  "metrics": {"source_count": 1}
}
```

Cada fonte preserva `id`, `titulo`, `url`, `texto` e `score`. Os campos opcionais
`document_id`, `chunk_id`, `postgres_id`, `source_type` e `source_object` ampliam
a rastreabilidade sem quebrar clientes anteriores. `source_type` é derivado como
`json`, `pdf` ou `unknown`, sem modificar PostgreSQL ou Qdrant.

Pergunta curta ou `top_k` fora de 1–20 retorna 422. Indisponibilidade do Ollama
retorna 503; ausência de evidência retorna HTTP 200 com recusa segura e sem
chamada ao modelo.

### Logging interno

Em INFO, a API registra decisão, motivo e contagem de candidatos. Em DEBUG,
registra scores vetorial/BM25/RRF, rankings, termos cobertos, IDs e metadados de
origem. O texto integral recuperado e a pergunta não são registrados nesses
eventos. Os detalhes diagnósticos não integram o contrato HTTP.

Swagger: `http://localhost:8001/docs`, `:8002/docs`, `:8003/docs`.
