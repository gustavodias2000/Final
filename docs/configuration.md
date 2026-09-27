# Configuração do backend

O backend não possui credenciais padrão. Antes de iniciá-lo, defina todas as variáveis de [`.env.example`](../backend/.env.example) no ambiente de execução ou no gerenciador de segredos do deploy.

## Variáveis obrigatórias

| Variável | Uso |
| --- | --- |
| `SECRET_KEY` | Assinatura de tokens JWT; use valor longo e aleatório. |
| `DATABASE_URL` | String de conexão PostgreSQL. |
| `CORS_ORIGINS` | Origens permitidas, separadas por vírgula. Não use `*`. |

## Desenvolvimento local no PowerShell

```powershell
$env:SECRET_KEY = "troque-por-um-segredo-local-longo"
$env:DATABASE_URL = "postgresql+psycopg2://usuario:senha@localhost:5432/auditor"
$env:CORS_ORIGINS = "http://localhost:3000"
uvicorn app.main:app --reload
```

Na inicialização, a aplicação valida esses valores antes de configurar a conexão SQLAlchemy. Uma configuração ausente interrompe a inicialização com uma mensagem explícita.
