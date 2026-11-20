# Preparação para a Sprint 03

O projeto é uma plataforma independente de auditoria e inteligência de leads. Empresas clientes ou pilotos devem usar `tenant_id` distintos; nenhum tenant deve ser assumido como organização proprietária da plataforma.

## Concluído antes de iniciar

- Revisada a working tree e preservado `frontend/next-env.d.ts`: sua alteração está em commit existente e não há edição local pendente nesse arquivo.
- Alinhado `API_CORS_ORIGINS` do exemplo com o formato JSON de lista consumido por Pydantic Settings.
- Confirmados IDs de projeto Firebase iguais no backend e frontend. As quatro variáveis públicas da aplicação Web estão presentes em `frontend/.env.local`, sem expor seus valores. ADC, quota, Email/Password e o domínio `localhost` foram validados.
- Revisadas autenticação Firebase, claims `role`/`tenant_id`, autorização de rotas e filtros por tenant. A API não tem rota de bypass.
- O bootstrap aprovado do primeiro administrador foi concluído para a conta existente do tenant `lead-intelligence-dev`. Uma consulta de leitura ao Firebase Admin SDK confirmou `role=admin` e o tenant esperado; nenhum usuário foi criado.
- O bootstrap exige exatamente o projeto verificado no backend e também valida o project ID do Firebase Admin app. Administradores podem consultar somente métricas agregadas e importações do próprio tenant no dashboard.
- A interface e os metadados visíveis usam a marca independente Lead Intelligence AI.
- A sessão autenticada local exibiu o perfil Administrador; `GET /api/dashboard` e `GET /api/imports` responderam `200`. As mesmas rotas sem bearer token responderam `401`.
- Uma planilha sintética foi importada localmente, gravada no tenant esperado e refletida nos indicadores. Testes com XLSX sintético em banco isolado cobriram importação e isolamento entre tenants; nenhum dado real foi usado.

## Pendências após as Entregas 1 a 3 da Sprint 03

1. Ampliar a avaliação determinística atual com revisão humana e exemplos aprovados; não ajustar prompts automaticamente em produção.
2. Implementar onboarding, convite e remoção de usuários para novas organizações com autorização mínima e trilha de auditoria. O bootstrap permanece restrito ao primeiro administrador de cada tenant.
3. Definir IDs estáveis para novos tenants e revisar registros legados sem tenant; não atribuí-los automaticamente a uma organização.
4. Antes de dados de clientes em ambiente compartilhado, aprovar política de retenção e base de uso, IAM de runtime, origens HTTPS CORS, limites compartilhados, PostgreSQL, backups e observabilidade.
5. Manter inferência paga, envio de mensagens, integrações reais e deploy bloqueados até autorização e critérios próprios de aceite. O plano de implantação está em [deployment-readiness.md](./deployment-readiness.md).

## Verificações desta etapa

- Na auditoria inicial desta preparação, `uv run pytest` passou com 58 testes e o banco estava na migração `0007`.
- Após as Entregas 1 a 3 da Sprint 03, o banco local também contém a jornada de simulação Karen; o resultado consolidado consta em [sprint-03-progress.md](./sprint-03-progress.md).
- `npm.cmd run typecheck` (executado em `frontend/`): aprovado.
- `npm.cmd run build` (executado em `frontend/`): aprovado; a raiz explícita do Turbopack está em `frontend/next.config.ts`.
- `uv run alembic check`: nenhuma divergência de schema detectada no banco local SQLite.
- O ID token não foi exibido; as chamadas autenticadas foram verificadas pela resposta da API. Para o histórico e o checklist do primeiro login, consulte [first-admin-login.md](./first-admin-login.md) e o [relatório de homologação da Sprint 02](./sprint-02-homologation.md).

Os testes de integração usam Firebase simulado e dados sintéticos; a validação de login real foi feita localmente, sem expor tokens. Nenhuma chamada de inferência paga, mensagem ou deploy foi executado. O SQLite local contém dados sintéticos da homologação da Sprint 02 e da demonstração da Base de Conhecimento; nenhum dado real de cliente foi usado.
