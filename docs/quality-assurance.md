# Qualidade e testes

## Escopo automatizado

O backend possui testes unitários para normalização, matching NCM, leitura de
planilhas, jobs e fontes de referência. A suíte de integração cobre o contrato
HTTP crítico:

- login com credenciais válidas e inválidas;
- acesso autenticado a uma auditoria e presença do identificador do item;
- isolamento de leitura e revisão entre tenants;
- persistência da decisão humana e bloqueio de uma segunda revisão;
- rejeição de extensão de upload não suportada sem criar auditoria.

Os testes de integração usam SQLite temporário e não acessam bases, segredos ou
fontes externas de produção.

## Execução local

No diretório `backend`, com as variáveis obrigatórias configuradas:

```powershell
$env:SECRET_KEY = "segredo-local-longo"
$env:DATABASE_URL = "postgresql+psycopg2://usuario:senha@localhost:5432/auditor"
$env:CORS_ORIGINS = "http://localhost:3000"
python -m unittest discover -s tests -v
```

Para verificar o cliente:

```powershell
cd ../frontend
npm run build
```

## Limites atuais

- A integração completa de upload exige uma base PostgreSQL com referência NCM
  carregada; ela será executada no ambiente de homologação.
- Os testes do worker cobrem conclusão, recuperação de lease expirada e falha
  definitiva. A homologação deve adicionar carga concorrente em PostgreSQL.
