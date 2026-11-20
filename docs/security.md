# Segurança e autorização da API

## Identidade e claims

A API valida Firebase Authentication ID tokens com Firebase Admin SDK e `check_revoked=True`. Não aceita segredo estático, sessão simulada ou token emitido pelo próprio backend. O claim customizado `role` precisa ser exatamente `admin`, `auditor` ou `gestor`; `tenant_id` e UID também são obrigatórios. As verificações de assinatura, validade, issuer e audience usam o Firebase Project ID fornecido ao Admin SDK.

`FIREBASE_PROJECT_ID` deve ser configurado somente depois de confirmar que o projeto Firebase Authentication corresponde a `GOOGLE_CLOUD_PROJECT`; a aplicação rejeita IDs divergentes. A configuração local aponta ambos ao projeto esperado. ADC, projeto de quota, Email/Password e o domínio `localhost` foram validados. O bootstrap aprovado do primeiro administrador foi concluído e uma consulta de leitura confirmou as claims esperadas; `/api/health` continua público. Consulte [first-admin-login.md](./first-admin-login.md) para o checklist atualizado.

No desenvolvimento local, o Firebase Admin SDK usa Application Default Credentials para verificar revogação. Em produção, use a identidade de runtime da aplicação, nunca uma chave de usuário ou arquivo de conta de serviço. Atenção: `/api/admin/users` e `/api/admin/users/{uid}/role` usam a Firebase Admin SDK para listar/consultar usuários e atualizar custom claims. Isso requer permissões Firebase Authentication de leitura e atualização no projeto; a permissão de atualização não é isolada por tenant no IAM. Antes de concedê-la ao runtime, revisar um custom role mínimo e aprovar explicitamente o risco, ou separar/desabilitar esse provisionamento. A validação de tenant no endpoint limita o uso normal, mas não reduz o impacto de uma identidade de runtime comprometida. Veja [deployment-readiness.md](./deployment-readiness.md).

Para configurar o primeiro administrador de uma organização, crie primeiro a conta pelo provedor aprovado e, em terminal interativo confiável, execute `uv run python -m backend.scripts.bootstrap_admin`. O comando exige `FIREBASE_PROJECT_ID` e `GOOGLE_CLOUD_PROJECT` coincidentes, confirmação explícita do projeto, do UID existente e do tenant. Ele usa ADC, recusa administradores já existentes nesse tenant (ou sem tenant) e contas que já tenham claims de acesso; não cria usuários/organizações, não altera contas existentes com claims e não adiciona bypass à API. Execute-o por um único operador de cada vez. O primeiro administrador da homologação já foi configurado; para novos tenants, repita o bootstrap controlado somente após confirmar a conta e o tenant aprovados. Para outros usuários do mesmo tenant, use o fluxo de administração autenticado.

O frontend usa Firebase Authentication Web com e-mail/senha ou Google e envia um ID token bearer em cada chamada comercial. As quatro variáveis públicas da aplicação Web estão presentes em `frontend/.env.local` para o projeto confirmado; nenhum segredo de conta de serviço deve ser colocado no frontend. A sessão local foi validada por respostas autenticadas da API sem exibir o ID token. A UI só mostra as seções correspondentes ao claim `role`, mas a API permanece a autoridade para autenticação, autorização e isolamento de tenant.

## Matriz de rotas

| Endpoint | Acesso | Dados/efeito |
|---|---|---|
| `GET /api/health` | Público | Estado do serviço, sem dados comerciais |
| `POST /api/imports/preview` | `admin` | Lê arquivo e persiste prévia do próprio tenant |
| `POST /api/imports/{import_id}/confirm` | `admin` | Confirma importação do próprio tenant |
| `GET /api/imports` | `admin` | Metadados de importações do próprio tenant |
| `GET /api/admin/users` | `admin` | Lista somente usuários com claim `tenant_id` igual ao do administrador |
| `PUT /api/admin/users/{uid}/role` | `admin` | Atualiza role de usuário no próprio tenant; não permite autoalteração nem transferência entre tenants |
| `GET /api/leads`, `GET /api/leads/{lead_id}`, `GET /api/leads/{lead_id}/detail` | `auditor` | Leads e histórico/status do próprio tenant |
| `GET /api/reasons` | `auditor` | Motivos associados a leads do próprio tenant |
| `GET /api/queues/audit`, `GET /api/queues/contact` | `auditor` | Filas e dados de leads do próprio tenant |
| `GET /api/leads/{lead_id}/audit-context` | `auditor` | Mensagens autorizadas, vigentes e do próprio tenant |
| `GET /api/leads/{lead_id}/audits` | `auditor` | Auditorias e evidências do próprio tenant |
| `POST /api/leads/{lead_id}/audits` | `auditor` | Cria auditoria simulada ou tenta modo real sujeito aos bloqueios |
| `POST /api/audits/{audit_id}/reprocess` | `auditor` | Reprocessa auditoria do próprio tenant |
| `POST /api/audits/{audit_id}/review` | `auditor` | Registra decisão/revisão humana do próprio tenant |
| `GET /api/dashboard` | `admin`, `gestor` | Indicadores e contagens agregadas do próprio tenant |
| `GET /api/queues/summary` | `gestor` | Contagens agregadas do próprio tenant |

`/docs`, `/redoc` e `/openapi.json` expõem apenas o contrato da API. Não há endpoint de download/exportação de arquivos, rota direta de mensagens ou operação para alterar/excluir evidências. Conversas só são devolvidas dentro do contexto de auditoria autorizado.

## Isolamento, auditoria e CORS

`tenant_id` é validado no token e aplicado às consultas de leads, importações, auditorias, filas, motivos e indicadores. As revisões 0005 e 0006 adicionam escopo de tenant; registros anteriores permanecem sem tenant e não são retornados. A atribuição desses registros exige uma migração de dados revisada, não uma atribuição automática a uma organização.

Toda mutação autorizada e leituras administrativas de usuários geram `admin_action_logs` com UID, role, tenant, método, rota-template, identificador interno de recurso e resultado HTTP. Corpos, tokens, e-mails, telefones e conteúdo de mensagens não entram nesses logs. A criação do registro de autorização ocorre antes da operação; se o log não puder ser persistido, a chamada é bloqueada.

CORS não aceita `*`, não envia credenciais cross-origin e permite somente origens explicitamente configuradas. `API_CORS_ORIGINS` é uma lista JSON (por exemplo, `["http://localhost:3000"]`), como esperado por Pydantic Settings. O padrão é `http://localhost:3000`; ambientes compartilhados devem configurar somente origens HTTPS aprovadas. `Authorization` é permitido para o bearer token.

Os testes de integração substituem a dependência de identidade por um principal sintético em fixtures; testes de segurança removem essa substituição e exercitam o fluxo protegido com verificação Firebase simulada. Não existe flag de bypass de autenticação no runtime.

## Limitações antes de uso compartilhado/produção

- Definir o onboarding de novos usuários/tenants e validar ADC/IAM da identidade de runtime em cada ambiente.
- Revisar/atribuir os registros antigos sem tenant antes de torná-los acessíveis.
- Revisar origens CORS HTTPS, PostgreSQL, limites compartilhados, retenção e observabilidade antes de implantar. O front-end não autentica com contas de serviço; o endpoint de criação inicial de claims não faz parte da API.
