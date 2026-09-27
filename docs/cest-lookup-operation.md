# Operacao da consulta CEST

A consulta externa de CEST fica desligada por padrao. Para habilita-la no worker,
defina `CEST_LOOKUP_ENABLED=true` no ambiente depois de validar a fonte, os termos
de uso e a frequencia permitida.

O worker consulta cada NCM no maximo uma vez por auditoria e registra no item o
status, a URL e o trecho de evidencia retornado. Um CEST somente e sugerido se a
fonte retornar exatamente um codigo; duas ou mais opcoes nunca sao escolhidas
automaticamente.

`CEST_LOOKUP_MAX_UNIQUE_NCMS` limita a quantidade de NCMs distintos consultados
em uma auditoria (padrao `250`), evitando scraping em massa para planilhas grandes.
