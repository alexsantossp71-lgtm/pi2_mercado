"""
Database Connection Helper for Dispensa Planejada FastAPI SGBD
Powered by Turso LibSQL
"""

import os
from dotenv import load_dotenv
import libsql_client

load_dotenv()

class CompatRow(dict):
    """Linha que suporta acesso por nome de coluna e por índice."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class LibSQLCursor:
    def __init__(self, client):
        self.client = client
        self.rs = None
        self.description = None

    def execute(self, sql, params=None):
        if params is None:
            params = []
        self.rs = self.client.execute(sql, params)
        if self.rs and hasattr(self.rs, "columns"):
            self.description = [(col,) for col in self.rs.columns]
        return self

    def fetchall(self):
        if not self.rs:
            return []
        # Convert rows to dict to act like sqlite3.Row
        results = []
        for row in self.rs.rows:
            # We assume row supports indexing and rs.columns provides keys
            results.append(CompatRow(zip(self.rs.columns, row)))
        return results

    def fetchone(self):
        all_rows = self.fetchall()
        if all_rows:
            return all_rows[0]
        return None

class LibSQLConnection:
    def __init__(self, client):
        self.client = client

    def cursor(self):
        return LibSQLCursor(self.client)

    def close(self):
        self.client.close()


def get_db_connection():
    # Use environment variables if deployed, else fallback to hardcoded for now
    url = os.environ.get("TURSO_DATABASE_URL")
    token = os.environ.get("TURSO_AUTH_TOKEN")
    
    if not url or not token:
        raise ValueError("Missing TURSO_DATABASE_URL or TURSO_AUTH_TOKEN environment variable.")
    
    # Harden env parsing: strip whitespace and surrounding quotes
    url = url.strip().strip("'\"")
    token = token.strip().strip("'\"")
    # Turso libsql URLs must use https:// scheme for the sync client
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    
    client = libsql_client.create_client_sync(url=url, auth_token=token)
    return LibSQLConnection(client)
