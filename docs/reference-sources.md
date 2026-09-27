# Referências NCM e CEST

## NCM

`SiscomexNcmCatalogClient` baixa a referência NCM configurada em `SISCOMEX_NCM_URL`. A resposta é validada, normalizada e deduplicada antes de ser entregue ao motor de auditoria.

Cada catálogo contém:

- URL da fonte;
- data e hora da coleta em UTC;
- `ETag`, quando a fonte o disponibilizar;
- versão determinística `sha256` do payload recebido.

A API web não baixa a base durante sua inicialização. A referência é persistida
por comando explícito, para que a origem, o hash e a data de cada versão sejam
rastreáveis.

## Sincronização inicial e atualizações

Depois de aplicar as migrações e configurar `DATABASE_URL`, execute:

```powershell
python -m app.services.reference.sync_ncm
```

O comando baixa a fonte configurada por `SISCOMEX_NCM_URL`, normaliza códigos,
calcula uma versão por SHA-256 e cria uma `ncm_reference_version` imutável com
os respectivos registros em `ncm`. Reexecutar o comando com o mesmo conteúdo
não duplica dados.

## CEST

`CestLookupClient` consulta uma URL parametrizada por NCM, com timeout e cache em memória. O resultado nunca presume que exista um único CEST: preserva todos os códigos encontrados, a URL consultada, a data de consulta e um trecho de evidência.

| Situação | Comportamento |
| --- | --- |
| Um único código encontrado | Pode ser apresentado como sugestão, sempre para revisão humana. |
| Vários códigos encontrados | Não seleciona um arbitrariamente; exige revisão humana. |
| Nenhum código encontrado | Retorna `not_found`. |
| Fonte indisponível | Retorna `unavailable`; não inventa valor. |
| NCM inválido | Retorna `invalid_ncm` sem fazer requisição externa. |

## Limites e governança

- O CEST depende de mais contexto do que o NCM em vários cenários. A consulta é evidência para revisão, não decisão fiscal definitiva.
- Antes de produção, confirmar fonte, termos de uso, frequência permitida e regras aplicáveis com responsável fiscal.
- A cache atual é local ao processo; a fase de operação substituirá ou complementará por cache compartilhado quando houver múltiplos workers.
