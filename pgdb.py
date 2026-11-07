"""VdkTree v1.0.1 — PostgreSQL connection for all runtime data.

DATABASE_URL is stored only in BotHost. No credentials, dumps or URLs in Git.
"""
import os
import threading
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


# Keep VdkTree tables separate from tables that BotHost or other apps may
# already have in public (e.g. public.users with an INTEGER primary key).
# Never drop, alter, or copy unrelated tables.
_SCHEMA = "vdktree"
_schema_lock = threading.Lock()
_schema_ready = False


def ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with psycopg.connect(get_database_url(), connect_timeout=10) as raw:
            raw.execute("CREATE SCHEMA IF NOT EXISTS vdktree")
        # Mark ready only after the CREATE SCHEMA transaction has committed.
        _schema_ready = True


@contextmanager
def connect():
    ensure_schema()
    # No 'public' fallback: every unqualified table and foreign-key target must
    # resolve in vdktree, so public.users can never collide with VdkTree.users.
    with psycopg.connect(
        get_database_url(), row_factory=hybrid_row, connect_timeout=10,
        options="-c search_path=vdktree"
    ) as raw:
        yield Connection(raw)
