# Scrapers e pipeline de dados — Despensa Planejada Santos

Documentação técnica da coleta de preços do comparador. O projeto mantém coletores
automatizados para os sites e APIs de quatro supermercados de Santos (SP) e um
pipeline de integração que publica tudo em um banco Neon/PostgreSQL consumido
pela API FastAPI.

```
sites/APIs das lojas
        │  4 coletores v2 (scraper/<loja>/scrap_<loja>.py)
        ▼
JSONs brutos por loja (fora do git)
        │
        ├── Soudaki e Atacadão ──► integração direta no Neon (--db / --integrar)
        │
        └── Carrefour e Pão de Açúcar ──► integrar_carrefour_pa.py (vínculo
                     │  por EAN-13/nome, filtro adulto, upsert de preço)
                     ▼
              Neon PostgreSQL (produção)
                     │
                     ▼
        API FastAPI (/api) ──► PWA (despensaplanejada.vercel.app)
```

> O caminho antigo via ETL (`importar_json_para_sqlite.py` →
> `dispensa.db` → `migrate_sqlite_to_neon.py`) continua disponível como
> alternativa para reconstruir o catálogo a partir dos JSONs
> `*_ampliado.json` da primeira geração de coletores.

## Estrutura de pastas

```text
scraper/
  README.md                  visão geral, comandos e regras de caminho
  requirements.txt           dependências dos coletores
  carrefour/
    scrap_carrefour.py       coletor v2 — API VTEX carrefourbrfood (loja_id=1)
  pao_de_acucar/
    scrap_paodeacucar.py     coletor v2 — API GPA api.vendas.gpa.digital (loja_id=2)
  atacadao/
    scrap_atacadao.py        coletor v2 — API VTEX atacadaobr + cache-buster (loja_id=3)
    teste_parser_atacadao.py testes unitários do parser
    README.md / COMECE_AQUI.txt
  soudaki/
    scrap_soudaki.py         coletor v2 — __NEXT_DATA__ do Next.js (loja_id=4)
    teste_parser.py          testes unitários do parser
    README.md / COMECE_AQUI.txt
  filtro_adulto.py           filtro de conteúdo adulto (2 camadas) — na raiz,
                             importado pelo ETL e pelo integrador
  integrar_carrefour_pa.py   publicação dos JSONs v2 do Carrefour/PA no Neon
  teste_integrador_pa.py     testes das funções puras do integrador (offline)
  limpar_mojibake.py         limpeza de produtos com double-encoding UTF-8
  teste_limpar_mojibake.py   testes das funções de detecção/decodificação
  atualizar_precos_ean_cep.py     atualização em lote de preços por EAN + CEP
  recoletar_por_ean.py            releitura de preço/estoque para EANs específicos
  relatorio_cobertura.py          métricas de cobertura por loja
webapp/backend/
  importar_json_para_sqlite.py    ETL: JSONs → dispensa.db (SQLite)
  migrate_sqlite_to_neon.py       carga: SQLite → Neon/PostgreSQL
```

Os coletores v1 (`secoes/coletor_vtex.py`, `secoes/coletar_*.py`,
`coletar_e_integrar_soudaki.py` v1, enriquecedores pontuais) foram
removidos: eram substituídos pelos v2 e permanecem no histórico do git
(`git log --diff-filter=D -- scraper/`) caso precise consultá-los.

## Pré-requisitos

- Python 3.10+ e as bibliotecas dos coletores:

```bash
cd scraper && python -m pip install -r requirements.txt
```

- Para o backend/ETL (raiz do repositório):

```bash
python -m pip install -r requirements.txt
```

- Variável de ambiente dos scripts que gravam direto no banco:

```bash
export DATABASE_URL="postgresql://..."   # ou NEON_DATABASE_URL
```

`db.py` reconhece `DATABASE_URL` e depois `NEON_DATABASE_URL`; sem nenhuma delas,
o backend cai no SQLite local `webapp/backend/dispensa.db`.

## Coletores por loja

### Carrefour (Ponta da Praia) — API VTEX

`scrap_carrefour.py` fala direto com a API clássica da VTEX
(`carrefourbrfood.myvtex.com/api/catalog_system`), que responde sem o
captcha da vitrine. Percorre os **11 corredores de mercado** do menu
(Drogaria, Utilidades Domésticas e Pet Care desativados a pedido),
paginando de 50 em 50; quando um corredor atinge o limite de paginação da
VTEX (`_from` ≈ 2500), desce para as subcategorias e deduplica por id+EAN.

```bash
python carrefour/scrap_carrefour.py --probe            # diagnóstico
python carrefour/scrap_carrefour.py --listar-corredores
python carrefour/scrap_carrefour.py                    # coleta completa
python carrefour/scrap_carrefour.py --corredores "Mercearia,Bebidas"
```

Saída: JSON único (`{fonte, loja_id, produtos: [...]}`) com preço,
estoque, EAN, imagem e URL por produto.

### Pão de Açúcar — API GPA

`scrap_paodeacucar.py` usa a camada de dados oficial
(`api.vendas.gpa.digital`): listagem por departamento via
`POST /pa/search/category-page` (100 itens/página) e detalhe via
`GET /pa/v4/products/ecom/{id}` (EAN + preço autoritativo). São **5
departamentos** ativos (alimentos, bebidas, limpeza, perfumaria, bebê e
criança); bazar, petshop, descartáveis e afins estão desativados.

```bash
python pao_de_acucar/scrap_paodeacucar.py --probe
python pao_de_acucar/scrap_paodeacucar.py --listar-departamentos
python pao_de_acucar/scrap_paodeacucar.py              # ~13 mil produtos, algumas horas
python pao_de_acucar/scrap_paodeacucar.py --departamentos "bebidas" --limite-teste 50
```

Saída: mesmo formato do Carrefour (`loja_id=2`).

### Atacadão — API VTEX com cache-buster

`scrap_atacadao.py` consulta `atacadaobr.vtexcommercestable.com.br`.
Duas descobertas de campo são essenciais: (1) a paginação `_from/_to`
exige `&_cb=<aleatório>`, porque o CloudFront ignora a query string no
cache e devolve sempre a página 1; (2) `fq=isAvailablePerSalesChannel_1:1`
filtra só o que é vendável online. Percorre as **515 folhas de categoria**
(nível 3) com checkpoint a cada 25 folhas.

```bash
python atacadao/scrap_atacadao.py --probe              # diagnóstico
python atacadao/scrap_atacadao.py --listar-categorias
python atacadao/scrap_atacadao.py --secao all --db --dry-run   # simula integração
python atacadao/scrap_atacadao.py --secao all --db
python atacadao/scrap_atacadao.py --integrar --dry-run # só integra JSONs existentes
```

Saída: `output/produtos_atacadao_full.json` + `precos_atacadao_full.json`
(schema do Soudaki v2) + `checkpoint_atacadao.json` (retomada).

> **A coleta do Atacadão está pausada** (catálogo mantido no banco);
> não retomar sem decisão do grupo.

### Soudaki (Daki) — Next.js com gravação direta

`scrap_soudaki.py` extrai o lote pré-carregado do `__NEXT_DATA__` de
`soudaki.com/shop/<secao>/` (**25 seções**), com plano B nas rotas
`/_next/data/<buildId>/` e fallback SSR `?page=N`. Verificado em campo:
a rolagem infinita já vem completa no lote inicial — `--sem-paginacao`
pula a descoberta. O site só entrega a loja para **IP brasileiro**.

```bash
python soudaki/scrap_soudaki.py --probe --secao laticinios
python soudaki/scrap_soudaki.py --secao all --sem-paginacao --db --dry-run
python soudaki/scrap_soudaki.py --integrar            # só integra JSONs existentes
```

Saída: `output/produtos_soudaki_full.json` + `precos_soudaki_full.json`.

### Integração no Neon (Soudaki e Atacadão)

Ambos os coletores gravam direto no Neon com `--db` (coleta + gravação)
ou `--integrar` (só grava os JSONs já coletados), sempre com `--dry-run`
disponível para simular. O vínculo é por **EAN-13** e, na falta, por
**nome normalizado** (preenchendo o EAN do produto existente quando
possível); produto sem correspondência é criado com `relevancia = 10`.
Preços fazem upsert em `precos` por `(produto_id, loja_id)` com
`data_coleta` de hoje. A integração resolve a raiz do repo via
`Path(__file__).parents[2]` e importa `webapp/backend/db.py` — por isso
as pastas `soudaki/` e `atacadao/` precisam ficar um nível abaixo de
`scraper/`.

### Carrefour e Pão de Açúcar — publicação no Neon

`integrar_carrefour_pa.py` lê os JSONs v2 (por padrão
`scraper/carrefour/carrefour_produtos.json` e
`scraper/pao_de_acucar/paodeacucar_produtos.json`) e publica com o mesmo
critério dos integradores do Soudaki/Atacadão: vínculo por **EAN-13**
(inclusive os códigos internos `0000000*` do GPA, já usados no catálogo)
e, na falta, por **nome normalizado** — preenchendo o EAN do produto
existente quando possível. Produto sem correspondência é criado com
`relevancia = 10` e categoria resolvida contra as canônicas do catálogo
(os corredores do Carrefour já são canônicos; os do Pão de Açúcar passam
pelos pares de unificação da normalização). O filtro adulto é aplicado
antes da gravação.

Preços fazem upsert em `precos` por `(produto_id, loja_id)` com
`data_coleta` extraída do `coleta_em` do JSON: quando há promoção
(`preco < preco_original`) o valor promocional vai em `preco_promocional`
e o de lista em `preco_regular`; sem promoção, `preco_promocional = NULL`
e o preço vigente fica só em `preco_regular` — o app lê com
`COALESCE(preco_promocional, preco_regular)`. `em_estoque` combina
`disponivel` e `estoque > 0` (o `99999` do Carrefour conta como "infinito").
Campos do JSON v2 mapeados: `imagem` → `imagem_url`, `unidade`+`multiplicador`
→ `apresentacao` (ex.: `"6 un"` para pack 6 unidades). Itens indisponíveis
ou sem preço positivo são ignorados e contados. Por padrão o script apenas
**simula**; `--db` grava (com commit único no fim) e `--limite N`
processa os N primeiros de cada arquivo — ideal para validar antes:

```bash
python scraper/integrar_carrefour_pa.py --limite 200      # simula
python scraper/integrar_carrefour_pa.py --db              # grava tudo
python scraper/integrar_carrefour_pa.py --db --arquivo scraper/pao_de_acucar/paodeacucar_produtos.json
python scraper/teste_integrador_pa.py                     # testes das funções puras (offline)
```

O script exige estar em `scraper/` (usa `filtro_adulto.py` da própria
pasta e `webapp/backend/db.py` da raiz, que lê `DATABASE_URL` ou
`NEON_DATABASE_URL` do `.env` da raiz do repositório). Os testes em
`teste_integrador_pa.py` cobrem offline (sem banco) as funções puras
`ean_valido`, `_split_preco`, `_em_estoque`, `_apresentacao`,
`resolver_categoria` e `data_da_coleta`.

## Filtro de conteúdo adulto

`filtro_adulto.py` aplica duas camadas — seção de origem (páginas adulta/sex shop
da VTEX) e análise de nome/marca — para remover produtos íntimos do catálogo.
Itens de uso pessoal legítimos (absorventes, coletores menstruais, preservativos)
têm exceções explícitas para não serem descartados por falso positivo. É usado
na coleta e no ETL (`webapp/backend/importar_json_para_sqlite.py`); por isso
precisa ficar na raiz de `scraper/`.

## Atualização de preços

- `recoletar_por_ean.py` — releitura de preço/estoque para uma lista de EANs
  passada por argumento: `python recoletar_por_ean.py 7891234567890 ...`.
- `atualizar_precos_ean_cep.py` — atualização em lote por EAN + CEP nos mercados
  (lê `scraper/catalogo_unificado.json` por padrão). Opções:
  `--eans` (lista explícita), `--faltantes` (só EANs faltantes), `--catalogo`
  (outro arquivo), `--limite N` (tamanho do lote), `--desde N` (índice inicial).
- `relatorio_cobertura.py` — métricas de cobertura por loja (`--kpi` para o
  painel resumido), usadas para decidir as próximas coletas.
- `limpar_mojibake.py` — limpeza pontual de produtos com mojibake (double-
  encoding UTF-8) legados do banco. Detecta nomes como "LinguiÃ§a" (Ã + §)
  e os reverte para "Linguiça" (ç), distinguindo de "Ã" legítimo em
  "São"/"Coração"/"Âmbar". Se existir versão correta correspondente (mesmo
  EAN ou nome), deleta o duplicata migrando os preços; senão corrige in-place.
  `--dry-run` apenas lista; `--aplicar` modifica o banco:

  ```bash
  python scraper/limpar_mojibake.py                 # detecta, não grava
  python scraper/limpar_mojibake.py --aplicar       # corrige/deleta
  python scraper/limpar_mojibake.py --ids           # só lista IDs afetados
  ```

## ETL e carga no banco

1. **ETL local** — `webapp/backend/importar_json_para_sqlite.py` lê os JSONs
   (`produtos_ampliado.json` + `precos_*_ampliado.json`), normaliza nomes
   (`nome_normalizado`), cruza produtos por EAN-13/nome e recria
   `dispensa.db`. Com `REMOVER_PRODUTOS_SEM_PRECO=True`, pula produtos do
   catálogo sem preço em nenhuma loja. **Apaga o banco anterior** — faça backup.
2. **Carga no Neon** — `webapp/backend/migrate_sqlite_to_neon.py` publica
   catálogo e preços no PostgreSQL de produção (requer `DATABASE_URL`).

### Schema (Neon)

| Tabela | Conteúdo |
| --- | --- |
| `lojas` | `id`, `chave`, `nome`, `icone` (1 Carrefour Ponta da Praia, 2 Pão de Açúcar, 3 Atacadão, 4 Soudaki) |
| `produtos` | `id`, `ean`, `nome`, `nome_normalizado`, `relevancia`, `categoria` |
| `precos` | `produto_id`, `loja_id`, `preco_promocional`, `preco_regular`, `em_estoque`, `cep_coleta`, `data_coleta` |

**Regra importante:** a coluna de preço efetivo é
`COALESCE(preco_promocional, preco_regular)` — não existe coluna `preco`.
Toda consulta de preço válido deve usar `COALESCE(...) IS NOT NULL AND COALESCE(...) > 0`.

## Convenções do repositório

- JSONs de coleta, checkpoints e bancos (`*.db`, `produtos.zip`) **não são
  versionados** — ficam apenas no disco do autor; os dados vivos são o Neon.
  Os padrões estão no `.gitignore` (`scraper/*/output/`, `scraper/<loja>/*.json`).
- Logs de execução (`*_log.txt`, `*_err.txt`) também ficam fora do git.
- A coleta do **Atacadão está pausada** (catálogo mantido no banco); não retomar
  sem decisão do grupo.
- Respeite os limites dos sites: prefira `--probe`/`--limite-teste` antes de uma
  coleta completa, mantenha os delays padrão e lotes pequenos na atualização por
  EAN + CEP.
