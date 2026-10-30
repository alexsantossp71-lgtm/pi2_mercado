# Coletor Atacadão v2.0 (atacadao.com.br)

Scraper de **todos os produtos do Atacadão** — mesmo formato de saída e mesma
arquitetura do `soudaki_v2`. Grava no Neon com **loja_id = 3**.

> **O que mudou da v1 para a v2:** a v1 tentava raspar o HTML das páginas
> `?page=N`. Ficou provado em campo que o site novo (VTEX FastStore) carrega
> os produtos via GraphQL no navegador — eles **não vêm no HTML**. A v2 fala
> direto com a **API da plataforma VTEX**, que é pública, pagina de verdade e
> não passa pelo Cloudflare.

## Como funciona (descobertas em campo, out/2026)

| Fato validado | Consequência |
|---|---|
| O site novo é **VTEX FastStore** (Next.js) | Produtos chegam via GraphQL no navegador; raspar HTML não funciona |
| O `www.atacadao.com.br` tem Cloudflare + proxy que **entrega lote fixo cacheado** e descarta `_from/_to` | O domínio www não serve para coleta |
| A conta VTEX é **atacadaobr** → `atacadaobr.vtexcommercestable.com.br/api/catalog_system/...` | API REST pura, **sem Cloudflare, acessível de qualquer IP** (não precisa mais de IP brasileiro nem cloudscraper) |
| Paginação `_from=N&_to=M` (50/pág.) **funciona**, MAS o CloudFront da VTEX cacheia 5 min **só pelo caminho** (ignora query string) | Todo request leva `&_cb=<aleatório>` (cache-buster). **Foi isso que "quebrou" a paginação do coletor antigo** |
| Header de resposta `resources` = `"0-49/542"` | Total de produtos da consulta em mãos → para exatamente no fim |
| `fq=isAvailablePerSalesChannel_1:1` | Só produtos vendíveis online (em "leites": catálogo bruto 542, mas só 40 têm preço — e são exatamente os disponíveis) |
| **Slugs de `drogaria/` são fantasmas**: a árvore lista, mas a busca ignora o path e devolve o catálogo inteiro (~4.873 itens de qualquer depto) | Drogaria excluída da coleta (medicamentos estão fora do escopo do projeto, decisão out/2026). Suplementos reais ficam no depto próprio |
| Departamentos com **vírgula no nome** ("Carnes, aves e peixes") | A comparação anti-fantasma normaliza pontuação antes de comparar |
| Árvore pública: `/api/catalog_system/pub/category/tree/3/` | 515 folhas em 20 departamentos (out/2026); 507 coletadas (8 de drogaria excluídas). Há cópia embutida no script como fallback |
| **EAN real** no catálogo VTEX | Cobertura `gtin_ean` de 86,9% (muito acima do Soudaki) |

### Guarda anti-path-fantasma

Toda folha é validada na 1ª página: se **menos da metade** dos produtos
retornados pertence ao departamento pedido (via `categories[]` do próprio
produto), o slug não resolveu na busca e a folha é descartada com log claro.
Isso evita envenenar os JSONs com produtos de categoria errada (aconteceu
com `drogaria/*` antes da exclusão — a API devolvia o catálogo inteiro).

## Resultado da coleta completa (29/10/2026)

**4.871 produtos / 4.871 preços / 18 departamentos / 0 falhas / 0 fantasmas**

Mercearia 1012 · Frios e congelados 856 · Higiene e perfumaria 676 ·
Carnes, aves e peixes 525 · Bebidas 491 · Limpeza 283 · Padaria e matinais
253 · Utilidades domésticas 238 · Hortifrúti 173 · Pet Shop 68 ·
Suplementos alimentares 68 · demais 228

## Requisitos

```
pip install requests
```

(só isso — nem cloudscraper precisa mais. Para gravar no Neon depois:
`pip install psycopg2-binary python-dotenv`)

## Uso

```powershell
# 1) diagnóstico — confirma API, paginação, EAN e amostra de preço
python scrap_atacadao.py --probe

# 2) ver as categorias (opcional)
python scrap_atacadao.py --listar-categorias

# 3) coletar TUDO (507 folhas — ~15 min; dá para parar e retomar)
python scrap_atacadao.py --secao all

#    ou categoria específica (lista separada por vírgula):
python scrap_atacadao.py --secao padaria-e-matinais/leites/leite-integral,mercearia/graos/arroz-branco

# 4) conferir o que seria gravado no Neon (NADA grava)
python scrap_atacadao.py --integrar --dry-run

# 5) gravar de verdade
python scrap_atacadao.py --integrar
```

### Saídas (pasta `output/`)

| Arquivo | Conteúdo |
|---|---|
| `produtos_atacadao_full.json` | cadastro: sku, gtin_ean, nome, marca, categoria, subsecao, apresentacao, imagem_url, link |
| `precos_atacadao_full.json` | preço do dia: preco_regular, preco_promocional, em_estoque, data_coleta |
| `checkpoint_atacadao.json` | folhas concluídas → `--secao all` retoma de onde parou |
| `categorias_atacadao.json` | só com `--listar-categorias` |

Rodar de novo noutro dia = merge (mesmos sku atualizam preço; novos entram).
Para recomeçar do zero: apague a pasta `output/`.

### Integração Neon (loja_id = 3)

Mesma lógica do Soudaki v2: match por **EAN** → match por **nome normalizado**
(enriquece o EAN faltante) → cria produto novo com `relevancia=10` → grava/atualiza
`precos (produto_id, 3, preco_promocional, preco_regular, em_estoque, data_coleta)`.

O script precisa estar em `<repo>/scraper/atacadao/` (ou `atacadao/`) para achar
`webapp/backend/db.py`, e o `.env` com `DATABASE_URL` do Neon na raiz do repo.

## Testes

```powershell
python teste_parser_atacadao.py    # 39 testes offline, sem rede
```

## Solução de problemas

- **HTTP 429 / 503** — o script já faz backoff automático (5s, 10s, 20s).
  Se persistir, aumente o intervalo: edite `_sleep(0.35)` no `main`.
- **Folha com FALHA na pág 1** — queda de rede pontual; a folha **não** é
  marcada como concluída. Rode `--secao all` de novo que só as faltosas refazem.
- **Folha com PATH FANTASMA** — slug que a árvore lista mas a busca não
  resolve; descartada por segurança e marcada como concluída.
- **--secao all diz "todas as folhas já estão no checkpoint"** — apague
  `output/checkpoint_atacadao.json` para recolerter.
- **Quero incluir produtos fora de estoque** — use `--sem-fq` (mais lento:
  percorre o catálogo bruto; os sem preço são descartados de qualquer forma).
- **Trava de segurança** — `--max-paginas` (padrão 50 páginas × 50 itens =
  2.500 produtos por categoria, cap da própria VTEX).
- **Quero incluir medicamentos** — remova `"drogaria/"` de
  `EXCLUIR_FOLHAS_PREFIXOS` no topo do script (as folhas ainda serão
  descartadas pelo guarda anti-fantasma enquanto a VTEX não consertar
  os slugs — é problema da loja, não do coletor).
