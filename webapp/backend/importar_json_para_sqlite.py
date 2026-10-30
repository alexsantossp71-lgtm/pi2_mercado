"""
ETL Script: Importa dados dos JSONs para o SGBD SQLite3 (dispensa.db)
Dispensa Planejada Santos — PI UNIVESP 2026.2
"""

import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

# Filtro de produtos adultos/sex shop (mesmo módulo usado na coleta).
# Se o módulo não existir neste checkout, segue com filtro desligado.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scraper"))
    from filtro_adulto import eh_produto_bloqueado
except ImportError:
    print("[AVISO] scraper/filtro_adulto.py não encontrado — filtro de produtos "
          "adultos DESLIGADO neste ETL.")
    def eh_produto_bloqueado(nome: str = "", marca: str = "", secao: str = "") -> bool:
        return False


def _norm_nome_flv(s: str) -> str:
    """Normaliza nome p/ match de Hortifrúti: minúsculo, sem acento, sem qtde/unidade."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # Remove número + unidade acoplada numa passada (ex.: "600g", "500 ml", "1kg")
    s = re.sub(r"\d+(?:[.,]\d+)?\s*(?:kg|g|ml|l|un|unid|unidade|aprox|pct|bandeja|cx|dz|org|organico|taeq)?", " ", s)
    # Remove unidades isoladas que tenham sobrado (ex.: "abacate g" -> "abacate")
    s = re.sub(r"\b(?:kg|g|ml|l|un|unid|unidade|aprox|pct|bandeja|cx|dz|org|organico|taeq)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _eh_flv(secao: str) -> bool:
    """Verdadeiro se uma seção refere-se a frutas/legumes/verduras (FLV)."""
    s = (secao or "").lower()
    return any(k in s for k in (
        "hortifruti", "fruta", "frutas", "legume", "legumes",
        "verdura", "verduras", "flv", "alimento",
    ))

# Configuração de caminhos
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR.parent if (BASE_DIR.parent / "produtos_ampliado.json").exists() else BASE_DIR
DB_PATH = BASE_DIR / "dispensa.db"

LOJAS_DATA = [
    (1, "carrefour", "Carrefour - Ponta da Praia", "🛍️"),
    (2, "pao_de_acucar", "Pão de Açúcar", "🥐"),
    (3, "atacadao", "Atacadão", "🏬"),
    (4, "soudaki", "Soudaki", "🧁"),
]

# Unificação de categorias fragmentadas (mesma regra de
# normalizar_categorias_neon.py — mantém SQLite local igual ao Neon).
CATEGORIA_CANONICA = {
    "Limpeza": "Limpeza e Lavanderia",
    "Perfumaria": "Higiene e Perfumaria",
    "Higiene e Beleza": "Higiene e Perfumaria",
    "Bebê e Criança": "Bebê e Infantil",
    "Carnes, aves e peixes": "Açougue e Peixaria",
    "Matinais": "Padaria e Matinais",
}


def normalizar_categoria(nome: str) -> str:
    """Aplica o mapa de unificação de seções (idempotente)."""
    return CATEGORIA_CANONICA.get(nome, nome)


# Remove do catálogo produtos sem preço em nenhuma loja — hoje eles aparecem na
# busca sem oferta nenhuma (ex.: bazar do Atacadão coletado sem preço). Só é
# aplicado se ao menos um arquivo de preços carregar, para não esvaziar a base
# num checkout sem precos_*.json.
REMOVER_PRODUTOS_SEM_PRECO = True

ARQUIVOS_PRECOS = {
    "carrefour": "precos_carrefour_ampliado.json",
    "pao_de_acucar": "precos_pao_de_acucar_ampliado.json",
    "atacadao": "precos_atacadao_ampliado.json",
    "soudaki": "precos_soudaki_ampliado.json",
}


def format_apresentacao(raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        qtd = raw.get("quantidade")
        unid = raw.get("unidade_medida") or ""
        if qtd is not None:
            return f"{qtd}{unid}"
    return str(raw)


def init_db(conn: sqlite3.Connection):
    cursor = conn.cursor()
    
    # Habilita Foreign Keys
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # DDL: Criar tabelas relacionais
    cursor.executescript("""
    DROP TABLE IF EXISTS precos;
    DROP TABLE IF EXISTS produtos_fts;
    DROP TABLE IF EXISTS produtos;
    DROP TABLE IF EXISTS lojas;

    CREATE TABLE lojas (
        id INTEGER PRIMARY KEY,
        chave TEXT UNIQUE NOT NULL,
        nome TEXT NOT NULL,
        icone TEXT NOT NULL
    );

    CREATE TABLE produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gtin_ean TEXT,
        nome TEXT NOT NULL,
        categoria TEXT NOT NULL,
        marca TEXT NOT NULL,
        relevancia INTEGER DEFAULT 0,
        imagem_url TEXT,
        apresentacao TEXT
    );

    CREATE TABLE precos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER NOT NULL,
        loja_id INTEGER NOT NULL,
        preco_promocional REAL,
        preco_regular REAL,
        em_estoque INTEGER DEFAULT 0,
        cep_coleta TEXT DEFAULT NULL,
        data_coleta TEXT DEFAULT NULL,
        FOREIGN KEY(produto_id) REFERENCES produtos(id) ON DELETE CASCADE,
        FOREIGN KEY(loja_id) REFERENCES lojas(id) ON DELETE CASCADE,
        UNIQUE(produto_id, loja_id, cep_coleta)
    );

    -- Índices B-Tree para buscas ultra-rápidas
    CREATE INDEX idx_produtos_ean ON produtos(gtin_ean);
    CREATE INDEX idx_produtos_cat ON produtos(categoria);
    CREATE INDEX idx_produtos_marca ON produtos(marca);
    CREATE INDEX idx_precos_prod_loja ON precos(produto_id, loja_id);
    CREATE INDEX IF NOT EXISTS idx_precos_cepa ON precos(produto_id, loja_id, cep_coleta);
    CREATE INDEX IF NOT EXISTS idx_precos_data_coleta ON precos(data_coleta);

    -- Tabela Virtual FTS5 para busca textual por termos
    CREATE VIRTUAL TABLE produtos_fts USING fts5(
        id UNINDEXED,
        nome,
        categoria,
        marca,
        tokenize = 'unicode61 remove_diacritics 1'
    );
    """)

    # Popula tabela de lojas
    cursor.executemany(
        "INSERT INTO lojas (id, chave, nome, icone) VALUES (?, ?, ?, ?);",
        LOJAS_DATA
    )
    conn.commit()


def run_etl():
    print(f"[ETL] Iniciando migracao para SGBD SQLite em: {DB_PATH}")
    start_time = time.time()

    if DB_PATH.exists():
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    cursor = conn.cursor()

    # 1. Carrega produtos do catálogo
    prod_json_path = DATA_DIR / "produtos_ampliado.json"
    print(f"[ETL] Lendo produtos de {prod_json_path}...")
    with open(prod_json_path, "r", encoding="utf-8") as f:
        produtos_raw = json.load(f)

    # 2. Carrega preços das lojas
    precos_por_ean = {}
    # Índice de preços de Hortifrúti por nome normalizado (para produtos sem EAN casando
    # entre lojas que vendem fruta avulsa por peso, ex.: abacate). Chave = nome FLV
    # normalizado, valor = {loja_chave: info}.
    precos_sem_ean_por_nome = {}
    precos_flv_por_nome = {}
    loja_id_map = {"carrefour": 1, "pao_de_acucar": 2, "atacadao": 3, "soudaki": 4}
    arquivos_preco_carregados = 0

    for loja_chave, filename in ARQUIVOS_PRECOS.items():
        filepath = DATA_DIR / filename
        if filepath.exists():
            arquivos_preco_carregados += 1
            print(f"[ETL] Lendo precos de {filename}...")
            with open(filepath, "r", encoding="utf-8") as f:
                p_list = json.load(f)
                for p in p_list:
                    gtin = p.get("gtin_ean")
                    if not gtin:
                        # Produto sem EAN (ex.: fruta avulsa) — indexa por nome se for FLV
                        sec_loja = p.get("secao") or p.get("categoria") or ""
                        if _eh_flv(sec_loja):
                            n = _norm_nome_flv(p.get("nome") or p.get("nome_completo") or "")
                            if n:
                                precos_flv_por_nome.setdefault(n, {})[loja_chave] = p
                                precos_sem_ean_por_nome.setdefault(n, {})[loja_chave] = p
                        continue
                    if gtin not in precos_por_ean:
                        precos_por_ean[gtin] = {}
                    precos_por_ean[gtin][loja_chave] = p
                    # Também indexa por nome quando for FLV (para match cruzado entre lojas)
                    sec_loja = p.get("secao") or p.get("categoria") or ""
                    if _eh_flv(sec_loja):
                        n = _norm_nome_flv(p.get("nome") or p.get("nome_completo") or "")
                        if n:
                            precos_flv_por_nome.setdefault(n, {})[loja_chave] = p

    # 3. Insere produtos do catálogo e seus preços
    print("[ETL] Inserindo produtos do catalogo...")
    prod_tuples = []
    fts_tuples = []
    preco_tuples = []
    eans_cadastrados = set()
    bloqueados_catalogo = 0
    sem_preco_catalogo = 0
    pular_sem_preco = REMOVER_PRODUTOS_SEM_PRECO and arquivos_preco_carregados > 0
    if REMOVER_PRODUTOS_SEM_PRECO and not pular_sem_preco:
        print("[AVISO] Nenhum precos_*.json carregado — filtro de produtos sem "
              "preco DESLIGADO nesta execucao.")

    for i, prod in enumerate(produtos_raw, start=1):
        gtin = prod.get("gtin_ean")
        nome = prod.get("nome_completo") or prod.get("nome") or "Produto sem nome"
        categoria = normalizar_categoria(prod.get("secao") or prod.get("categoria") or "Geral")
        marca = prod.get("marca") or "Não Informada"

        # Bloqueio de produtos adultos/sex shop (ver scraper/filtro_adulto.py)
        if eh_produto_bloqueado(nome, marca, categoria):
            bloqueados_catalogo += 1
            continue

        relevancia = prod.get("relevancia", 0)
        imagem_url = prod.get("imagem_url")
        apresentacao = format_apresentacao(prod.get("apresentacao"))

        # Preços por loja — passo 1: match por GTIN
        lojas_com_preco = set()
        n_preco_antes = len(preco_tuples)
        if gtin and gtin in precos_por_ean:
            p_dict = precos_por_ean[gtin]
            for loja_chave, l_id in loja_id_map.items():
                if loja_chave in p_dict:
                    info = p_dict[loja_chave]
                    prom = info.get("preco_promocional")
                    reg = info.get("preco_regular")
                    est = 1 if info.get("em_estoque") else 0
                    preco_tuples.append((i, l_id, prom, reg, est, None, info.get("data_coleta")))
                    lojas_com_preco.add(loja_chave)

        # passo 2: fallback — match por nome normalizado para FLV sem preço via GTIN
        if _eh_flv(categoria):
            k = _norm_nome_flv(nome)
            if k and k in precos_flv_por_nome:
                p_dict = precos_flv_por_nome[k]
                for loja_chave, l_id in loja_id_map.items():
                    if loja_chave not in lojas_com_preco and loja_chave in p_dict:
                        info = p_dict[loja_chave]
                        prom = info.get("preco_promocional")
                        reg = info.get("preco_regular")
                        est = 1 if info.get("em_estoque") else 0
                        preco_tuples.append((i, l_id, prom, reg, est, None, info.get("data_coleta")))

        # Produto sem preço em nenhuma loja: fora do catálogo (configurável)
        if pular_sem_preco and len(preco_tuples) == n_preco_antes:
            sem_preco_catalogo += 1
            continue

        prod_tuples.append((i, gtin, nome, categoria, marca, relevancia, imagem_url, apresentacao))
        fts_tuples.append((i, nome, categoria, marca))
        if gtin:
            eans_cadastrados.add(gtin)

    # 4. Cadastra produtos órfãos (existem em preços mas não no catálogo)
    eans_orfaos = set(precos_por_ean.keys()) - eans_cadastrados
    next_id = len(produtos_raw) + 1
    orfaos_count = 0

    if eans_orfaos:
        print(f"[ETL] Cadastrando {len(eans_orfaos)} produtos orfaos (presentes em precos mas ausentes no catalogo)...")
        bloqueados_orfaos = 0
        for gtin in sorted(eans_orfaos):
            p_dict = precos_por_ean[gtin]
            # Tenta extrair nome dos dados de preço (campo 'nome' ou 'nome_completo')
            nome = None
            marca = "Não Informada"
            categoria = "Geral"
            imagem_url = None
            for info in p_dict.values():
                nome = nome or info.get("nome_completo") or info.get("nome")
                if info.get("marca") and info["marca"] != "Não Informada":
                    marca = info["marca"]
                if info.get("secao") and info["secao"] != "Geral":
                    categoria = info["secao"]
                if info.get("categoria") and categoria == "Geral":
                    categoria = info["categoria"]
                if info.get("imagem_url"):
                    imagem_url = info["imagem_url"]
            categoria = normalizar_categoria(categoria)

            # Bloqueio de produtos adultos/sex shop também entre os órfãos
            if eh_produto_bloqueado(nome or "", marca, categoria):
                bloqueados_orfaos += 1
                continue

            if not nome:
                nome = f"Produto EAN {gtin}"

            prod_tuples.append((next_id, gtin, nome, categoria, marca, 0, imagem_url, None))
            fts_tuples.append((next_id, nome, categoria, marca))

            for loja_chave, l_id in loja_id_map.items():
                if loja_chave in p_dict:
                    info = p_dict[loja_chave]
                    prom = info.get("preco_promocional")
                    reg = info.get("preco_regular")
                    est = 1 if info.get("em_estoque") else 0
                    preco_tuples.append((next_id, l_id, prom, reg, est, None, info.get("data_coleta")))

            next_id += 1
            orfaos_count += 1

        print(f"[ETL] Orfaos bloqueados (adulto/sex shop): {bloqueados_orfaos}")
    if precos_sem_ean_por_nome:
        # nomes normalizados ja presentes no catalogo (FLV) — ja receberam fallback
        catalog_flv_nomes = set()
        for prod in produtos_raw:
            sec = prod.get("secao") or prod.get("categoria") or ""
            if _eh_flv(sec):
                n = _norm_nome_flv(prod.get("nome_completo") or prod.get("nome") or "")
                if n:
                    catalog_flv_nomes.add(n)
        flv_orfaos = {k: v for k, v in precos_sem_ean_por_nome.items()
                      if k not in catalog_flv_nomes}
        if flv_orfaos:
            print(f"[ETL] Cadastrando {len(flv_orfaos)} produtos FLV sem EAN orfaos...")
            for nome_norm in sorted(flv_orfaos.keys()):
                p_dict = flv_orfaos[nome_norm]
                nome = None
                marca = "Não Informada"
                categoria = "Hortifruti"
                imagem_url = None
                for info in p_dict.values():
                    nome = nome or info.get("nome_completo") or info.get("nome")
                    if info.get("marca") and info["marca"] != "Não Informada":
                        marca = info["marca"]
                    if info.get("imagem_url"):
                        imagem_url = info["imagem_url"]
                if not nome:
                    nome = nome_norm.title()

                prod_tuples.append((next_id, None, nome, categoria, marca, 0, imagem_url, None))
                fts_tuples.append((next_id, nome, categoria, marca))

                for loja_chave, l_id in loja_id_map.items():
                    if loja_chave in p_dict:
                        info = p_dict[loja_chave]
                        prom = info.get("preco_promocional")
                        reg = info.get("preco_regular")
                        est = 1 if info.get("em_estoque") else 0
                        preco_tuples.append(
                            (next_id, l_id, prom, reg, est, None, info.get("data_coleta"))
                        )

                next_id += 1
                orfaos_count += 1

    # 5. Executa INSERTs em bloco
    cursor.executemany(
        "INSERT INTO produtos (id, gtin_ean, nome, categoria, marca, relevancia, imagem_url, apresentacao) VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
        prod_tuples
    )
    cursor.executemany(
        "INSERT INTO produtos_fts (id, nome, categoria, marca) VALUES (?, ?, ?, ?);",
        fts_tuples
    )
    cursor.executemany(
        "INSERT INTO precos (produto_id, loja_id, preco_promocional, preco_regular, em_estoque, cep_coleta, data_coleta) VALUES (?, ?, ?, ?, ?, ?, ?);",
        preco_tuples
    )

    conn.commit()

    # Estatísticas pós-importação
    cursor.execute("SELECT COUNT(*) FROM produtos;")
    total_prod = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM precos WHERE preco_promocional IS NOT NULL AND em_estoque = 1;")
    total_precos = cursor.fetchone()[0]

    cursor.execute("""
        SELECT l.nome, COUNT(p.id)
        FROM precos p JOIN lojas l ON p.loja_id = l.id
        GROUP BY l.nome ORDER BY l.nome;
    """)
    precos_por_loja = cursor.fetchall()

    db_size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    elapsed = time.time() - start_time

    print(f"\n[ETL SUCCESS] SGBD SQLite criado com sucesso em {elapsed:.2f}s!")
    print(f"  - Produtos do catalogo: {len(produtos_raw):,}")
    print(f"  - Bloqueados adulto/sex shop (catalogo): {bloqueados_catalogo:,}")
    print(f"  - Sem preço em nenhuma loja (catalogo): {sem_preco_catalogo:,}")
    print(f"  - Produtos orfaos cadastrados: {orfaos_count:,}")
    print(f"  - Total de produtos: {total_prod:,}")
    print(f"  - Total de precos ativos: {total_precos:,}")
    cursor.execute("SELECT COUNT(*) FROM precos WHERE preco_promocional IS NOT NULL;")
    total_precos_all = cursor.fetchone()[0]
    print(f"  - Total de precos (incl. indisponiveis): {total_precos_all:,}")
    for nome_loja, qtd in precos_por_loja:
        print(f"    {nome_loja}: {qtd:,} precos")
    print(f"  - Tamanho do arquivo dispensa.db: {db_size_mb:.2f} MB")

    conn.close()


if __name__ == "__main__":
    run_etl()
