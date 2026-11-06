"""VdkTree v0.7.0 — PostgreSQL connection for all runtime data.

DATABASE_URL is stored only in BotHost. No credentials, dumps or URLs in Git.
"""
import os
from contextlib import contextmanager

import psycopg


class HybridRow(dict):
    """A mapping row with optional integer indexing for older COUNT(*) queries."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def hybrid_row(cursor):
    columns = [column.name for column in (cursor.description or ())]
    return lambda values: HybridRow(zip(columns, values))


class Connection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, query, params=None):
        # Existing inventory SQL uses SQLite-style positional placeholders.
        # Queries are authored in this repository, not from user input.
        return self.raw.execute(query.replace("?", "%s"), params)

    def executescript(self, sql):
        # Static, trusted schema script; no client input is concatenated.
        return self.raw.execute(sql)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()


def get_database_url():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("Задайте DATABASE_URL с адресом PostgreSQL в переменных BotHost")
    return url


@contextmanager
def connect():
    with psycopg.connect(get_database_url(), row_factory=hybrid_row, connect_timeout=10) as raw:
        yield Connection(raw)
