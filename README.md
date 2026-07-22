# Intelligent News RAG Platform

Plataforma local de Engenharia de Dados e recuperação inteligente para acervos
jornalísticos e documentais.

## Visão geral

Plataforma experimental que integra Engenharia de Dados, APIs FastAPI e RAG
conversacional totalmente local. A implementação atual valida o fluxo completo
com um recorte do Jornal da USP, sem representar a cobertura integral do portal.

## Escopo do acervo

O MinIO Bronze contém o recorte aprovado: 100 objetos JSON e 1 PDF, todos com URL
já registrada. A transformação integral reproduz 528 chunks JSON e 4 chunks PDF
(532 no total). O Gold validado possui 663 registros no PostgreSQL e 663 vetores
no Qdrant: os 619 registros anteriores foram preservados e 44 chunks foram
acrescentados com IDs determinísticos para resolver colisões de identidade nos
dez primeiros nomes de arquivo. Esse recorte não representa todo o conteúdo
publicado pelo Jornal da USP e pode ser ampliado futuramente.

> As respostas são baseadas em um recorte de notícias do Jornal da USP atualmente
> indexado no Data Lake e podem não representar todo o conteúdo publicado no site.

## Arquitetura

```text
Jornal da USP
  → Generator API
  → MinIO / Bronze
  → Pipeline API
  → Silver: limpeza, Markdown e chunks
  → Gold: PostgreSQL + Qdrant
  → Retriever: BGE-M3 + BM25 + RRF
  → avaliação de evidências
  → Ollama local / gemma3:4b
  → RAG API / resposta com fontes
```

### Arquitetura Medalhão

- **Bronze:** JSON/PDF bruto preservado no MinIO.
- **Silver:** texto limpo e normalizado, dividido em chunks de até 1200 caracteres
  com overlap de 200.
- **Gold:** texto/metadados no PostgreSQL e embeddings BGE-M3 no Qdrant, ligados
  por `postgres_id`.

## Serviços e portas

| Serviço | Porta | Função |
|---|---:|---|
| Generator API | 8001 | Coleta e geração da Bronze |
| Pipeline API | 8002 | Bronze → Silver → Gold |
| RAG API | 8003 | Consulta conversacional e fontes |
| PostgreSQL | 5432 | Gold textual |
| Qdrant | 6333 | Gold vetorial |
| MinIO API / Console | 9000 / 9001 | Armazenamento Bronze |
| Ollama | 11434 | LLM local `gemma3:4b` |

## APIs

- Generator: `GET /health`, `GET /site`, `GET /pdf`.
- Pipeline: `GET /health`, `POST /processar-site`, `POST /processar-pdf`;
  `/site` e `/pdf` são aliases legados.
- RAG: `GET /`, `GET /health`, `POST /pergunta`.

Swagger: [Generator](http://localhost:8001/docs),
[Pipeline](http://localhost:8002/docs) e [RAG](http://localhost:8003/docs).

## Tecnologias

Python 3.12, FastAPI, Docker Compose, MinIO, PostgreSQL, Qdrant, BGE-M3,
BM25, Reciprocal Rank Fusion, Ollama e Gemma 3 4B.

## Estrutura oficial

```text
src/api/generator_api.py   # Generator API
src/api/pipeline_api.py    # Pipeline API
src/api/rag_api.py         # RAG API
src/retriever.py           # busca híbrida e evidências
src/llm_service.py         # Ollama local
tests/                     # unittest
docs/                      # arquitetura, APIs e demonstração
docker-compose.yml         # Compose oficial
docker/docker-compose.yml  # alternativa mantida por compatibilidade
Dockerfile                 # imagem das APIs
```

O Docker oficial usa exclusivamente as aplicações em `src/api/`.

## Instalação no Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -r requirements-api.txt
Copy-Item .env.example .env
```

Instale o Ollama separadamente e confirme que `gemma3:4b` já está disponível.
Nenhuma chave de API é necessária.

Antes de subir o Pipeline, ajuste `HF_CACHE_HOST` no `.env` para um cache local
completo do `BAAI/bge-m3`. O Compose monta esse diretório como somente leitura no
container; os pesos não devem ser copiados para o repositório.

## Subir e parar

```powershell
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml ps
```

Parar sem excluir volumes:

```powershell
docker compose -f docker-compose.yml stop
```

O primeiro carregamento do BGE-M3 consome memória e pode ser demorado. Pré-aqueça
Pipeline e RAG antes da apresentação e evite rebuild ao vivo. O mesmo cache offline
é montado explicitamente como somente leitura nos dois serviços.

## Demonstração

```powershell
Invoke-RestMethod http://localhost:8001/health
Invoke-RestMethod http://localhost:8002/health
$body = @{ pergunta = 'Quais pesquisas da USP tratam de inteligência artificial?'; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8003/pergunta -ContentType 'application/json' -Body $body
```

Payload seguro do pipeline para uma amostra existente:

```json
{"source":"minio","limit":1,"load_postgres":false,"load_qdrant":false}
```

## Testes

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

A validação atual executa 55 testes unitários e de contrato. Importação, OpenAPI
e health checks não carregam embeddings nem acessam serviços externos.

## Segurança e limitações

- Geração exclusivamente local pelo Ollama; não há OpenAI ativa.
- Embeddings locais BGE-M3.
- Recusa segura quando a evidência é insuficiente.
- Implementação limitada aos 100 JSONs e ao PDF existentes; não é solução de produção nem
  cobertura integral.
- CPU/RAM disponíveis tornam cold start e geração do Ollama lentos.

## Fluxo e otimização da RAG

```text
Pergunta → BGE-M3 local → Hybrid Retriever → Evidence Check
         → contexto deduplicado → Ollama local → resposta com fontes
```

Recuperação localiza candidatos; o Evidence Check impede que resultados fracos
cheguem ao modelo; somente então o Ollama redige a resposta. A RAG carrega o
BGE-M3 uma vez no lifespan, usa cache offline/read-only, limita o contexto a 6.000
caracteres e três documentos, remove textos duplicados e agrupa chunks do mesmo
documento. O Ollama usa `temperature=0.1`, `num_predict=96`, `num_ctx=2048`,
`keep_alive=10m` e conexão HTTP reutilizável.

Perguntas sem evidência retornam recusa limitada ao acervo, com
`evidence_sufficient=false` e `ollama_skipped=true`. A resposta expõe métricas
seguras de recuperação, contexto e geração.

Cada fonte preserva `id`, `titulo`, `url`, `texto` e `score` e também pode expor
`document_id`, `chunk_id`, `postgres_id`, `source_type` e `source_object`. Os
campos adicionais são opcionais e retrocompatíveis. `source_type` é derivado dos
metadados disponíveis como `json`, `pdf` ou `unknown`; nenhum dado Gold é alterado
para preencher a resposta.

A API registra em INFO um resumo da decisão de evidência e, em DEBUG, scores,
rankings e metadados dos candidatos. O texto integral dos documentos não é
incluído no diagnóstico.

## Validação conversacional observada

Três chamadas reais foram executadas no ambiente local com BGE-M3 e
`gemma3:4b`: uma notícia JSON respondeu em 144,17 s; o PDF respondeu em 47,69 s;
e uma pergunta externa foi recusada em 19,20 s sem chamar o Ollama. Esses tempos
são observações do hardware de desenvolvimento, não metas ou garantias de
desempenho. Consulte o roteiro de demonstração para as perguntas utilizadas.

## Inventário validado

- MinIO: bucket `bronze`, prefixos `raw/` e `raw/pdf/`, 101 objetos válidos.
- URLs: 101 URLs distintas do recorte; 100 responderam 2xx na primeira checagem e
  a única que expirou respondeu 200 na repetição isolada. Nenhum link foi seguido.
- PDF: assinatura válida, 1 página integralmente extraída, 3.523 caracteres e 4
  chunks com título, URL e `source_object` preservados.
- Gold: PostgreSQL/Qdrant em 663/663, IDs e `postgres_id` sincronizados, vetores
  BGE-M3 com dimensão 1024 e distância Cosine.
- Idempotência: segunda carga dos 528 chunks JSON e dos 4 chunks PDF criou zero
  registros e zero vetores novos.

## Próximos passos opcionais

Expansão controlada do acervo, observabilidade e interface simples podem ser
avaliadas futuramente; não fazem parte da implementação atual.

Consulte [Arquitetura](docs/ARQUITETURA.md), [API](docs/API.md) e
[Demonstração](docs/DEMONSTRACAO.md). Para falhas operacionais, consulte
[Troubleshooting](docs/TROUBLESHOOTING.md).
