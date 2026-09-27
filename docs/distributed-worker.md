# Worker de auditorias

## Arquitetura

O processo web aceita, valida e persiste a auditoria. Ele não executa matching
NCM em memória. As linhas normalizadas da planilha ficam em `audit_input_items`;
isso permite que um processo worker independente execute a auditoria depois de a
requisição HTTP já ter terminado.

```text
API web -> audits (processing) + audit_input_items -> worker -> audit_items (completed)
```

## Leasing e recuperação

O worker obtém uma linha `audits` com bloqueio transacional e registra um
`worker_id`, contador de tentativas e `lease_expires_at`. Ele renova a lease ao
registrar progresso. Se o processo encerrar, outro worker poderá assumir a
auditoria quando a lease vencer. Após `AUDIT_WORKER_MAX_ATTEMPTS`, a auditoria
passa a `failed` com uma mensagem segura para o usuário.

## Execução

Primeiro aplique as migrações. Em seguida, rode API e worker em processos ou
serviços distintos, com as mesmas variáveis de ambiente.

```powershell
cd backend
python -m alembic -c alembic.ini upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
# em outro terminal
python -m app.services.audit_worker
```

Para containerização, `Dockerfile` atende a API e `Dockerfile.worker` atende o
worker. Ambos precisam do mesmo PostgreSQL e da referência NCM já carregada.

## Variáveis

| Variável | Padrão | Uso |
| --- | ---: | --- |
| `AUDIT_WORKER_POLL_INTERVAL_SECONDS` | 2 | Espera quando não há auditorias. |
| `AUDIT_WORKER_LEASE_SECONDS` | 120 | Prazo para outro worker recuperar trabalho abandonado. |
| `AUDIT_WORKER_MAX_ATTEMPTS` | 3 | Tentativas antes de marcar falha definitiva. |
