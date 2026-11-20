# Verificação da Sprint 02

Executado localmente em Windows 11 / PowerShell 5.1, usando somente registros sintéticos:

- `uv run pytest`: **58 testes passaram** com dados sintéticos. Inclui autenticação sem bearer, token inválido, claims inválidos, exigência de verificação de revogação pelo Firebase Admin SDK, separação de roles, isolamento entre tenants e dados legados sem tenant, dashboard administrativo agregado e tenant-scoped, validação do projeto/claims no bootstrap administrativo, prévia/confirmação de XLSX sintético em dois tenants, importação protegida, administração de usuários, logs sem credenciais/contatos, auditoria baseada em evidências, persistência/retensão, tombstones limitados à conversa e bloqueio de chamadas pagas. Há um aviso de depreciação em `google-genai`.
- SQLite temporário: revisões `0001` a `0007` aplicadas; downgrade de `0007`, re-upgrade e `alembic check` aprovados. Nenhum banco local existente foi migrado nesta validação.
- `uv run alembic check`: **nenhuma operação de migração pendente**.
- `uv lock --check`: lockfile consistente.
- `uv run python -m compileall -q backend tests`: compilação Python concluída.
- `npm.cmd run typecheck` e `npm.cmd run build` (executados em `frontend/`): aprovados. A configuração explícita de `turbopack.root` evita que o Next.js use o `package-lock.json` fora do repositório como raiz.
- `npm.cmd audit --omit=dev`: **0 vulnerabilidades** após atualizar a dependência transitiva `@grpc/grpc-js` para faixa corrigida.
- O modo real foi testado somente como bloqueado por padrão; nenhum SDK enviou requisições ao Vertex.

Na homologação local, uma sessão Firebase autenticada carregou `GET /api/dashboard` e `GET /api/imports` com `200`; sem token, ambos retornaram `401`. Uma planilha sintética foi importada pela interface, e o dashboard refletiu um registro `research` no tenant esperado. A conta também foi confirmada por consulta de leitura ao Firebase Admin SDK, sem exibir token ou dados pessoais. O teste multi-tenant permanece sintético e usa banco isolado.

Nenhuma chamada de inferência Vertex AI, ação de Salesforce, mensagem, deploy, habilitação de APIs ou provisionamento de recursos cloud foi realizada. Não foram usados dados reais de clientes ou da BC Energia.
