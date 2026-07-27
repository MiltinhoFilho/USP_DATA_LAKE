# Frontend — Chatbot Jornal da USP

Interface estática em HTML, CSS e JavaScript puro para a RAG API do projeto.
As respostas são limitadas ao recorte de 100 notícias atualmente indexadas e não
representam todo o acervo do Jornal da USP.

## Contrato utilizado

- API: `http://localhost:8003`
- Saúde: `GET /health`
- Perguntas: `POST /pergunta`
- Corpo: `{"pergunta": "...", "top_k": 5}`
- Resposta principal: `resposta`
- Fontes: `fontes`

A URL pode ser ajustada na constante `API_URL`, no início de `app.js`.

## Execução

Na raiz do projeto, com a infraestrutura e a RAG API já iniciadas:

```powershell
C:\Projetos\usp-data-lake-main\.venv\Scripts\python.exe -m http.server 8080 --directory frontend
```

Depois, abra `http://localhost:8080` no navegador.

Para interromper apenas o frontend, pressione `Ctrl+C` no terminal que executa o
servidor estático. O backend e seus contêineres não serão interrompidos.

## CORS

A RAG API atual não registra `CORSMiddleware`. Assim, navegadores bloqueiam a
chamada direta de `http://localhost:8080` para `http://localhost:8003` mesmo que
ambos os serviços estejam ativos. O backend não foi alterado.

Para uma execução sem mudança no código da API, utilize um proxy local que sirva
o frontend e encaminhe `/api/pergunta` e `/api/health` para a porta 8003 sob a
mesma origem; nesse caso, ajuste `API_URL` para `/api/pergunta`.

Se for autorizada uma correção mínima no backend, o arquivo a revisar é
`src/api/rag_api.py`. A solução é registrar o middleware CORS do FastAPI/Starlette
permitindo explicitamente as origens locais usadas na apresentação, por exemplo
`http://localhost:8080` e `http://127.0.0.1:8080`. Não utilize `*` em conjunto
com credenciais.

## Ordem de inicialização para a apresentação

1. Inicie o Ollama e confirme o modelo configurado com `ollama list`.
2. Execute `docker compose -f docker-compose.yml up -d --build`.
3. Confira `docker compose -f docker-compose.yml ps`.
4. Valide `http://localhost:8003/health`.
5. Inicie o servidor estático do frontend ou o proxy de mesma origem.
6. Abra o endereço do frontend no navegador.

## Perguntas de demonstração

Com evidência conhecida no recorte:

- `Quais são os riscos da gamificação no cotidiano?`
- `Quais são os quatro módulos do curso de organização financeira da USP?`

Fora do escopo, para demonstrar a recusa segura:

- `Quais missões tripuladas da USP chegaram a Marte em 2035?`

Antes da apresentação, valide as três perguntas no ambiente que será utilizado.
