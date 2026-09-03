"""
ETL Script: Importa dados dos JSONs para o SGBD SQLite3 (dispensa.db)
Dispensa Planejada Santos — PI UNIVESP 2026.2
"""

import json
import os
import sqlite3
import time
from pathlib import Path

# Configuração de caminhos
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR.parent if (BASE_DIR.parent / "produtos_ampliado.json").exists() else BASE_DIR
DB_PATH = BASE_DIR / "dispensa.db"

LOJAS_DATA = [
    (1, "carrefour", "Carrefour - Ponta da Praia", "🛍️"),
    (2, "pao_de_acucar", "Pão de Açúcar", "🥐"),
    (3, "atacadao", "Atacadão", "🏬"),
]

ARQUIVOS_PRECOS = {
    "carrefour": "precos_carrefour_ampliado.json",
    "pao_de_acucar": "precos_pao_de_acucar_ampliado.json",
    "atacadao": "precos_atacadao_ampliado.json",
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
    loja_id_map = {"carrefour": 1, "pao_de_acucar": 2, "atacadao": 3}

    for loja_chave, filename in ARQUIVOS_PRECOS.items():
        filepath = DATA_DIR / filename
        if filepath.exists():
            print(f"[ETL] Lendo precos de {filename}...")
            with open(filepath, "r", encoding="utf-8") as f:
                p_list = json.load(f)
                for p in p_list:
                    gtin = p.get("gtin_ean")
                    if not gtin:
                        continue
                    if gtin not in precos_por_ean:
                        precos_por_ean[gtin] = {}
                    precos_por_ean[gtin][loja_chave] = p

    # 3. Insere produtos do catálogo e seus preços
    print("[ETL] Inserindo produtos do catalogo...")
    prod_tuples = []
    fts_tuples = []
    preco_tuples = []
    eans_cadastrados = set()

    for i, prod in enumerate(produtos_raw, start=1):
        gtin = prod.get("gtin_ean")
        nome = prod.get("nome_completo") or prod.get("nome") or "Produto sem nome"
        categoria = prod.get("secao") or prod.get("categoria") or "Geral"
        marca = prod.get("marca") or "Não Informada"
        relevancia = prod.get("relevancia", 0)
        imagem_url = prod.get("imagem_url")
        apresentacao = format_apresentacao(prod.get("apresentacao"))

        prod_tuples.append((i, gtin, nome, categoria, marca, relevancia, imagem_url, apresentacao))
        fts_tuples.append((i, nome, categoria, marca))
        if gtin:
            eans_cadastrados.add(gtin)

        # Preços por loja
        if gtin and gtin in precos_por_ean:
            p_dict = precos_por_ean[gtin]
            for loja_chave, l_id in loja_id_map.items():
                if loja_chave in p_dict:
                    info = p_dict[loja_chave]
                    prom = info.get("preco_promocional")
                    reg = info.get("preco_regular")
                    est = 1 if info.get("em_estoque") else 0
                    preco_tuples.append((i, l_id, prom, reg, est, None))

    # 4. Cadastra produtos órfãos (existem em preços mas não no catálogo)
    eans_orfaos = set(precos_por_ean.keys()) - eans_cadastrados
    next_id = len(produtos_raw) + 1
    orfaos_count = 0

    if eans_orfaos:
        print(f"[ETL] Cadastrando {len(eans_orfaos)} produtos orfaos (presentes em precos mas ausentes no catalogo)...")
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
                    preco_tuples.append((next_id, l_id, prom, reg, est, None))

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
        "INSERT INTO precos (produto_id, loja_id, preco_promocional, preco_regular, em_estoque, cep_coleta) VALUES (?, ?, ?, ?, ?, ?);",
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
    print(f"  - Produtos orfaos cadastrados: {orfaos_count:,}")
    print(f"  - Total de produtos: {total_prod:,}")
    print(f"  - Total de precos ativos: {total_precos:,}")
    for nome_loja, qtd in precos_por_loja:
        print(f"    {nome_loja}: {qtd:,} precos")
    print(f"  - Tamanho do arquivo dispensa.db: {db_size_mb:.2f} MB")

    conn.close()


if __name__ == "__main__":
    run_etl()
