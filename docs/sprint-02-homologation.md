# Relatório de homologação — Sprint 02

- **Data:** 2026-11-20
- **Branch:** `feat/sprint-02-auditoria-ia`

## Firebase Authentication e sessão administrativa

- As quatro variáveis públicas do Firebase Web estão presentes em `frontend/.env.local`; nenhum valor foi exibido.
- O Firebase Admin SDK confirmou, em consulta somente de leitura, `role=admin` e `tenant_id=lead-intelligence-dev` para a conta selecionada.
- A sessão local exibiu o perfil **Administrador**. As requisições da aplicação enviaram um Firebase ID token aceito pela API; o token não foi lido, exibido ou registrado.
- `GET /api/dashboard` e `GET /api/imports` autenticados responderam `200`. As mesmas rotas sem autenticação responderam `401`.
- `/api/health` respondeu `200`.

## Importação, indicadores e isolamento

- A base local estava vazia antes do teste. Foi usada uma única linha CSV sintética, com endereço `.invalid`, e nenhum dado real de cliente ou da BC Energia.
- A prévia respondeu `200`, identificou uma linha válida sem duplicidade, erro ou aviso. A confirmação respondeu `200` e adicionou um registro.
- O registro criado foi verificado no banco local: tenant `lead-intelligence-dev`, classificação `research`.
- Após a importação, o dashboard autenticado respondeu `200` com `total_leads=1` e `classifications={"research":1}`; o histórico de importações respondeu `200` com uma importação concluída.
- O registro sintético permanece no SQLite local para que os indicadores homologados continuem visíveis. O arquivo temporário de upload foi removido.
- Um teste de integração com XLSX sintético em banco isolado cobriu preview e confirmação em dois tenants. Cada administrador viu apenas seu próprio registro/importação; a confirmação de importação de outro tenant respondeu `404`.
- Testes sintéticos confirmaram `403` quando a role admin tenta acessar rotas exclusivas do auditor.

## Verificações

- `uv run pytest`: **58 aprovados**; um aviso de depreciação proveniente do pacote `google-genai`.
- `npm.cmd run typecheck` em `frontend/`: **aprovado**.
- `npm.cmd run build` em `frontend/`: **aprovado**. O build regenerou referências em `frontend/next-env.d.ts`; a alteração automática foi restaurada ao estado versionado.
- Nenhum deploy, commit, push, merge, chamada paga ao Gemini/Vertex AI ou envio de mensagem foi executado.

## Estado após a Sprint 03, Entrega 2

Este relatório preserva os resultados da homologação original da Sprint 02. A suíte
consolidada posterior passou com **70 testes**; a migração atual está em
`0009_knowledge_base`. A aplicação continua sem implantação; a preparação de App
Hosting, Cloud Run e PostgreSQL está descrita em
[deployment-readiness.md](./deployment-readiness.md) e depende de aprovação separada
de custo e segurança.

## Próximos passos para a Sprint 03

1. Construir respostas, fluxos, simulações fictícias e avaliação supervisionada conforme
   o estado atual em [sprint-03-progress.md](./sprint-03-progress.md).
2. Definir onboarding, convites, remoção de usuários e provisionamento de tenants.
3. Revisar registros legados sem tenant antes de disponibilizá-los.
4. Antes do uso compartilhado/produção, aprovar IAM de runtime, origens HTTPS, limites
   de taxa, PostgreSQL, backup, retenção e observabilidade.
5. Manter inferência paga, mensagens e deploy bloqueados até critérios próprios de
   aceite e autorização.
