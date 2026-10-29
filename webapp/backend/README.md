# Backend — Despensa Planejada Santos

API principal em FastAPI. O ponto de entrada é `main.py`; execute-a a partir desta pasta com:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

A documentação interativa fica em `http://localhost:8000/docs`.

## Banco de dados

O banco de produção do projeto é Neon/PostgreSQL. `db.py` reconhece estas variáveis de ambiente, nesta ordem:

1. `DATABASE_URL`
2. `NEON_DATABASE_URL`

Quando uma delas está definida, o backend conecta ao PostgreSQL com `psycopg2`. Em desenvolvimento local, se nenhuma URL estiver definida, procura um arquivo SQLite local, incluindo `webapp/backend/dispensa.db`.

Para a implantação Vercel, configure `DATABASE_URL` ou `NEON_DATABASE_URL` no ambiente correspondente (Production, Preview ou Development, conforme necessário). Use a URL de conexão do Neon. Não grave URLs, senhas ou tokens no Git; utilize as variáveis de ambiente locais ou o gerenciador de segredos da plataforma. Após mudar uma variável na implantação, faça um novo deploy e confira os logs e os endpoints.

## Desenvolvimento local

Na raiz do repositório:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r webapp/backend/requirements.txt
cd webapp/backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Sem URL PostgreSQL, o backend usa o SQLite local se o arquivo estiver disponível. Para abrir a interface simultaneamente, sirva a pasta `webapp/` em `http://localhost:8080`; essa origem está permitida por padrão na configuração CORS da API.

## Recriar SQLite para desenvolvimento

`importar_json_para_sqlite.py` importa os arquivos de dados de `webapp/` para `dispensa.db`. O script remove o banco existente e recria as tabelas e os dados; faça backup antes de executá-lo. Essa rotina é somente para o banco local de desenvolvimento e não deve ser usada contra o Neon de produção.

## Verificação após deploy

Teste, no mínimo, `/api/meta`, `/api/categorias`, uma busca em `/api/produtos` e `POST /api/calcular`. Uma página HTML acessível não garante que o backend esteja conectado ao banco.
