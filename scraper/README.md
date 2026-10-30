# Scrapers — Despensa Planejada Santos

Coletores de preços dos quatro supermercados comparados pelo projeto
(PI2 UNIVESP 2026.2). Cada loja tem uma pasta com coletor autônomo
(`scrap_<loja>.py`) que usa a API/estrutura de dados real do site — sem
raspagem de HTML renderizado.

| Loja | Pasta | Técnica | `loja_id` | Saída | Integração Neon |
| --- | --- | --- | --- | --- | --- |
| Carrefour (Ponta da Praia) | `carrefour/` | API VTEX `carrefourbrfood.myvtex.com` (sem captcha) | 1 | JSON único com preço embutido | `integrar_carrefour_pa.py` |
| Pão de Açúcar | `pao_de_acucar/` | API GPA `api.vendas.gpa.digital` | 2 | JSON único com preço embutido | `integrar_carrefour_pa.py` |
| Atacadão | `atacadao/` | API VTEX `atacadaobr.vtexcommercestable.com.br` + cache-buster `&_cb=` | 3 | `output/*.json` (produtos + preços) | direto: `--db` / `--integrar` |
| Soudaki (Daki) | `soudaki/` | `__NEXT_DATA__` + rotas `/_next/data` do Next.js | 4 | `output/*.json` (produtos + preços) | direto: `--db` / `--integrar` |

## Instalação

```bash
cd scraper
python -m pip install -r requirements.txt
```

`cloudscraper` é opcional (plano B contra Cloudflare) mas recomendado.

## Uso rápido

```bash
# diagnóstico (30 s) — todos os coletores têm --probe
python carrefour/scrap_carrefour.py --probe
python pao_de_acucar/scrap_paodeacucar.py --probe
python atacadao/scrap_atacadao.py --probe
python soudaki/scrap_soudaki.py --probe --secao laticinios

# coleta completa
python carrefour/scrap_carrefour.py                     # 11 corredores de mercado
python pao_de_acucar/scrap_paodeacucar.py               # 5 departamentos
python soudaki/scrap_soudaki.py --secao all --sem-paginacao

# coleta + gravação direta no Neon (Soudaki e Atacadão)
python soudaki/scrap_soudaki.py --secao all --db --dry-run   # simula antes
python soudaki/scrap_soudaki.py --secao all --db
python atacadao/scrap_atacadao.py --secao all --db
```

Cada coletor documenta seus parâmetros no cabeçalho e tem `README.md`
próprio (Soudaki e Atacadão trazem também `COMECE_AQUI.txt` com o passo
a passo na máquina do autor).

## Regras de caminho (importante)

- `soudaki/` e `atacadao/` precisam ficar **um nível abaixo de `scraper/`**:
  a integração resolve a raiz do repo com `Path(__file__).parents[2]` e
  importa `webapp/backend/db.py` (que usa `DATABASE_URL` ou
  `NEON_DATABASE_URL`; sem elas cai no SQLite local).
- `filtro_adulto.py` precisa ficar **na raiz de `scraper/`**: o ETL
  (`webapp/backend/importar_json_para_sqlite.py`) o importa por
  `parents[2]/scraper`; se sumir, o filtro de produtos adultos fica
  silenciosamente desligado.

## Dados de coleta (fora do git)

JSONs brutos, checkpoints e `output/` ficam apenas no disco do autor
(padronizados no `.gitignore`); os dados vivos são o **Neon/PostgreSQL**.
A coleta do **Atacadão está pausada** — não retomar sem decisão do grupo.

## Fluxo de publicação

1. **Soudaki / Atacadão** — coletor grava direto no Neon
   (match por EAN-13 → nome normalizado; cria produto novo com
   `relevancia = 10` quando não há correspondência).
2. **Carrefour / Pão de Açúcar** — os JSONs v2 (formato único com preço
   embutido) entram pelo `integrar_carrefour_pa.py`, com o mesmo critério
   dos integradores dos Soudaki/Atacadão: vínculo por EAN-13 (inclusive
   os códigos internos `0000000*` do GPA, já usados no catálogo) ou nome
   normalizado, produto novo com `relevancia = 10`, categoria resolvida
   contra as canônicas do catálogo, filtro adulto aplicado e upsert de
   preço por `(produto_id, loja_id)` — quando há promoção (`preco <
   preco_original`) o valor promocional vai em `preco_promocional` e o
   de lista em `preco_regular`; sem promoção, `preco_promocional = NULL`
   (o app lê `COALESCE(preco_promocional, preco_regular)`). Campos do
   JSON v2 mapeados: `imagem` → `imagem_url`, `unidade`+`multiplicador`
   → `apresentacao`, `disponivel`+`estoque > 0` → `em_estoque`
   (Carrefour usa `99999` como "infinito"):

   ```bash
   python scraper/integrar_carrefour_pa.py                 # simula (dry-run)
   python scraper/integrar_carrefour_pa.py --db            # grava no Neon
   python scraper/integrar_carrefour_pa.py --db --limite 200  # teste curto
   python scraper/teste_integrador_pa.py                   # testes das funções puras
   ```

   O refresco pontual de preços segue disponível via
   `atualizar_precos_ean_cep.py`.
3. Utilitários: `recoletar_por_ean.py` (releitura de preço/estoque para
   EANs específicos), `relatorio_cobertura.py` (métricas por loja,
   `--kpi`) e `atualizar_precos_ean_cep.py` (lote por EAN + CEP).

Documentação técnica completa: [`docs/scrapers.md`](../docs/scrapers.md).
