# Soudaki (Daki) — Coletor v2

Scraper de **todos** os produtos de `https://soudaki.com/shop/<secao>/` — sucessor do
`scraper/coletar_e_integrar_soudaki.py` (v1), com paginação profunda e modo diagnóstico.

## Por que uma v2?

O site mudou e agora tem **bloqueio geográfico**: só entrega a loja para IP brasileiro
(do contrário a Cloudflare/Webflow devolve 404). Além disso, o v1 coletava apenas o
**lote pré-carregado** no HTML inicial de cada seção — as subcategorias com infinite
scroll têm mais produtos do que aparecem nesse lote. A v2 resolve os dois problemas:

1. Roda **na sua máquina** (IP de Santos/SP) → recebe a loja real com status 200.
2. Descobre automaticamente as **rotas de dados do Next.js** (`/_next/data/<buildId>/...`)
   para paginar além do lote pré-carregado, com fallback para `?page=N` no HTML.

## Instalação

```bash
# dentro do repositório (a pasta scraper/soudaki/)
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install requests
pip install cloudscraper   # opcional, recomendado se a Cloudflare começar a desafiar
```

> **Importante:** mantenha o script em `scraper/soudaki/` dentro do repo — a
> integração com o banco importa `webapp/backend/db.py` por caminho relativo.

## Como usar (ordem recomendada)

### 1. Diagnóstico (30 segundos)

```bash
python scrap_soudaki.py --probe --secao laticinios
```

Mostra o `buildId` do Next.js, as chaves de `pageProps`, as subcategorias encontradas
nos links e quantos SKUs vieram no lote pré-carregado. Se aparecer `SKUs pré-carregados:
0`, o site mudou a estrutura → me mande a saída do probe que eu ajusto o parser.

### 2. Seção teste (laticínios)

```bash
python scrap_soudaki.py --secao laticinios
```

O script vai: coletar o lote inicial → testar padrões de paginação → paginar até
esgotar → salvar em `output/`:

| Arquivo | Conteúdo |
|---|---|
| `produtos_soudaki_full.json` | catálogo dedup por SKU (nome, marca, EAN, imagem...) |
| `precos_soudaki_full.json`   | preço/estoque do dia por SKU |
| `checkpoint_laticinios.json` | buildId + padrão de paginação descoberto |

No console você verá se a paginação funcionou:
`[paginação] ✔ PADRÃO FUNCIONANDO: /_next/data/<buildId>/shop/laticinios.json?page={p}`

### 3. Todas as 25 seções

```bash
python scrap_soudaki.py --secao all --sem-paginacao
# ou seções específicas:
python scrap_soudaki.py --secao laticinios,bebidas,mercearia
```

> ✅ **Verificado em campo (out/2026):** o site **não tem paginação de servidor** — a
> rolagem infinita já renderiza o catálogo completo que vem no `__NEXT_DATA__`
> (ex.: laticinios = 320 SKUs no lote pré-carregado). Por isso use `--sem-paginacao`:
> pula a descoberta de padrões e economiza ~20s de testes 404 por seção
> (~8 min no run completo). Sem o flag o coletor continua compatível caso o
> site passe a paginar de verdade.

Cada execução **faz merge** com os JSONs existentes (não perde coletas anteriores).

### 4. Gravar no Neon

Primeiro confira os JSONs. Depois, com `DATABASE_URL` do Neon definido
(no `.env.local` da raiz do repo, como o backend já faz):

```bash
python scrap_soudaki.py --integrar --dry-run   # simula: mostra matches/novos sem gravar
python scrap_soudaki.py --integrar             # grava de verdade (loja_id=4)
```

A integração usa a mesma lógica do v1: match por **EAN** → match por **nome normalizado**
(preenchendo EAN faltante) → cria produto novo (relevância 10) → upsert em `precos`.

Também dá para coletar e gravar em um comando só: `python scrap_soudaki.py --secao all --db`.

## Solução de problemas

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `[HTTP 403]` em tudo | Cloudflare desafiando o requests | `pip install cloudscraper` e rode de novo |
| `[HTTP 404]` no `/shop/` | Você está fora do Brasil (VPN/proxy) ou a loja saiu do ar de vez | rode sem VPN; confirme no navegador |
| `SKUs pré-carregados: 0` | Estrutura do `__NEXT_DATA__` mudou | mande a saída do `--probe` |
| `[paginação] nenhum padrão` | **Comportamento esperado** — a rolagem infinita já traz tudo no pré-carregado (confirmado em out/2026) | nada a fazer; use `--sem-paginacao` para acelerar. Se a seção na tela do navegador tiver MUITO mais produtos que o lote, aí sim: DevTools (F12) → Network → role a página → copie o XHR que carrega mais produtos e me mande |
| `buildId` mudou de um dia pro outro | Deploy novo do site | normal — a v2 redescobre sozinha a cada execução |

## Uso responsável

- O ritmo padrão é ~1 request/segundo com jitter — não reduza o `SLEEP_BASE` abaixo de 0.5.
- Dados são públicos (nomes/preços de produtos); não há dados pessoais envolvidos.
- Uso acadêmico (Projeto Integrador UNIVESP); confira os Termos de Uso do site antes
  de qualquer uso comercial.

## Diferenças para o v1 (`coletar_e_integrar_soudaki.py`)

| | v1 | v2 |
|---|---|---|
| Escopo | lote pré-carregado da seção | lote + paginação profunda + subcategorias |
| Diagnóstico | nenhum | `--probe` com buildId/estrutura |
| Saída | direto no Neon | JSON revisável primeiro, Neon depois (`--db`/`--integrar`) |
| Retomada | não | checkpoint por seção |
| Parser | chaves fixas | resiliente a renomeação de chaves (varredura recursiva) |
| Fallback | nenhum | cloudscraper + rotas alternativas + HTML SSR |
