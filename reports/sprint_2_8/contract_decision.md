# Decisão de contrato editorial — fases 1–8

## Terminologia arquitetural

- **Bronze** é a camada persistida que preserva os documentos de origem.
- **Silver** é uma etapa de transformação não persistida.
- **Golden** é a camada persistida operacional de chunks, embeddings,
  PostgreSQL e Qdrant.

## Estratégia selecionada

Foi selecionada a Opção A:

- manter `conteudo` com o HTML original por compatibilidade;
- adicionar `conteudo_html` com cópia idêntica do HTML original;
- adicionar `conteudo_texto` com a representação editorial limpa;
- adicionar `document_id` derivado do nome canônico.

## Justificativa

O contrato atual ainda é consumido diretamente por:

- `src/scraper.py`;
- `src/transform.py`;
- `src/silver.py`;
- `src/pdf_generator.py`;
- testes de Bronze, PDF e Silver.

Migrar ou remover `conteudo` nesta fase quebraria consumidores existentes. A
opção aditiva mantém compatibilidade e permite validar o novo campo antes de
qualquer publicação.

## Estado de publicação

Os 100 JSONs estruturados existem somente em
`data/sprint_2_8_staging/json/`. Nenhum JSON ou PDF oficial foi publicado ou
regenerado. A adaptação da etapa Silver para priorizar `conteudo_texto`
permanece fora do escopo das fases 1–8.
