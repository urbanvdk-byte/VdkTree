"""VdkTree v0.5.0 — non-invasive inventory data model and permission rules.

This module defines rules for the NEXT integration phase. It does not alter
existing app.py routes or automatically migrate the live SQLite databases.
"""
import json
import math
import re
import time
from pathlib import Path

CATALOG = json.loads((Path(__file__).with_name("inventory") / "catalog.json").read_text(encoding="utf-8"))

ROLES = frozenset(("user", "moderator", "admin"))
POINT_TYPES = frozenset(("tree", "shrub"))
AREA_TYPES = frozenset(("lawn", "flowerbed", "natural_community"))
OBJECT_TYPES = POINT_TYPES | AREA_TYPES
POINT_STATUSES = frozenset(("proposed", "confirmed"))
OPEN_NOTE = "open"
AUTHOR_EDIT_WINDOW = 7 * 24 * 60 * 60
WGS84_BOUNDS = {"lat": (42.0, 44.0), "lon": (130.0, 134.0)}
LOGIN_LESS_VIEWING = True


class InventoryValidationError(ValueError):
    """Invalid inventory object from a user, importer or map editor."""


def can_view_object(role=None):
    """Every map visitor can view ALL submitted objects, including proposed."""
    return True


def can_create_object(role: str, object_type: str) -> bool:
    if role not in ROLES:
        return False
    if object_type in POINT_TYPES:
        return True
    return object_type in AREA_TYPES and role in ("moderator", "admin")


def can_edit_object(role: str, actor_id: str, item: dict, now: int | None = None) -> bool:
    """User: only own, proposed point within 7 * 24 hours. Mod: proposed points.

    Polygon editing by moderators is limited to their own polygon submissions
    pending a separate decision on a general polygon editing workflow.
    """
    if role not in ROLES or not actor_id or not isinstance(item, dict):
        return False
    if role == "admin":
        return True
    object_type = item.get("object_type")
    owner_id = item.get("created_by")
    if object_type in AREA_TYPES:
        return role == "moderator" and owner_id == actor_id
    if object_type not in POINT_TYPES or item.get("confirmation_status") != "proposed":
        return False
    if role == "moderator":
        return True
    if role != "user" or owner_id != actor_id:
        return False
    created_at = item.get("created_at")
    if type(created_at) not in (int, float) or not math.isfinite(created_at):
        return False
    current = int(time.time()) if now is None else now
    return created_at <= current < created_at + AUTHOR_EDIT_WINDOW


def can_confirm_point(role: str, item: dict) -> bool:
    return (role in ("moderator", "admin")
            and isinstance(item, dict)
            and item.get("object_type") in POINT_TYPES
            and item.get("confirmation_status") == "proposed")


def can_create_note(role: str, item: dict) -> bool:
    return role in ROLES and isinstance(item, dict) and item.get("object_type") in OBJECT_TYPES


def can_close_note(role: str) -> bool:
    return role in ("moderator", "admin")


def can_import_bulk(role: str) -> bool:
    return role == "admin"


def can_access_admin_backend(role: str) -> bool:
    return role == "admin"


def needs_clarification(notes: list) -> bool:
    """A red badge is independent from confirmation status."""
    return any(isinstance(note, dict) and note.get("status") == OPEN_NOTE for note in notes)


def marker_style(object_type: str, confirmation_status: str, notes: list | None = None) -> dict:
    """Tree status drives grey/green; shrubs stay blue, with styled outline."""
    if object_type not in POINT_TYPES or confirmation_status not in POINT_STATUSES:
        raise InventoryValidationError("Point object type and confirmation status required")
    result = dict(CATALOG["map_markers"][object_type][confirmation_status])
    result["clarification_badge"] = needs_clarification(notes or [])
    if result["clarification_badge"]:
        result["clarification_badge_color"] = CATALOG["map_markers"]["notes_badge"]["fill"]
    return result


def _bounded_number(value, lower, upper, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InventoryValidationError(f"{name}: требуется число")
    if not math.isfinite(value) or not (lower <= value <= upper):
        raise InventoryValidationError(f"{name}: значение вне допустимого диапазона")
    return float(value)


def _validate_polygon_geometry(geojson):
    """Validate basic GeoJSON Polygon / MultiPolygon structure and WGS84 bounds.

    Topology (self-intersections), area computation and legal parcel boundaries
    require GIS validation before the production polygon API is enabled.
    """
    if not isinstance(geojson, dict) or geojson.get("type") not in ("Polygon", "MultiPolygon"):
        raise InventoryValidationError("Ожидается GeoJSON Polygon или MultiPolygon")
    coords = geojson.get("coordinates")
    kind = geojson["type"]
    if not isinstance(coords, list) or not coords:
        raise InventoryValidationError("Пустой полигон")
    polygons = [coords] if kind == "Polygon" else coords
    vertices = 0
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise InventoryValidationError("У полигона нет внешнего кольца")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                raise InventoryValidationError("Кольцо должно содержать не менее четырёх вершин")
            if ring[0] != ring[-1]:
                raise InventoryValidationError("Кольцо полигона не замкнуто")
            vertices += len(ring)
            if vertices > 10000:
                raise InventoryValidationError("Слишком сложный полигон")
            for point in ring:
                if not isinstance(point, list) or len(point) != 2:
                    raise InventoryValidationError("Координата GeoJSON должна быть [долгота, широта]")
                _bounded_number(point[0], *WGS84_BOUNDS["lon"], "Долгота")
                _bounded_number(point[1], *WGS84_BOUNDS["lat"], "Широта")
    return geojson


def validate_object(item: dict) -> dict:
    """Validate shape and simple citizen-entered fields; no database writes.

    Confirmation is controlled by can_confirm_point plus server-side authentication.
    Objects must always remain visible on the public map after submission.
    """
    if not isinstance(item, dict):
        raise InventoryValidationError("Объект должен быть структурой полей")
    kind = item.get("object_type")
    if kind not in OBJECT_TYPES:
        raise InventoryValidationError("Неизвестный тип объекта")
    normalized = dict(item)
    if kind in POINT_TYPES:
        if item.get("geometry") is not None:
            raise InventoryValidationError("Дерево и кустарник должны быть точками")
        normalized["lat"] = _bounded_number(item.get("lat"), *WGS84_BOUNDS["lat"], "Широта")
        normalized["lon"] = _bounded_number(item.get("lon"), *WGS84_BOUNDS["lon"], "Долгота")
        if item.get("confirmation_status", "proposed") not in POINT_STATUSES:
            raise InventoryValidationError("Неизвестный статус подтверждения")
        normalized["confirmation_status"] = item.get("confirmation_status", "proposed")
    else:
        if item.get("lat") is not None or item.get("lon") is not None:
            raise InventoryValidationError("Площадной объект задаётся контуром, а не точкой")
        normalized["geometry"] = _validate_polygon_geometry(item.get("geometry"))
        if item.get("confirmation_status") is not None:
            raise InventoryValidationError("Статусы площадных объектов будут определены отдельно")
        normalized["confirmation_status"] = None
    species = item.get("species_common")
    if species is not None:
        if not isinstance(species, str) or len(species.strip()) > 120:
            raise InventoryValidationError("Недопустимое название растения")
        normalized["species_common"] = species.strip()
    comment = item.get("comment", "")
    if not isinstance(comment, str) or len(comment) > 1000:
        raise InventoryValidationError("Комментарий не должен превышать 1000 символов")
    normalized["comment"] = comment.strip()
    if "sanitary_condition_score" in item and item["sanitary_condition_score"] is not None:
        score = item["sanitary_condition_score"]
        if type(score) is not int or score not in range(1, 7):
            raise InventoryValidationError("Экспертная санитарная оценка должна быть от 1 до 6")
    if "visible_condition" in item and item["visible_condition"] is not None:
        if item["visible_condition"] not in ("unknown", "looks_healthy", "damaged", "dry"):
            raise InventoryValidationError("Неизвестная визуальная оценка")
    return normalized


def validate_bulk_import_row(row: dict) -> dict:
    """Validate a single row from the standard template; import is admin-only."""
    if not isinstance(row, dict):
        raise InventoryValidationError("Строка импорта должна содержать столбцы")
    kind = (row.get("object_type") or "tree").strip()
    if kind not in POINT_TYPES:
        raise InventoryValidationError("Табличный импорт: только дерево/кустарник")
    try:
        lat = float(row.get("latitude") or "")
        lon = float(row.get("longitude") or "")
    except (ValueError, TypeError):
        raise InventoryValidationError("Для импорта необходимы широта и долгота")
    obj = validate_object({
        "object_type": kind, "lat": lat, "lon": lon,
        "species_common": row.get("species_common", ""),
        "comment": row.get("comment", ""),
        "confirmation_status": "proposed",
    })
    if row.get("sanitary_condition_score"):
        try:
            score = int(row["sanitary_condition_score"])
        except (TypeError, ValueError):
            raise InventoryValidationError("Неправильная санитарная оценка")
        obj["sanitary_condition_score"] = score
        validate_object(obj)
    return obj
