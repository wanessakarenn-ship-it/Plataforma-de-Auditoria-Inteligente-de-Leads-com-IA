# Arquitetura inicial

## Persistência

SQLAlchemy 2 e Alembic suportam SQLite local e PostgreSQL (`postgresql+psycopg`). A migração inicial cria entidades para leads, lotes/importações, histórico de status/fase, catálogos de motivos, conversas/mensagens, auditorias/evidências, filas de auditoria e contato, permissões e logs de processamento. Confirme com a planilha Salesforce original os nomes e domínios dos campos antes de impor novas restrições.

O histórico guarda a origem e os valores de status/fase. O lote mantém um retrato serializado da prévia para permitir confirmação explícita. A política de retenção desses dados deve ser definida antes do uso com clientes.

## Importação e classificação

CSV e XLSX são lidos sem enviar o arquivo a terceiros. O cabeçalho de exportações Salesforce é procurado nas primeiras 30 linhas usando alias comuns; o mapeamento final fica visível antes de confirmar. Identificador Salesforce tem prioridade de deduplicação; na ausência dele, e-mail normalizado e depois telefone normalizado. Uma colisão com lead já persistido é ignorada nesta versão (não faz merge nem atualiza Salesforce).

Status/fases são classificados por regras explícitas em `backend/app/classification.py`; valores desconhecidos recebem `unknown` e aviso. Ajuste os sinônimos após revisar uma exportação sanitizada real.

## Separação e segurança das filas

Leads que ainda exigem análise entram na `audit_queue`, exceto ganhos. Candidatos não ganhos a contato podem entrar na `contact_queue` como `draft_needs_review`. A importação não cria consentimento ou aprovação: elegibilidade exige contato válido, permissão `granted`, ausência de supressão e aprovação manual. A função de elegibilidade retorna apenas aptidão para revisão manual; não aciona canal de comunicação. Não há transportador nem endpoint de envio nesta sprint.

## Vertex AI

`backend/app/services/vertex_audit.py` define limites de lote e os modelos estruturados de entrada/saída, mas a execução sempre falha de forma explícita enquanto o conector não estiver habilitado. Próximos passos: escolher modelo/região aprovados, definir retenção e minimização de dados, validar custos/quotas e política de dados; integrar um cliente Vertex isolado e testar com conteúdo sintético antes de qualquer dado real.

## Integrações futuras

- **Salesforce:** iniciar em leitura/exportação, documentar mapeamento após validar a planilha; nunca escrever de volta sem escopo, consentimento e aprovação explícita.
- **WhatsApp:** definir base legal, opt-in, opt-out, política de supressão, revisão humana, limites e aprovação; habilitar envio somente em etapa separada.
- **Produção:** decidir Cloud SQL PostgreSQL, autenticação IAM/service account com privilégio mínimo, rede, backups, gestão de segredos, logging e orçamento antes de provisionar.
