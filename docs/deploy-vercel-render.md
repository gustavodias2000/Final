# Publicacao inicial: Vercel + Render + worker local

Esta configuracao publica o frontend React na Vercel e a API FastAPI no Render.
O PostgreSQL continua no Supabase. O worker de auditoria continua no computador
local e consulta o mesmo banco; portanto, ele precisa estar iniciado para que
auditorias enviadas pelo site sejam processadas.

## Antes de publicar

1. Confirme que as migracoes ja foram aplicadas no Supabase:

   ```powershell
   cd D:\Claude\AUDITOR\Final\backend
   python -m alembic -c alembic.ini current
   ```

   O resultado deve terminar em `20260926_0004 (head)` ou em uma revisao mais
   recente, caso novas migracoes tenham sido criadas.

2. Nunca envie `DATABASE_URL`, `SECRET_KEY` ou a senha do Supabase para o GitHub.
   O arquivo `.gitignore` ja protege arquivos `.env` locais.

## 1. Enviar o codigo ao GitHub

Na pasta `D:\Claude\AUDITOR\Final`, revise e publique apenas o codigo:

```powershell
git status
git add .
git commit -m "Configura deploy inicial Vercel e Render"
git push origin master
```

Se o Git pedir autenticacao, conclua pelo navegador. Confira no GitHub que
arquivos `.env` e credenciais nao aparecem no repositorio.

## 2. Criar a API no Render

1. Acesse [Render](https://render.com/) e entre com GitHub.
2. Clique em **New > Blueprint** e conecte o repositorio `gustavodias2000/Final`.
3. Selecione a branch `master`. O Render encontrara `render.yaml` na raiz.
4. Na tela de variaveis, preencha:

   | Variavel | Valor |
   | --- | --- |
   | `DATABASE_URL` | URI completa do **Session pooler** do Supabase, com `postgresql+psycopg2://` no inicio |
   | `SECRET_KEY` | gere com `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
   | `CORS_ORIGINS` | `http://localhost:3000` temporariamente |

5. Crie o Blueprint e aguarde o deploy. Ao terminar, abra a URL da API e acrescente
   `/health`. O retorno esperado e `{"status":"ok","environment":"production"}`.
6. Guarde a URL, por exemplo: `https://auditor-ncm-api.onrender.com`.

O plano gratuito da API pode demorar aproximadamente um minuto no primeiro acesso
apos inatividade. Isso e esperado no MVP.

## 3. Criar o frontend na Vercel

1. Acesse [Vercel](https://vercel.com/) e importe o mesmo repositorio GitHub.
2. Em **Root Directory**, selecione `frontend`.
3. O framework pode ser identificado como **Vite**. Confirme:

   | Campo | Valor |
   | --- | --- |
   | Build Command | `npm run build` |
   | Output Directory | `dist` |

4. Antes do deploy, adicione a variavel de ambiente de producao:

   ```text
   VITE_API_BASE_URL=https://SUA-API.onrender.com
   ```

   Nao use barra no final. Substitua pela URL real recebida no passo anterior.
5. Clique em **Deploy** e guarde a URL `https://...vercel.app` gerada.

## 4. Liberar somente o site publicado na API

No Render, abra o servico `auditor-ncm-api` > **Environment** e troque
`CORS_ORIGINS` pela URL exata da Vercel, por exemplo:

```text
https://auditor-ncm.vercel.app
```

Salve escolhendo **Save and deploy**. Se adicionar um dominio proprio depois,
inclua ambos separados por virgula. Nunca use `*`.

## 5. Iniciar o worker local ao usar auditorias

Abra um PowerShell separado e execute:

```powershell
cd D:\Claude\AUDITOR\Final\backend
$env:DATABASE_URL = 'postgresql+psycopg2://COLE_A_URI_DO_SUPABASE_AQUI'
$env:SECRET_KEY = 'use-um-segredo-local-longo'
$env:CORS_ORIGINS = 'https://SUA-URL.vercel.app'
python -m app.services.audit_worker
```

Mantenha esta janela aberta durante os testes. Ela deve permanecer sem mensagens
quando nao houver auditorias e registrar o processamento quando um arquivo for
enviado pelo site.

Para parar o worker, pressione `Ctrl+C`. A API e o site continuarao online, mas
novas auditorias ficarao aguardando no banco ate o worker voltar a ser iniciado.

## Verificacao final

1. Abra o site da Vercel em janela anonima.
2. Entre com o usuario `admin` criado no Supabase.
3. Envie uma planilha valida.
4. Confirme que o worker local registra o processamento.
5. Atualize a pagina e confira o resultado, a evidencia e a exportacao CSV.

## Limite desta etapa

Esta e uma configuracao de demonstracao/MVP. O worker local depende do computador
estar ligado e conectado a internet. Antes de atender clientes continuamente,
migre o worker para um servico gerenciado pago e configure monitoramento,
backups e dominio proprio.
