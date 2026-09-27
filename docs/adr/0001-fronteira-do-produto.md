# ADR 0001 — Fronteira do produto e artefatos canônicos

- Status: aceito
- Data: 2026-09-22
- Decisor: equipe do Auditor NCM/CEST

## Contexto

O workspace possui dois conjuntos de artefatos com objetivos sobrepostos:

- `PJ NCM/`: especificação inicial, documentos comerciais e protótipos Python com interface desktop (`customtkinter`);
- `Final/`: aplicação web com frontend React e backend FastAPI.

Eles possuem implementações diferentes para consulta de NCM, auditoria, upload e interface. Considerá-los duas fontes ativas cria regras concorrentes, contratos incompatíveis e risco de correções divergentes.

## Decisão

1. `Final/` será a única fonte de código do produto em evolução.
2. O produto seguirá a arquitetura web: React no cliente, FastAPI na API, worker para trabalhos longos e PostgreSQL como persistência principal.
3. `PJ NCM/` será preservado como acervo de requisitos, protótipos e evidências históricas; não é alvo de novas funcionalidades nem de correções operacionais.
4. A especificação histórica orienta requisitos de domínio, mas não impõe a interface desktop nem autoriza copiar código legado. Seus requisitos serão reavaliados frente ao SaaS web.
5. A primeira entrega de produção será Excel → auditoria → revisão humana → exportação. Conectores de bancos externos e escrita em lote são extensões posteriores.

## Consequências

- Há um único local para APIs, regras, contratos e testes.
- A UI desktop deixa de disputar prioridade com a UI web.
- Estratégias de fontes de dados continuam válidas como conceito de domínio, mas só serão implementadas quando o fluxo de Excel estiver consolidado.
- Qualquer sugestão de NCM/CEST é uma recomendação auditável, não uma alteração fiscal automática.

## Fora de escopo desta fase

- apagar ou migrar os arquivos de `PJ NCM/`;
- implementar integração com Siscomex, scraping de CEST ou conectores de banco;
- alterar o comportamento de produção da API ou do frontend.
