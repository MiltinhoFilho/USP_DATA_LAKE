# Troubleshooting

## A RAG demora para iniciar

O BGE-M3 é carregado localmente durante o lifespan da RAG. Confirme que
`HF_CACHE_HOST` aponta para um cache completo e que Pipeline e RAG montam o mesmo
diretório em `/models/huggingface:ro`. Os containers devem possuir
`HF_HUB_OFFLINE=1` e `TRANSFORMERS_OFFLINE=1`.

Não copie pesos para o repositório e não remova o volume de dados para solucionar
um problema de cache.

## O Ollama excede o timeout

Confirme `http://localhost:11434/api/tags`, a presença de `gemma3:4b` e o acesso
do container por `http://host.docker.internal:11434`. A primeira chamada pode
incluir o carregamento do modelo. Use `keep_alive`, evite gerações concorrentes e
faça um warm-up curto antes de uma demonstração.

No ambiente local validado, uma chamada direta fria levou 41,81 s e a seguinte
4,11 s. Em diferentes execuções E2E, perguntas positivas levaram aproximadamente
34,52–121,05 s somente na geração. Esses números são observações, não garantias
para outros hardwares.

## A API retorna 503 em `/pergunta`

- Verifique se PostgreSQL e Qdrant estão ativos.
- Confirme que a coleção configurada existe.
- Confirme que o cache BGE-M3 está legível no container.
- Verifique se o Ollama está ativo e se o modelo configurado está instalado.

Import, OpenAPI, `/` e `/health` não comprovam a disponibilidade desses recursos,
pois deliberadamente não os inicializam nem consultam.

## Uma pergunta é recusada

A recusa é esperada quando os candidatos não oferecem evidência suficiente. A
mensagem se limita ao recorte atualmente indexado e não afirma inexistência no
Jornal da USP inteiro. Consulte os eventos `rag_evidence_decision` em INFO e
`rag_evidence_candidate` em DEBUG. Os logs de candidatos não contêm texto
integral dos documentos.

Não desative o Evidence Check nem reduza limiares sem criar testes específicos
para falsos positivos e falsos negativos.

## Conferir os testes

No Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

A validação atual possui 55 testes. Avisos de depreciação do TestClient/httpx e
do PyPDF2 não representam falha, mas devem ser acompanhados em manutenção futura.
