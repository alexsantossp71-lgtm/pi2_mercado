"""
Normaliza categorias fragmentadas no Neon Postgres.

Com 4 lojas coletadas, cada scraper chegou com nomenclatura própria e o
catálogo ficou com pares/trios de seções equivalentes (ex.: "Limpeza" e
"Limpeza e Lavanderia"). Isso divide a contagem do filtro de seções e
espalha itens parecidos no checklist.

Uso (a partir da raiz do projeto, com DATABASE_URL no .env):
    python webapp/backend/normalizar_categorias_neon.py           # simulação
    python webapp/backend/normalizar_categorias_neon.py --aplicar # executa

O script é conservador: só mescla categorias claramente equivalentes.
Categorias-ruído ("Geral", "Utilidades Domésticas", "Produtos Daki") são
apenas REPORTADAS, não alteradas — decidir sobre elas é tarefa do time.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent.parent / ".env")
load_dotenv(BASE_DIR / ".env")

# Mapa de unificação: categoria atual -> categoria canônica.
# Escolheu-se o nome com MAIOR número de produtos de cada grupo
# (números medidos em 30/10/2026).
CATEGORIA_CANONICA = {
    # Limpeza (1.537) -> Limpeza e Lavanderia (6.222)
    "Limpeza": "Limpeza e Lavanderia",
    # Perfumaria (1.170) / Higiene e Beleza (124) -> Higiene e Perfumaria (11.134)
    "Perfumaria": "Higiene e Perfumaria",
    "Higiene e Beleza": "Higiene e Perfumaria",
    # Bebê e Criança (30) -> Bebê e Infantil (4.355)
    "Bebê e Criança": "Bebê e Infantil",
    # Carnes, aves e peixes (465) -> Açougue e Peixaria (461)
    "Carnes, aves e peixes": "Açougue e Peixaria",
    # Matinais (13) -> Padaria e Matinais (1.193)
    "Matinais": "Padaria e Matinais",
}

# Categorias problemáticas que o script apenas reporta (não mexe)
RUIDO_REPORTAVEL = ["Geral", "Utilidades Domésticas", "Produtos Daki"]


def contar(cursor, sql: str, params=None) -> int:
    cursor.execute(sql, params or ())
    row = cursor.fetchone()
    return int(row[0] if row else 0)


def main(aplicar: bool) -> None:
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL ausente. Configure o Neon no .env.")

    import psycopg2

    conn = psycopg2.connect(database_url.strip().strip("'\""), connect_timeout=20)
    cursor = conn.cursor()

    print("=== Situação atual das categorias afetadas ===")
    for de in CATEGORIA_CANONICA:
        n = contar(cursor, "SELECT COUNT(*) FROM produtos WHERE categoria = %s", (de,))
        if n:
            print(f"  {de}: {n:,} produtos -> {CATEGORIA_CANONICA[de]}")

    print("\n=== Categorias-ruído (apenas relatório, sem alteração) ===")
    for nome in RUIDO_REPORTAVEL:
        n = contar(cursor, "SELECT COUNT(*) FROM produtos WHERE categoria = %s", (nome,))
        if n:
            print(f"  ⚠️  {nome}: {n:,} produtos")

    cursor.execute(
        "SELECT categoria, COUNT(*) FROM produtos GROUP BY categoria ORDER BY COUNT(*) DESC"
    )
    todas = cursor.fetchall()
    print(f"\nTotal de categorias distintas: {len(todas)}")
    print("Top 10:")
    for cat, qtd in todas[:10]:
        print(f"  {cat}: {qtd:,}")

    total_mover = sum(
        contar(cursor, "SELECT COUNT(*) FROM produtos WHERE categoria = %s", (de,))
        for de in CATEGORIA_CANONICA
    )
    if not aplicar:
        print(f"\n[SIMULAÇÃO] {total_mover:,} produtos seriam reclassificados. "
              f"Execute com --aplicar para gravar.")
        cursor.close()
        conn.close()
        return

    print(f"\n[APLICANDO] Reclassificando {total_mover:,} produtos...")
    for de, para in CATEGORIA_CANONICA.items():
        # Atualiza categoria e recalcula a coluna 'busca' (nome + marca + categoria)
        cursor.execute(
            """
            UPDATE produtos
            SET categoria = %s,
                busca = coalesce(nome, '') || ' ' || coalesce(marca, '') || ' ' || %s
            WHERE categoria = %s
            """,
            (para, para, de),
        )
        print(f"  {de} -> {para}: {cursor.rowcount:,} linhas")

    conn.commit()

    print("\n=== Situação final ===")
    cursor.execute(
        "SELECT categoria, COUNT(*) FROM produtos GROUP BY categoria ORDER BY COUNT(*) DESC"
    )
    finais = cursor.fetchall()
    print(f"Categorias distintas: {len(finais)} (antes: {len(todas)})")
    for cat, qtd in finais[:10]:
        print(f"  {cat}: {qtd:,}")

    cursor.close()
    conn.close()
    print("\nConcluído.")


if __name__ == "__main__":
    main(aplicar="--aplicar" in sys.argv)
