# Classificação Sprint 01

| Classificação | Exemplos de status/fase reconhecidos |
|---|---|
| Desqualificado (`disqualified`) | Desqualificado, Disqualified |
| Perdido (`lost`) | Perdido, Lost, Closed Lost |
| Qualificado na fase Perdido (`qualified_lost`) | Status de qualificação com fase Perdido/Lost |
| Pesquisa (`research`) | Pesquisa, Research, Novo/New |
| Em conexão (`connecting`) | Em Conexão, Connected, Contacted |
| Levantada de Mão (`hand_raised`) | Levantada de Mão, Hand Raised, MQL |
| Nutrição (`nurture`) | Nutrição, Nurture |
| Negociação comercial (`commercial_negotiation`) | Negociação, Proposal, Contrato |
| Ganho (`won`) | Ganho, Won, Closed Won |
| Revisão (`unknown`) | Valor não reconhecido |

As regras são heurísticas configuráveis, não uma afirmação sobre os picklists da organização. O importador preserva os valores de origem. Valide valores e sinônimos com a exportação real, sem colocar dados pessoais em fixtures.

## Resultado de auditoria baseado em evidências

O resultado da auditoria é distinto da classificação comercial do lead:

- **Confirmado** e **Divergente** só são aceitos com ao menos uma citação literal que corresponda a uma mensagem autorizada e ainda retida.
- **Inconclusivo** significa que o contexto não sustenta uma conclusão; ausência de correspondência não comprova divergência.
- **Não auditável** é usado sem motivo original ou histórico autorizado disponível.

Todas as execuções requerem revisão humana. O modo simulado apenas verifica correspondência literal e não usa IA; o modo Vertex permanece desativado até configuração explícita e aprovação.
