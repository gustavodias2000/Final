# Fluxo operacional do dashboard

O dashboard é a interface operacional de uma auditoria. Ele usa o contrato
`/api/v1/audits` e não interpreta planilhas no navegador.

## Fluxo

1. O usuário envia uma planilha `.xlsx` ou `.xls`.
2. A API devolve uma auditoria com status `processing`.
3. Enquanto esse status estiver ativo, a interface consulta a auditoria a cada
   1,5 segundo e atualiza o progresso, os contadores e as mensagens de erro.
4. Ao concluir, os itens podem ser pesquisados, filtrados e revisados
   individualmente como aprovados ou rejeitados.
5. A visualização filtrada pode ser exportada em CSV para conferência externa.

## Configuração do cliente

O frontend lê `VITE_API_BASE_URL`; se ela não estiver definida, usa
`http://localhost:8000`. Copie `frontend/.env.example` para `.env.local` para
apontar a aplicação a outro ambiente.

No desenvolvimento padrão, o Vite atende em `http://localhost:3000`. Portanto,
o `CORS_ORIGINS` do backend precisa incluir essa origem.

## Estados previstos

- Inicial: orienta o envio de planilha.
- Enviando: desabilita novo envio e informa que o arquivo está sendo enviado.
- Processando: mostra a faixa de etapas, percentual e andamento.
- Concluído: exibe métricas, filtros, tabela, revisão e exportação.
- Falha: apresenta o erro devolvido pela API sem perder a opção de reenviar.
