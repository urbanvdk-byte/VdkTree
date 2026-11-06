"""VdkTree v0.5.0: inventory model, permissions and geometry regression tests."""
import copy
import unittest

from inventory_model import (
    AUTHOR_EDIT_WINDOW, InventoryValidationError,
    can_access_admin_backend, can_close_note, can_confirm_point,
    can_create_note, can_create_object, can_edit_object,
    can_import_bulk, can_view_object, marker_style,
    needs_clarification, validate_bulk_import_row, validate_object
)


class TestInventoryModel(unittest.TestCase):
    def setUp(self):
        self.pending_tree = {
            "object_type": "tree", "confirmation_status": "proposed",
            "created_by": "anna", "created_at": 1_000_000,
            "lat": 43.115, "lon": 131.885, "species_common": "Дуб",
        }
        self.confirmed_tree = dict(self.pending_tree, confirmation_status="confirmed")

    def test_create_roles_and_object_types(self):
        for role in ("user", "moderator", "admin"):
            for kind in ("tree", "shrub"):
                self.assertTrue(can_create_object(role, kind))
        for kind in ("lawn", "flowerbed", "natural_community"):
            self.assertFalse(can_create_object("user", kind))
            self.assertTrue(can_create_object("moderator", kind))
            self.assertTrue(can_create_object("admin", kind))
        self.assertFalse(can_create_object("guest", "tree"))
        self.assertFalse(can_create_object("user", "building"))
        self.assertTrue(can_view_object(None))
        self.assertTrue(can_view_object("user"))

    def test_owner_edit_for_seven_days_and_never_others(self):
        item = self.pending_tree
        self.assertTrue(can_edit_object("user", "anna", item, now=1_000_000))
        self.assertTrue(can_edit_object("user", "anna", item, now=1_000_000 + AUTHOR_EDIT_WINDOW - 1))
        self.assertFalse(can_edit_object("user", "anna", item, now=1_000_000 + AUTHOR_EDIT_WINDOW))
        self.assertFalse(can_edit_object("user", "bob", item, now=1_000_100))
        self.assertFalse(can_edit_object("user", "anna", self.confirmed_tree, now=1_000_100))
        self.assertFalse(can_edit_object("user", "", item, now=1_000_001))
        self.assertFalse(can_edit_object("user", "anna", dict(item, created_at="bad"), now=1_000_001))

    def test_moderator_edits_only_unconfirmed_point_objects(self):
        self.assertTrue(can_edit_object("moderator", "bob", self.pending_tree, now=9_000_000))
        self.assertFalse(can_edit_object("moderator", "bob", self.confirmed_tree, now=1_000_100))
        self.assertTrue(can_edit_object("admin", "bob", self.confirmed_tree, now=9_000_000))
        area = {"object_type": "lawn", "created_by": "mod", "created_at": 1}
        self.assertFalse(can_edit_object("user", "mod", area, now=2))
        self.assertTrue(can_edit_object("moderator", "mod", area, now=2))
        self.assertFalse(can_edit_object("moderator", "other", area, now=2))
        self.assertTrue(can_edit_object("admin", "any", area, now=2))

    def test_confirmation_and_comments_are_separate(self):
        self.assertTrue(can_confirm_point("moderator", self.pending_tree))
        self.assertTrue(can_confirm_point("admin", self.pending_tree))
        self.assertFalse(can_confirm_point("user", self.pending_tree))
        self.assertFalse(can_confirm_point("moderator", self.confirmed_tree))
        self.assertTrue(can_create_note("user", self.confirmed_tree))
        self.assertTrue(can_create_note("user", self.pending_tree))
        self.assertFalse(can_create_note("anonymous", self.pending_tree))
        self.assertTrue(can_close_note("moderator"))
        self.assertFalse(can_close_note("user"))
        self.assertFalse(needs_clarification([]))
        self.assertFalse(needs_clarification([{"status": "closed"}]))
        self.assertTrue(needs_clarification([{"status": "closed"}, {"status": "open"}]))
        self.assertEqual(marker_style("tree", "confirmed", [{"status": "open"}])["fill"], "#259D55")
        self.assertTrue(marker_style("tree", "confirmed", [{"status": "open"}])["clarification_badge"])
        self.assertEqual(marker_style("tree", "proposed")["fill"], "#9CA3AF")
        self.assertEqual(marker_style("shrub", "proposed")["fill"], "#42B8E6")
        self.assertEqual(marker_style("shrub", "confirmed")["fill"], "#42B8E6")

    def test_admin_only_backend_and_bulk(self):
        for role in ("user", "moderator", None):
            self.assertFalse(can_import_bulk(role))
            self.assertFalse(can_access_admin_backend(role))
        self.assertTrue(can_import_bulk("admin"))
        self.assertTrue(can_access_admin_backend("admin"))

    def test_point_validation(self):
        result = validate_object(self.pending_tree)
        self.assertEqual(result["lat"], 43.115)
        self.assertEqual(result["lon"], 131.885)
        self.assertEqual(result["confirmation_status"], "proposed")
        result = validate_object({"object_type": "shrub", "lat": 43.1, "lon": 131.9})
        self.assertEqual(result["confirmation_status"], "proposed")
        for payload in (
            dict(self.pending_tree, lat=44.5),
            dict(self.pending_tree, lat=float("nan")),
            dict(self.pending_tree, lon=True),
            dict(self.pending_tree, confirmation_status="dead"),
            dict(self.pending_tree, geometry={"type": "Point", "coordinates": [131.8, 43.1]}),
            dict(self.pending_tree, sanitary_condition_score=8),
            dict(self.pending_tree, sanitary_condition_score="2"),
            dict(self.pending_tree, visible_condition="needs_rescue"),
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(InventoryValidationError):
                    validate_object(payload)

    def test_polygon_validation(self):
        geometry = {"type": "Polygon", "coordinates": [[
            [131.8,43.1], [131.81,43.1], [131.81,43.11], [131.8,43.1]
        ]]}
        for kind in ("lawn", "flowerbed", "natural_community"):
            obj = validate_object({"object_type": kind, "geometry": copy.deepcopy(geometry)})
            self.assertIsNone(obj["confirmation_status"])
        for payload in (
            {"object_type":"lawn", "lat":43.1, "lon":131.8, "geometry": geometry},
            {"object_type":"lawn", "geometry": {"type":"Point", "coordinates":[131.8,43.1]}},
            {"object_type":"lawn", "geometry": {"type":"Polygon", "coordinates":[
                [[131.8,43.1],[131.81,43.1],[131.81,43.11],[131.82,43.12]]]}},
            {"object_type":"lawn", "geometry": {"type":"Polygon", "coordinates":[
                [[131.8,43.1],[131.81,43.1],[131.81,44.1],[131.8,43.1]]]}},
            {"object_type":"lawn", "geometry": geometry, "confirmation_status":"confirmed"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(InventoryValidationError):
                    validate_object(payload)

    def test_bulk_import_validation(self):
        row = {"object_type": "tree", "latitude": "43.115", "longitude": "131.885",
               "species_common": "Кедр", "sanitary_condition_score": "3"}
        imported = validate_bulk_import_row(row)
        self.assertEqual(imported["sanitary_condition_score"], 3)
        self.assertEqual(imported["confirmation_status"], "proposed")
        for change in (
            {"latitude": ""},
            {"longitude": "nonsense"},
            {"object_type": "lawn"},
            {"sanitary_condition_score": "9"},
        ):
            with self.subTest(change=change):
                with self.assertRaises(InventoryValidationError):
                    validate_bulk_import_row(dict(row, **change))


if __name__ == "__main__":
    unittest.main()
