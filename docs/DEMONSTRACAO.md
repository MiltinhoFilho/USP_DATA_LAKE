# Roteiro de demonstração

## Preparação anterior

1. Confirmar `ollama list` e `gemma3:4b`.
2. Confirmar que `HF_CACHE_HOST` no `.env` aponta para o cache completo do BGE-M3.
3. Subir `docker compose -f docker-compose.yml up -d`.
4. Pré-aquecer Pipeline/RAG e aguardar os health checks; não fazer rebuild durante a apresentação.
5. Conferir `docker compose -f docker-compose.yml ps`.

## Apresentação

1. Explicar o recorte de 100 JSONs + 1 PDF, que reproduz 532 chunks, e o Gold de
   663 registros preservando os 619 históricos.
2. Abrir Generator Swagger em `http://localhost:8001/docs` e executar `/health`.
3. Explicar que `/site` e `/pdf` sempre gravam na Bronze local e somente enviam
   ao MinIO quando `upload_minio=true`, sem repetir scraping desnecessário.
4. Abrir MinIO em `http://localhost:9001` e mostrar `bronze/raw/` quando o upload
   opcional tiver sido executado.
5. Abrir Pipeline Swagger em `http://localhost:8002/docs` e executar `/health`.
6. Explicar `/processar-site`: Bronze → Silver → PostgreSQL/Qdrant Gold.
   Para a carga vetorial, manter `load_postgres=true`, pois o Qdrant depende do
   `postgres_id` gerado pelo PostgreSQL.
7. Mostrar PostgreSQL com 663 chunks e Qdrant com 663 vetores, IDs sincronizados.
8. Abrir RAG Swagger em `http://localhost:8003/docs`.
9. Executar uma pergunta previamente validada do recorte com `top_k=5`; pré-aquecer
   o Ollama porque a geração em CPU pode exceder o tempo de uma demonstração fria.
10. Mostrar resposta, URLs, textos e scores das fontes.
11. Explicar busca híbrida, evidence check e recusa segura.
12. Encerrar reforçando que o recorte não cobre todo o Jornal da USP.

O `/health` da RAG retorna apenas o status da API. A inicialização efetiva do
Retriever ocorre antes, no startup, quando o lifespan carrega BGE-M3, índice BM25
e cliente Qdrant; por isso, aguarde a conclusão do startup antes da demonstração.

## Encerramento seguro

```powershell
docker compose -f docker-compose.yml stop
```

Não usar `down -v`, pois isso excluiria volumes de dados.

## Warm-up e perguntas recomendadas

```powershell
Invoke-RestMethod http://localhost:8003/health
Invoke-RestMethod http://localhost:11434/api/tags

$warm = @{
  model = 'gemma3:4b'; stream = $false; keep_alive = '10m'
  options = @{ temperature = 0; num_predict = 1; num_ctx = 512 }
  messages = @(@{ role = 'user'; content = 'Responda apenas: OK' })
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post http://localhost:11434/api/chat -ContentType 'application/json' -Body $warm

# Aquece o BGE-M3 e confirma recusa sem Ollama
$body = @{ pergunta = 'Qual foi o resultado do campeonato intergaláctico de xadrez quântico da USP?'; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Method Post http://localhost:8003/pergunta -ContentType 'application/json' -Body $body

# JSON
$body = @{ pergunta = 'Quais são os riscos da gamificação no cotidiano?'; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Method Post http://localhost:8003/pergunta -ContentType 'application/json' -Body $body

# PDF
$body = @{ pergunta = 'Quais são os quatro módulos do curso de organização financeira da USP?'; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Method Post http://localhost:8003/pergunta -ContentType 'application/json' -Body $body
```

No relatório local disponível, respostas positivas variaram de aproximadamente
55 a 151 segundos conforme pressão de CPU/memória. Aguarde cada chamada terminar e nunca
execute gerações concorrentes durante a apresentação.

## Resultados E2E observados

Com os serviços aquecidos e `top_k=5`, a validação real mais recente registrou:

| Cenário | Evidence Check | Ollama | Tempo total |
|---|---|---|---:|
| Cultura de inovação — JSON | aceito | executado | 151,093 s |
| Quatro módulos do curso — PDF | aceito | executado | 54,952 s |
| Missões da USP em Marte — externa | recusado | ignorado | 0,867 s |

Os valores acima provêm de `data/rag_demo_report.json`. As duas respostas positivas retornaram título, URL e score. A resposta PDF foi
baseada no trecho que enumera literalmente os quatro módulos. Os tempos refletem
somente o ambiente local observado e podem variar de acordo com CPU, memória,
aceleração e estado frio ou aquecido dos modelos.
