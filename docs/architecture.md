# Arquitetura Sprint 02

## Persistência

SQLAlchemy 2 e Alembic suportam SQLite local e PostgreSQL (`postgresql+psycopg`). A migração inicial cria entidades para leads, lotes/importações, histórico de status/fase, catálogos de motivos, conversas/mensagens, auditorias/evidências, filas de auditoria e contato, permissões e logs de processamento. Confirme com a planilha Salesforce original os nomes e domínios dos campos antes de impor novas restrições.

O histórico guarda a origem e os valores de status/fase. O lote mantém um retrato serializado da prévia para permitir confirmação explícita. Mensagens registram identificadores de origem, remetente/destinatário, timestamps, estado de autorização/sincronização, prazo de retenção e eventos de edição/exclusão. Mensagens antigas sem autorização ou prazo conhecido não são elegíveis para auditoria.

A retenção configurável de mensagens é `MESSAGE_RETENTION_DAYS` (90 dias por padrão, limite de 1 a 365). No início da API e diariamente, a limpeza remove conteúdo, identificadores do provedor, metadados e cópias de evidência vencidas; eventos preservam somente o fato e a data da alteração. Uma exclusão mantém por prazo limitado hashes do identificador externo e da conversa para impedir reimportações na conversa afetada; esses hashes são removidos ao vencer a retenção. Tombstones antigos sem hash da conversa permanecem globalmente válidos até expirarem. Antes de usar dados de clientes, o responsável deve confirmar o prazo e a base de retenção aplicáveis.

## Importação e classificação

CSV e XLSX são lidos sem enviar o arquivo a terceiros. O cabeçalho de exportações Salesforce é procurado nas primeiras 30 linhas em diferentes delimitadores, permitindo linhas informativas anteriores ao cabeçalho. São mapeados data de criação, fase, status, campanha, origem, sobrenome, e-mail, celular, valor mensal, motivo e descrições; data e moeda são convertidas e validadas. O mapeamento final fica visível antes de confirmar. Identificador Salesforce tem prioridade de deduplicação; na ausência dele, e-mail normalizado e depois telefone normalizado. Uma colisão com lead já persistido é ignorada nesta versão (não faz merge nem atualiza Salesforce).

Status/fases são classificados por regras explícitas em `backend/app/classification.py`; valores desconhecidos recebem `unknown` e aviso. Ajuste os sinônimos após revisar uma exportação sanitizada real.

## Separação e segurança das filas

Leads que ainda exigem análise entram na `audit_queue`, exceto ganhos. Candidatos não ganhos a contato podem entrar na `contact_queue` como `draft_needs_review`. A importação não cria consentimento ou aprovação: elegibilidade exige contato válido, permissão `granted`, ausência de supressão e aprovação manual. A função de elegibilidade retorna apenas aptidão para revisão manual; não aciona canal de comunicação. Não há transportador nem endpoint de envio nesta sprint.

## Vertex AI

`backend/app/services/vertex_audit.py` desacopla simulação e Vertex AI. O modo simulado é local e cita somente trechos literais. O modo real exige `VERTEX_AI_ENABLED=true`, `VERTEX_AI_APPROVED=true`, Vertex AI selecionado, modelo/versão/prompt configurados e tarifas de entrada/saída e teto de custo explícitos; os valores do `.env.example` bloqueiam chamadas. Há limites de lote, concorrência, taxa, contexto, mensagens, saída e timeout. Saída JSON validada exige citações em mensagens autorizadas; datas e referências são obtidas do banco, não do modelo. Cada execução registra modo, modelo/versão, prompt, tokens, custo estimado, hash e ligação de reprocessamento. Erros são persistidos sem incluir o conteúdo enviado.

Autenticação e autorização estão centralizadas em `backend/app/auth.py`: Firebase Admin SDK verifica ID tokens, revogação, `role` e `tenant_id`; endpoints exigem perfil explícito. Migrações 0005–0007 isolam os dados por tenant e conversa, além de registrar ações autorizadas. O Project ID `prime-amulet-439718-e3` foi confirmado; o frontend usa Firebase Authentication e envia o ID token em todas as chamadas comerciais. Consulte `docs/security.md` para a matriz de rotas, a configuração da aplicação Web, logs e pendências.

## Integrações futuras

- **Salesforce:** iniciar em leitura/exportação, documentar mapeamento após validar a planilha; nunca escrever de volta sem escopo, consentimento e aprovação explícita.
- **WhatsApp:** definir base legal, opt-in, opt-out, política de supressão, revisão humana, limites e aprovação; habilitar envio somente em etapa separada.
- **Produção:** configurar a aplicação Firebase Web e provedores autorizados, definir identidade de runtime e IAM mínimo, revisar migração de tenant para registros legados, decidir Cloud SQL PostgreSQL, rede, backups, logging, retenção aprovada e orçamento antes de provisionar.
