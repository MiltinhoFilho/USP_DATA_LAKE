# Arquitetura

## Fluxo

```text
Jornal da USP → Generator API → MinIO Bronze
MinIO Bronze → Pipeline API → Silver → PostgreSQL + Qdrant Gold
Pergunta → RAG API → Retriever híbrido → avaliação de evidências
        → Ollama local → resposta fundamentada com fontes
```

## Componentes

- **Generator API:** coleta controlada de site e PDF e grava os artefatos brutos.
- **MinIO/Bronze:** preserva os objetos como recebidos; não é uma API do projeto.
- **Pipeline API:** lê Bronze, limpa HTML ou extrai PDF, normaliza em texto/Markdown
  e cria chunks de 1200 caracteres com overlap 200.
- **PostgreSQL/Gold:** guarda chunk, título, URL, autor, categoria e data.
- **Qdrant/Gold:** guarda vetores BGE-M3 com distância cosseno e payload com
  `postgres_id`, `documento_id` e `chunk_id`.
- **Cache de embeddings:** Pipeline monta o cache BGE-M3 já existente no host em
  modo somente leitura e opera com Hugging Face/Transformers offline. Pesos não
  pertencem ao repositório nem ao contexto de build.
- **Retriever:** combina busca vetorial, BM25 e RRF, deduplica URLs e avalia a
  suficiência das evidências.
- **Ollama:** executa `gemma3:4b` localmente e só é chamado com evidência suficiente.
- **RAG API:** preserva contrato estável e retorna resposta, textos e fontes com
  rastreabilidade opcional até documento, chunk e objeto Bronze.

## Acervo e Gold validados

O Bronze possui 100 JSONs e 1 PDF (101 objetos e 101 URLs). A transformação atual
gera 528 chunks JSON e 4 PDF. O Gold possui 663 linhas/vetores porque preserva os
619 registros históricos e acrescenta 44 chunks de dez documentos cujos nomes de
arquivo colidiam com identidades anteriores; esses documentos recebem IDs
determinísticos derivados da URL. PostgreSQL e Qdrant usam o mesmo ID, dimensão
1024 e distância Cosine.

O PDF é validado pela assinatura, extraído página por página e mantém ordem,
título, URL e `source_object`. JSON e PDF com a mesma notícia permanecem como
origens distintas, sem apagar qualquer origem válida.

## Limitações

O acervo não representa todo o Jornal da USP. Cold start do BGE-M3 em Docker e
geração CPU-only do Ollama são lentos no hardware disponível; os serviços devem
ser pré-aquecidos. A implementação atual não inclui nuvem, autenticação, agentes
ou reranker.

## Etapa conversacional

1. O BGE-M3 gera o embedding local da pergunta.
2. O Retriever combina Qdrant, BM25 e RRF.
3. O Evidence Check avalia cobertura e sinais híbridos. Evidências complexas
   podem combinar título e corpo somente com rank lexical/híbrido 1 e sinal
   vetorial forte.
4. O contexto remove duplicações, agrupa chunks do mesmo documento e preserva a
   melhor fonte dentro do orçamento de 6.000 caracteres.
5. O Ollama `gemma3:4b` gera no máximo 96 tokens e permanece carregado por 10 minutos.

O cache BGE-M3 é montado na Pipeline e na RAG como somente leitura; ambas usam
`HF_HUB_OFFLINE=1` e `TRANSFORMERS_OFFLINE=1`. Import, OpenAPI e health não iniciam
PostgreSQL, Qdrant, embeddings ou Ollama.

## Rastreabilidade e diagnóstico

As fontes públicas mantêm os campos históricos e podem incluir `document_id`,
`chunk_id`, `postgres_id`, `source_type` e `source_object`. A API deriva o tipo de
origem sem alterar os registros Gold. A decisão do Evidence Check gera um resumo
em INFO; detalhes de scores, rankings e metadados ficam em DEBUG, sem texto
integral do documento e sem exposição no payload HTTP.
