# Catalogo CEST local

O catalogo CEST e uma referencia independente, versionada por SHA-256 e
persistida no PostgreSQL. O worker sempre usa a versao mais recente desse
catalogo antes de considerar uma consulta externa opcional.

## Arquivo aceito

Importe um arquivo `.csv` ou `.xlsx` com estas colunas:

| Coluna | Obrigatoria | Exemplo |
| --- | --- | --- |
| `ncm` | Sim | `0901.21.00` ou `2710.19.3` |
| `cest` | Sim | `01.001.00` |
| `descricao` | Nao | `Cafe torrado` |

Os aliases `ncm_codigo`, `codigo_ncm`, `cest_codigo` e `codigo_cest` tambem
sao aceitos. NCM e CEST sao normalizados durante a importacao.

Uma regra NCM com menos de oito digitos e tratada como prefixo. Por exemplo,
`2710.19.3` pode servir como evidência para `2710.19.30`, mas o sistema nao
gera sugestao automatica de CEST somente com essa correspondencia ampla. Ela
fica marcada para revisao humana com a regra e a versao do catalogo utilizadas.

## Validar e importar

Com `DATABASE_URL`, `SECRET_KEY` e `CORS_ORIGINS` configurados no terminal do
backend:

```powershell
python -m alembic -c alembic.ini upgrade head
python -m app.services.reference.sync_cest .\dados\cest_oficial.xlsx --source-url "https://fonte-oficial.exemplo" --dry-run
python -m app.services.reference.sync_cest .\dados\cest_oficial.xlsx --source-url "https://fonte-oficial.exemplo"
```

Uma nova importacao com o mesmo conteudo nao duplica registros. Ao auditar, um
unico CEST para a NCM pode ser sugerido para revisao humana; duas ou mais
opcoes permanecem sem escolha automatica.

## Atualizacao rastreavel pela fonte de download

Para a carga inicial e atualizacoes periodicas, o projeto tambem aceita o JSON
de mapeamento NCM x CEST publicado pela Tabelas Fiscais. A URL consultada fica
registrada junto com o hash SHA-256 da versao importada. Primeiro execute
somente a validacao:

```powershell
python -m app.services.reference.sync_cest --url "https://tabelasfiscais.com.br/public/downloads/cest_ncm.json" --dry-run
```

Confirme que a contagem e plausivel e, entao, execute o mesmo comando sem
`--dry-run`:

```powershell
python -m app.services.reference.sync_cest --url "https://tabelasfiscais.com.br/public/downloads/cest_ncm.json"
```

Use o terminal que ja possui as variaveis do backend configuradas. Nao cole
nem registre `DATABASE_URL`, `SECRET_KEY` ou senhas. Ao terminar a importacao,
reinicie o worker local para que novas auditorias usem a ultima versao do
catalogo. Auditorias ja concluidas preservam a evidencia da versao anterior e
nao sao alteradas.

## Multiplas opcoes para a mesma NCM

Quando uma regra NCM exata tiver mais de um CEST, o worker compara a descricao
do produto com as descricoes do catalogo. Ele somente recomenda a opcao com
maior similaridade quando o score atingir `CEST_CANDIDATE_SCORE_THRESHOLD`
(padrao 85) e superar a segunda opcao por `CEST_CANDIDATE_SCORE_MARGIN`
(padrao 12). A evidencia guarda o ranking; a decisao continua sujeita a revisao
humana.
