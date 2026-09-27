# Regras do motor de auditoria NCM

## Princípios

- O motor gera recomendações, nunca altera dados fiscais.
- A comparação usa descrição normalizada e `token_set_ratio` do RapidFuzz.
- Um NCM somente é tratado como válido quando possui oito dígitos após a remoção de pontuação.
- A referência utilizada é informada em cada resultado.

## Fluxo de decisão

```text
Produto → normalizar descrição e NCM atual
        → NCM atual existe e score ≥ 70?
             ├─ sim: sem sugestão
             └─ não: procurar melhor candidato
                        → score ≥ 70 e NCM diferente?
                             ├─ sim: sugerir para revisão humana
                             └─ não: sem sugestão
```

## Limiar inicial

O limiar de compatibilidade e de sugestão é **70/100**, conforme a especificação histórica. É um parâmetro de política, não uma verdade fiscal. Ele deve ser recalibrado com uma amostra revisada por especialista fiscal antes de habilitar qualquer fluxo operacional.

## Estados de saída

| Estado | Significado |
| --- | --- |
| `suggested` | Há candidato diferente, com confiança mínima; requer revisão humana. |
| `no_suggestion` | Não há evidência suficiente para sugerir mudança, ou o NCM atual é compatível. |

Estados de revisão (`pending_review`, `approved`, `rejected`) serão persistidos na fase de dados e revisão humana.
