"""VdkTree v0.7.0 — shared PostgreSQL inventory API and persistent images."""
import json
import os
import secrets
import time
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pgdb import connect
from pydantic import BaseModel, ConfigDict, Field

from auth_backend import current_session
from inventory_model import (
    POINT_TYPES, AREA_TYPES, InventoryValidationError, can_create_object,
    can_edit_object, can_confirm_point, can_create_note, can_close_note,
    validate_object,
)

SCHEMA = Path(__file__).parent / "inventory" / "schema_postgres.sql"
router = APIRouter(prefix="/api/v2", tags=["inventory"])


def initialize():
    with connect() as con:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))


initialize()


class ObjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_type: Literal["tree", "shrub", "lawn", "flowerbed", "natural_community"]
    lat: float | None = None
    lon: float | None = None
    geometry: dict | None = None
    species_common: str = Field(default="", max_length=120)
    approx_height_band: Literal["unknown", "under_2m", "2_5m", "5_10m", "over_10m"] | None = None
    approx_diameter_cm: float | None = Field(default=None, gt=0, le=1000)
    visible_condition: Literal["unknown", "looks_healthy", "damaged", "dry"] = "unknown"
    visible_damage: list[Literal["broken_branches", "hollow", "cracks", "leaning", "dry_crown", "other"]] = Field(default_factory=list, max_length=6)
    observed_on: date | None = None
    comment: str = Field(default="", max_length=1000)


class ObjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    geometry: dict | None = None
    lat: float | None = None
    lon: float | None = None
    species_common: str | None = Field(default=None, max_length=120)
    approx_height_band: Literal["unknown", "under_2m", "2_5m", "5_10m", "over_10m"] | None = None
    approx_diameter_cm: float | None = Field(default=None, gt=0, le=1000)
    visible_condition: Literal["unknown", "looks_healthy", "damaged", "dry"] | None = None
    visible_damage: list[Literal["broken_branches", "hollow", "cracks", "leaning", "dry_crown", "other"]] | None = Field(default=None, max_length=6)
    observed_on: date | None = None
    comment: str | None = Field(default=None, max_length=1000)


class NoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=3, max_length=1500)


class NoteClose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: str = Field(min_length=3, max_length=1500)


def _validate(payload):
    try:
        return validate_object(payload)
    except InventoryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _get(con, object_id):
    row = con.execute("SELECT * FROM inventory_objects WHERE id=?", (object_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Объект не найден")
    return dict(row)


def _summary_rows(con, bounds, object_id=None):
    sql = """
        SELECT o.id,o.object_type,o.geometry_type,o.lat,o.lon,o.geometry_geojson,
               o.confirmation_status,o.created_by,o.created_at,o.updated_at,o.observed_on,
               o.confirmed_at,b.species_common,b.approx_height_band,
               b.approx_diameter_cm,b.visible_condition,b.visible_damage_json,b.comment,
               (SELECT COUNT(*) FROM inventory_clarifications n
                WHERE n.object_id=o.id AND n.status='open') AS open_notes,
               (SELECT p.storage_key FROM inventory_photos p
                WHERE p.object_id=o.id ORDER BY p.created_at DESC LIMIT 1) AS photo_key
        FROM inventory_objects o
        LEFT JOIN inventory_basic b ON o.id=b.object_id
        WHERE (o.geometry_type='Polygon' OR
               (o.lat BETWEEN ? AND ? AND o.lon BETWEEN ? AND ?))
          AND (?::text IS NULL OR o.id=?)
        ORDER BY o.created_at DESC LIMIT 5000
    """
    result = []
    for row in con.execute(sql, (*bounds, object_id, object_id)):
        obj = dict(row)
        raw = obj.pop("geometry_geojson")
        obj["geometry"] = json.loads(raw) if raw else None
        obj["visible_damage"] = json.loads(obj.pop("visible_damage_json") or "[]")
        photo_key = obj.pop("photo_key")
        obj["photo_url"] = "/photos/" + photo_key if photo_key else None
        obj["needs_clarification"] = bool(obj["open_notes"])
        result.append(obj)
    return result


@router.get("/objects")
def list_objects(min_lat: float=42, max_lat: float=44, min_lon: float=130, max_lon: float=134):
    if not (42 <= min_lat <= max_lat <= 44 and 130 <= min_lon <= max_lon <= 134):
        raise HTTPException(422, "Недопустимые границы карты")
    with connect() as con:
        return {"objects": _summary_rows(con, (min_lat,max_lat,min_lon,max_lon))}


@router.get("/objects/{object_id}")
def get_object(object_id: str):
    with connect() as con:
        obj = next(iter(_summary_rows(con, (42,44,130,134), object_id)), None)
        if obj is None:
            raise HTTPException(404, "Объект не найден")
        obj["notes"] = [dict(r) for r in con.execute("""
          SELECT id,author_id,message,status,created_at,closed_at,resolution FROM inventory_clarifications
          WHERE object_id=? ORDER BY created_at DESC LIMIT 100
        """, (object_id,))]
        obj["photos"] = ["/photos/"+r["storage_key"] for r in con.execute(
          "SELECT storage_key FROM inventory_photos WHERE object_id=? ORDER BY created_at DESC LIMIT 12", (object_id,))]
        return obj


@router.post("/objects", status_code=201)
def create_object(payload: ObjectInput, user=Depends(current_session)):
    body = payload.model_dump(mode="json", exclude_none=True)
    kind = payload.object_type
    if not can_create_object(user["role"], kind):
        raise HTTPException(403, "Нет прав добавлять объект этого типа")
    data = _validate(body)
    now = int(time.time())
    object_id = secrets.token_hex(16)
    is_point = kind in POINT_TYPES
    with connect() as con:
        con.execute("""
            INSERT INTO inventory_objects
              (id,object_type,geometry_type,lat,lon,geometry_geojson,
               confirmation_status,created_by,created_at,updated_at,observed_on,source_type)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,'citizen')
        """, (object_id, kind, "Point" if is_point else "Polygon",
              data.get("lat"), data.get("lon"),
              None if is_point else json.dumps(data["geometry"], ensure_ascii=False),
              "proposed" if is_point else None,user["id"],now,now,data.get("observed_on")))
        con.execute("""
            INSERT INTO inventory_basic
              (object_id,species_common,approx_height_band,approx_diameter_cm,
               visible_condition,visible_damage_json,comment)
            VALUES(?,?,?,?,?,?,?)
        """, (object_id, data.get("species_common",""), data.get("approx_height_band"),
              data.get("approx_diameter_cm"),data.get("visible_condition", "unknown"),
              json.dumps(data.get("visible_damage", [])),data.get("comment", "")))
        con.execute("""
          INSERT INTO inventory_audit(id,object_id,actor_id,action,after_json,created_at)
          VALUES(?,?,?,'create',?,?)
        """, (secrets.token_hex(16),object_id,user["id"],json.dumps(data,ensure_ascii=False),now))
    return get_object(object_id)


@router.patch("/objects/{object_id}")
def edit_object(object_id: str, payload: ObjectPatch, user=Depends(current_session)):
    changes = payload.model_dump(mode="json", exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Нет изменений")
    if any(value is None for value in changes.values()):
        raise HTTPException(422, "Для очистки используйте пустую строку или «Не знаю»")
    with connect() as con:
        old = _get(con, object_id)
        if not can_edit_object(user["role"], user["id"], old):
            raise HTTPException(403, "Редактирование недоступно")
        is_point = old["object_type"] in POINT_TYPES
        if is_point and "geometry" in changes:
            raise HTTPException(422, "Точка не может иметь контур")
        if not is_point and ("lat" in changes or "lon" in changes):
            raise HTTPException(422, "Площадной объект изменяется через контур")
        row = con.execute("SELECT * FROM inventory_basic WHERE object_id=?", (object_id,)).fetchone()
        basic = dict(row) if row else {}
        candidate = {
            "object_type": old["object_type"],
            "species_common": changes.get("species_common", basic.get("species_common") or ""),
            "approx_height_band": changes.get("approx_height_band", basic.get("approx_height_band")),
            "approx_diameter_cm": changes.get("approx_diameter_cm", basic.get("approx_diameter_cm")),
            "visible_condition": changes.get("visible_condition", basic.get("visible_condition") or "unknown"),
            "visible_damage": changes.get("visible_damage", json.loads(basic.get("visible_damage_json") or "[]")),
            "comment": changes.get("comment", basic.get("comment") or ""),
        }
        if is_point:
            candidate["lat"] = changes.get("lat", old["lat"])
            candidate["lon"] = changes.get("lon", old["lon"])
        else:
            candidate["geometry"] = changes.get("geometry", json.loads(old["geometry_geojson"]))
        normalized = _validate(candidate)
        now = int(time.time())
        observed_on = changes.get("observed_on", old["observed_on"])
        if is_point:
            con.execute("""
              UPDATE inventory_objects SET lat=?,lon=?,observed_on=?,updated_at=? WHERE id=?
            """, (normalized["lat"], normalized["lon"], observed_on, now, object_id))
        else:
            con.execute("""
              UPDATE inventory_objects SET geometry_geojson=?,observed_on=?,updated_at=? WHERE id=?
            """, (json.dumps(normalized["geometry"],ensure_ascii=False),observed_on,now,object_id))
        con.execute("""
            UPDATE inventory_basic SET species_common=?,approx_height_band=?,
              approx_diameter_cm=?,visible_condition=?,visible_damage_json=?,comment=?
            WHERE object_id=?
        """, (normalized.get("species_common",""),normalized.get("approx_height_band"),
              normalized.get("approx_diameter_cm"),normalized.get("visible_condition","unknown"),
              json.dumps(normalized.get("visible_damage", [])),
              normalized.get("comment", ""),object_id))
        con.execute("""
            INSERT INTO inventory_audit(id,object_id,actor_id,action,before_json,after_json,created_at)
            VALUES(?,?,?,'edit',?,?,?)
        """, (secrets.token_hex(16),object_id,user["id"],
              json.dumps(old,ensure_ascii=False),json.dumps(normalized,ensure_ascii=False),now))
    return get_object(object_id)


@router.post("/objects/{object_id}/confirm")
def confirm_object(object_id: str, user=Depends(current_session)):
    with connect() as con:
        old = _get(con, object_id)
        if not can_confirm_point(user["role"], old):
            raise HTTPException(403, "Подтверждение доступно только модератору или администратору")
        now = int(time.time())
        updated = con.execute("""
          UPDATE inventory_objects SET confirmation_status='confirmed',confirmed_by=?,
           confirmed_at=?,updated_at=? WHERE id=? AND confirmation_status='proposed'
        """, (user["id"], now,now,object_id))
        if updated.rowcount != 1:
            raise HTTPException(409, "Объект уже подтверждён")
        con.execute("INSERT INTO inventory_audit(id,object_id,actor_id,action,created_at) VALUES(?,?,?,'confirm',?)",
                    (secrets.token_hex(16),object_id,user["id"],now))
    return get_object(object_id)


@router.post("/objects/{object_id}/notes", status_code=201)
def add_note(object_id: str, payload: NoteInput, user=Depends(current_session)):
    text = payload.message.strip()
    if len(text) < 3:
        raise HTTPException(422, "Введите текст замечания")
    with connect() as con:
        obj = _get(con, object_id)
        if not can_create_note(user["role"], obj):
            raise HTTPException(403, "Нет доступа к замечаниям")
        now = int(time.time())
        last = con.execute("""
          SELECT created_at FROM inventory_clarifications
          WHERE author_id=? AND object_id=? ORDER BY created_at DESC LIMIT 1
        """, (user["id"],object_id)).fetchone()
        if last and now - last["created_at"] < 60:
            raise HTTPException(429, "Подождите минуту перед следующим замечанием")
        daily = con.execute("SELECT COUNT(*) FROM inventory_clarifications WHERE author_id=? AND created_at>?",
                            (user["id"],now-86400)).fetchone()[0]
        if daily >= 20:
            raise HTTPException(429, "Достигнут дневной лимит замечаний")
        note_id = secrets.token_hex(16)
        con.execute("""
            INSERT INTO inventory_clarifications(id,object_id,author_id,message,status,created_at)
            VALUES(?,?,?,?,'open',?)
        """, (note_id,object_id,user["id"],text,now))
        con.execute("""
            INSERT INTO inventory_audit(id,object_id,actor_id,action,after_json,created_at)
            VALUES(?,?,?,'add_note',?,?)
        """, (secrets.token_hex(16),object_id,user["id"],json.dumps({"note_id":note_id,"message":text},ensure_ascii=False),now))
    return {"id":note_id,"status":"open","created_at":now}


@router.post("/objects/{object_id}/notes/{note_id}/close")
def close_note(object_id: str, note_id: str, payload: NoteClose, user=Depends(current_session)):
    if not can_close_note(user["role"]):
        raise HTTPException(403, "Закрывать замечания могут модератор и администратор")
    with connect() as con:
        _get(con, object_id)
        now = int(time.time())
        updated = con.execute("""
          UPDATE inventory_clarifications
          SET status='closed',closed_by=?,closed_at=?,resolution=?
          WHERE id=? AND object_id=? AND status='open'
        """, (user["id"],now,payload.resolution.strip(),note_id,object_id))
        if updated.rowcount != 1:
            raise HTTPException(404, "Открытое замечание не найдено")
        con.execute("INSERT INTO inventory_audit(id,object_id,actor_id,action,created_at) VALUES(?,?,?,'close_note',?)",
                    (secrets.token_hex(16),object_id,user["id"],now))
    return {"ok":True}


@router.post("/objects/{object_id}/photos", status_code=201)
async def upload_photo(object_id: str, photo: UploadFile=File(...), user=Depends(current_session)):
    data = await photo.read(5*1024*1024+1)
    if len(data) > 5*1024*1024:
        raise HTTPException(413, "Максимальный размер фото — 5 МБ")
    if data.startswith(bytes.fromhex("ffd8ff")):
        suffix, mime = ".jpg", "image/jpeg"
    elif data.startswith(bytes.fromhex("89504e470d0a1a0a")):
        suffix, mime = ".png", "image/png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        suffix, mime = ".webp", "image/webp"
    else:
        raise HTTPException(422, "Допускаются только JPG, PNG или WebP")
    name = secrets.token_hex(20) + suffix
    with connect() as con:
        # Row lock prevents simultaneous uploads from bypassing the 8-photo limit.
        locked = con.execute("SELECT * FROM inventory_objects WHERE id=? FOR UPDATE", (object_id,)).fetchone()
        if not locked:
            raise HTTPException(404, "Объект не найден")
        if not can_edit_object(user["role"], user["id"], dict(locked)):
            raise HTTPException(403, "Недостаточно прав для загрузки фотографии")
        count = con.execute("SELECT COUNT(*) FROM inventory_photos WHERE object_id=?", (object_id,)).fetchone()[0]
        if count >= 8:
            raise HTTPException(422, "К объекту можно добавить не более 8 фотографий")
        con.execute("""
            INSERT INTO inventory_photos
                (id,object_id,uploaded_by,storage_key,mime_type,content,created_at)
            VALUES(?,?,?,?,?,?,?)
        """, (secrets.token_hex(16), object_id, user["id"], name, mime, data, int(time.time())))
    return {"url": "/photos/" + name}
