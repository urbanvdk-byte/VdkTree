"""VdkTree v0.9.0 — expert card and area details, based on regulation section 5 / tables 2.3–2.5."""
import json
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from auth_backend import current_session
from inventory_model import POINT_TYPES, AREA_TYPES, can_edit_object
from pgdb import connect

router = APIRouter(prefix="/api/v2", tags=["expert"])


class ExpertPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plot_number: str | None = Field(default=None, max_length=80)
    biogroup_number: str | None = Field(default=None, max_length=80)
    plant_number: str | None = Field(default=None, max_length=80)
    planting_type: str | None = Field(default=None, max_length=120)
    life_form: str | None = Field(default=None, max_length=120)
    botanical_species: str | None = Field(default=None, max_length=160)
    quantity: int | None = Field(default=None, gt=0, le=100000)
    trunk_diameter_130_cm: float | None = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    height_m: float | None = Field(default=None, gt=0, le=100, allow_inf_nan=False)
    approx_age_years: int | None = Field(default=None, ge=0, le=10000)
    sanitary_condition_score: int | None = Field(default=None, ge=1, le=6)
    dieback_category: str | None = Field(default=None, max_length=120)
    defects: str | None = Field(default=None, max_length=2000)
    care_recommendations: str | None = Field(default=None, max_length=2000)
    slope_protection: bool | None = None
    trunk_lean_degrees: float | None = Field(default=None, ge=0, le=90, allow_inf_nan=False)
    crown_asymmetry: str | None = Field(default=None, max_length=1000)
    endemic_or_relict: bool | None = None


class AreaPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area_m2: float | None = Field(default=None, gt=0, le=100000000, allow_inf_nan=False)
    lawn_type: str | None = Field(default=None, pattern=r"^(ordinary|meadow|parterre|slope|inert)$")
    area_condition: str | None = Field(default=None, pattern=r"^(good|satisfactory|poor)$")
    annual_m2: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    perennial_m2: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    bulbous_m2: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    roses_m2: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    mixed_m2: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    community_type: str | None = Field(default=None, pattern=r"^(forest|meadow|waterside)$")


EXPERT_FIELDS = tuple(ExpertPatch.model_fields)
AREA_FIELDS = tuple(AreaPatch.model_fields)


def _record(con, object_id):
    obj = con.execute("SELECT * FROM inventory_objects WHERE id=?", (object_id,)).fetchone()
    if not obj:
        raise HTTPException(404, "Объект не найден")
    return dict(obj)


def _read(con, table, object_id):
    row = con.execute("SELECT * FROM " + table + " WHERE object_id=?", (object_id,)).fetchone()
    return dict(row) if row else None


def _store(con, table, columns, object_id, data):
    # Columns are fixed in this module, never interpolated from user-provided names.
    names = ("object_id",) + columns
    update = ", ".join(name + "=EXCLUDED." + name for name in columns)
    query = ("INSERT INTO " + table + " (" + ",".join(names) + ") VALUES (" +
             ",".join("?" for _ in names) + ") ON CONFLICT(object_id) DO UPDATE SET " + update)
    values = tuple(int(data[name]) if name in ("slope_protection", "endemic_or_relict")
                   and data.get(name) is not None else data.get(name)
                   for name in columns)
    con.execute(query, (object_id, *values))


def _update(object_id, body, fields, table, allowed_types, action, user):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Не указаны изменения")
    with connect() as con:
        obj = con.execute(
            "SELECT * FROM inventory_objects WHERE id=? FOR UPDATE", (object_id,)
        ).fetchone()
        if not obj:
            raise HTTPException(404, "Объект не найден")
        obj = dict(obj)
        if obj["object_type"] not in allowed_types:
            raise HTTPException(422, "Эти сведения не подходят данному типу объекта")
        if user["role"] not in ("moderator", "admin") or not can_edit_object(
            user["role"], user["id"], obj
        ):
            raise HTTPException(403, "Профессиональные сведения доступны модератору или администратору с правом редактирования")
        previous = _read(con, table, object_id)
        merged = {name: previous.get(name) if previous else None for name in fields}
        merged.update(changes)
        _store(con, table, fields, object_id, merged)
        now = int(time.time())
        con.execute("UPDATE inventory_objects SET updated_at=? WHERE id=?", (now,object_id))
        con.execute("""
            INSERT INTO inventory_audit
              (id,object_id,actor_id,action,before_json,after_json,created_at)
            VALUES(?,?,?,?,?,?,?)
        """, (secrets.token_hex(16),object_id,user["id"],action,
              json.dumps(previous,ensure_ascii=False),
              json.dumps(merged,ensure_ascii=False),now))
    return {"object_id":object_id,"data":merged,"ok":True}


@router.get("/objects/{object_id}/expert")
def get_expert(object_id: str):
    with connect() as con:
        obj = _record(con, object_id)
        if obj["object_type"] in POINT_TYPES:
            return {"object_id":object_id, "kind":"point",
                    "data": _read(con,"inventory_expert",object_id) or {}}
        if obj["object_type"] in AREA_TYPES:
            return {"object_id":object_id, "kind":"area",
                    "data":_read(con,"inventory_area_details",object_id) or {}}
    raise HTTPException(422, "Неизвестный тип объекта")


@router.patch("/objects/{object_id}/expert")
def save_expert(object_id: str, payload: ExpertPatch, user=Depends(current_session)):
    return _update(object_id,payload,EXPERT_FIELDS,"inventory_expert",
                   POINT_TYPES,"expert_edit",user)


@router.patch("/objects/{object_id}/area-details")
def save_area(object_id: str, payload: AreaPatch, user=Depends(current_session)):
    return _update(object_id,payload,AREA_FIELDS,"inventory_area_details",
                   AREA_TYPES,"area_details_edit",user)
