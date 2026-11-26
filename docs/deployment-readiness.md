# Preparação de implantação — Lead Intelligence AI

**Estado:** guia de prontidão, não um inventário do ambiente nem uma confirmação de
deploy. Não inclua neste documento IDs de projetos, nomes de recursos, URLs privadas,
caminhos de máquinas, credenciais ou estado operacional não validado. Confirme os
valores e as permissões no ambiente autorizado antes de qualquer alteração.

## Condições e bloqueios

- O estado atual de serviços, autenticação, faturamento, IAM, domínio e rollout não é
  afirmado por este guia; valide-o no console autorizado antes de agir.
- A cadeia Alembic foi exercitada em SQLite descartável. Isso não comprova
  compatibilidade PostgreSQL; valide-a em uma instância PostgreSQL descartável antes
  de qualquer migração persistente.
- Não crie recursos nem aplique migrações sem autorização, alvo descartável confirmado
  e procedimento de validação e limpeza.

## Arquitetura proposta

- **Frontend:** Firebase App Hosting para a aplicação Next.js em `frontend/`, com
  raiz do monorepo configurada como `frontend`. App Hosting tem suporte integrado a
  Next.js, mas exige o plano Blaze e aciona Cloud Build, Cloud Run, Artifact Registry,
  Cloud CDN e Secret Manager conforme a configuração.
- **API:** imagem do [Dockerfile](../backend/Dockerfile) para Cloud Run na região
  aprovada. O serviço precisa aceitar tráfego HTTPS do navegador; Cloud Run IAM
  não deve substituir a autenticação Firebase da aplicação. As rotas protegidas
  continuam exigindo ID token, role e `tenant_id`; `/api/health` não dá acesso a dados.
- **Banco:** PostgreSQL gerenciado, separado do filesystem efêmero do Cloud Run.
  `psycopg` e o Cloud SQL Python Connector suportam autenticação IAM automática no
  SQLAlchemy. Use identidades e privilégios separados para runtime e migrações.
  Nenhuma migração deve ser aplicada a uma instância persistente sem aprovação
  explícita e plano de validação. Não copie bancos locais para a nuvem.
- **Segredos:** com IAM DB Auth automática, não há senha de banco na aplicação. O
  Connector usa ADC da identidade de runtime do Cloud Run; não usar arquivo JSON de
  service account nem credenciais de usuário. Configuração Firebase Web é pública e
  deve ser fornecida como variáveis `NEXT_PUBLIC_*`, disponíveis no build do frontend.

## Configuração preparada

- [backend/Dockerfile](../backend/Dockerfile): Python 3.12, dependências congeladas
  pelo `uv.lock`, usuário não-root e processo Uvicorn no `$PORT`; não executa migrações
  no startup.
- [`.dockerignore`](../.dockerignore): exclui ambientes locais, bancos, uploads,
  dependências e arquivos do frontend do contexto da imagem da API.
- [frontend/apphosting.yaml](../frontend/apphosting.yaml): configuração inicial
  conservadora; valide limites e capacidade para o ambiente aprovado.
- Não copie arquivos de ambiente locais nem credenciais para configurações versionadas.

### Prévia frontend-only

Para uma prévia frontend-only, `frontend/apphosting.yaml` define
`NEXT_PUBLIC_APP_ENV=preview`. Não configurar `NEXT_PUBLIC_API_URL`: a aplicação
bloqueia chamadas ao FastAPI nesse modo, mantém a autenticação Firebase e exibe estados
indisponíveis sem fabricar dados ou sucesso. O simulador Karen mostra somente os nomes
dos cenários sintéticos; registrar uma conversa continua dependendo da API.

Manter essa configuração bloqueada até a API de homologação estar implantada e
validada. Uma futura publicação integrada exige uma alteração explícita e revisada
para `NEXT_PUBLIC_APP_ENV=homologation` e `NEXT_PUBLIC_API_URL=https://<URL-Cloud-Run>/api`
disponíveis durante o build do Next.js; não fazer essa troca como parte da prévia
frontend-only.

No App Hosting, as variáveis públicas da aplicação Web devem ser configuradas a partir
da Firebase Web App existente: `NEXT_PUBLIC_FIREBASE_API_KEY`,
`NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`, `NEXT_PUBLIC_FIREBASE_PROJECT_ID` e
`NEXT_PUBLIC_FIREBASE_APP_ID`. Não transferir arquivos de ambiente locais nem
adicionar tokens, senhas ou credenciais privadas ao frontend. O domínio gerado para a
prévia precisa estar autorizado no Firebase Authentication para permitir login.

Para rollouts integrados que incluam a API, configurar no App Hosting, disponíveis em
**BUILD** e **RUNTIME**, as quatro variáveis Firebase Web já existentes localmente,
além de:

- `NEXT_PUBLIC_API_URL=https://<URL-Cloud-Run>/api`
- `NEXT_PUBLIC_FIREBASE_PROJECT_ID=<FIREBASE_PROJECT_ID>`
- `NEXT_PUBLIC_FIREBASE_API_KEY`, `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN` e
  `NEXT_PUBLIC_FIREBASE_APP_ID`, obtidos da aplicação Web aprovada no Firebase Console.

No Cloud Run configurar `APP_ENV=production`,
`FIREBASE_PROJECT_ID=<FIREBASE_PROJECT_ID>`,
`GOOGLE_CLOUD_PROJECT=<GCP_PROJECT_ID>`, `API_CORS_ORIGINS` como JSON com
somente as origens HTTPS reais do App Hosting/domínio aprovado,
`MESSAGE_RETENTION_DAYS` conforme política aprovada, e as flags de inferência pagas
mantidas desabilitadas. Para o Cloud SQL de homologação, configurar
`CLOUD_SQL_IAM_AUTH=true`,
`CLOUD_SQL_CONNECTION_NAME=<GCP_PROJECT_ID>:<REGION>:<INSTANCE_NAME>`,
`CLOUD_SQL_DB_NAME=<DATABASE_NAME>`,
`CLOUD_SQL_EXECUTION_IDENTITY=<API_RUNTIME_IDENTITY>` e
`CLOUD_SQL_API_RUNTIME_DB_USER` com o usuário PostgreSQL IAM correspondente à
identidade de runtime. A aplicação usa o Cloud SQL Python Connector com psycopg; não
precisa de `DATABASE_URL` nem de senha de banco nesse modo.
O usuário migrador deve ser configurado separadamente no processo de migração, nunca
como fallback do runtime. A seleção de configuração não prova qual principal ADC está
anexado ao Cloud Run ou ao job; confirme a identidade de execução no ambiente GCP antes
de conectar.

### Execução futura de migrações

As migrações não foram executadas nesta etapa. Antes de uma execução aprovada, confirme
o banco, o usuário IAM PostgreSQL e os privilégios necessários na instância. Execute
Alembic em um job/processo controlado com ADC da identidade migradora e estas
configurações explícitas:

```text
APP_ENV=homologation
CLOUD_SQL_CONNECTION_NAME=<GCP_PROJECT_ID>:<REGION>:<INSTANCE_NAME>
CLOUD_SQL_DB_NAME=<DATABASE_NAME>
CLOUD_SQL_IAM_AUTH=true
CLOUD_SQL_EXECUTION_IDENTITY=<MIGRATOR_IDENTITY>
CLOUD_SQL_MIGRATOR_DB_USER=<usuário PostgreSQL IAM do migrador>
GOOGLE_CLOUD_PROJECT=<GCP_PROJECT_ID>
FIREBASE_PROJECT_ID=<FIREBASE_PROJECT_ID>
API_CORS_ORIGINS=["https://<origem-HTTPS-aprovada>"]
VERTEX_AI_ENABLED=false
VERTEX_AI_APPROVED=false
FIREBASE_ADMIN_USER_MANAGEMENT_ENABLED=false
```

Então, somente após aprovação operacional, execute `uv run alembic upgrade head`.
Configure a API separadamente com a identidade de runtime aprovada; a API não executa
migrações no startup.

## Segurança e requisitos de produção

- **Firebase Auth/RBAC:** manter a verificação de ID token, verificação de revogação,
  igualdade do Project ID configurado e claims válidas `role`/`tenant_id`. Habilitar
  no Firebase Auth os provedores aprovados e autorizar o domínio de produção.
- **IAM:** usar identidades distintas para deploy, hosting, API e migrações, com
  privilégios mínimos. Funcionalidades administrativas de usuários podem exigir
  permissões com escopo de projeto; avaliar o impacto e separar ou desabilitar essas
  funções antes de conceder acesso ao runtime. Conceder ao conector e ao migrador
  somente os acessos necessários. Não reutilizar credenciais de usuário nem conceder
  papéis amplos por conveniência. Nenhuma identidade ou permissão deve ser inferida
  deste guia.
- **Tenant:** manter filtros por `tenant_id`, constraints compostas, testes de acesso
  cruzado e registros de ações administrativas. Executar regressão multi-tenant contra
  PostgreSQL antes de receber qualquer dado de cliente.
- **CORS:** origens explícitas HTTPS apenas; nunca `*`. Manter `localhost` somente em
  ambientes locais.
- **Migrações:** aplicar `alembic upgrade head` como etapa controlada/Job único antes
  de enviar tráfego à nova revisão; não iniciar migrações no startup concorrente das
  instâncias.
- **Migração de dados:** não existe utilitário validado de transferência SQLite →
  PostgreSQL. Primeiro aplicar todas as migrações até 0010 a uma instância PostgreSQL
  descartável de teste;
  depois desenvolver e testar um processo de importação idempotente para dados
  explicitamente autorizados, com mapeamento de tenants revisado, contagem por tabela,
  verificações de chaves/isolamento e backup da origem. O SQLite local atual não deve
  ser copiado automaticamente.
- **Backups:** habilitar backups automáticos, PITR e teste periódico de restauração.
  Definir e aprovar frequência e janela de recuperação por ambiente. Backup e retenção
  de conteúdo são controles distintos.
- **Retenção:** a limpeza de conteúdo expirado roda no lifespan de cada instância.
  Antes de escalar, movê-la para execução singleton (Cloud Run Job/Cloud Scheduler ou
  lease distribuído) para evitar trabalho duplicado. Definir e aprovar políticas para
  cada categoria de dados; versões de conhecimento e logs administrativos também
  precisam de uma política explícita.
- **Importações:** `import_batches.records_json` persiste os registros completos do
  preview por tenant, incluindo campos brutos e dados de contato, e é lido na confirmação
  da importação. Não há expurgo automático desses registros. Definir e aprovar uma
  retenção específica antes de introduzir limpeza; a rotina existente de mensagens não
  cobre importações. Definir e aprovar regras de expiração e anonimização antes de
  introduzir limpeza; validar suporte, auditoria e obrigações legais.
- **Operação:** definir limites máximos de instâncias/conexões, alertas, logs sem tokens
  ou conteúdo sensível, revisão de dependências e teste de carga. O limite de orçamento
  do Cloud Run/App Hosting não substitui alertas e monitoramento do billing.

## Custos

Este guia não contém estimativas nem valores de orçamento. Antes de habilitar
faturamento ou criar recursos, calcule os custos com região, dimensionamento,
armazenamento, backups, rede e tráfego efetivamente aprovados. Obtenha aprovação
financeira específica e configure alertas. Não habilite inferência paga nem canais de
mensageria como parte desta preparação.

## Migração, promoção e rollback

1. Aprovar domínio, política de retenção, região, tamanho PostgreSQL, backup/PITR,
   IAM e teto de custo.
2. Validar o Dockerfile e a migração 0009 em PostgreSQL de teste; executar testes de
   autenticação, isolamento e migração de dados sintéticos.
3. Provisionar banco e segredos somente após aprovação; aplicar Alembic em etapa única.
4. Publicar API como revisão Cloud Run sem tráfego, verificar `/api/health`, CORS,
   login e endpoints com token válido/inválido; depois direcionar tráfego.
5. Criar/configurar App Hosting para a raiz `frontend`, fornecer variáveis no build e
   ligar somente a uma branch de release aprovada. App Hosting pode iniciar rollout
   automático em pushes à branch conectada; não conectar uma branch de trabalho sem
   aprovação.
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

## Bootstrap determinístico de banco novo

As revisões Alembic `0001`–`0010` são a cadeia legada e não devem ser reescritas.
Para inicializar um banco novo, existe um baseline Core versionado em
`backend/migrations/bootstrap_schema.py`, independente de `Base.metadata`. O comando
`backend.migrations.bootstrap` exige uma URL SQLite absoluta dentro do diretório
descartável autorizado, o alvo `disposable-test` e a confirmação
`--confirm-disposable`; ele não é executado pela API.

Exemplo somente em POSIX/Linux, para um arquivo SQLite descartável dentro de um
diretório temporário privado criado para esta execução. O diretório é explicitamente
autorizado por `LEAD_INTELLIGENCE_BOOTSTRAP_DIR`:

```sh
export LEAD_INTELLIGENCE_BOOTSTRAP_DIR
LEAD_INTELLIGENCE_BOOTSTRAP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/lead-bootstrap.XXXXXXXX")"
chmod 700 "$LEAD_INTELLIGENCE_BOOTSTRAP_DIR"

uv run python -m backend.migrations.bootstrap \
  --database-url "sqlite:///$LEAD_INTELLIGENCE_BOOTSTRAP_DIR/lead-bootstrap-test.sqlite" \
  --target-environment disposable-test \
  --confirm-disposable
```

O comando recusa tabelas, views, sequências, schemas adicionais ou uma tabela
`alembic_version` preexistentes. Ele cria o schema completo equivalente a
`0010_karen_simulations`, compara tabelas, colunas, tipos, nulabilidade, defaults,
PK/FK, uniques, índices, checks e ações referenciais; só então pede ao Alembic para
registrar `0010_karen_simulations` na mesma conexão/transação. Depois verifica que a
versão registrada é exatamente uma linha e que o schema físico ainda corresponde ao
baseline. A URL não é obtida de arquivos de ambiente nem impressa.

Se a criação, validação ou gravação falhar, o comando não informa sucesso, não tenta
`stamp` como recuperação e não remove objetos. Um destino que tenha ficado parcial deve
ser descartado manualmente somente depois de confirmar que é realmente descartável;
uma nova execução deve recusá-lo no preflight. O argumento `--confirm-disposable` é
uma declaração operacional, não uma prova automática de que o servidor remoto é de
testes. Por isso todas as URLs PostgreSQL são bloqueadas nesta etapa, inclusive
localhost e Cloud SQL. O diretório descartável pode ser controlado pela variável
`LEAD_INTELLIGENCE_BOOTSTRAP_DIR` e deve existir sem symlinks. Caminhos relativos,
absolutos fora desse diretório, equivalentes por `..`, symlinks e o nome persistente
de um banco persistente conhecido pela aplicação são rejeitados antes da criação do
engine.

Antes da criação do engine, o processo obtém um lock exclusivo associado ao caminho
do banco. O lock permanece durante preflight, criação, validação inicial, stamp,
validação posterior e liberação da transação. Uma segunda execução recebe falha
segura de concorrência. Falhas antes da tentativa de stamp são reportadas separadamente
das falhas posteriores à tentativa de stamp.

Proteção adicional contra substituição:

- todos os componentes do caminho são examinados antes da normalização e os
  symlinks/reparse points são rejeitados;
- o diretório temporário privado é criado pelo processo ou deve ser um diretório
  existente sem symlinks, próprio do usuário e não gravável por outros usuários;
- a identidade física do arquivo (`st_dev`/`st_ino` em sistemas POSIX e identidade
  de arquivo quando fornecida pelo runtime Windows) é capturada após a aquisição do
  lock e revalidada antes do preflight, criação, stamp e confirmação do sucesso;
- remoção ou substituição do alvo interrompem o bootstrap com erro.

Em SQLite não existe uma API de abertura por handle que SQLAlchemy possa manter
através de substituições arbitrárias do nome do arquivo. Em POSIX, um diretório
privado com modo `0700` impede escrita por outros usuários, mas não remove a ameaça
de um processo malicioso executando com o mesmo UID. Em Windows, a implementação exige
uma identidade de arquivo utilizável pelo runtime; se ela não estiver disponível,
o bootstrap é bloqueado em vez de continuar. Reparse points não são tratados como
caminhos seguros. Mesmo com lock cooperativo, testes não podem prometer proteção
contra um usuário privilegiado ou administrador que substitua o arquivo externamente.

Bancos existentes continuam no fluxo legado de `alembic upgrade head`; o bootstrap
não tenta inferir ou reparar revisões intermediárias. Inspecionar e reconciliar
qualquer schema que não corresponda à versão registrada antes de migrar. PostgreSQL
está preparado no manifesto para tipos JSON, TIMESTAMPTZ, FKs compostas e ações
referenciais, mas ainda não foi homologado em PostgreSQL descartável. SQLite local
não é evidência suficiente dessa compatibilidade. Downgrades permanecem potencialmente
destrutivos e não são uma estratégia de rollback; preferir revisões forward e
restauração aprovada.
