# Auditor NCM/CEST

Produto web SaaS para importar cadastros de produtos, identificar divergências
de NCM/CEST, produzir recomendações explicáveis e encaminhá-las para revisão
humana.

## Fonte canônica

`Final/` é o código-fonte canônico do produto. Ele contém o frontend React e a
API FastAPI. O diretório `PJ NCM/` guarda materiais de descoberta, especificações
e protótipos desktop legados, exclusivamente como referência histórica.

## Limite do MVP

1. autenticação e isolamento por tenant;
2. importação de uma planilha Excel padronizada;
3. criação e acompanhamento de uma auditoria;
4. sugestão explicável de NCM/CEST;
5. revisão humana e exportação do resultado.

Conexões diretas com bancos dos clientes e atualizações em lote só serão
adicionadas depois que esse fluxo estiver estável, rastreável e testado. O
sistema não altera cadastro fiscal automaticamente.

## Documentação

- [Decisão de fronteira do produto](docs/adr/0001-fronteira-do-produto.md)
- [Escopo e critérios do MVP](docs/mvp-v1.md)
- [Contrato da API de auditorias v1](docs/api-contract-v1.md)
- [Configuração segura do backend](docs/configuration.md)
- [Regras do motor de auditoria](docs/audit-rules.md)
- [Referências NCM e CEST](docs/reference-sources.md)
- [Upload e auditorias assíncronas](docs/async-audits.md)
- [Persistência e isolamento por tenant](docs/persistence-and-tenancy.md)
- [Fluxo operacional do dashboard](docs/dashboard-workflow.md)
- [Qualidade e testes](docs/quality-assurance.md)
- [Worker distribuído](docs/distributed-worker.md)
- [Especificação histórica](../PJ%20NCM/Especificação%20Técnica%20de%20Projeto_%20Auditor%20e%20Corretor%20Inteligente%20NCM_CEST.md)

## Estado atual

As dez fases de estabilização do MVP foram concluídas. A API persiste entradas
normalizadas e o worker independente assume, recupera e conclui auditorias por
meio de leases no banco. Antes do deploy, aplique as migrações e rode API e
worker como processos separados.
