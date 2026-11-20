# Progresso da Sprint 03

## Entrega incremental 1 — Estúdio de IA: cadastro de agentes

O escopo desta entrega cobriu o registro administrativo de agentes. A Base de
Conhecimento foi concluída na Entrega 2 abaixo; a simulação de conversas está
descrita na Entrega 3.

### Contratos e segurança

- Agentes e snapshots de versão pertencem a um `tenant_id`; todos os endpoints exigem
  Firebase Authentication e role `admin`, com filtro de tenant no backend.
- As ações passam pelo registro administrativo já existente.
- O modelo selecionável neste incremento é somente `local-simulated`. Não há endpoint
  de execução, chamada externa, cobrança ou envio de mensagem.
- `execution_enabled` é sempre `false`. O estado ativo indica disponibilidade para
  futuras simulações, não execução em produção.
- Um rascunho precisa de aprovação humana explícita antes da publicação. Alterações
  criam nova versão, retiram a aprovação/publicação anterior e desativam o agente.
- Os dois modelos iniciais são criados explicitamente por organização, são idempotentes
  e começam inativos como rascunhos.

### Endpoints

- `GET /api/studio/agents`
- `POST /api/studio/agents`
- `POST /api/studio/agents/initial-templates`
- `GET /api/studio/agents/{agent_id}`
- `PUT /api/studio/agents/{agent_id}`
- `GET /api/studio/agents/{agent_id}/versions`
- `POST /api/studio/agents/{agent_id}/publication`
- `PUT /api/studio/agents/{agent_id}/activation`

### Migração e validação

- Migração aditiva `0008_ai_agent_registry`, posterior a `0007`; cria as tabelas
  `ai_agents` e `ai_agent_versions`, com índices e unicidade por organização/modelo.
- Aplicada no SQLite local: `0008_ai_agent_registry` (head), sem alteração das tabelas
  de dados existentes. `uv run alembic check` não detectou divergências de schema.
- `uv run pytest`: 62 aprovados; typecheck e build do frontend aprovados.
- Demonstração local autenticada: os dois agentes foram criados no tenant de
  desenvolvimento, carregados na interface e exibidos como rascunhos inativos; o
  histórico da versão 1 foi consultado. Nenhuma inferência foi executada.

## Entrega incremental 2 — Base de Conhecimento local

### Funcionalidades e segurança

- Biblioteca tenant-scoped para textos, FAQs, políticas, produtos, serviços, objeções
  e respostas aprovadas, com pesquisa e filtros por categoria, estado e agente.
- Criação, edição, aprovação, arquivamento/restauração e versionamento imutável; cada
  versão registra autoria, origem e data. Conteúdos editados voltam a rascunho.
- Vínculo de um conteúdo a múltiplos agentes, com validação de tenant. Todos os
  endpoints exigem Firebase Authentication e role `admin`; IDs de outros tenants
  retornam `404`, sem revelar a existência do recurso.
- A política `knowledge_requires_approval` é habilitada por padrão. Conteúdo não
  aprovado não é recuperado para esses agentes e impede a publicação do agente.
- Ingestão local de TXT, PDF e DOCX: limite padrão de 5 MB por arquivo, 500.000
  caracteres extraídos e 200 páginas de PDF. Formato e limites de descompactação do
  DOCX são validados; arquivos originais não são armazenados. PDF sem texto extraível
  é rejeitado; OCR não está habilitado.
- Indexação lexical determinística, ranking estável e referências citáveis, sem
  embeddings, Vertex AI, Gemini ou chamadas externas. Contexto serializado marca as
  fontes recuperadas como dados não confiáveis, nunca como instruções privilegiadas.

### Endpoints

- `GET/POST /api/knowledge/contents`
- `GET/PUT /api/knowledge/contents/{content_id}`
- `POST /api/knowledge/files`
- `PUT /api/knowledge/contents/{content_id}/agents`
- `POST /api/knowledge/contents/{content_id}/state`
- `GET /api/knowledge/contents/{content_id}/versions`
- `POST /api/knowledge/retrieve`

### Migração, demonstração e validação

- Migração aditiva `0009_knowledge_base`, posterior a `0008_ai_agent_registry`;
  adiciona conteúdo, snapshots de versão, vínculos compostos tenant-scoped e a
  política de aprovação dos agentes.
- Demonstração na interface com política inteiramente sintética: a pesquisa do agente
  não retornou o rascunho; após aprovação, retornou a versão 2 com referência,
  relevância e aviso de fonte não confiável. Nenhum dado de cliente foi utilizado.
- `uv run pytest`: 70 aprovados; 1 aviso de depreciação proveniente de
  `google-genai`.
- `uv run alembic current`: `0009_knowledge_base` (head). `uv run alembic check`:
  nenhuma operação nova detectada.
- `npm.cmd run typecheck` e `npm.cmd run build`: aprovados.
- `git diff --check`: aprovado.

## Entrega incremental 3 — Karen e jornada comercial simulada

### Cadastro e comportamento

- `POST /api/studio/agents/karen-template` cria Karen idempotentemente por tenant,
  como rascunho inativo, versão 1, modelo `local-simulated`, custo zero e sem execução.
- Identidade, tom acolhedor, instruções, prompt de sistema, critérios de decisão,
  segurança e transferência humana ficam versionados nos snapshots do Estúdio de IA.
- Karen identifica-se como assistente virtual. A Base de Conhecimento existente é
  consultada somente por vínculo com agente e conteúdo aprovado/vigente; referências
  recuperadas são preservadas como evidência e não executam instruções das fontes.

### Jornada, simulações e segurança

- Migração aditiva `0010_karen_simulations` cria jornadas e eventos isolados por
  `tenant_id`. Não altera `0008_ai_agent_registry` nem `0009_knowledge_base`.
  Eventos têm sequência única por jornada e a API não oferece edição ou exclusão
  de evidências.
- Estados incluem elegibilidade, confirmação, interesse, qualificação, proposta,
  negociação, documentação, contrato, assinatura simulada e pós-venda, além de
  opt-out, sem interesse, bloqueio, suspensão e transferência humana.
- Dez cenários são fictícios e não se associam a leads. A API rejeita e-mail e
  telefone no texto livre, registra turnos e decisões, referências aprovadas e
  avaliações determinísticas de gentileza, conformidade e precisão.
- Opt-out impede novos turnos e transições comerciais. Elegibilidade, proposta,
  preparação de contrato, link fictício e assinatura simulada exigem aprovação
  humana autenticada; a aprovação é registrada e consumida na trilha de eventos.
- Sem integração de WhatsApp, CRM ou fornecedor contratual. Não há envio automático,
  documento jurídico ou contratação real; links de contrato usam domínio `.invalid`.
- O contrato provider-neutral `ElectronicSignatureProvider` define operações futuras
  de criação/consulta de envelope, sem implementação, credenciais ou chamadas externas.
- `GET /api/karen/config`, endpoints `/api/karen/simulations` e sub-recursos de
  `turns`, `actions` e `approvals` permitem consultar a máquina e executar o simulador.
  Admins e gestores podem simular e aprovar ações sensíveis; auditores não têm acesso.

### Interface

- A área “Karen · Simulador” consulta configuração, cenários e jornadas por tenant,
  apresenta conversa/trilha/evidências, permite aplicar transições e registrar
  aprovações humanas. O Estúdio de IA oferece a criação do rascunho da Karen e edição
  do prompt versionado; a Base de Conhecimento permanece reutilizada.

### Pendências restantes da Sprint 03

1. Ampliar a avaliação supervisionada com exemplos aprovados e revisão humana de
   métricas; as notas automáticas atuais são verificações locais determinísticas.
2. Onboarding, convite e remoção de usuários para novas organizações com autorização
   mínima e trilha de auditoria. O bootstrap permanece restrito ao primeiro admin.
3. Definir IDs estáveis para novos tenants e revisar registros legados sem tenant;
   não atribuí-los automaticamente a uma organização.
4. Antes de dados de clientes em ambiente compartilhado, aprovar retenção e base de
   uso, IAM de runtime, origens HTTPS CORS, limites, PostgreSQL, backups e observabilidade.
5. Manter inferência paga, envio de mensagens e deploy bloqueados até autorização e
   critérios próprios de aceite. Integrações reais permanecem fora deste incremento.

### Verificações da Entrega 3

- `uv run pytest`: 79 aprovados; 1 aviso de depreciação proveniente de `google-genai`.
- `uv run alembic current`: `0010_karen_simulations` (head); `uv run alembic check`:
  nenhuma operação nova detectada.
- `npm.cmd run typecheck` e `npm.cmd run build` (em `frontend/`): aprovados.
- `git diff --check`: aprovado.
- Nenhum deploy, inferência paga, envio WhatsApp, alteração Salesforce ou recurso pago.

1. Construir editor de respostas e fluxos, simulações exclusivamente fictícias e
   comparação de versões com desempenho observado.
2. Implementar avaliação humana, conjuntos de exemplos aprovados e métricas
   supervisionadas, sem alterar prompts automaticamente em produção.
3. Implementar WhatsApp Cloud API sem envio: estado verificável, webhook assinado,
   deduplicação, consentimento, associação revisada e revogação segura. Não exibir
   conexão como ativa até configurar e validar credenciais reais autorizadas.
4. Definir papéis de acesso e políticas de retenção antes de persistir conteúdo de
   conversas; a Base de Conhecimento atual permanece restrita a `admin`.

## Situação consolidada

Em 2026-11-20, as entregas incrementais 1, 2 e 3 estão implementadas localmente:
79 testes passaram, typecheck/build foram aprovados e Alembic está em
`0010_karen_simulations`. A Sprint 02 permanece homologada localmente; nenhum deploy
foi feito. O plano de publicação e implantação está em
[deployment-readiness.md](./deployment-readiness.md) e exige aprovação de custos e
segurança antes de qualquer publicação ou provisionamento.
