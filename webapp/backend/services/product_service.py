"""
Product Service for Dispensa Planejada FastAPI Backend
Executes SQL queries against the SQLite SGBD (dispensa.db).
"""

import math
from typing import List, Optional, Tuple
from db import get_db_connection


def search_products(
    q: Optional[str] = None,
    categoria: Optional[str] = None,
    marca: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> Tuple[int, int, int, int, List[dict]]:
    q_clean = (q or "").strip()
    cat_clean = (categoria or "").strip()
    marca_clean = (marca or "").strip()

    if not q_clean and not cat_clean and not marca_clean:
        return 0, page, limit, 0, []

    conn = get_db_connection()
    cursor = conn.cursor()

    conditions = []
    params = []

    if cat_clean:
        conditions.append("LOWER(p.categoria) = LOWER(?)")
        params.append(cat_clean)

    if marca_clean:
        conditions.append("LOWER(p.marca) = LOWER(?)")
        params.append(marca_clean)

    if q_clean:
        conditions.append("(p.id IN (SELECT id FROM produtos_fts WHERE produtos_fts MATCH ?) OR LOWER(p.nome) LIKE ? OR LOWER(p.marca) LIKE ?)")
        # Order-independent FTS: split the query into whitespace-separated
        # tokens and AND-combine each token with a trailing wildcard, so
        # "Biscoito club social" and "club social biscoito" match the same set.
        words = q_clean.split()
        fts_query = " AND ".join(f'"{w}"*' for w in words)
        like_query = f"%{q_clean.lower()}%"
        params.extend([fts_query, like_query, like_query])

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

    # Count total matching rows
    count_sql = f"SELECT COUNT(*) FROM produtos p {where_clause};"
    cursor.execute(count_sql, params)
    total = cursor.fetchone()[0]

    total_pages = math.ceil(total / limit) if total > 0 else 0
    offset = (page - 1) * limit

    # Query items with store prices joined
    query_sql = f"""
    SELECT 
        p.id, p.gtin_ean, p.nome, p.categoria, p.marca, p.relevancia, p.imagem_url, p.apresentacao,
        pr1.preco_promocional AS p1, pr1.preco_regular AS r1, pr1.em_estoque AS e1,
        pr2.preco_promocional AS p2, pr2.preco_regular AS r2, pr2.em_estoque AS e2,
        pr3.preco_promocional AS p3, pr3.preco_regular AS r3, pr3.em_estoque AS e3
    FROM produtos p
    LEFT JOIN precos pr1 ON p.id = pr1.produto_id AND pr1.loja_id = 1
    LEFT JOIN precos pr2 ON p.id = pr2.produto_id AND pr2.loja_id = 2
    LEFT JOIN precos pr3 ON p.id = pr3.produto_id AND pr3.loja_id = 3
    {where_clause}
    ORDER BY p.relevancia DESC, p.nome ASC
    LIMIT ? OFFSET ?;
    """

    query_params = params + [limit, offset]
    cursor.execute(query_sql, query_params)
    rows = cursor.fetchall()
    conn.close()

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "gtin_ean": r["gtin_ean"],
            "nome": r["nome"],
            "categoria": r["categoria"],
            "marca": r["marca"],
            "relevancia": r["relevancia"],
            "imagem_url": r["imagem_url"],
            "apresentacao": r["apresentacao"],
            "preco": [r["p1"], r["p2"], r["p3"]],
            "preco_regular": [r["r1"], r["r2"], r["r3"]],
            "em_estoque": [bool(r["e1"]), bool(r["e2"]), bool(r["e3"])],
        })

    return total, page, limit, total_pages, items


def get_categories() -> List[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT categoria AS nome, COUNT(*) AS quantidade_produtos 
        FROM produtos 
        GROUP BY categoria 
        ORDER BY quantidade_produtos DESC, categoria ASC;
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_brands(categoria: Optional[str] = None) -> List[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()

    if categoria:
        cursor.execute("""
            SELECT marca AS nome, COUNT(*) AS quantidade_produtos 
            FROM produtos 
            WHERE LOWER(categoria) = LOWER(?) AND LOWER(marca) NOT IN ('não informada', 'não informado') AND LOWER(marca) NOT LIKE '%genérico%'
            GROUP BY marca 
            ORDER BY marca ASC;
        """, (categoria.strip(),))
    else:
        cursor.execute("""
            SELECT marca AS nome, COUNT(*) AS quantidade_produtos 
            FROM produtos 
            WHERE LOWER(marca) NOT IN ('não informada', 'não informado') AND LOWER(marca) NOT LIKE '%genérico%'
            GROUP BY marca 
            ORDER BY marca ASC;
        """)

    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_product_by_id(product_id: int) -> Optional[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            p.id, p.gtin_ean, p.nome, p.categoria, p.marca, p.relevancia, p.imagem_url, p.apresentacao,
            pr1.preco_promocional AS p1, pr1.preco_regular AS r1, pr1.em_estoque AS e1,
            pr2.preco_promocional AS p2, pr2.preco_regular AS r2, pr2.em_estoque AS e2,
            pr3.preco_promocional AS p3, pr3.preco_regular AS r3, pr3.em_estoque AS e3
        FROM produtos p
        LEFT JOIN precos pr1 ON p.id = pr1.produto_id AND pr1.loja_id = 1
        LEFT JOIN precos pr2 ON p.id = pr2.produto_id AND pr2.loja_id = 2
        LEFT JOIN precos pr3 ON p.id = pr3.produto_id AND pr3.loja_id = 3
        WHERE p.id = ?;
    """, (product_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row["id"],
        "gtin_ean": row["gtin_ean"],
        "nome": row["nome"],
        "categoria": row["categoria"],
        "marca": row["marca"],
        "relevancia": row["relevancia"],
        "imagem_url": row["imagem_url"],
        "apresentacao": row["apresentacao"],
        "preco": [row["p1"], row["p2"], row["p3"]],
        "preco_regular": [row["r1"], row["r2"], row["r3"]],
        "em_estoque": [bool(row["e1"]), bool(row["e2"]), bool(row["e3"])],
    }
