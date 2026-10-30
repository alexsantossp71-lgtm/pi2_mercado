# Changelog

Mudanças notáveis do projeto **Despensa Planejada Santos**.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
versões semânticas simplificadas (data por sessão de trabalho).

## [2026-10-30] — Sessão de limpeza do banco e UX

### Adicionado
- `scraper/limpar_mojibake.py`: detecta e corrige produtos com double-encoding
  UTF-8 no Neon (regex precisa `[\u00C3\u00C2][\u00A0-\u00BF]` distingue
  "LinguiÃ§a" de "Coração" legítimo). Para cada produto: se há versão correta
  correspondente por EAN/nome, deleta a duplicata migrando os preços; senão
  corrige o nome in-place. Commit em lotes de 50 para evitar timeout.
- `scraper/teste_limpar_mojibake.py`: 4 testes das funções puras
  (`tem_mojibake`, `decodificar_mojibake` com bytes órfãos, `_norm_nome`,
  `resolver_categoria`).
- `scraper/integrar_carrefour_pa.py`: integrador Neon para os JSONs v2 do
  Carrefour e Pão de Açúcar (loja_id 1 e 2), com o mesmo critério do
  Soudaki/Atacadão: vínculo por EAN-13 (inclui códigos internos `0000000*`
  do GPA) ou nome normalizado, produto novo com `relevancia = 10`,
  categoria resolvida contra as canônicas, filtro adulto aplicado, upsert
  de preço por `(produto_id, loja_id)`.
- `scraper/teste_integrador_pa.py`: 6 testes das funções puras do integrador.
- `LICENSE` (MIT) e este `CHANGELOG.md`.

### Corrigido
- **Mojibake em produção**: 832 produtos do Soudaki estavam com
  double-encoding UTF-8 no Neon (ex.: "LinguiÃ§a" em vez de "Linguiça").
  Raiz: `scraper/soudaki/scrap_soudaki.py` função `baixar()` usava
  `r.text` sem forçar `r.encoding = 'utf-8'` — o site Soudaki serve
  UTF-8 mas não declara `charset` no `Content-Type`, então o `requests`
  aplica ISO-8859-1 por default (RFC 2616). Fix: força UTF-8 quando
  encoding vem vazio ou Latin-1. Aplicado `limpar_mojibake.py` no Neon:
  461 corrigidos in-place + 487 deletados como duplicatas com migração
  de preços. Zero mojibakes restantes.
- **Bug no `integrar_carrefour_pa.py`**: usava `p.get('imagem_url')` e
  `p.get('apresentacao')`, mas o JSON v2 tem `imagem` e
  `unidade`+`multiplicador`. Ambos ficavam sempre NULL. Corrigido com
  helpers `_apresentacao()` e mapeamento direto.
- **Lógica de preço do integrador**: sempre preenchia `preco_promocional`,
  mesmo sem promoção. Agora `NULL` quando `preco == preco_original`
  (preço efetivo via `COALESCE(preco_promocional, preco_regular)`).
- **`em_estoque` do integrador**: ignorava o campo `estoque`. Agora combina
  `disponivel AND estoque > 0` (Carrefour usa `99999` como "infinito").
- **7 produtos em categoria "Churrasco"** residual: 6 cervejas/RTDs →
  "Bebidas", 1 carvão → "Bazar".

### Mudado
- **Consolidação de categorias**: 33 → 15 categorias no catálogo.
  - **Deletadas (5)**: Vestuário, Automotivo, Esporte e lazer, Papelaria,
    Eletrônicos e Eletroportáteis (159 produtos fora de escopo de
    supermercado alimentar).
  - **Deletadas (1)**: "Geral" — 19.755 placeholders com nome
    "Produto EAN <numero>" sem utilidade para o usuário.
  - **Fundidas (12)**: Vinhos+Destilados+Cervejas → Bebidas;
    Biscoitos+Chocolates+Molhos → Mercearia; Sorvetes → Congelados;
    Farmácia → Higiene e Perfumaria; Descartáveis → Limpeza; Saudáveis →
    Suplementos; Pratos Prontos distribuído; "Produtos Daki" + "Prático
    e Rápido" → Mercearia.
  - **Novas (2)**: Cozinha (14.397 itens de panelas/talheres) e Banheiro
    e Sanitário (5.870), desmembradas de Bazar para melhor granularidade.
  - **Reclassificação por palavra-chave**: 42.335 produtos de "Utilidades
    Domésticas" → Bazar; 11.166 de "Alimentos" distribuídos em 8 categorias
    via heurística de palavras-chave em 5 rodadas (1 residual movido
    manualmente para Mercearia).

### Resultado no Neon
- Produtos: **113.516 → 93.115** (-20.401, -18%)
- Preços: **123.539 → 103.156** (-20.383)
- Categorias: **33 → 15** (-18)
- Comparáveis (2+ lojas): **6.719** (mantido)

### UX (home)
- **Invertida a ordem dos campos**: produto agora vem antes de marca
  (lógica do usuário: busca pelo produto primeiro, filtra marca depois).
  Placeholder de marca mudou para "Filtrar por marca (opcional)...".
- **Checkbox "Mostrar só produtos com preço em 2+ lojas"** movido para
  linha própria alinhado à esquerda (antes flutuava à direita do botão
  Adicionar e parecia descartado).
- **Alinhamento da Linha 2** (seção + marca) corrigido com `flex: 0 0 auto`
  no select e `flex: 1 1 auto` no input — preenche a largura total,
  alinhado com a Linha 1 acima.
- Cache PWA elevado: v8 → v11 (3 bumps durante a sessão).

### Documentação
- `README.md` atualizado com números reais (93.115 / 6.719 / 15 categorias).
- `docs/scrapers.md` reescrito com diagrama do pipeline atual e novos
  scripts (`limpar_mojibake.py`, `teste_integrador_pa.py`).
- `scraper/README.md` reescrito com tabela das 4 lojas, comandos e regras
  de caminho (parents[2], filtro_adulto na raiz).
- `webapp/scrapers.html` atualizado com números reais pós-limpeza.

## [2026-10-30 — início da sessão] — Reestruturação da pasta scraper/

### Adicionado
- Reorganização completa da pasta `scraper/` com 4 coletores v2 autônomos,
  um por loja: `carrefour/scrap_carrefour.py`, `pao_de_acucar/scrap_paodeacucar.py`,
  `atacadao/scrap_atacadao.py`, `soudaki/scrap_soudaki.py`. Cada um com
  README próprio (Atacadão e Soudaki têm também `COMECE_AQUI.txt`).
- `scraper/requirements.txt`: `requests`, `cloudscraper`, `psycopg2-binary`,
  `python-dotenv`.
- `scraper/README.md` com tabela das 4 lojas (técnica/loja_id/saída/integração).
- `docs/scrapers.md` reescrito: diagrama do pipeline, estrutura de pastas,
  comandos por loja, regras de integração, schema do banco, convenções.
- `webapp/scrapers.html`: página pública "Como coletamos os preços" com
  pipeline em 5 etapas, cards por loja com logos oficiais, tema claro/escuro.

### Removido
- Pipeline v1 (25 arquivos): `scraper/secoes/` (coletor_vtex.py, coletar_pa.py
  etc.), `coletar_e_integrar_soudaki.py` v1, enriquecedores pontuais,
  `coletar_carrefour_categorias_db.py`, `cruzar_produtos.py`, `_run_batch.py`,
  `scraper/openfoodfacts/`. Histórico preservado no git.

## [2026-10-30 — anteriormente]

### Adicionado
- Filtro de conteúdo adulto (`scraper/filtro_adulto.py`): 2 camadas
  (seção adulta + nome/marca), exceções para coletor menstrual e
  preservação de falsos positivos reais (Abelha Rainha, Sexyhair,
  camisinhas, Algemarin). 54 casos de teste.
- ETL `importar_json_para_sqlite.py`: pula produtos do catálogo sem
  preço em nenhuma loja (17.267 produtos removidos do SQLite local).
- UX v7: comparativo honesto (MENOR PREÇO só para lista completa,
  parciais com `*` e legenda), microcopy do MELHOR, aviso de economia
  < R$1, resumo-resposta no topo, checklist tátil (check circular 28px,
  riscado, barra de progresso), laranja unificado, chips de produtos
  populares no estado vazio.

### Removido
- 226 arquivos mortos do repo (plugins/tooling antigo, logs, render.yaml,
  redirect raiz, frontend React de protótipo, vercel.json duplicado em
  webapp/, app.py Flask de protótipo, data_loader e migrate_to_turso/
  test_sql — Turso abandonado).
- ~150MB de dados de coleta (JSONs brutos, `dispensa.db`, `produtos.zip`)
  do git; arquivos permanecem no PC do autor; dados vivos no Neon;
  `.gitignore` com padrões de dados/logs.

## [2026-10-29] — Ajustes de backend

### Corrigido
- `backend/main.py`: removido `ALTER TABLE` em `precos` do endpoint
  `api_meta` para evitar locks na tabela.
- Busca re-ranqueada, melhor loja única por cobertura, preços frescos
  via `POST /api/produtos/lote`, fotos nas sugestões, seções com contagem
  e normalizador de categorias do Neon (`webapp/backend/normalizar_categorias_neon.py`).
