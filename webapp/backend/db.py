"""Conexão com o Neon Postgres fornecido pela integração da Vercel."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Em produção, a Vercel injeta DATABASE_URL. Em desenvolvimento, esta chamada
# permite usar o arquivo local criado a partir das variáveis do projeto.
load_dotenv(Path(__file__).resolve().parents[2] / ".env.local")
load_dotenv()


class CompatRow(dict):
    """Linha que suporta acesso por nome de coluna e por índice."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class NeonCursor:
    def __init__(self, connection):
        self.cursor = connection.cursor()
        self.description = None

    def execute(self, sql, params=None):
        # Converte placeholders ? (SQLite) para %s (PostgreSQL) se executando no Postgres
        sql_pg = sql.replace("?", "%s")
        # Se contiver chamada de FTS5 do SQLite, adapta para busca ILIKE na coluna 'busca' ou 'nome'
        if "produtos_fts" in sql_pg:
            fts_placeholder = "p.id IN (SELECT id FROM produtos_fts WHERE produtos_fts MATCH %s)"
            if params:
                params_list = list(params)
                new_params = []
                words_conditions = []
                for p in params_list:
                    if isinstance(p, str) and ('"' in p or '*' in p):
                        words = [w.strip('"*').strip() for w in p.split() if w.strip('"*').strip()]
                        for w in words:
                            words_conditions.append("(unaccent(p.busca) ILIKE unaccent(%s) OR unaccent(p.nome) ILIKE unaccent(%s))")
                            new_params.extend([f"%{w}%", f"%{w}%"])
                    else:
                        new_params.append(p)
                
                clause = " AND ".join(words_conditions) if words_conditions else "(unaccent(p.busca) ILIKE unaccent(%s) OR unaccent(p.nome) ILIKE unaccent(%s))"
                if not words_conditions:
                    new_params.extend(["%%", "%%"])
                sql_pg = sql_pg.replace(fts_placeholder, f"({clause})")
                params = new_params
            else:
                sql_pg = sql_pg.replace(fts_placeholder, "(unaccent(p.busca) ILIKE unaccent(%s) OR unaccent(p.nome) ILIKE unaccent(%s))")
        self.cursor.execute(sql_pg, () if params is None else params)
        self.description = self.cursor.description
        return self

    def fetchall(self):
        return [CompatRow(row) for row in self.cursor.fetchall()]

    def fetchone(self):
        row = self.cursor.fetchone()
        return CompatRow(row) if row else None


class NeonConnection:
    """Adaptador mínimo para a interface já usada pelos serviços da API."""

    is_postgres = True

    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return NeonCursor(self.connection)

    def close(self):
        self.connection.close()


class SQLiteCursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.description = None

    def execute(self, sql, params=None):
        self.cursor.execute(sql, () if params is None else params)
        self.description = self.cursor.description
        return self

    def fetchall(self):
        return [CompatRow(row) for row in self.cursor.fetchall()]

    def fetchone(self):
        row = self.cursor.fetchone()
        return CompatRow(row) if row else None


class SQLiteConnection:
    """Adaptador para SQLite mantendo compatibilidade com cursor/CompatRow."""

    is_postgres = False

    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return SQLiteCursor(self.connection.cursor())

    def close(self):
        self.connection.close()


def get_db_connection():
    """Abre uma conexão com o banco Neon Postgres ou faz fallback para SQLite local."""
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")

    if database_url:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        connection = psycopg2.connect(
            database_url.strip().strip("'\""),
            connect_timeout=10,
            cursor_factory=RealDictCursor,
        )
        return NeonConnection(connection)

    # Fallback local para SQLite (desenvolvimento / testes locais)
    import sqlite3
    db_paths = [
        Path(__file__).resolve().parent / "dispensa.db",
        Path(__file__).resolve().parents[1] / "backend" / "dispensa.db",
        Path.cwd() / "dispensa.db",
        Path.cwd() / "webapp" / "backend" / "dispensa.db",
    ]
    for path in db_paths:
        if path.exists():
            conn = sqlite3.connect(str(path))
            conn.row_factory = sqlite3.Row
            return SQLiteConnection(conn)

    raise ValueError(
        "Nenhum banco de dados configurado. Defina DATABASE_URL para Neon Postgres "
        "ou certifique-se de que dispensa.db exista localmente."
    )
