"""Migra o catálogo local SQLite para o banco Neon conectado ao Vercel.

Execute a partir da raiz do projeto, sem expor credenciais:
    python webapp/backend/migrate_sqlite_to_neon.py

O script preserva os IDs existentes e pode ser executado novamente com segurança.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, Sequence

import psycopg2
from psycopg2.extras import execute_values


BASE_DIR = Path(__file__).resolve().parent
SQLITE_PATH = BASE_DIR / "dispensa.db"
BATCH_SIZE = 2_000


def batches(rows: Iterable[Sequence[object]], size: int = BATCH_SIZE):
    batch = []
    for row in rows:
        batch.append(tuple(row))
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def create_schema(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lojas (
            id INTEGER PRIMARY KEY,
            chave TEXT UNIQUE NOT NULL,
            nome TEXT NOT NULL,
            icone TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY,
            gtin_ean TEXT,
            nome TEXT NOT NULL,
            categoria TEXT NOT NULL,
            marca TEXT NOT NULL,
            relevancia INTEGER NOT NULL DEFAULT 0,
            imagem_url TEXT,
            apresentacao TEXT,
            busca TEXT
        );

        CREATE TABLE IF NOT EXISTS precos (
            id INTEGER PRIMARY KEY,
            produto_id INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
            loja_id INTEGER NOT NULL REFERENCES lojas(id) ON DELETE CASCADE,
            preco_promocional DOUBLE PRECISION,
            preco_regular DOUBLE PRECISION,
            em_estoque BOOLEAN NOT NULL DEFAULT FALSE,
            cep_coleta TEXT,
            data_coleta TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_produtos_ean ON produtos (gtin_ean);
        CREATE INDEX IF NOT EXISTS idx_produtos_categoria ON produtos (categoria);
        CREATE INDEX IF NOT EXISTS idx_produtos_marca ON produtos (marca);
        CREATE INDEX IF NOT EXISTS idx_precos_produto_loja
            ON precos (produto_id, loja_id);
        CREATE INDEX IF NOT EXISTS idx_precos_data_coleta
            ON precos (data_coleta);
    """)


def upsert_rows(cursor, table: str, columns: list[str], rows) -> int:
    columns_sql = ", ".join(columns)
    update_sql = ", ".join(
        f"{column} = EXCLUDED.{column}" for column in columns if column != "id"
    )
    query = f"""
        INSERT INTO {table} ({columns_sql}) VALUES %s
        ON CONFLICT (id) DO UPDATE SET {update_sql}
    """
    count = 0
    for batch in batches(rows):
        execute_values(cursor, query, batch, page_size=len(batch))
        count += len(batch)
    return count


def migrate() -> None:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR.parent.parent / ".env")
    load_dotenv(BASE_DIR / ".env")
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL ausente. Configure o Neon no arquivo .env."
        )
    if not SQLITE_PATH.exists():
        raise FileNotFoundError(f"Banco SQLite não encontrado: {SQLITE_PATH}")

    source = sqlite3.connect(SQLITE_PATH)
    source.row_factory = sqlite3.Row
    target = psycopg2.connect(database_url, connect_timeout=20)

    try:
        with target.cursor() as cursor:
            create_schema(cursor)
        target.commit()

        # Custom iterator / adapter for precos to convert em_estoque to boolean properly
        class PrecosAdapter:
            def __init__(self, sqlite_cursor):
                self.cursor = sqlite_cursor

            def __iter__(self):
                for row in self.cursor:
                    yield (
                        row["id"],
                        row["produto_id"],
                        row["loja_id"],
                        row["preco_promocional"],
                        row["preco_regular"],
                        bool(row["em_estoque"]),
                        row["cep_coleta"],
                        row["data_coleta"],
                    )

        migrations = [
            (
                "lojas",
                ["id", "chave", "nome", "icone"],
                "SELECT id, chave, nome, icone FROM lojas ORDER BY id",
                None,
            ),
            (
                "produtos",
                [
                    "id", "gtin_ean", "nome", "categoria", "marca", "relevancia",
                    "imagem_url", "apresentacao", "busca"
                ],
                """
                SELECT id, gtin_ean, nome, categoria, marca, relevancia,
                       imagem_url, apresentacao,
                       coalesce(nome, '') || ' ' || coalesce(marca, '') || ' ' || coalesce(categoria, '') as busca
                FROM produtos ORDER BY id
                """,
                None,
            ),
            (
                "precos",
                [
                    "id", "produto_id", "loja_id", "preco_promocional",
                    "preco_regular", "em_estoque", "cep_coleta", "data_coleta",
                ],
                """
                SELECT id, produto_id, loja_id, preco_promocional, preco_regular,
                       em_estoque, cep_coleta, data_coleta
                FROM precos ORDER BY id
                """,
                PrecosAdapter,
            ),
        ]

        for table, columns, select_sql, adapter_cls in migrations:
            sqlite_cursor = source.execute(select_sql)
            rows = adapter_cls(sqlite_cursor) if adapter_cls else sqlite_cursor
            with target.cursor() as cursor:
                total = upsert_rows(cursor, table, columns, rows)
            target.commit()
            print(f"{table}: {total:,} linhas migradas")

        with target.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM lojas")
            lojas_row = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM produtos")
            produtos_row = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM precos")
            precos_row = cursor.fetchone()

        if not lojas_row or not produtos_row or not precos_row:
            raise RuntimeError("Não foi possível validar os totais migrados no Neon.")

        lojas = lojas_row[0]
        produtos = produtos_row[0]
        precos = precos_row[0]
        print(f"Concluído: {lojas:,} lojas, {produtos:,} produtos, {precos:,} preços.")
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()


if __name__ == "__main__":
    try:
        migrate()
    except Exception as error:
        print(f"Falha na migração: {error}", file=sys.stderr)
        raise
