# Sprint 2.7.2 — Correção controlada da Bronze

## 1. Resumo executivo

A intervenção mínima autorizada foi tentada uma única vez sobre os 100 PDFs
canônicos. O comando `icacls` encerrou no primeiro arquivo com código 5
(`Acesso negado`), registrando zero arquivos processados com sucesso e uma
falha. Conforme o procedimento aprovado, a operação não foi repetida e nenhuma
outra correção de ACL ou proprietário foi tentada.

Uma verificação somente leitura após a falha confirmou que os 100 PDFs e os 100
JSONs mantiveram seus hashes SHA-256. As ACLs dos 100 PDFs continuam protegidas,
sem regras herdadas. A correção, portanto, não foi aplicada.

## 2. Estado Git

- Branch: `main`
- Commit de referência: `8081fba Adiciona documentação técnica e framework de avaliação`
- O estado preexistente do código foi preservado.
- A única inclusão desta sprint é o diretório autorizado de relatórios
  `reports/sprint_2_7_2/`.
- Nenhum arquivo do Bronze, Silver, Golden, APIs ou frontend foi editado.

## 3. Escopo da intervenção

O padrão foi validado previamente e selecionava exatamente:

```text
C:\Projetos\usp-data-lake-main\bronze\raw\usp_news_000001.pdf
...
C:\Projetos\usp-data-lake-main\bronze\raw\usp_news_000100.pdf
```

Foram encontrados 100 PDFs e 100 JSONs. Nenhum arquivo estava vazio e o padrão
não alcançava JSONs, diretórios ou arquivos fora da faixa canônica.

## 4. Comando executado

```powershell
icacls "C:\Projetos\usp-data-lake-main\bronze\raw\usp_news_*.pdf" /inheritance:e
```

O comando foi executado uma única vez.

Resultado:

- código de saída: `5`;
- arquivos informados como processados com sucesso: `0`;
- falhas informadas: `1`;
- primeiro arquivo: `usp_news_000001.pdf`;
- mensagem: `Acesso negado`.

Os arquivos `usp_news_000002.pdf` a `usp_news_000100.pdf` não foram reportados
como processados pelo comando.

## 5. Baseline anterior

- PDFs inventariados: 100;
- hashes PDF: 100;
- JSONs inventariados: 100;
- hashes JSON: 100;
- PDFs vazios: 0;
- JSONs vazios: 0;
- assinaturas `%PDF-` inválidas: 0;
- hashes PDF duplicados: 0;
- hashes JSON duplicados: 0;
- PDFs com ACL protegida: 100.

O baseline detalhado está em:

- `pre_correction_inventory.json`;
- `pre_correction_hashes.json`;
- `pre_correction_acl.json`.

## 6. ACL antes e depois

### Antes

- proprietário dos PDFs: `CodexSandboxOffline`;
- `AreAccessRulesProtected=True`: 100;
- regras herdadas: 0;
- regras DENY: 0.

### Depois da tentativa

- proprietário: inalterado;
- `AreAccessRulesProtected=True`: 100;
- PDFs com regras herdadas: 0;
- regras DENY adicionadas: 0.

Nenhuma alteração de proprietário, `/grant`, `/reset`, `takeown` ou segunda
tentativa foi executada.

## 7. Comparação de hashes

| Tipo | Iguais | Divergentes |
|---|---:|---:|
| PDF | 100 | 0 |
| JSON | 100 | 0 |

O conteúdo binário permaneceu integralmente preservado. Os dados completos
estão em `post_correction_hashes.json` e `hash_comparison.json`.

## 8. Validação como Milton

Não foi possível avançar para a validação como Milton porque a herança não foi
ativada. A conta utilizada pelo comando não obteve autoridade para modificar a
DACL do primeiro PDF.

Permanecem pendentes:

- `Get-FileHash` dos PDFs como Milton;
- leitura binária como Milton;
- abertura pelo `PdfReader` como Milton;
- extração textual como Milton;
- abertura manual no VS Code;
- abertura manual no navegador.

## 9. Reconciliação e testes

A reconciliação Bronze/Silver e os testes de PDF/Bronze/Silver não foram
executados. O procedimento determinava interrupção imediata em caso de falha
parcial da correção.

## 10. Infraestrutura preservada

- nenhum PDF foi regenerado;
- nenhum JSON foi alterado;
- Silver não foi persistida;
- Golden não foi acessada ou modificada;
- PostgreSQL não foi acessado;
- Qdrant não foi acessado;
- Retriever não foi executado;
- Ollama não foi executado;
- APIs e frontend não foram alterados.

## 11. Próxima ação proposta

É necessária nova autorização e um contexto Windows que possua autoridade para
alterar a DACL, provavelmente um terminal administrativo controlado pelo
usuário. O comando não deve ser repetido automaticamente nesta sessão.

Não há justificativa atual para alterar proprietário, conceder `Full Control`,
usar `/grant`, `/reset` ou `takeown`.

## 12. Quality Gate

| Item | Status | Observação |
|---|---|---|
| Estado Git preservado | PASSOU | Código preexistente intacto |
| Baseline pré-correção registrado | PASSOU | Três relatórios JSON |
| 100 PDFs selecionados | PASSOU | Faixa canônica completa |
| 100 JSONs preservados | PASSOU | 100 hashes idênticos |
| Somente `/inheritance:e` executado | PASSOU | Uma tentativa |
| Nenhum `takeown` executado | PASSOU | Confirmado |
| Nenhum `/grant` executado | PASSOU | Confirmado |
| Nenhum `/reset` executado | PASSOU | Confirmado |
| Nenhum `/setowner` executado | PASSOU | Confirmado |
| Herança ativada nos 100 PDFs | FALHOU | 100 ainda protegidos |
| Zero DENY | PASSOU | Nenhum DENY |
| 100 PDFs legíveis como Milton | FALHOU | ACL não corrigida |
| 100 hashes PDF como Milton | FALHOU | ACL não corrigida |
| 100 hashes PDF preservados | PASSOU | 100/100 |
| 100 hashes JSON preservados | PASSOU | 100/100 |
| Zero PDF vazio | PASSOU | 0 |
| Zero JSON vazio | PASSOU | 0 |
| 100 assinaturas PDF válidas | PASSOU | 100/100 no baseline |
| 100 PDFs abertos por PdfReader | PENDENTE | Interrompido |
| Extração textual | PENDENTE | Interrompida |
| Reconciliação JSON × PDF | PENDENTE | Interrompida |
| Testes Bronze | PENDENTE | Interrompidos |
| Testes Silver | PENDENTE | Interrompidos |
| Validação manual no VS Code | PENDENTE | Requer Milton |
| Validação manual no navegador | PENDENTE | Requer Milton |
| Nenhum PDF regenerado | PASSOU | Confirmado |
| Nenhum conteúdo modificado | PASSOU | Hashes idênticos |
| Silver não persistida | PASSOU | Confirmado |
| Golden não modificada | PASSOU | Confirmado |
| PostgreSQL não acessado | PASSOU | Confirmado |
| Qdrant não acessado | PASSOU | Confirmado |
| Retriever não executado | PASSOU | Confirmado |
| Ollama não executado | PASSOU | Confirmado |
| Nenhuma ação destrutiva | PASSOU | Confirmado |
| Relatório gerado | PASSOU | Este documento |

## 13. Decisão

**SPRINT 2.7.2 REPROVADA — CORREÇÃO INCOMPLETA OU DIVERGÊNCIA DETECTADA**
