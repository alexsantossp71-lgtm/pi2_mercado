# Despensa Planejada Santos

Comparador de preços de supermercados de Santos (SP) com coleta própria de dados.
Projeto Integrador em Computação II — UNIVESP 2026.2.

**Aplicação publicada:** [despensaplanejada.vercel.app](https://despensaplanejada.vercel.app/)
**Como os preços são coletados:** [página no app](https://despensaplanejada.vercel.app/scrapers.html) · [docs/scrapers.md](docs/scrapers.md)

## O que faz

- Pesquisa produtos por texto, seção e marca, com busca por palavra independente de ordem.
- Monta uma lista de compras com quantidades (PWA instalável, funciona offline com o catálogo carregado).
- Compara a cesta completa em cada loja e estima uma opção dividida entre lojas, com aviso honesto quando dividir não compensa.
- Mostra a cobertura real de cada estabelecimento (selo "MENOR PREÇO" apenas para lojas com a lista completa).
- Oferece checklist de compras para uso na loja e compartilhamento da lista via WhatsApp.

## Números da base (30/10/2026)

| Indicador | Valor |
| --- | --- |
| Produtos no catálogo | 113.516 |
| Produtos com preço em 2+ lojas (comparáveis) | 6.729 |
| Supermercados monitorados | 4 — Carrefour Ponta da Praia, Pão de Açúcar, Atacadão, Soudaki |
| Coleta mais recente | 30/10/2026 |

Os preços refletem o momento da coleta e podem variar por unidade, CEP, estoque e
condições da oferta. Confirme o preço e a disponibilidade com a loja antes de comprar.
A data exibida no cabeçalho é a coleta mais recente do conjunto geral — não significa
que todas as lojas tenham sido atualizadas nessa data.

## Arquitetura

```
coletores (scraper/) ──► JSONs brutos ──► ETL ──► Neon PostgreSQL ──► API FastAPI ──► PWA
```

- **Coletores**: Python + requests/BeautifulSoup, um por plataforma (VTEX para
  Carrefour/Atacadão, API GPA para Pão de Açúcar, leitura direta para Soudaki).
- **ETL**: normaliza nomes, cruza produtos por EAN-13/nome, aplica filtro de
  conteúdo adulto e descarta itens sem preço.
- **Banco de produção**: Neon/PostgreSQL, acessado pela API FastAPI.
- **Frontend**: HTML/CSS/JS modular como PWA, servido estaticamente na Vercel.

Detalhes completos de cada etapa, schema do banco e comandos: [`docs/scrapers.md`](docs/scrapers.md).

## Estrutura do repositório

```text
webapp/                     aplicação publicada
  index.html                comparador (interface principal)
  scrapers.html             página "Como coletamos os preços"
  js/  css/  img/           módulos do navegador, estilos e logotipos
  backend/
    main.py                 API FastAPI (ponto de entrada da Vercel)
    db.py                   conexão Neon/PostgreSQL (fallback SQLite local)
    services/               busca de produtos e cálculo da cesta
    importar_json_para_sqlite.py   ETL: JSONs → SQLite
    migrate_sqlite_to_neon.py      carga: SQLite → Neon
    normalizar_categorias_neon.py  manutenção de categorias no Neon
  sw.js                     service worker (cache PWA)
scraper/                    coletores e integração de dados (ver docs/scrapers.md)
tests/                      testes unitários (busca)
docs/                       documentação técnica
vercel.json                 rotas de deploy (API + estáticos)
```

Arquivos de dados de coleta (JSONs grandes, `*.db`, logs e `produtos.zip`) ficam
**fora do git** — os dados vivos são o Neon. Os padrões estão no `.gitignore`.

## Executar localmente

Requisitos: Python 3.10+. Na raiz do repositório:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt pytest httpx
```

Configure a conexão com o banco e inicie a API:

```bash
export DATABASE_URL="postgresql://..."   # URL do Neon (ou SQLite local, se existir)
cd webapp/backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Em outro terminal, sirva a interface estática:

```bash
python3 -m http.server 8080 --directory webapp
```

Abra `http://localhost:8080`. A documentação interativa da API fica em
`http://localhost:8000/docs`. O backend permite por padrão as origens
`http://localhost:8080` e `http://127.0.0.1:8080` (CORS).

**Nota:** o banco SQLite `webapp/backend/dispensa.db` não é mais versionado. Sem
um `DATABASE_URL` válido, o backend só funciona se você gerar o SQLite local com o
ETL a partir dos JSONs de coleta (que também ficam fora do git) — na prática,
desenvolva apontando `DATABASE_URL` para um banco PostgreSQL com o schema carregado.

## Endpoints principais

- `GET /api/meta` — lojas e data global da coleta.
- `GET /api/categorias` — categorias disponíveis.
- `GET /api/marcas` — marcas disponíveis.
- `GET /api/produtos?q=arroz&limit=20` — busca paginada.
- `GET /api/produtos/{id}` — detalhe e preços do produto.
- `POST /api/produtos/lote` — preços frescos de uma lista de IDs.
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

```bash
python -m pytest -q tests/test_search_order_independent.py
```

Os testes unitários de busca cobrem ordem independente das palavras na consulta FTS.
Os testes de API (`webapp/backend/test_api.py`) exigem um banco acessível; sem
`DATABASE_URL` válida eles falham por conexão. **Não** aponte os testes para o banco
de produção — alguns exercitam escrita.

## Implantação (Vercel)

- `vercel.json` direciona `/api/*` para `webapp/backend/main.py` e serve os
  estáticos de `webapp/` (incluindo `scrapers.html`).
- Configure `DATABASE_URL` (ou `NEON_DATABASE_URL`) no ambiente da Vercel com a
  URL de conexão do Neon. Nunca versione credenciais.
- Após mudar variáveis de ambiente, faça novo deploy e valide `/api/meta`,
  `/api/categorias`, uma busca conhecida e um cálculo em `/api/calcular`.
  Página estática carregando sozinha não comprova que a API e o banco estão saudáveis.
- Alterações no frontend devem elevar a versão do cache em `webapp/sw.js`
  (`CACHE_NAME`) e nos `?v=` de `index.html` para invalidar o cache do PWA.
