"""v0.5.0 — inventory SQLite schema invariants (not live DB migration)."""
import sqlite3
import unittest
from pathlib import Path


SCHEMA = (Path(__file__).resolve().parents[1] / "inventory" / "schema_v050.sql").read_text(encoding="utf-8")


class TestInventorySQL(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    def tearDown(self):
        self.db.close()

    def create_point(self, id, status="proposed", type="tree"):
        confirmed = status == "confirmed"
        self.db.execute("""
            INSERT INTO inventory_objects(
                id,object_type,geometry_type,lat,lon,confirmation_status,
                created_by,created_at,updated_at,confirmed_by,confirmed_at)
            VALUES(?,?,'Point',43.115,131.885,?,'person',100,100,?,?)
        """, (id,type,status,"moderator" if confirmed else None, 120 if confirmed else None))

    def test_create_all_tables(self):
        tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for required in (
            "inventory_objects", "inventory_basic", "inventory_expert", "inventory_area_details",
            "inventory_clarifications", "inventory_photos", "inventory_audit", "inventory_import_batches",
        ):
            self.assertIn(required, tables)

    def test_points_and_shrubs(self):
        self.create_point("oak")
        self.create_point("blue-shrub", "confirmed", "shrub")
        self.assertEqual(self.db.execute("SELECT count(*) FROM inventory_objects").fetchone()[0], 2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.create_point("bad-status", "dead")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("""
                INSERT INTO inventory_objects
                (id,object_type,geometry_type,lat,lon,confirmation_status,created_by,created_at,updated_at)
                VALUES('missing-coordinates','tree','Point',NULL,NULL,'proposed','x',1,1)
            """)
        with self.assertRaises(sqlite3.IntegrityError):
            self.create_point("bad-confirmed", "confirmed-by-nobody")

    def test_area_needs_polygon_not_point(self):
        self.db.execute("""
            INSERT INTO inventory_objects
            (id,object_type,geometry_type,geometry_geojson,created_by,created_at,updated_at)
            VALUES('lawn','lawn','Polygon','{"type":"Polygon","coordinates":[]}','mod',10,10)
        """)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("""
                INSERT INTO inventory_objects
                (id,object_type,geometry_type,lat,lon,confirmation_status,created_by,created_at,updated_at)
                VALUES('bad-lawn','lawn','Point',43.1,131.8,'proposed','mod',10,10)
            """)

    def test_notes_independent_of_confirmation(self):
        self.create_point("tree", "confirmed")
        self.db.execute("""
            INSERT INTO inventory_clarifications(id,object_id,author_id,message,status,created_at)
            VALUES('note1','tree','person2','Засохло','open',1000)
        """)
        self.assertEqual(self.db.execute("""
            SELECT confirmation_status FROM inventory_objects WHERE id='tree'
        """).fetchone()[0], "confirmed")
        self.assertEqual(self.db.execute("""
            SELECT count(*) FROM inventory_clarifications WHERE object_id='tree' AND status='open'
        """).fetchone()[0], 1)
        self.db.execute("""
            UPDATE inventory_clarifications SET status='closed',closed_by='mod',
            closed_at=2000,resolution='Проверено' WHERE id='note1'
        """)
        self.assertEqual(self.db.execute("""
            SELECT count(*) FROM inventory_clarifications WHERE object_id='tree' AND status='open'
        """).fetchone()[0], 0)

    def test_expert_score_constrained(self):
        self.create_point("tree")
        self.db.execute("INSERT INTO inventory_expert(object_id,sanitary_condition_score) VALUES('tree',1)")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE inventory_expert SET sanitary_condition_score=7 WHERE object_id='tree'")


if __name__ == "__main__":
    unittest.main()
