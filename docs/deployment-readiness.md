# Preparação de implantação — Lead Intelligence AI

**Estado:** somente planejamento local; nenhum serviço, API, banco ou backend App
Hosting foi criado. Nenhum deploy foi executado. Projeto-alvo existente:
`prime-amulet-439718-e3`, região proposta `us-central1`.
O estado atual de faturamento/Blaze, APIs habilitadas, IAM e quotas não foi consultado
nem alterado nesta etapa; precisa ser confirmado antes de qualquer provisionamento.

## Arquitetura proposta

- **Frontend:** Firebase App Hosting para a aplicação Next.js em `frontend/`, com
  raiz do monorepo configurada como `frontend`. App Hosting tem suporte integrado a
  Next.js, mas exige o plano Blaze e aciona Cloud Build, Cloud Run, Artifact Registry,
  Cloud CDN e Secret Manager conforme a configuração.
- **API:** imagem do [Dockerfile](../backend/Dockerfile) para Cloud Run em
  `us-central1`. O serviço precisa aceitar tráfego HTTPS do navegador; Cloud Run IAM
  não deve substituir a autenticação Firebase da aplicação. As rotas protegidas
  continuam exigindo ID token, role e `tenant_id`; `/api/health` não dá acesso a dados.
- **Banco:** Cloud SQL for PostgreSQL, separado do filesystem efêmero do Cloud Run.
  `psycopg` já está declarado e `DATABASE_URL` suporta PostgreSQL; a migração 0009,
  contudo, só foi validada localmente com SQLite. Não copiar o SQLite local para a
  nuvem sem autorização explícita e plano de saneamento.
- **Segredos:** Secret Manager para a URL/senha do banco. A identidade de runtime usa
  ADC do próprio Cloud Run; não usar arquivo JSON de service account nem credenciais
  de usuário. Configuração Firebase Web é pública e deve ser fornecida como variáveis
  `NEXT_PUBLIC_*`, disponíveis no build do frontend.

## Configuração preparada

- [backend/Dockerfile](../backend/Dockerfile): Python 3.12, dependências congeladas
  pelo `uv.lock`, usuário não-root e processo Uvicorn no `$PORT`; não executa migrações
  no startup.
- [`.dockerignore`](../.dockerignore): exclui ambientes locais, bancos, uploads,
  dependências e arquivos do frontend do contexto da imagem da API.
- [frontend/apphosting.yaml](../frontend/apphosting.yaml): configuração inicial
  conservadora com zero instâncias mínimas e limite de três instâncias.
- Não há valores de `frontend/.env.local` ou credenciais copiados para esses arquivos.

### Prévia frontend-only

Para a prévia solicitada, `frontend/apphosting.yaml` define
`NEXT_PUBLIC_APP_ENV=preview`. Não configurar `NEXT_PUBLIC_API_URL`: a aplicação
bloqueia chamadas ao FastAPI nesse modo, mantém a autenticação Firebase e exibe estados
indisponíveis sem fabricar dados ou sucesso. O simulador Karen mostra somente os nomes
dos cenários sintéticos; registrar uma conversa continua dependendo da API.

Na consulta somente leitura do Firebase Authentication, Email/Senha estava ativado e
Google não aparecia como provedor ativo. A tela de login da prévia deixa Google
indisponível; nenhum provedor ou usuário foi alterado.

No App Hosting, as variáveis públicas da aplicação Web devem ser configuradas a partir
da Firebase Web App existente: `NEXT_PUBLIC_FIREBASE_API_KEY`,
`NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`, `NEXT_PUBLIC_FIREBASE_PROJECT_ID` e
`NEXT_PUBLIC_FIREBASE_APP_ID`. Não transferir arquivos `.env.local` inteiros nem
adicionar tokens, senhas ou credenciais privadas ao frontend. O domínio gerado para a
prévia precisa estar autorizado no Firebase Authentication para permitir login.

Para rollouts integrados que incluam a API, configurar no App Hosting, disponíveis em
**BUILD** e **RUNTIME**, as quatro variáveis Firebase Web já existentes localmente,
além de:

- `NEXT_PUBLIC_API_URL=https://<URL-Cloud-Run>/api`
- `NEXT_PUBLIC_FIREBASE_PROJECT_ID=prime-amulet-439718-e3`
- `NEXT_PUBLIC_FIREBASE_API_KEY`, `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN` e
  `NEXT_PUBLIC_FIREBASE_APP_ID`, obtidos da aplicação Web aprovada no Firebase Console.

No Cloud Run configurar `APP_ENV=production`,
`FIREBASE_PROJECT_ID=prime-amulet-439718-e3`,
`GOOGLE_CLOUD_PROJECT=prime-amulet-439718-e3`, `API_CORS_ORIGINS` como JSON com
somente as origens HTTPS reais do App Hosting/domínio aprovado,
`MESSAGE_RETENTION_DAYS` conforme política aprovada, e as flags de inferência pagas
mantidas desabilitadas. `DATABASE_URL` deve ser injetada como segredo, não como texto
em YAML, linha de comando ou Git.

## Segurança e requisitos de produção

- **Firebase Auth/RBAC:** manter a verificação de ID token, verificação de revogação,
  igualdade do Project ID configurado e claims válidas `role`/`tenant_id`. Habilitar
  no Firebase Auth os provedores aprovados e autorizar o domínio de produção.
- **IAM:** criar identidades separadas para deploy, App Hosting e API. Há um requisito
  que precisa de decisão antes da produção: `/api/admin/users` e
  `/api/admin/users/{uid}/role` usam `list_users`, `get_user` e `set_custom_user_claims`.
  Portanto, o runtime precisaria de `firebaseauth.users.get`,
  `firebaseauth.users.update` e `serviceusage.services.use`, além do acesso ao segredo
  e ao Cloud SQL. A permissão de atualização é de projeto, não de tenant; embora o
  endpoint valide a role e o tenant, comprometimento do runtime ampliaria o impacto
  a contas Firebase do projeto. Revisar um custom role mínimo e decidir entre aceitar
  esse risco ou separar/desabilitar o provisionamento de roles antes de conceder IAM.
  Não conceder papel amplo `Firebase Authentication Admin` por conveniência. O
  bootstrap administrativo permanece um procedimento operacional separado.
- **Tenant:** manter filtros por `tenant_id`, constraints compostas, testes de acesso
  cruzado e registros de ações administrativas. Executar regressão multi-tenant contra
  PostgreSQL antes de receber qualquer dado de cliente.
- **CORS:** origens explícitas HTTPS apenas; nunca `*`. Manter `localhost` somente em
  ambientes locais.
- **Migrações:** aplicar `alembic upgrade head` como etapa controlada/Job único antes
  de enviar tráfego à nova revisão; não iniciar migrações no startup concorrente das
  instâncias.
- **Migração de dados:** não existe utilitário validado de transferência SQLite →
  PostgreSQL. Primeiro aplicar 0009 a uma instância PostgreSQL descartável de teste;
  depois desenvolver e testar um processo de importação idempotente para dados
  explicitamente autorizados, com mapeamento de tenants revisado, contagem por tabela,
  verificações de chaves/isolamento e backup da origem. O SQLite local atual não deve
  ser copiado automaticamente.
- **Backups:** habilitar backups automáticos, PITR e teste periódico de restauração.
  Proposta inicial para aprovação: backup diário e janela de recuperação de 7 dias,
  em região aprovada. Backup e retenção de conteúdo são controles distintos.
- **Retenção:** a limpeza atual elimina conteúdo de mensagens expiradas após 90 dias,
  mas roda no lifespan de cada instância. Antes de escalar, movê-la para execução
  singleton (Cloud Run Job/Cloud Scheduler ou lease distribuído) para evitar trabalho
  duplicado. Definir também retenção para versões de conhecimento e logs administrativos,
  que hoje não têm expiração equivalente.
- **Operação:** definir limites máximos de instâncias/conexões, alertas, logs sem tokens
  ou conteúdo sensível, revisão de dependências e teste de carga. O limite de orçamento
  do Cloud Run/App Hosting não substitui alertas e monitoramento do billing.

## Estimativa preliminar de custos

Valores em USD, antes de impostos/câmbio; são referências públicas e não uma cotação
nem aprovação de gasto:

- **App Hosting:** exige Blaze. A documentação informa quotas sem custo para certos
  componentes e um exemplo de aproximadamente **US$ 0,01/mês para 10 mil visitas** e
  **US$ 69,58/mês para 1 milhão de visitas**, conforme hipóteses de cache, tamanho de
  resposta e requisições. O valor real pode divergir bastante.
- **Cloud Run:** com escala para zero e limites `minInstances=0`, consumo baixo pode
  ficar dentro das quotas mensais sem custo (incluem 2 milhões de requisições no modelo
  por requisição); imagens, rede, logs e uso agregado do billing continuam relevantes.
- **Cloud SQL PostgreSQL:** não tem custo zero equivalente para banco persistente.
  Como referência, 1 vCPU e 3,75 GiB em `us-central1` usando as taxas publicadas
  consultadas equivale a cerca de **US$ 49/mês de compute** (730 h), antes de disco,
  backups, PITR e rede. Alta disponibilidade aproximadamente dobra compute/memória,
  para cerca de **US$ 99/mês**, mais armazenamento e backup.
- **Custos adicionais possíveis:** Artifact Registry, Cloud Build, Secret Manager,
  Cloud Logging, Cloud Storage, egress, rede privada/connector e backups. App Hosting
  pode criar/usar esses produtos automaticamente.

**Recomendação antes da aprovação:** usar o Google Cloud Pricing Calculator com
região, tamanho, HA, armazenamento, backups e tráfego escolhidos; revisar o orçamento
com responsável do projeto e criar alertas antes de habilitar billing/deploy. Não
ativar Gemini/Vertex AI nem WhatsApp nesta etapa.

## Migração, promoção e rollback

1. Aprovar domínio, política de retenção, região, tamanho PostgreSQL, backup/PITR,
   IAM e teto de custo.
2. Validar o Dockerfile e a migração 0009 em PostgreSQL de teste; executar testes de
   autenticação, isolamento e migração de dados sintéticos.
3. Provisionar banco e segredos somente após aprovação; aplicar Alembic em etapa única.
4. Publicar API como revisão Cloud Run sem tráfego, verificar `/api/health`, CORS,
   login e endpoints com token válido/inválido; depois direcionar tráfego.
5. Criar/configurar App Hosting para a raiz `frontend`, fornecer variáveis no build e
   ligar a uma branch de release aprovada. App Hosting pode iniciar rollout automático
   em cada push à branch conectada; não conectar a branch de trabalho sem aprovação.
6. Smoke tests multi-tenant, importação sintética, dashboard e acesso administrativo;
   monitorar erros e custo antes de ampliar tráfego.

Para rollback da API, redirecionar tráfego para a revisão Cloud Run anterior. Para o
frontend, usar o rollout estável anterior quando disponível ou reverter o commit e
acionar novo rollout controlado. Usar migrações aditivas/expand-contract; não executar
`alembic downgrade` automaticamente em produção. Restaurar banco somente por processo
aprovado, com backup/PITR e avaliação de perda de gravações posteriores.

## Referências oficiais consultadas

- [Firebase App Hosting](https://firebase.google.com/docs/app-hosting)
- [Custos do Firebase App Hosting](https://firebase.google.com/docs/app-hosting/costs)
- [Configuração de App Hosting e variáveis/segredos](https://firebase.google.com/docs/app-hosting/configure)
- [Preços do Cloud Run](https://cloud.google.com/run/pricing)
- [Preços do Cloud SQL](https://cloud.google.com/sql/pricing)
- [Backups e recuperação do Cloud SQL](https://cloud.google.com/sql/docs/postgres/backup-recovery/backups)
