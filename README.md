# BC Lead Intelligence

Aplicação local-first para importar, classificar e auditar leads. Nesta Sprint 01 não há envio de mensagens, integração mutável com Salesforce, processamento real com Gemini nem provisionamento de recursos Google Cloud.

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
npm.cmd install
npm.cmd run dev
```

Abra `http://localhost:3000`. A API está em `http://localhost:8000`; documentação OpenAPI em `/docs`.

Para PostgreSQL, defina `DATABASE_URL` no `.env` com uma URL `postgresql+psycopg://...`. Mantenha senhas apenas no `.env` local, que é ignorado pelo Git. Execute `uv run alembic upgrade head` depois de configurar a URL.

## Importação

Em **Importação**, selecione um CSV ou XLSX. O importador procura o cabeçalho nas primeiras 30 linhas, mapeia nomes/cabeçalhos Salesforce conhecidos, valida e-mail/telefone, destaca duplicados e oferece uma prévia antes de confirmar. Limites padrão: 20 MB e 10.000 linhas.

Não há planilha Salesforce original neste repositório. Os testes usam apenas registros sintéticos; verifique os nomes de cabeçalho e campos de motivo com uma exportação sanitizada antes de uma importação operacional. A confirmação cria leads novos e não modifica registros no Salesforce.

## Segurança e escopo

- Uma fila de auditoria separada de uma fila de contato em rascunho.
- O estado padrão de consentimento é desconhecido; contato exige permissão e aprovação verificáveis.
- Não existe endpoint nem código de envio de WhatsApp ou de outras mensagens.
- Vertex AI está preparado, mas desativado; nenhum dado de cliente é enviado a modelos.
- Nenhum bucket, banco Cloud SQL, serviço, API ou outro recurso GCP é criado ou habilitado por esta aplicação.
- SQLite é adequado somente para desenvolvimento local; use PostgreSQL gerenciado/operado com backups, rede privada, segredo externo e controle de acesso antes de produção.

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

Consulte [docs/architecture.md](docs/architecture.md) para detalhes de dados, classificação e integração futura.
