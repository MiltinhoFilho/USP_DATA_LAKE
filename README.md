# USP Data Lake

Pipeline de Engenharia de Dados para coleta, armazenamento, transformacao e vetorizacao de noticias do [Jornal da USP](https://jornal.usp.br/).

## Fluxo implementado

```
Jornal USP
    ↓
Web Scraping
    ↓
JSON bruto
    ↓
MinIO (Bronze)
    ↓
Limpeza HTML -> Markdown
    ↓
Chunks (1200 caracteres / 200 overlap)
    ↓
Embeddings BGE-M3
    ↓
PostgreSQL (texto) + Qdrant (vetores)
```

## Estrutura

```
usp-data-lake/
├── data/                    # staging local ignorado pelo Git
├── bronze/raw/              # JSONs bronze locais ignorados pelo Git
├── src/
│   ├── scraper.py           # coleta noticias do Jornal da USP
│   ├── minio_client.py      # cliente MinIO
│   ├── upload_bronze.py     # upload dos JSONs para MinIO
│   ├── transform.py         # leitura MinIO, limpeza e chunking
│   ├── chunking.py          # regra 1200/200
│   ├── embedding.py         # embeddings com BAAI/bge-m3
│   ├── postgres_loader.py   # armazenamento textual Gold
│   └── qdrant_loader.py     # armazenamento vetorial Gold
├── docker/
│   └── docker-compose.yml
├── docker-compose.yml       # MinIO + PostgreSQL + Qdrant
├── requirements.txt
└── .env.example
```

## Instalação

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Subir infraestrutura

```bash
docker compose up -d
```

- MinIO API: `http://localhost:9000`
- MinIO console: `http://localhost:9001`
- PostgreSQL: `localhost:5432`
- Qdrant: `http://localhost:6333`

## Executar o pipeline

### 1. Web scraping

```bash
python src/scraper.py --limit 10
```

Gera JSON bruto em `data/raw_news.json` e arquivos individuais em `bronze/raw/`.

### 2. Bronze no MinIO

```bash
python src/upload_bronze.py
```

Envia os arquivos para o bucket `bronze`, prefixo `raw/`.

### 3. Transformacao Silver

```bash
python src/transform.py --source minio --output data/chunks.jsonl
```

Essa etapa le os JSONs do MinIO, limpa o HTML, converte o conteudo para Markdown e gera chunks de 1200 caracteres com overlap de 200.

Para testar sem MinIO, usando os JSONs locais:

```bash
python src/transform.py --source local --limit 2 --output data/chunks.jsonl
```

### 4. Gold em PostgreSQL e Qdrant

Execucao em uma chamada:

```bash
python src/transform.py --source minio --load-gold --output data/chunks_postgres.jsonl
```

Ou em etapas separadas:

```bash
python src/postgres_loader.py --input data/chunks.jsonl --output data/chunks_postgres.jsonl
python src/embedding.py --input data/chunks_postgres.jsonl --output data/chunks_embeddings.jsonl
python src/qdrant_loader.py --input data/chunks_embeddings.jsonl
```

O PostgreSQL cria a tabela `chunks`. O Qdrant cria a colecao `usp_news_embeddings`.

O vinculo entre texto e vetor e garantido assim:

- `chunks.id` no PostgreSQL identifica o texto original.
- O mesmo valor e usado como `point_id` no Qdrant.
- O payload do Qdrant tambem guarda `postgres_id`, `documento_id` e `chunk_id`.

## Variaveis de ambiente

Principais valores em `.env.example`:

```env
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=bronze
MINIO_SECURE=false

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=usp_data_lake
POSTGRES_USER=usp
POSTGRES_PASSWORD=usp123

QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=usp_news_embeddings

EMBEDDING_MODEL=BAAI/bge-m3
```

## Parar serviços

```bash
docker compose down
```
