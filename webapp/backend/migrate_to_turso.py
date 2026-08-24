import sqlite3
import libsql_client
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

# Credenciais lidas de webapp/backend/.env (nunca versionar este arquivo)
load_dotenv(Path(__file__).parent / ".env")

DB_PATH = Path(__file__).parent / "dispensa.db"
TURSO_URL = os.environ["TURSO_DATABASE_URL"]
TURSO_TOKEN = os.environ["TURSO_AUTH_TOKEN"]

async def migrate():
    print("Conectando ao Turso...")
    
    local_conn = sqlite3.connect(DB_PATH)
    local_cursor = local_conn.cursor()
    
    local_cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables_ddl = [row[0] for row in local_cursor.fetchall() if row[0]]

    local_cursor.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%';")
    indexes_ddl = [row[0] for row in local_cursor.fetchall() if row[0]]

    async with libsql_client.create_client(url=TURSO_URL, auth_token=TURSO_TOKEN) as client:
        # FTS5 virtual tables need special care. Turso supports FTS5.
        
        # 1. Create tables
        for ddl in tables_ddl:
            # Skip FTS shadow tables (they are created automatically)
            if "produtos_fts_data" in ddl or "produtos_fts_idx" in ddl or "produtos_fts_docsize" in ddl or "produtos_fts_config" in ddl:
                continue
            
            # Recreate cleanly
            # First parse table name
            # simple regex or string manipulation
            if "CREATE TABLE" in ddl:
                table_name = ddl.split("CREATE TABLE")[1].split("(")[0].strip()
                if "VIRTUAL" in ddl:
                    table_name = ddl.split("CREATE VIRTUAL TABLE")[1].split("USING")[0].strip()
                try:
                    await client.execute(f"DROP TABLE IF EXISTS {table_name}")
                except Exception as e:
                    pass
            
            try:
                await client.execute(ddl)
            except Exception as e:
                print("ERRO no DDL:", e, ddl)

        for idx in indexes_ddl:
            try:
                await client.execute(idx)
            except Exception as e:
                pass
                
        # 2. Copy Data
        tables = ["lojas", "produtos", "precos", "produtos_fts"]
        for table in tables:
            print(f"Lendo tabela {table}...")
            local_cursor.execute(f"SELECT * FROM {table};")
            rows = local_cursor.fetchall()
            if not rows: continue

            col_names = [d[0] for d in local_cursor.description]
            placeholders = ", ".join(["?"] * len(col_names))
            
            print(f"Enviando {len(rows)} registros para {table}...")
            # batch max size is often 1000 for APIs
            chunk_size = 500
            for i in range(0, len(rows), chunk_size):
                chunk = rows[i:i + chunk_size]
                stmts = [libsql_client.Statement(f"INSERT INTO {table} VALUES ({placeholders})", list(row)) for row in chunk]
                try:
                    await client.batch(stmts)
                except Exception as e:
                    print(f"Erro no batch do {table} index {i}: {e}")

    print("Concluido!")

if __name__ == "__main__":
    asyncio.run(migrate())
