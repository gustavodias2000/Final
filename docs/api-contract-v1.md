# Contrato da API — Auditorias v1

## Endpoint

`POST /api/v1/audits/upload` recebe um campo multipart chamado `file` e devolve `202 Accepted`. Consulte `GET /api/v1/audits/{audit_id}` até o status deixar de ser `processing`.

## Resposta de sucesso

```json
{
  "audit_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "arquivo": "produtos.xlsx",
  "resumo": {
    "total_produtos": 20,
    "itens_com_sugestao": 18,
    "itens_sem_sugestao": 2
  },
  "data": [
    {
      "codigo_produto": "SKU-001",
      "descricao": "Produto de exemplo",
      "ncm_atual": "00000000",
      "ncm_sugerido": "11111111",
      "cest_atual": null,
      "cest_sugerido": null,
      "score": 87.5,
      "status": "suggested",
      "motivo": "Maior similaridade textual encontrada na base de referência.",
      "fonte_referencia": "base_ncm",
      "versao_referencia": null
    }
  ],
  "progresso": {
    "processados": 20,
    "total": 20
  },
  "errors": []
}
```

## Semântica dos estados

| Campo | Valores | Significado |
| --- | --- | --- |
| `status` da auditoria | `processing`, `completed`, `failed` | Estado do processamento completo. |
| `status` do item | `suggested`, `no_suggestion`, `pending_review`, `approved`, `rejected` | Estado da recomendação e de sua revisão humana. |

`ncm_sugerido` e `cest_sugerido` podem ser `null`. Nenhum valor sugerido representa correção fiscal automática.

## Erros

Erros de domínio seguirão este envelope, adotado integralmente na fase de validação de upload:

```json
{
  "code": "invalid_spreadsheet",
  "message": "A planilha não contém as colunas obrigatórias.",
  "details": ["Coluna ausente: ncm_atual"]
}
```

Os códigos HTTP previstos são `400` para entrada inválida, `401` para ausência de autenticação, `403` para violação de tenant, `413` para arquivo acima do limite e `422` para dados semanticamente inválidos.
