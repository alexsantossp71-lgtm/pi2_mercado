# Despensa Planejada Santos

Aplicação web de comparação de preços e planejamento de compras em supermercados de Santos (SP), desenvolvida como Projeto Integrador em Computação II da UNIVESP.

**Aplicação publicada:** [despensaplanejada.vercel.app](https://despensaplanejada.vercel.app/)

## O que faz

- Pesquisa produtos por texto, seção e marca.
- Permite montar uma lista com quantidades.
- Compara a cesta em uma loja e estima uma opção dividida entre lojas.
- Exibe a disponibilidade registrada e o preço coletado para cada estabelecimento.
- Oferece checklist de compras e compartilhamento da lista.

Os preços refletem os dados disponíveis no momento da coleta. Podem variar por unidade, CEP, estoque e condições da oferta. Confirme o preço e a disponibilidade com a loja antes de comprar. A data exibida no cabeçalho é a data mais recente encontrada no conjunto geral; não significa que todas as lojas tenham sido atualizadas nessa data.

## Tecnologias e estrutura

A interface principal é HTML, CSS e JavaScript modular, dentro de `webapp/`. A API principal é FastAPI e está em `webapp/backend/`. Os coletores e rotinas de integração de catálogo e preços ficam em `scraper/`. **O banco de produção é Neon/PostgreSQL.** O backend reconhece `DATABASE_URL` ou `NEON_DATABASE_URL`; sem essas variáveis, tenta abrir o SQLite local `webapp/backend/dispensa.db`.

```text
webapp/
  index.html                 interface principal
  js/                        módulos do navegador e cliente da API
  css/                       estilos
  backend/
    main.py                  API FastAPI
    db.py                    conexão Neon/PostgreSQL ou SQLite local
    services/                busca de produtos e cálculo da cesta
    dispensa.db              banco SQLite local versionado
scraper/                     coletores e integração de dados
```

A pasta `webapp/frontend/` contém um protótipo React separado; ela não é a interface publicada pela configuração Vercel na raiz. `webapp/backend/app.py` contém uma aplicação Flask de sazonalidade separada da API principal.

## Executar localmente

Requisitos: Python 3.10 ou superior. Em um terminal, na raiz do repositório:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r webapp/backend/requirements.txt
```

Inicie a API em um terminal:

```bash
cd webapp/backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Em outro terminal, também na raiz do repositório, sirva a interface estática:

```bash
python3 -m http.server 8080 --directory webapp
```

Abra `http://localhost:8080`. A documentação interativa da API fica em `http://localhost:8000/docs`. O cliente web local aponta para `http://localhost:8000`; o backend permite por padrão a origem `http://localhost:8080` e `http://127.0.0.1:8080`.

### Banco de dados

Em produção, a API conecta ao Neon/PostgreSQL. Configure `DATABASE_URL` ou `NEON_DATABASE_URL` com a URL de conexão do Neon no ambiente de execução. Nunca grave credenciais no Git. Consulte [`webapp/backend/README.md`](webapp/backend/README.md) para detalhes.

No desenvolvimento local, se nenhuma URL PostgreSQL estiver definida, o backend usa `webapp/backend/dispensa.db` quando o arquivo estiver disponível. O script `webapp/backend/importar_json_para_sqlite.py` recria esse banco a partir dos JSONs presentes em `webapp/`. **Ele apaga e recria as tabelas/banco local.** Faça uma cópia de segurança e confirme os arquivos de entrada antes de executá-lo; não use contra o banco de produção.

## Endpoints principais

- `GET /api/meta` — lojas e data global da coleta.
- `GET /api/categorias` — categorias disponíveis.
- `GET /api/marcas` — marcas disponíveis.
- `GET /api/produtos?q=arroz&limit=20` — busca paginada.
- `GET /api/produtos/{id}` — detalhe e preços do produto.
- `POST /api/calcular` — compara uma lista. Exemplo do corpo:

```json
{
  "itens": [
    {"id": 123, "qtd": 1}
  ]
}
```

Use `/docs` para explorar os parâmetros e testar as rotas.

## Testes

Instale as ferramentas de teste:

```bash
python -m pip install pytest httpx
```

Execute os testes unitários e de API locais:

```bash
python -m pytest -q tests/test_search_order_independent.py webapp/backend/test_api.py
```

**Estado conhecido:** na verificação de 29/10/2026, os testes de API passaram, mas um teste de busca falhou porque espera operadores `AND` explícitos na consulta FTS; o serviço atualmente monta os termos separados por espaços. Atualize o teste ou a implementação para alinhar a expectativa antes de considerar a suíte verde. Evite executar todos os arquivos `test_*.py` sem revisão: alguns scripts de diagnóstico podem depender de serviços externos ou credenciais.

## Implantação

A configuração Vercel da raiz direciona `/api/*` para `webapp/backend/main.py` e serve os arquivos estáticos de `webapp/`. Para produção, configure no ambiente da implantação `DATABASE_URL` ou `NEON_DATABASE_URL` com a URL do Neon e confirme que o schema e os dados necessários estão disponíveis. Antes de considerar um deploy pronto, valide `/api/meta`, `/api/categorias`, uma busca conhecida e um cálculo em `/api/calcular`. O carregamento da página estática, sozinho, não comprova que a API ou o banco estão funcionando.
