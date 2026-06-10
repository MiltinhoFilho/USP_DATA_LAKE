# USP Data Lake - Apresentação do Projeto

## Slide 1: Visão Geral do Projeto

**Objetivo**
- Construir um pipeline de engenharia de dados
- Processar conteúdo de múltiplas fontes (Jornal da USP, arquivos PDF)
- Armazenar, transformar e vetorizar dados
- Possibilitar buscas semânticas e análises

**Stack Tecnológico**
- MinIO: Armazenamento de objetos (Bronze)
- PostgreSQL: Banco de dados relacional (Gold)
- Qdrant: Banco de dados vetorial (Gold)
- Python: Orquestração e processamento
- Docker: Containerização do pipeline

---

## Slide 2: Arquitetura - Camadas de Dados

### Estrutura em 3 Camadas

```
BRONZE LAYER (Raw Data)
├── JSON do Jornal da USP
└── Arquivos PDF (novo)
    ↓
SILVER LAYER (Cleaned & Processed)
├── HTML limpo para Markdown
├── Extração de texto de PDFs
└── Chunking (1200 caracteres / 200 overlap)
    ↓
GOLD LAYER (Business Ready)
├── PostgreSQL: Texto completo indexado
└── Qdrant: Vetores (embeddings BGE-M3)
```

**Benefício**: Separação clara de responsabilidades, fácil manutenção e rastreamento de dados

---

## Slide 3: Fluxo de Dados Detalhado

### Etapa 1: Ingestão (Bronze)
- **Fonte 1**: Web Scraping do Jornal da USP
  - Coleta automática de notícias
  - Armazenamento em JSON
  
- **Fonte 2**: Upload de PDFs
  - Inserção manual de documentos
  - Suporte nativo a PDF

- **Destino**: MinIO (armazenamento S3-compatível)

---

## Slide 4: Fluxo de Dados - Transformação (Silver)

### Etapa 2: Limpeza e Chunking
- **Entrada**: JSONs e PDFs do MinIO
- **Processamento**:
  - Extração de texto (HTML → Markdown para JSON)
  - Extração de texto para PDFs (PyPDF2)
  - Remoção de ruído (scripts, estilos, publicidades)
  - Divisão em chunks de 1200 caracteres com overlap de 200

- **Saída**: Chunks estruturados em JSONL

**Exemplo de chunk**:
```
{
  "documento_id": "usp_news_000001_001",
  "chunk_id": 1,
  "texto": "...",
  "titulo": "...",
  "url": "...",
  "categoria": "..."
}
```

---

## Slide 5: Fluxo de Dados - Armazenamento (Gold)

### Etapa 3: Carregamento em Gold

#### PostgreSQL (Texto)
- Armazena chunks completos indexados
- Permite buscas por palavra-chave
- Mantém rastreabilidade: documento_id, chunk_id, timestamps
- Tabela `chunks` com constraints de integridade

#### Qdrant (Vetores)
- Embeddigns BGE-M3 (multilíngue, 384 dimensões)
- Permite buscas semânticas (similaridade coseno)
- Point ID = PostgreSQL ID (vínculo 1:1)
- Payload armazena metadados: título, URL, categoria

**Resultado**: Texto + Vetor sincronizados para buscas híbridas

---

## Slide 6: Suporte a PDF - Novo Requisito

### Integração com PDFs

**Desafio Original**: Pipeline era exclusivamente JSON

**Solução Implementada**:
- Biblioteca PyPDF2 para extração de texto
- Detecção automática de tipo de arquivo (.json vs .pdf)
- Processamento transparente no pipeline existente
- Metadados genéricos para PDFs (título baseado no nome do arquivo)

**Fluxo**:
```
PDF → Extrair Texto → Limpar → Chunking → Gold
```

**Benefício**: Reutilização de todo o pipeline para múltiplos formatos

---

## Slide 7: Containerização com Docker

### Arquitetura de Containers

```
docker-compose.yml
├── minio (container)
│   └── Porta 9000 (API) / 9001 (Console)
├── postgres (container)
│   └── Porta 5432 (conexão)
├── qdrant (container)
│   └── Porta 6333 (API)
└── app (container - NOVO)
    └── Python + Dependências
       └── Pipeline executável
```

**Vantagem**: 
- Isolamento de ambientes
- Reprodutibilidade garantida
- Fácil deploy em qualquer máquina
- Integração entre serviços via Docker network

---

## Slide 8: Container App - Detalhes

### Dockerfile do Pipeline

**Camadas do build**:
1. Base: Python 3.12 slim
2. Dependências do sistema: gcc, libxml2, libxslt1
3. Pip upgrade + Requirements (torch, pandas, transformers, etc.)
4. Código-fonte copiado

**Vantagem**: 
- Build reproducível
- Cache eficiente de dependências
- Imagem otimizada (~2GB com torch)

**Execução**:
```powershell
docker compose run --rm app python src/transform.py --source local
```

---

## Slide 9: Impedimentos Enfrentados

### 1. Tamanho das Dependências
- **Problema**: torch (531MB), CUDA libraries (1.2GB total)
- **Impacto**: Build demorado (18 minutos), imagem grande
- **Solução**: Aceitação de trade-off: qualidade de embedding vs tamanho

### 2. Caminhos de Arquivo em Windows
- **Problema**: Docker compose busca arquivo em diretório errado
- **Impacto**: Comando falhava se não estivesse no diretório correto
- **Solução**: Uso de caminhos absolutos com `-f` flag

### 3. Integração Multi-Serviço
- **Problema**: Comunicação entre 4 containers diferentes
- **Impacto**: Variáveis de ambiente, nomes de host (minio vs localhost)
- **Solução**: Configuração centralizada no docker-compose.yml

---

## Slide 10: Impedimentos - Continuação

### 4. Extração de PDF
- **Problema**: PDFs com encoding complexo, caracteres especiais
- **Impacto**: Perda de formatação ou erros de extração
- **Solução**: PyPDF2 + normalização de texto após extração

### 5. Dependência do PostgreSQL
- **Problema**: Chunks precisam ser inseridos no PG antes de ir para Qdrant
- **Impacto**: Sequência obrigatória de etapas
- **Solução**: Orchestração via `--load-gold` que executa em ordem

### 6. Performance de Embedding
- **Problema**: BGE-M3 lento para grandes volumes
- **Impacto**: Tempo de processamento alto (batch processing necessário)
- **Solução**: Batch size configurável (default 16), GPU suportada

---

## Slide 11: Dificuldades Técnicas Resolvidas

| Desafio | Causa | Resolução |
|---------|-------|-----------|
| **Build longo** | Dependencies (torch, CUDA) | Cache eficiente, imagem otimizada |
| **Paths incorretos** | Diretório de execução variável | Caminhos absolutos |
| **Conexão MinIO** | Docker network name resolution | Env vars com nome interno do service |
| **PDF encoding** | Caracteres especiais | Normalização pós-extração |
| **Consistência dados** | IDs entre PG e Qdrant | Foreign key via postgres_id |
| **Memory overflow** | Embeddings em batch grande | Batch size configurável |

---

## Slide 12: Fluxo Operacional - Passo a Passo

### 1. Iniciar Infraestrutura
```
docker compose -f docker/docker-compose.yml up -d --build
```
→ MinIO, PostgreSQL, Qdrant, App prontos

### 2. Preparar Dados
- Colocar JSONs em `bronze/raw/`
- Colocar PDFs em `bronze/raw/`

### 3. Executar Pipeline
```
docker compose run --rm app python src/transform.py --source local --load-gold
```
→ Processa, limpa, chunking, PostgreSQL, Qdrant

### 4. Resultado
- PostgreSQL: `chunks` table pronta
- Qdrant: `usp_news_embeddings` collection com vetores
- Pronto para buscas semânticas!

---

## Slide 13: Métricas e Performance

### Capacidade do Pipeline

| Métrica | Valor | Notas |
|---------|-------|-------|
| **Tamanho chunk** | 1200 caracteres | Configurável |
| **Overlap** | 200 caracteres | Mantém contexto |
| **Modelo embedding** | BGE-M3 | 384 dimensões |
| **Batch size** | 16 (default) | Configurável |
| **Tempo build** | ~18 min | Primeira vez |
| **Tempo processamento** | ~10s por PDF | Estimado |
| **PostgreSQL rows** | Ilimitado | Escalável |
| **Qdrant points** | Ilimitado | Escalável |

---

## Slide 14: Benefícios da Solução

✅ **Escalabilidade**: Arquitetura em camadas, múltiplos formatos  
✅ **Reprodutibilidade**: Docker garante ambiente idêntico  
✅ **Flexibilidade**: JSON e PDF processados pelo mesmo pipeline  
✅ **Rastreabilidade**: Cada chunk vinculado ao documento original  
✅ **Performance**: Busca em texto + busca semântica  
✅ **Manutenibilidade**: Código modularizado, separação de responsabilidades  
✅ **DevOps**: Containerização facilita deploy  

---

## Slide 15: Próximas Etapas Sugeridas

### Curto Prazo
- Testes com volumes maiores de PDF
- Otimização de batch size para GPU
- Dashboard de monitoramento

### Médio Prazo
- API REST para consultas (FastAPI)
- Web UI para busca semântica
- Integração com sistema externo

### Longo Prazo
- Fine-tuning de embeddings para domínio específico (USP)
- Processamento em streaming
- Replication/failover do PostgreSQL

---

## Slide 16: Conclusão

### Projeto Alcançado

**Objetivo Inicial**: ✅ Completo
- Pipeline de dados funcional
- Suporte a JSON e PDF
- Armazenamento em Bronze/Silver/Gold
- Containerização Docker

**Novo Requisito**: ✅ Implementado
- PDF handling integrado
- Pipeline reutilizável
- Docker-ready

**Aprendizados Principais**
- Importância de arquitetura em camadas
- Docker como ferramenta essencial para reprodutibilidade
- Trade-offs: tamanho vs qualidade (torch)
- Coordenação de múltiplos serviços

---

## Slide 17: Obrigado!

**Perguntas?**

---

# Notas Adicionais

## Ambiente de Execução

**Sistema Operacional**: Windows 10/11  
**Container Runtime**: Docker Desktop  
**Python Version**: 3.12 (dentro do container)  
**Armazenamento**: Local (volumes Docker)

## Acessos Durante Desenvolvimento

- MinIO Console: http://localhost:9001
- PostgreSQL: localhost:5432 (user: usp, db: usp_data_lake)
- Qdrant API: http://localhost:6333

## Comandos Úteis

```powershell
# Ver logs do container app
docker compose logs -f app

# Acessar shell do container
docker compose exec app /bin/bash

# Parar infraestrutura
docker compose down

# Limpar volumes
docker compose down -v
```
