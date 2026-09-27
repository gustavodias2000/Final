# Cadeia de fontes NCM e CEST

Quando `EXTERNAL_REFERENCE_LOOKUP_ENABLED=true`, o worker consulta cada NCM no
maximo uma vez por auditoria e segue esta ordem:

1. API Tabelas Fiscais: NCM e CEST;
2. NCM.api.br: confirmacao de NCM quando `NCM_API_KEY` estiver configurada;
3. AZX: link para consulta humana, sem scraping automatico;
4. Siscomex/NCM local e catalogo CEST local versionado.

Uma resposta de negocio, como NCM inexistente ou nenhum CEST aplicavel, encerra a
consulta. Timeout, 429, 5xx e resposta invalida sao falhas tecnicas. Quando as
duas APIs principais falham, o worker aguarda ate completar 70 segundos desde a
falha da Tabelas Fiscais e tenta novamente as duas APIs. Apenas se as duas
falharem pela segunda vez consecutiva o worker segue para AZX e para o
Siscomex/catalogo local. Se essa rota alternativa nao encontrar evidencia, ele
aguarda ate completar 120 segundos desde a segunda falha da Tabelas Fiscais e
reinicia tudo pela Tabelas Fiscais. O padrao e no maximo tres ciclos,
configuravel por `EXTERNAL_REFERENCE_MAX_CYCLES`, para impedir bloqueio indefinido.

Cada item persiste as tentativas com fonte, estado, URL e detalhe. A consulta
externa permanece opt-in e limitada por
`EXTERNAL_REFERENCE_LOOKUP_MAX_UNIQUE_NCMS` (padrao: 100), protegendo o limite
gratuito das APIs e auditorias grandes.

Quando o catálogo local encontra um CEST atual incompatível, a Tabelas Fiscais
é consultada uma vez para confirmação. Se ela também não aceitar o CEST atual,
o resultado fica como incompatibilidade confirmada. Se aceitar o CEST atual ou
contradizer o CEST sugerido pelo catálogo local, o resultado é marcado como
conflito e exige revisão humana; nenhuma sugestão automática é mantida.

A NCM.api.br continua sendo usada apenas para confirmação de NCM. Ela não é
tratada como fonte de CEST sem um contrato documentado que exponha esse dado.
