# MEMORY.md — Dispensa Planejada Santos

> Documentação técnica completa do sistema. Atualizado em 2026-08-26.
> Projeto Integrador em Computação II — UNIVESP 2026.2

---

## 1. Visão Geral do Sistema

**Dispensa Planejada Santos** é um sistema de comparação de preços de supermercados
na cidade de Santos/SP. O objetivo é permitir que o consumidor monte uma lista de
compras e descuba qual loja (ou combinação de lojas) oferece o menor custo total.

**Stack:**
- **Scraper:** Python (requests) — coleta preços de 3 redes de supermercado
- **Backend:** FastAPI + Turso LibSQL (SQLite serverless) + FTS5
- **Frontend:** HTML/JS vanilla + React (protótipo de sazonalidade)
- **Deploy:** Render (backend) + Vercel (frontend/estático)

**Lojas monitoradas:**
| Loja | Plataforma | Método de Coleta |
|------|-----------|-----------------|
| Carrefour (Ponta da Praia) | VTEX | API REST `/api/catalog_system/pub/products/search` |
| Pão de Açúcar | GPA Digital | API REST `api.vendas.gpa.digital/pa` |
| Atacadão | VTEX | API REST (mesmo endpoint do Carrefour) |

---

## 2. Arquitetura de Dados — Fluxo Completo

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FASE 1: COLETA (Scraper)                     │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │ coletar_     │  │ coletar_     │  │ coletar_     │             │
│  │ carrefour.py │  │ pa.py        │  │ atacadao.py  │             │
│  │ (VTEX)       │  │ (GPA API)    │  │ (VTEX)       │             │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘             │
│         │                 │                 │                       │
│         ▼                 ▼                 ▼                       │
│  produtos_           produtos_         produtos_                    │
│  carrefour.json      pa.json           atacadao.json               │
│  precos_carrefour_   precos_pao_de_    precos_atacadao_            │
│  ampliado.json       acucar_ampliado   ampliado.json               │
│                      .json                                         │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FASE 2: CONSOLIDAÇÃO                              │
│                                                                     │
│  consolidar.py                                                      │
│    ├── Merge catálogos (dedup por EAN)                              │
│    ├── Calcula relevância (lista curada + cobertura lojas)          │
│    └── Copia JSONs para webapp/                                     │
│                                                                     │
│  enriquecer_orfaos.py                                               │
│    ├── Identifica EANs em preços mas ausentes no catálogo           │
│    ├── Busca dados via VTEX (Carrefour/Atacadão)                   │
│    └── Fallback: Open Food Facts API                                │
│                                                                     │
│  Resultado:                                                         │
│    produtos_ampliado.json (catálogo unificado ~2000+ produtos)      │
│    precos_*_ampliado.json (preços por loja)                         │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 FASE 3: importar_json_para_sqlite.py                │
│                                                                     │
│  Lê JSONs → cria dispensa.db (SQLite local)                         │
│    ├── Tabela `lojas` (3 registros)                                 │
│    ├── Tabela `produtos` (id, gtin_ean, nome, categoria, marca...)  │
│    ├── Tabela `precos` (produto_id, loja_id, preco_promo, regular)  │
│    ├── Índices B-Tree (ean, categoria, marca, produto+loja)         │
│    └── Tabela virtual FTS5 (busca textual por nome/categoria/marca) │
│                                                                     │
│  Cadastra "órfãos" automaticamente (preços sem catálogo prévio)    │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                FASE 4: migrate_to_turso.py                          │
│                                                                     │
│  Copia dispensa.db → Turso LibSQL (produção cloud)                  │
│    ├── DDL (tabelas + índices + FTS5)                               │
│    └── Dados em batches de 500 registros                            │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                FASE 5: FastAPI Backend (main.py)                    │
│                                                                     │
│  Conecta ao Turso via libsql_client                                 │
│  Endpoints:                                                         │
│    GET  /api/produtos?q=&categoria=&marca=&page=&limit=            │
│         → Busca FTS5 + filtros + paginação                          │
│    GET  /api/produtos/{id}                                          │
│         → Detalhe de 1 produto + preços nas 3 lojas                │
│    GET  /api/categorias                                             │
│         → Lista categorias com contagem                              │
│    GET  /api/marcas?categoria=                                      │
│         → Lista marcas (filtrável por categoria)                    │
│    POST /api/calcular                                               │
│         → Otimização multi-loja (menor cesto)                       │
│    GET  /api/sazonalidade?item=                                     │
│         → Análise de sazonalidade (Flask legado, proto)             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Scraper — Detalhamento

### 3.1 Coletor VTEX (Carrefour + Atacadão)

**Arquivo:** `scraper/secoes/coletor_vtex.py`

Ambas as lojas rodam na plataforma VTEX. O scraper é o mesmo, parametrizado.

**Como funciona:**
1. Carrega "folhas" (slug de categorias) de `folhas_carrefour.json` / `folhas_atacadao.json`
2. Para cada folha, faz paginasção via API VTEX (`_from` / `_to`)
3. Filtra por `fq=isAvailablePerSalesChannel_1:1` (só produtos disponíveis no canal online)
4. Extrai de cada produto:
   - **EAN-13** (via `items[0].ean` ou `alternateIds`)
   - **Preço** (menor preço entre sellers, descontando marketplace)
   - **Nome, marca, imagem, seção**
5. Deduplica por EAN ao longo de toda a execução
6. **Checkpoint** a cada N folhas (retomada automática em caso de interrupção)
7. Limite de 2.500 itens por folha (cap de offset da VTEX)

**Configuração por loja:**
```python
# Carrefour
base_url = "https://www.carrefour.com.br"
pagina_tamanho = 50
limite_max = 2500
sleep = 0.2s
checkpoint_a_cada = 10 folhas

# Atacadão (idêntico, exceto checkpoint)
checkpoint_a_cada = 20 folhas
```

**Arquivos de saída:**
- `produtos_carrefour.json` / `produtos_atacadao.json`
- `precos_carrefour_ampliado.json` / `precos_atacadao_ampliado.json`
- Arquivos `.parcial` durante execução (checkpoint)

### 3.2 Coletor GPA (Pão de Açúcar)

**Arquivo:** `scraper/secoes/coletar_pa.py`

O Pão de Açúcar usa uma API própria (GPA Digital), diferente da VTEX.

**Como funciona:**
1. Percorre 8 `multiCategorys` (alimentos, bebidas, limpeza, perfumaria, bazar, descartaveis, bebe-e-crianca, petshop)
2. Cada multiCategory tem subcategorias via filtro `facetSubShelf_ss`
3. **Fase 1 — Listagem:** Paginação com POST na API de busca, coleta IDs únicos
   - A API GPA tem paginação rotativa → faz 8 varreduras por subcategoria para capturar 95%+ dos IDs
4. **Fase 2 — Detalhe:** Para cada ID, busca detalhe via GET `/v4/products/ecom/{id}`
   - Extrai EAN, preço regular, promoções ativas, estoque
5. Deduplica por EAN

**Diferenças vs VTEX:**
- Não usa slug de categorias — usa filtros facetados
- Precisa de 2 fases (listagem + detalhe) por causa da API
- Detecta promoções ativas (com datas de início/fim)

### 3.3 Configuração de Seções

**Arquivo:** `scraper/secoes/config_secoes.py`

Define as folhas-alvo (slugs VTEX) e as subcategorias GPA.
- `folhas_carrefour.json` — ~200+ slugs de categorias do Carrefour
- `folhas_atacadao.json` — ~448 slugs de categorias do Atacadão

### 3.4 Geração de Folhas

**Arquivo:** `scraper/secoes/gerar_folhas.py`

Script que descobre automaticamente os slugs disponíveis em cada loja VTEX
(varrendo a árvore de categorias da API).

---

## 4. Consolidação e Enriquecimento

### 4.1 consolidar.py

**Arquivo:** `scraper/secoes/consolidar.py`

Executa **após** todas as coletas das 3 lojas.

**Processo:**
1. Carrega catálogos individuais de cada loja
2. Merge por EAN (deduplicação):
   - Se o EAN já existe → mantém, mas preenche campos faltantes (nome, marca)
   - Se é novo → adiciona
3. Calcula **relevância** para cada produto (0-100)
4. Copia JSONs consolidados para `webapp/`

### 4.2 Algoritmo de Relevância

**Arquivo:** `scraper/secoes/relevancia.py`

```
relevancia = curado(0-100) × 0.70
           + cobertura_lojas(0-100) × 0.20
           + desempate(0-12) × 0.10
           - penalidade_derivado
           + bonus_tipo_principal
```

- **curado:** Match contra lista de ~80 itens essenciais (cesta básica brasileira)
  - Peso 100: arroz, feijão, açúcar, leite, café
  - Peso 60-80: macarrão, ovos, frango, papel higiênico
  - Peso 40-55: itens menos essenciais
- **cobertura:** Quantas lojas vendem o mesmo EAN (0-3 lojas)
- **desempate:** Fator 0.3-1.2 (kits perdem, marcas conhecidas ganham)
- **penalidade_derivado:** Leite condensado ≠ leite, creme de leite ≠ leite, etc.
- **bonus_tipo_principal:** "leite integral" ganha bônus vs "leite de coco"

### 4.3 enriquecer_orfaos.py

**Arquivo:** `scraper/enriquecer_orfaos.py`

Produtos "órfãos" = EANs que aparecem nos preços mas não têm cadastro no catálogo.

**Fontes de enriquecimento (em ordem):**
1. VTEX (Carrefour) — busca por EAN
2. VTEX (Atacadão) — busca por EAN
3. Open Food Facts — fallback global (API pública)

---

## 5. Banco de Dados

### 5.1 Schema SQLite (local)

```sql
CREATE TABLE lojas (
    id INTEGER PRIMARY KEY,
    chave TEXT UNIQUE NOT NULL,    -- 'carrefour', 'pao_de_acucar', 'atacadao'
    nome TEXT NOT NULL,
    icone TEXT NOT NULL
);

CREATE TABLE produtos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gtin_ean TEXT,                 -- EAN-13 (código de barras)
    nome TEXT NOT NULL,
    categoria TEXT NOT NULL,
    marca TEXT NOT NULL,
    relevancia INTEGER DEFAULT 0, -- 0-100
    imagem_url TEXT,
    apresentacao TEXT              -- ex: "500g", "1L", "12un"
);

CREATE TABLE precos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id INTEGER NOT NULL,
    loja_id INTEGER NOT NULL,
    preco_promocional REAL,
    preco_regular REAL,
    em_estoque INTEGER DEFAULT 0,
    FOREIGN KEY(produto_id) REFERENCES produtos(id),
    FOREIGN KEY(loja_id) REFERENCES lojas(id)
);

-- Índices para performance
CREATE INDEX idx_produtos_ean ON produtos(gtin_ean);
CREATE INDEX idx_produtos_cat ON produtos(categoria);
CREATE INDEX idx_produtos_marca ON produtos(marca);
CREATE INDEX idx_precos_prod_loja ON precos(produto_id, loja_id);

-- Busca textual full-text
CREATE VIRTUAL TABLE produtos_fts USING fts5(
    id UNINDEXED, nome, categoria, marca,
    tokenize='unicode61 remove_diacritics 1'
);
```

### 5.2 Turso LibSQL (produção)

Mesmo schema, hospedado no Turso (SQLite serverless). Conexão via `libsql_client`.
URL e token ficam em `webapp/backend/.env`:
```
TURSO_DATABASE_URL=libsql://dispensa-xxx.turso.io
TURSO_AUTH_TOKEN=eyJ...
```

### 5.3 ETL: JSON → SQLite

**Arquivo:** `webapp/backend/importar_json_para_sqlite.py`

1. Lê `produtos_ampliado.json` + 3 arquivos de preços
2. Cria tabelas (DROP + CREATE)
3. Insere produtos (com ID sequencial)
4. Cadastra órfãos (preços sem catálogo → cria registro mínimo)
5. Preenche FTS5
6. Gera `dispensa.db`

### 5.4 Migração: SQLite → Turso

**Arquivo:** `webapp/backend/migrate_to_turso.py`

1. Lê DDL do SQLite local
2. Recria tabelas no Turso
3. Copia dados em batches de 500

---

## 6. Backend FastAPI

### 6.1 Estrutura

```
webapp/backend/
├── main.py                    # Entrypoint FastAPI
├── models.py                  # Pydantic models
├── db.py                      # Conexão Turso LibSQL
├── services/
│   ├── product_service.py     # CRUD de produtos + busca FTS
│   └── price_service.py       # Cálculo de cesto multi-loja
├── importar_json_para_sqlite.py  # ETL local
├── migrate_to_turso.py        # Migração para cloud
├── requirements.txt
└── .env                       # Credenciais Turso
```

### 6.2 Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Status da API |
| GET | `/api/produtos` | Busca com FTS + filtros + paginação |
| GET | `/api/produtos/{id}` | Detalhe de 1 produto |
| GET | `/api/categorias` | Lista categorias |
| GET | `/api/marcas` | Lista marcas |
| POST | `/api/calcular` | Otimização multi-loja |
| GET | `/api/sazonalidade` | Análise de sazonalidade (Flask legado) |

### 6.3 Lógica de Otimização Multi-Loja (`price_service.py`)

Dada uma lista de produtos com quantidades:
1. **Loja única:** Calcula o total se comprar tudo em cada loja → identifica melhor/pior
2. **Multi-loja:** Para cada produto, seleciona a loja com menor preço → soma otimizada
3. Retorna economia potencial (diferença entre pior loja única e otimização multi-loja)

**Lojas fixas (hardcoded):**
```python
LOJAS = {
    "carrefour":     {"nome": "Carrefour - Ponta da Praia", "icone": "🛍️", "index": 0},
    "pao_de_acucar": {"nome": "Pão de Açúcar",              "icone": "🥐", "index": 1},
    "atacadao":      {"nome": "Atacadão",                    "icone": "🏬", "index": 2},
}
```

---

## 7. Frontend

### 7.1 Webapp Principal

**Arquivo:** `webapp/index.html` — HTML/JS vanilla, bem mais completo que o React.

Funcionalidades:
- Busca de produtos com autocompletar
- Filtro por categoria e marca
- Exibição de preços nas 3 lojas (colunas)
- Montagem de lista de compras
- Cálculo de total por loja e multi-loja
- Indicação de melhor loja

### 7.2 Protótipo de Sazonalidade

**Arquivo:** `webapp/frontend/src/App.js` — React simples

- Input: nome do item
- Chama Flask legado (`/api/sazonalidade`)
- Retorna CSV de sazonalidade (análise estatística de preços históricos)
- Gerado por `prototipo/analise_sazonalidade.py`

---

## 8. Scripts de Validação e Diagnóstico

Na raiz do workspace há vários scripts Python para verificação de dados:

| Script | Função |
|--------|--------|
| `check_ean.py` | Verifica validade de EANs (dígito verificador) |
| `check_all_ean.py` | Verifica TODOS os EANs do catálogo |
| `count_products.py` | Conta produtos por loja/categoria |
| `check_petshop_prices.py` | Valida preços da seção petshop |
| `check_folhas_pet.py` | Verifica folhas de petshop |
| `check_atacadao_pet.py` | Valida dados do Atacadão pet |
| `check_atacadao_overlap.py` | Verifica sobreposição entre lojas |
| `check_atacadao_debug.py` | Debug da coleta Atacadão |
| `petshop_coverage.py` | Análise de cobertura petshop |
| `check_carrefour_petshop.py` | Valida Carrefour petshop |
| `compare_structures.py` | Compara estruturas de dados entre lojas |
| `enrich_catalog.py` | Enriquecimento adicional do catálogo |
| `list_petshop_folhas.py` | Lista folhas de petshop disponíveis |

---

## 9. JSON Files — Catálogo e Preços

### 9.1 Catálogo de Produtos

**`produtos_ampliado.json`** — Array de objetos:
```json
{
  "gtin_ean": "7891234567890",
  "secao": "Alimentos",
  "subsecao": "Mercearia Salgada",
  "nome_completo": "Arroz Tipo 1 Camil 5kg",
  "marca": "Camil",
  "apresentacao": {"quantidade": 5, "unidade_medida": "kg"},
  "imagem_url": "https://...",
  "data_cadastro": "2026-08-20",
  "relevancia": 95
}
```

### 9.2 Preços por Loja

**`precos_{loja}_ampliado.json`** — Array de objetos:
```json
{
  "gtin_ean": "7891234567890",
  "supermercado": "Carrefour",
  "preco_regular": 27.99,
  "preco_promocional": 22.99,
  "em_estoque": true,
  "data_coleta": "2026-08-25"
}
```

### 9.3 Arquivos de Backup

`.bak` files são cópias de segurança dos preços antes de atualização.

---

## 10. Problemas Conhecidos e Atualização da Base

### 10.1 O Problema Central: Atualização de Preços e Produtos

A atualização da base enfrenta os seguintes desafios:

1. **Rotatividade de preços:** Preços mudam diariamente; a coleta precisa ser periódica
2. **Produtos novos/discontinuados:** Catálogo precisa ser atualizado, não só preços
3. **Órfãos:** Produtos que aparecem nos preços mas não no catálogo → precisa enriquecimento
4. **Folhas desatualizadas:** Slugs de categorias podem mudar nas lojas VTEX
5. **APIs instáveis:** Rate limits, mudanças de API, bloqueio de IP

### 10.2 Pipeline de Atualização (ideal)

```bash
# 1. Atualizar folhas (descobrir novas categorias)
python scraper/secoes/gerar_folhas.py

# 2. Coletar preços (cada loja separadamente)
python scraper/secoes/coletar_carrefour.py
python scraper/secoes/coletar_pa.py
python scraper/secoes/coletar_atacadao.py

# 3. Consolidar + relevância
python scraper/secoes/consolidar.py

# 4. Enriquecer órfãos
python scraper/enriquecer_orfaos.py

# 5. ETL: JSON → SQLite local
python webapp/backend/importar_json_para_sqlite.py

# 6. Migrar para Turso
python webapp/backend/migrate_to_turso.py
```

### 10.3 Problemas Identificados

- **`data_loader.py`** no backend carrega JSONs em memória (legado) — o `main.py` FastAPI usa Turso diretamente
- **`app.py`** é Flask legado (sazonalidade) — não é o backend principal
- **Hardcoded:** Lojas fixas em 3 (não configurável)
- **Sem agendamento:** Coleta é manual, não automatizada (sem cron/scheduler)
- **Testes limitados:** Apenas `test_api.py` e `test_perf.py`

---

## 11. Estrutura de Diretórios

```
G:\pi 2 - 2026\
├── scraper/                          # Motor de coleta
│   ├── openfoodfacts/                # Dados Open Food Facts
│   ├── secoes/                       # Coleta por seção
│   │   ├── coletor_vtex.py           # Coletor genérico VTEX
│   │   ├── coletar_carrefour.py      # Entrypoint Carrefour
│   │   ├── coletar_atacadao.py       # Entrypoint Atacadão
│   │   ├── coletar_pa.py             # Entrypoint Pão de Açúcar
│   │   ├── consolidar.py             # Merge + relevância
│   │   ├── relevancia.py             # Algoritmo de relevância
│   │   ├── config_secoes.py          # Configuração de seções
│   │   ├── gerar_folhas.py           # Descoberta de slugs
│   │   └── folhas_*.json             # Slugs por loja
│   ├── cruzar_produtos.py            # Cruzamento OFF + Carrefour
│   ├── enriquecer_orfaos.py          # Enriquecimento de órfãos
│   └── *.json                        # Dados brutos por loja
│
├── webapp/                           # Aplicação web
│   ├── index.html                    # Frontend principal
│   ├── backend/
│   │   ├── main.py                   # FastAPI (backend principal)
│   │   ├── models.py                 # Pydantic models
│   │   ├── db.py                     # Conexão Turso
│   │   ├── services/
│   │   │   ├── product_service.py    # Busca de produtos
│   │   │   └── price_service.py      # Otimização de cesto
│   │   ├── importar_json_para_sqlite.py  # ETL
│   │   └── migrate_to_turso.py       # Migração cloud
│   ├── frontend/
│   │   └── src/App.js                # React (protótipo sazonalidade)
│   ├── css/, js/, assets/            # Frontend estático
│   └── api/                          # Serverless functions (Vercel)
│
├── prototipo/                        # Análise de sazonalidade
├── turso/                            # Config Turso CLI
├── testes_app/                       # Testes manuais
├── regulamentos/                     # Regulamentos UNIVESP
├── modelos_documentos/               # Modelos de relatório
├── cronograma/                       # Cronograma do PI
│
├── *.json                            # Dados consolidados na raiz
├── *.py                              # Scripts de validação
├── MEMORY.md                         # Este arquivo
└── .env                              # Credenciais (não versionar)
```

---

## 12. Tecnologias e Dependências

### Backend
- Python 3.11+
- FastAPI + uvicorn
- Pydantic (models)
- libsql_client (Turso)
- python-dotenv

### Scraper
- Python 3.11+
- requests (HTTP)
- json (padrão)

### Frontend
- HTML5 / CSS3 / JavaScript vanilla
- React (protótipo)
- Sem bundler (CDN)

### Infra
- Turso (SQLite serverless)
- Render (deploy backend)
- Vercel (deploy frontend)

---

## 13. Comandos Úteis

```bash
# Rodar backend localmente
cd webapp/backend
python main.py
# → http://localhost:8000/docs (Swagger)

# Rodar scraper (exemplo: Carrefour)
cd scraper/secoes
python coletar_carrefour.py

# Consolidar dados
cd scraper/secoes
python consolidar.py

# ETL local
cd webapp/backend
python importar_json_para_sqlite.py

# Migrar para Turso
cd webapp/backend
python migrate_to_turso.py

# Verificar EANs
python check_all_ean.py

# Contar produtos
python count_products.py
```

---

## 14. Notas para Futuro

1. **Automação:** Criar scheduler (cron/Rundeck/Airflow) para coleta periódica
2. **Histórico de preços:** Schema versionado para tracking temporal
3. **Alertas de preço:** Notificação quando produto baixa de valor
4. **Expansão de lojas:** Tornar lojas configurável (não hardcoded)
5. **Cache:** Redis/Memcached para respostas da API
6. **Testes:** Expandir cobertura (pytest + fixtures com dados mock)
7. **CI/CD:** GitHub Actions para deploy automático
