# Relatório de avaliação da RAG

## Escopo e objetivo

Avaliar de forma reproduzível a decisão de evidência, a recuperação, a resposta e a latência no corpus local indexado.

> Os resultados apresentados são válidos apenas para o conjunto documental local utilizado no experimento. O corpus representa um recorte do Jornal da USP e não deve ser interpretado como uma avaliação de cobertura ou desempenho sobre todo o portal.

## Inventário do corpus

- Chunks no PostgreSQL: 663
- Identidades documentais: 111
- URLs distintas: 110
- Objetos de origem: 102
- Embeddings validados externamente ao benchmark: 663 vetores BGE-M3 no Qdrant.

## Metodologia

O benchmark preliminar contém 20 casos: 10 JSON, 4 PDF e 6 negativos.
Cada resposta positiva exige decisão aceita e recuperação da fonte esperada para ser classificada como TP.

## Critérios de inclusão das perguntas

Perguntas positivas usam apenas trechos diretamente indexados; perguntas negativas usam expressões distintivas confirmadas como ausentes nos 663 chunks. O único PDF recebe somente quatro perguntas não repetitivas.

## Revisão humana do ground truth

Itens aprovados: 0 de 20.

| ID | Pergunta | Respondível | Documento esperado | Revisão |
|---|---|---:|---|---|
| json-001 | O que caracteriza uma cultura de inovação segundo a notícia? | sim | A verdadeira face da cultura de inovação | pending |
| json-002 | Quais efeitos a ampliação do Bolsa Família teve sobre hospitalizações, mortalidade e empregabilidade? | sim | Bolsa Família reduziu hospitalizações e aumentou empregabilidade, aponta estudo | pending |
| json-003 | Como o GeoReDUS facilita o acesso aos dados urbanos do CEM? | sim | CEM transforma dados urbanos em ferramenta para pesquisas e políticas públicas | pending |
| json-004 | Quais mecanismos do canabidiol podem auxiliar na recuperação da fadiga muscular? | sim | Canabidiol ganha espaço no esporte como aliado na recuperação muscular | pending |
| json-005 | Qual é o objetivo do e-book A arte de comer sem glúten? | sim | E-book gratuito reúne opções de lanches sem glúten e de baixo custo desenvolvidas em pesquisas | pending |
| json-006 | Por que a participação humana continua importante em processos seletivos que usam inteligência artificial? | sim | Uso de IA em processos seletivos reitera a importância da participação humana | pending |
| json-007 | Quais riscos da gamificação para crianças e adolescentes são destacados na notícia? | sim | Quando o jogo sai da tela: os riscos da gamificação no cotidiano | pending |
| json-008 | Quais três fatores são apontados como fundamentais para avançar na alfabetização na idade certa? | sim | Alfabetização na idade certa mobiliza formações na Bahia | pending |
| json-009 | Quais tratamentos combinados causaram os danos mais graves aos cabelos no estudo? | sim | Microscópio eletrônico mostra danos estruturais ao cabelo após descoloração, alisamento e calor | pending |
| json-010 | Qual disponibilidade semanal é exigida dos estudantes selecionados para o PET-Saúde Clima? | sim | USP e Secretaria Municipal de Saúde selecionam estudantes para o PET-Saúde Clima | pending |
| pdf-001 | Qual serviço oferece a Jornada SOFt 2026? | sim | Como organizar as finanças e investir melhor? Serviço da USP abre inscrições para curso | pending |
| pdf-002 | Quando ocorre a Jornada SOFt 2026 e qual é o formato do curso? | sim | Como organizar as finanças e investir melhor? Serviço da USP abre inscrições para curso | pending |
| pdf-003 | Quais são os quatro módulos do curso de organização financeira? | sim | Como organizar as finanças e investir melhor? Serviço da USP abre inscrições para curso | pending |
| pdf-004 | Quais são os três pilares da metodologia SOFt? | sim | Como organizar as finanças e investir melhor? Serviço da USP abre inscrições para curso | pending |
| negative-001 | Qual foi o resultado do campeonato intergaláctico de xadrez quântico da USP? | não | recusa segura | pending |
| negative-002 | Quando a USP demonstrou o primeiro teletransporte humano para a Lua? | não | recusa segura | pending |
| negative-003 | Onde foi encontrado o dinossauro lunar estudado pela USP? | não | recusa segura | pending |
| negative-004 | Quem recebeu o Nobel de Física de 2040 por uma pesquisa da USP? | não | recusa segura | pending |
| negative-005 | Como funciona a base submarina da USP na lua Europa de Júpiter? | não | recusa segura | pending |
| negative-006 | Qual energia produz a usina de antimatéria da USP em Saturno? | não | recusa segura | pending |

## Resultados

**Relatório preliminar:** o ground truth ainda não foi integralmente aprovado.
Accuracy, Precision, Recall, F1-score, métricas de recuperação e gráficos não são apresentados como resultados oficiais.

### Matriz de confusão

Não calculada: existem itens com revisão pendente.

### Accuracy, Precision, Recall, F1-score, Specificity e Balanced Accuracy

Não calculadas: existem itens com revisão pendente.

### Métricas de recuperação

Hit Rate@k, Recall@k, MRR e NDCG@3 não calculados nesta etapa preliminar.

### Métricas de latência

Não calculadas: a execução controlada ainda não foi autorizada.

### Gráficos

Não gerados: não existem resultados reais aprovados.

## Protocolo de qualidade das respostas

Fidelidade, cobertura, ausência de informação não sustentada, fonte correta e clareza devem ser avaliadas manualmente em escala 0–2. O modelo avaliado não é usado como único juiz.

## Limitações e ameaças à validade

- O corpus é um recorte controlado, não uma amostra representativa de todo o portal.
- Existe apenas um PDF; métricas por tipo possuem tamanhos muito diferentes.
- O ground truth preliminar possui uma fonte relevante binária por caso.
- Latências dependem do hardware, carga, cold start e estado do Ollama.
- Perguntas negativas sintéticas medem recusa segura, mas não cobrem toda ambiguidade possível.

## Conclusão

Nenhuma conclusão quantitativa oficial deve ser publicada antes da revisão humana e da execução controlada.
