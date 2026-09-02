"""
Unit test verifying that product search treats each query word independently
and ignores word order when building the FTS query.
"""

import os
import sys
from unittest.mock import patch

# Ensure the backend package is importable from the repo-root tests/ dir.
BACKEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "webapp", "backend")
)
sys.path.insert(0, BACKEND_DIR)

from services.product_service import search_products  # noqa: E402


class MockCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params if params is not None else []))
        return self

    def fetchone(self):
        return [0]

    def fetchall(self):
        return []


class MockConnection:
    def __init__(self):
        self.cursor_obj = MockCursor()

    def cursor(self):
        return self.cursor_obj

    def close(self):
        pass


def _run_search(q):
    conn = MockConnection()
    with patch(
        "services.product_service.get_db_connection", return_value=conn
    ):
        result = search_products(q=q)
    return conn.cursor_obj.executed, result


def test_fts_query_includes_all_tokens_original_order():
    executed, result = _run_search("Biscoito club social")
    # First executed statement is the COUNT query; its params are
    # [fts_query, like_query, like_query], so the FTS MATCH value is params[0].
    fts_query = executed[0][1][0]
    assert fts_query == '"Biscoito"* AND "club"* AND "social"*'
    for token in ('"Biscoito"*', '"club"*', '"social"*'):
        assert token in fts_query
    # Function returns an empty (mocked) result set without raising.
    assert result == (0, 1, 20, 0, [])


def test_fts_query_includes_all_tokens_reordered():
    executed, result = _run_search("club social biscoito")
    fts_query = executed[0][1][0]
    # FTS preserves the input's case, so tokens here are lowercase.
    for token in ('"club"*', '"social"*', '"biscoito"*'):
        assert token in fts_query
    assert result == (0, 1, 20, 0, [])
