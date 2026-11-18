# BC Lead Intelligence

Aplicação local-first para importar, classificar e auditar leads. A Sprint 02 inclui auditoria simulada baseada em citações de mensagens autorizadas, histórico independente de conversas e preparo opt-in do Vertex AI. Não há envio de mensagens, integração mutável com Salesforce nem provisionamento de recursos Google Cloud.

## Requisitos

- Python 3.12–3.14 e `uv`
- Node.js 20.9+ e npm
- PostgreSQL para ambientes compartilhados/produção; SQLite é usado por padrão em desenvolvimento local

## Executar localmente (PowerShell)

Na raiz deste repositório:

```powershell
Copy-Item .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn backend.app.main:app --reload
```

Em outro terminal:

```powershell
cd frontend
Copy-Item .env.example .env.local
npm.cmd install
npm.cmd run dev
```

Preencha em `frontend/.env.local` os valores públicos da aplicação Web Firebase vinculada ao projeto confirmado; habilite o provedor de login escolhido no Firebase Authentication e reinicie o frontend. O acesso exige os custom claims `role` e `tenant_id` emitidos pelo backend operacional confiável. Abra `http://localhost:3000`. A API está em `http://localhost:8000`; documentação OpenAPI em `/docs`.

Para PostgreSQL, defina `DATABASE_URL` no `.env` com uma URL `postgresql+psycopg://...`. Mantenha senhas apenas no `.env` local, que é ignorado pelo Git. Execute `uv run alembic upgrade head` depois de configurar a URL.

## Importação

Em **Importação**, selecione um CSV ou XLSX. O importador procura o cabeçalho nas primeiras 30 linhas, mapeia nomes/cabeçalhos Salesforce conhecidos, valida e-mail/telefone, destaca duplicados e oferece uma prévia antes de confirmar. Limites padrão: 20 MB e 10.000 linhas.

Não há planilha Salesforce original neste repositório. Os testes usam apenas registros sintéticos; verifique os nomes de cabeçalho e campos de motivo com uma exportação sanitizada antes de uma importação operacional. A confirmação cria leads novos e não modifica registros no Salesforce.

## Segurança e escopo

- Uma fila de auditoria separada de uma fila de contato em rascunho.
- O estado padrão de consentimento é desconhecido; contato exige permissão e aprovação verificáveis.
- Não existe endpoint nem código de envio de WhatsApp ou de outras mensagens.
- A simulação usa correspondência literal e nunca chama serviços externos. Vertex AI real permanece bloqueado por padrão e exige flags explícitas, tarifas do modelo e teto de custo.
- Auditorias conclusivas exigem citações que correspondam exatamente a mensagens autorizadas; resultados precisam de revisão humana.
- A API valida Firebase Authentication ID tokens e exige `role` (`admin`, `auditor` ou `gestor`) e `tenant_id`; consulte [docs/security.md](./docs/security.md) para a matriz de endpoints.
- `FIREBASE_PROJECT_ID` e o projeto Firebase Web usam o projeto confirmado `prime-amulet-439718-e3`; os valores restantes da aplicação Web devem vir da configuração oficial do Firebase, nunca de credenciais privadas.
- Antes de iniciar a API, configure Application Default Credentials para o Firebase Admin SDK. Não copie tokens nem credenciais para `.env`; use o mecanismo ADC local aprovado ou a identidade de runtime em produção.
- O frontend autentica com Firebase Authentication (e-mail/senha ou Google) e envia ID tokens bearer. Os componentes de navegação são limitados pelo perfil; autorização e tenant continuam sendo aplicados pela API.
- Mensagens não autorizadas, excluídas ou expiradas não entram no contexto. A retenção local padrão é 90 dias (`MESSAGE_RETENTION_DAYS`, limitado a 1–365), com limpeza automática no início e diariamente.
- O arquivo Salesforce real não está no repositório. A cobertura usa fixtures sintéticas; valide os mapeamentos em uma cópia sanitizada antes do uso operacional.
- Nenhum bucket, banco Cloud SQL, serviço, API ou outro recurso GCP é criado ou habilitado por esta aplicação.
- SQLite é adequado somente para desenvolvimento local; use PostgreSQL gerenciado/operado com backups, rede privada, segredo externo e controle de acesso antes de produção.
- A API e o frontend têm autenticação, autorização por role e escopo por tenant. Antes de expor ou implantar, configure os provedores e valores oficiais do Firebase Web, ADC/IAM de runtime, origens CORS, limites compartilhados e migração revisada dos dados legados.

## Verificações

```powershell
uv run pytest
uv run alembic upgrade head
cd frontend
npm.cmd run typecheck
npm.cmd run build
```

## Estrutura

- `backend/app`: API FastAPI, modelos, importador, classificação e arquitetura Vertex AI.
- `backend/migrations`: esquema versionado Alembic.
- `frontend/app`: interface Next.js, TypeScript e Tailwind CSS.
- `tests`: testes com planilhas e dados fictícios.
- `docs`: decisões, classificação e integrações futuras.

Consulte [docs/architecture.md](docs/architecture.md) para detalhes de dados, retenção, auditoria e integração futura.
