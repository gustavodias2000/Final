# Persistência e isolamento por tenant

## Migrações

O schema PostgreSQL é controlado por Alembic. A primeira migração está em `backend/alembic/versions/20260922_0001_initial_schema.py`.

```powershell
cd backend
$env:DATABASE_URL = "postgresql+psycopg2://usuario:senha@host:5432/auditor"
python -m alembic -c alembic.ini upgrade head
```

## Propriedade dos dados

| Entidade | Escopo |
| --- | --- |
| `tenants` e `users` | Organização e identidade autenticada. |
| `ncm_reference_versions` e `ncm` | Referência global, versionada e não pertencente a um tenant. |
| `audits` | Pertence obrigatoriamente a um tenant. Mantém arquivo, checksum, progresso, erros e versão da referência. |
| `audit_items` | Pertence à auditoria e registra entradas, recomendações, evidências e decisão humana. |

As rotas de auditoria exigem JWT. Toda busca de auditoria filtra simultaneamente por `audit_id` e pelo `tenant_id` presente no usuário autenticado; outro tenant recebe `404` e não descobre a existência do recurso.

## Revisão humana

`POST /api/v1/audits/{audit_id}/items/{item_id}/review` recebe `approved` ou `rejected`. A ação registra usuário, horário e novo estado do item. Apenas itens sugeridos ou pendentes podem ser revisados.

## Retenção de arquivo

O MVP persiste nome, tamanho e SHA-256 do upload para rastreabilidade. O binário não é gravado no PostgreSQL nesta fase; storage de objetos e política de retenção serão definidos no deploy.
