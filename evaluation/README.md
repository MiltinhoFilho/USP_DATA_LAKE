# Avaliação quantitativa da RAG

Este diretório contém um benchmark reproduzível e limitado ao corpus local
indexado. Ele não avalia todo o Jornal da USP e não sustenta generalizações sobre
conteúdo ausente do recorte.

## Estado atual

- 20 casos preliminares: 10 JSON, 4 PDF e 6 fora do corpus.
- Todos os casos estão com `review_status: "pending"`.
- Nenhuma métrica oficial foi calculada.
- Nenhuma execução completa foi iniciada.

O inventário contém 663 chunks, 111 identidades documentais, 110 URLs e 102
objetos de origem. As diferenças decorrem das identidades históricas preservadas
no Gold. Há 110 identidades JSON/659 chunks e uma identidade PDF/4 chunks.

## Arquivos

- `corpus_inventory.json`: inventário completo exportado do PostgreSQL.
- `questions.json`: entradas estáveis do benchmark.
- `ground_truth.json`: fontes, trechos e respostas para revisão humana.
- `run_benchmark.py`: executor sequencial com checkpoint JSONL.
- `metrics.py`: classificação, recuperação e latência.
- `report.py`: relatório preliminar ou final.
- `results/`: resultados brutos locais.
- `reports/`: relatório e figuras derivadas somente de resultados reais.

## Revisão humana obrigatória

Para cada item, confira no corpus indexado:

1. se a pergunta é realmente respondível;
2. se título, URL, `document_id` e `source_object` estão corretos;
3. se o trecho sustenta diretamente a resposta de referência;
4. se o rótulo positivo ou negativo está correto;
5. se não há conhecimento externo na resposta.

Somente depois altere o `review_status` do item para `approved`. A revisão deve
ser registrada por uma pessoa; geração automática não constitui aprovação.

## Tabela para revisão

| Grupo | Quantidade | Critério |
|---|---:|---|
| JSON | 10 | Fonte e trecho de categorias variadas do corpus |
| PDF | 4 | Questões distintas sustentadas pelos quatro chunks do único PDF |
| Fora do corpus | 6 | Expressões distintivas com zero ocorrência lexical nos 663 chunks |

O detalhamento por pergunta está no relatório preliminar.

## Piloto depois da aprovação

O executor bloqueia itens pendentes por padrão. Após a aprovação humana, execute
um piloto sequencial de três casos — um de cada grupo:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_benchmark --ids json-001 pdf-003 negative-001
```

Para validar apenas o formato antes da aprovação, é possível usar explicitamente
`--allow-pending`; esse resultado continua preliminar e não libera métricas.

Cada linha é salva e sincronizada imediatamente em
`evaluation/results/results.jsonl`. Uma retomada ignora IDs já concluídos. Não
execute perguntas em paralelo no ambiente local.

## Execução completa

Somente após aprovação do ground truth e do piloto:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_benchmark
.\.venv\Scripts\python.exe -m evaluation.report
```

Com base nas latências E2E já observadas, o piloto de três casos deve demandar
aproximadamente 4–10 minutos. Os 20 casos devem demandar aproximadamente 30–50
minutos, podendo se aproximar de 70 minutos com cold starts ou pressão de CPU.
O JSONL deve ocupar menos de 1 MB sem textos integrais das fontes.

Essas estimativas são específicas do hardware local e devem ser recalculadas a
partir do piloto. O checkpoint permite retomar a execução após timeout ou falha.

## Métricas

Somente casos aprovados entram em TP, TN, FP, FN, Accuracy, Precision, Recall,
F1-score, Specificity, Balanced Accuracy, FPR e FNR. Um positivo só é TP quando
o Evidence Check aceita e uma fonte relevante esperada é recuperada.

Hit Rate, Recall@k e MRR usam a fonte rotulada. Como há uma única fonte relevante
binária por caso preliminar, Hit Rate@k e Recall@k coincidem. NDCG@3 permanece
indisponível até existir relevância graduada suficiente.

A qualidade textual é separada e requer avaliação humana 0–2 para fidelidade,
cobertura, ausência de informação não sustentada, fonte correta e clareza.

> Os resultados são válidos apenas para o conjunto documental local utilizado no
> experimento. O corpus representa um recorte do Jornal da USP e não deve ser
> interpretado como avaliação de cobertura ou desempenho sobre todo o portal.
