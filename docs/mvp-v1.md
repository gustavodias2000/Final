# MVP v1 — Escopo, regras operacionais e aceite

## Objetivo

Permitir que um usuário autenticado envie uma planilha de produtos, receba recomendações de NCM/CEST com evidências, revise cada recomendação e exporte o resultado para tratamento controlado.

## Fluxo do usuário

```text
Login → enviar Excel → validar arquivo → processar auditoria
      → revisar sugestões → aprovar/rejeitar → exportar relatório
```

## Incluído

| Capacidade | Resultado esperado |
| --- | --- |
| Autenticação | Usuário só acessa dados do próprio tenant. |
| Importação | Planilha `.xlsx` em modelo publicado, com relatório de erros por linha. |
| Auditoria | Cada produto possui NCM atual, sugestão, score, razão e versão da referência utilizada. |
| CEST | Resultado informa fonte, data da consulta e indisponibilidade quando não houver evidência confiável. |
| Revisão | Ação explícita de aprovar, rejeitar ou deixar pendente, com usuário e horário. |
| Exportação | Arquivo de resultados e decisões, sem modificar a base de origem. |

## Não incluído no MVP

- alteração automática de dados fiscais;
- conexão e atualização direta de SQL Server, MySQL, PostgreSQL ou Firebird do cliente;
- promessa de classificação fiscal definitiva;
- inferência de CEST sem fonte, data e evidência registradas;
- UI desktop paralela.

## Regras de segurança e domínio

1. NCM e CEST sugeridos são recomendações e exigem validação de responsável fiscal habilitado antes de qualquer uso operacional.
2. Uma recomendação deve ser reproduzível: guardar entrada normalizada, algoritmo/limiar, versão da referência e data de execução.
3. Falha ou indisponibilidade de uma fonte externa não pode resultar em dado inventado; o item deve ficar como `sem_evidencia` ou `pendente_revisao`.
4. Arquivos enviados, auditorias e decisões pertencem a um tenant e não podem ser consultados por outro.

## Critérios de aceite do MVP

- Um usuário autenticado conclui o fluxo completo com uma planilha válida.
- Uma planilha inválida retorna erros de cabeçalho e de linha compreensíveis, sem gerar auditoria parcial silenciosa.
- O resultado apresentado no React é idêntico ao contrato retornado pela API.
- Toda sugestão exibida contém score, motivo, fonte e estado de revisão.
- A exportação reproduz as entradas, sugestões e decisões persistidas.
- Nenhuma ação do MVP modifica planilha ou banco de dados externo.

## Indicadores iniciais

- taxa de linhas rejeitadas na importação;
- percentual de sugestões aprovadas, rejeitadas e pendentes;
- tempo de processamento por auditoria;
- percentual de itens sem evidência de CEST;
- falhas de integrações de referência.
