# Upload e auditorias assíncronas

## Contrato

`POST /api/v1/audits/upload` recebe `.xlsx`, valida-o e responde `202 Accepted`
com uma auditoria em `processing`. O resultado é consultado com
`GET /api/v1/audits/{audit_id}`.

O campo `progresso` informa `processados` e `total`. Enquanto o worker estiver
em processamento, `data` pode estar vazia. Ao concluir, o mesmo contrato passa
a conter os resultados.

## Planilha aceita

| Coluna | Obrigatória | Regra |
| --- | --- | --- |
| `codigo_produto` | Sim | Identificador não vazio. |
| `descricao` | Sim | Descrição não vazia. |
| `ncm_atual` | Sim como coluna; valor pode ser vazio | Quando informado, deve conter 8 dígitos. |
| `cest_atual` | Sim como coluna; valor pode ser vazio | Quando informado, formato `00.000.00`. |

Cabeçalhos são normalizados para minúsculas, sem acentos e com `_`. Um erro em
qualquer linha rejeita toda a importação; não existe importação parcial
silenciosa.

## Limites

- Apenas arquivos `.xlsx`.
- Limite configurável por `MAX_UPLOAD_BYTES`, padrão de 10 MiB.
- Até 100 erros de linha retornados por requisição.

## Execução distribuída

A API persiste auditoria, checksum, tamanho do arquivo e linhas normalizadas.
O matching é executado pelo worker independente descrito em
[Worker de auditorias](distributed-worker.md). Assim, o encerramento ou reinício
do processo web não cancela auditorias aceitas.
