"""v1.0.1 — reproduce BotHost collision with pre-existing public.users(id INTEGER)."""
import os
import unittest

import psycopg

from app import app
from pgdb import connect


class SchemaIsolationTests(unittest.TestCase):
    def test_existing_public_users_integer_id_is_untouched(self):
        # Workflow seeds public.users before importing app.py.
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            old = db.execute("""
                SELECT data_type FROM information_schema.columns
                WHERE table_schema='public' AND table_name='users' AND column_name='id'
            """).fetchone()
            self.assertIsNotNone(old)
            self.assertEqual(old[0], "integer")
            self.assertEqual(
                db.execute("SELECT id FROM public.users WHERE id=1234").fetchone()[0], 1234
            )

    def test_vdktree_auth_tables_created_in_dedicated_schema(self):
        with connect() as db:
            self.assertEqual(db.execute("SELECT current_schema()").fetchone()[0], "vdktree")
            row = db.execute("""
                SELECT data_type FROM information_schema.columns
                WHERE table_schema='vdktree' AND table_name='users' AND column_name='id'
            """).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "text")
            for table in ("users", "sessions", "login_limits", "inventory_objects",
                          "inventory_photos", "inventory_import_batches", "inventory_import_rows"):
                exists = db.execute("""
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema='vdktree' AND table_name=?
                """, (table,)).fetchone()
                self.assertIsNotNone(exists, "VdkTree table missing: "+table)
            foreign = db.execute("""
                SELECT ns.nspname AS target_schema
                FROM pg_constraint c
                JOIN pg_class t ON t.oid=c.confrelid
                JOIN pg_namespace ns ON ns.oid=t.relnamespace
                WHERE c.conname='sessions_user_id_fkey'
                  AND c.conrelid='vdktree.sessions'::regclass
            """).fetchone()
            self.assertIsNotNone(foreign)
            self.assertEqual(foreign["target_schema"], "vdktree")


if __name__ == "__main__":
    unittest.main()
