# USP Data Lake

Pipeline de Engenharia de Dados para coleta, armazenamento e processamento de notícias do [Jornal da USP](https://jornal.usp.br/).

## Primeira entrega

Fluxo implementado:

```
Jornal da USP → Web Scraping → JSON local → MinIO (Bronze)
```

### Camada Bronze

Dados brutos, sem limpeza ou transformação — exatamente como extraídos do site.

## Estrutura do projeto

```
usp-data-lake/
├── data/                  # staging local (raw_news.json agregado)
├── bronze/raw/            # arquivos bronze individuais
├── src/
│   ├── scraper.py         # coleta notícias do Jornal da USP
│   ├── minio_client.py    # cliente MinIO
│   └── upload_bronze.py   # upload para camada Bronze
├── docker/
│   └── docker-compose.yml # MinIO local
├── notebooks/
├── requirements.txt
└── .env.example
```

## Pré-requisitos

- Python 3.10+
- Docker e Docker Compose

## Instalação

```bash
cd usp-data-lake
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Subir o MinIO

```bash
cd docker
docker compose up -d
```

- API S3: `http://localhost:9000`
- Console web: `http://localhost:9001`
- Credenciais padrão: `minioadmin` / `minioadmin123`

## Executar o pipeline

### 1. Web scraping

```bash
python src/scraper.py --limit 10
```

Gera:

- `data/raw_news.json` — todas as notícias em um arquivo
- `bronze/raw/usp_news_001.json`, `usp_news_002.json`, ... — um arquivo por notícia

Campos extraídos:

| Campo | Descrição |
|---|---|
| `titulo` | Título da notícia |
| `autor` | Autor |
| `data` | Data de publicação |
| `categoria` | Categoria |
| `conteudo` | HTML bruto do corpo |
| `url` | URL da notícia |

### 2. Upload para MinIO (Bronze)

```bash
python src/upload_bronze.py
```

Envia os arquivos de `bronze/raw/` para o bucket `bronze` com prefixo `raw/`:

```
bronze/raw/usp_news_001.json
```

## Validar a entrega

1. **Scraping:** verifique que `data/raw_news.json` contém notícias com todos os campos.
2. **Bronze local:** confira os arquivos em `bronze/raw/`.
3. **MinIO:** acesse `http://localhost:9001`, entre no bucket `bronze` e confirme os objetos em `raw/`.

## Arquitetura (visão geral)

```
Jornal USP
    ↓
Web Scraping          ← você está aqui
    ↓
MinIO (Bronze)        ← você está aqui
    ↓
Silver (limpeza)      ← futuro
    ↓
Gold (chunks + embeddings) ← futuro
    ↓
Qdrant + Postgres + IA
```

## Variáveis de ambiente

Copie `.env.example` para `.env`:

```
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=bronze
MINIO_SECURE=false
```

## Parar o MinIO

```bash
cd docker
docker compose down
```
