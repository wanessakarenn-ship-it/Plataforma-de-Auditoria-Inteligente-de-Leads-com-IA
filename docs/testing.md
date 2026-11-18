# Verificação da Sprint 01

Executado localmente em Windows 11 / PowerShell 5.1, usando somente registros sintéticos:

- `uv run pytest`: **12 testes passaram** (CSV, XLSX, detecção de cabeçalho, mapeamento, validação, normalização/deduplicação, motivos, filas, histórico, persistência, detalhes de lead e ausência de rotas outbound).
- `uv run alembic upgrade head`: migração inicial aplicada a SQLite local.
- `uv run alembic check`: **nenhuma operação de migração pendente**.
- `uv lock --check`: lockfile consistente.
- `uv run python -m compileall -q backend tests`: compilação Python concluída.
- `npm.cmd ls --depth=0`: dependências resolvidas, nenhuma vulnerabilidade reportada no `npm install`/`npm prune`.
- `npm.cmd run typecheck`: aprovado.
- `npm.cmd run build`: build Next.js concluído.
- Smoke test HTTP local: `/api/health` retornou `ok`, `/api/dashboard` respondeu sem dados de clientes; OpenAPI não contém rotas de envio.

Não foram feitas chamadas de inferência Vertex AI, ações de Salesforce, mensagens, deploy, habilitação de APIs ou provisionamento de recursos cloud.
