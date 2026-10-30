# Scrapers e pipeline de dados — Despensa Planejada Santos

Documentação técnica da coleta de preços do comparador. O projeto mantém coletores
automatizados para os sites e APIs de quatro supermercados de Santos (SP) e um
pipeline de integração que publica tudo em um banco Neon/PostgreSQL consumido
pela API FastAPI.

```
sites/APIs das lojas
        │  coleta por seções (requests + BeautifulSoup)
        ▼
JSONs brutos por loja (fora do git)
        │  filtro_adulto.py  ── remove seção adulta/sex shop
        ▼
ETL  importar_json_para_sqlite.py ── normaliza, cruza por EAN-13/nome, monta catálogo
        │
        ├──► dispensa.db (SQLite local, para desenvolvimento)
        │            │  migrate_sqlite_to_neon.py
        ▼            ▼
      Neon PostgreSQL (produção)
        │
        ▼
API FastAPI (/api) ──► PWA (despensaplanejada.vercel.app)
```

## Estrutura de pastas

```text
scraper/
  secoes/                    coletores por seção (geração atual)
    coletor_vtex.py          coletor VTEX genérico (Carrefour e Atacadão)
    coletar_carrefour.py     orquestra o Carrefour (chamado pelo run_carrefour.bat)
    coletar_atacadao.py      orquestra o Atacadão
    coletar_pa.py            coletor do Pão de Açúcar (API GPA)
    config_secoes.py         configuração das seções por loja
    gerar_folhas.py          gera folhas_*.json (listas de categorias-alvo)
    dimensionar.py           mede o tamanho de cada folha antes de coletar
    consolidar.py            consolida saídas parciais
    relevancia.py            pontua relevância de produtos
    validar_atacadao.py      valida a coleta do Atacadão
    rodar_carrefour_seguro.py execução do Carrefour com limites de segurança
    run_pipeline_completa.py orquestrador com log (pipeline_log.txt)
    run_*.bat                lançadores locais (máquina do autor, Windows)
  filtro_adulto.py           filtro de conteúdo adulto (2 camadas)
  coletar_e_integrar_soudaki.py   Soudaki/Daki — grava direto no Neon (loja_id=4)
  coletar_carrefour_categorias_db.py  cesta básica do Carrefour — grava Neon + SQLite
  atualizar_precos_ean_cep.py     atualização em lote de preços por EAN + CEP
  recoletar_por_ean.py            releitura de preço/estoque para EANs específicos
  enriquecer_orfaos.py            vincula produtos sem EAN ao catálogo
  enriquecer_overlap_atacadao.py  completa o overlap do Atacadão
  cruzar_produtos.py              cruza Open Food Facts (BR) com Carrefour → catalogo_unificado.json
  relatorio_cobertura.py          métricas de cobertura por loja
  _run_batch.py                   executor em lote
webapp/backend/
  importar_json_para_sqlite.py    ETL: JSONs → dispensa.db (SQLite)
  migrate_sqlite_to_neon.py       carga: SQLite → Neon/PostgreSQL
  normalizar_categorias_neon.py   manutenção: normaliza categorias fragmentadas no Neon
```

## Pré-requisitos

- Python 3.10+ e as bibliotecas dos coletores:

```bash
python -m pip install requests beautifulsoup4 psycopg2-binary
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

### Carrefour (Ponta da Praia) e Atacadão — plataforma VTEX

Ambos usam o `secoes/coletor_vtex.py`, que percorre folhas de categoria declaradas
em `secoes/folhas_carrefour.json` / `secoes/folhas_atacadao.json`, paginando cada
folha com truncamento configurável (`limite_max`). Os arquivos de folhas são
gerados pelo `gerar_folhas.py` a partir do mapa de seções (`config_secoes.py`).

Fluxos de execução:

- `coletar_carrefour.py` e `coletar_atacadao.py` — coleta por loja.
- `run_pipeline_completa.py` — roda a esteira inteira com log em
  `secoes/pipeline_log.txt`.
- `rodar_carrefour_seguro.py` — execução do Carrefour com limites de segurança
  (evita bloqueio por volume).
- `run_carrefour.bat` / `run_atacadao.bat` / `run_pa.bat` — lançadores no Windows
  da máquina do autor (caminhos locais; servem de exemplo de agendamento).

Saída: JSONs de catálogo e preços por loja (`produtos_*.json`, `precos_*.json` —
mantidos fora do git por tamanho).

### Pão de Açúcar — API GPA

`secoes/coletar_pa.py` consulta a API oficial do GPA e percorre as 8
multi-categorias válidas de mercado (alimentos, bebidas, limpeza, perfumaria,
bazar, descartáveis, bebê e criança, pet), paginando cada subcategoria.
Saída: JSONs do Pão de Açúcar.

### Soudaki (Daki) — gravação direta no Neon

`coletar_e_integrar_soudaki.py` extrai produtos, preços e estoques de
`soudaki.com/shop/<secao>/` (25 categorias) e **grava direto no Neon**
(`loja_id = 4`), vinculando por EAN-13 ou nome normalizado com o catálogo
compartilhado. Requer `DATABASE_URL` apontando para o Neon.

### Coletor de categorias do Carrefour (cesta básica)

`coletar_carrefour_categorias_db.py` coleta categorias essenciais da cesta básica
em `mercado.carrefour.com.br` e grava direto no Neon e no SQLite.

## Filtro de conteúdo adulto

`filtro_adulto.py` aplica duas camadas — seção de origem (páginas adulta/sex shop
da VTEX) e análise de nome/marca — para remover produtos íntimos do catálogo.
Itens de uso pessoal legítimos (absorventes, coletores menstruais, preservativos)
têm exceções explícitas para não serem descartados por falso positivo. É usado
na coleta (coletor VTEX) e no ETL.

## Atualização de preços

- `recoletar_por_ean.py` — releitura de preço/estoque para uma lista de EANs
  passada por argumento: `python recoletar_por_ean.py 7891234567890 ...`.
- `atualizar_precos_ean_cep.py` — atualização em lote por EAN + CEP nos mercados
  (lê `scraper/catalogo_unificado.json` por padrão). Opções:
  `--eans` (lista explícita), `--faltantes` (só EANs faltantes), `--catalogo`
  (outro arquivo), `--limite N` (tamanho do lote), `--desde N` (índice inicial).
- `relatorio_cobertura.py` — métricas de cobertura por loja (`--kpi` para o
  painel resumido), usadas para decidir as próximas coletas.

## ETL e carga no banco

1. **ETL local** — `webapp/backend/importar_json_para_sqlite.py` lê os JSONs,
   normaliza nomes (`nome_normalizado`), cruza produtos por EAN-13/nome e recria
   `dispensa.db`. Com `REMOVER_PRODUTOS_SEM_PRECO=True`, pula produtos do catálogo
   sem preço em nenhuma loja. **Apaga o banco anterior** — faça backup.
2. **Carga no Neon** — `webapp/backend/migrate_sqlite_to_neon.py` publica
   catálogo e preços no PostgreSQL de produção (requer `DATABASE_URL`).
3. **Manutenção de categorias** — `normalizar_categorias_neon.py` unifica
   nomenclaturas fragmentadas entre lojas (ex.: "Limpeza" × "Limpeza e Lavanderia").

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

- JSONs de coleta e bancos (`*.db`, `produtos.zip`) **não são versionados** —
  ficam apenas no disco do autor; os dados vivos são o Neon. Os padrões estão no
  `.gitignore`.
- Logs de execução (`*_log.txt`, `*_err.txt`, `pipeline_log.txt`) também ficam
  fora do git.
- A coleta do **Atacadão está pausada** (catálogo mantido no banco); não retomar
  sem decisão do grupo.
- Respeite os limites dos sites: use `rodar_carrefour_seguro.py` e prefira lotes
  pequenos na atualização por EAN + CEP.
