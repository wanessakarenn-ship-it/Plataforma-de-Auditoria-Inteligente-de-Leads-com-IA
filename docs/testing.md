# Verificação da Sprint 02

Executado localmente em Windows 11 / PowerShell 5.1, usando somente registros sintéticos:

- `uv run pytest`: **49 testes passaram** com dados sintéticos. Inclui autenticação sem bearer, token inválido, claims inválidos, exigência de verificação de revogação pelo Firebase Admin SDK, separação de roles, isolamento entre tenants e dados legados sem tenant, importação protegida, administração de usuários, logs sem credenciais/contatos, auditoria baseada em evidências, persistência/retensão, tombstones limitados à conversa e bloqueio de chamadas pagas.
- SQLite temporário: revisões `0001` a `0007` aplicadas; downgrade de `0007`, re-upgrade e `alembic check` aprovados. Nenhum banco local existente foi migrado nesta validação.
- `uv run alembic check`: **nenhuma operação de migração pendente**.
- `uv lock --check`: lockfile consistente.
- `uv run python -m compileall -q backend tests`: compilação Python concluída.
- `npm.cmd run typecheck` e `npm.cmd run build`: aprovados após adicionar login Firebase e chamadas autenticadas por token.
- `npm.cmd audit --omit=dev`: **0 vulnerabilidades** após atualizar a dependência transitiva `@grpc/grpc-js` para faixa corrigida.
- O modo real foi testado somente como bloqueado por padrão; nenhum SDK enviou requisições ao Vertex.

Nenhuma chamada de inferência Vertex AI, ação de Salesforce, mensagem, deploy, habilitação de APIs ou provisionamento de recursos cloud foi realizada. A planilha Salesforce original não foi encontrada; o cabeçalho e os tipos foram testados com fixture sintética. Firebase ID tokens reais não foram usados nos testes; o login real exige os valores públicos da aplicação web e provedor configurado no Firebase.
