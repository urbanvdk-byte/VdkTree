"""VdkTree v0.8.0 — moderator workspace. Every decision is checked and logged server-side."""
import json
import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from auth_backend import current_session
from inventory_model import can_confirm_point, POINT_TYPES
from pgdb import connect

router = APIRouter(prefix="/api/v2/moderation", tags=["moderation"])


def staff(user=Depends(current_session)):
    if user["role"] not in ("moderator", "admin"):
        raise HTTPException(403, "Панель доступна только модератору и администратору")
    return user


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["confirm", "request_changes"]
    comment: str = Field(default="", max_length=1500)


def _queue_conditions(mode: str, kind: str):
    parts = []
    if mode == "pending":
        parts.append("o.confirmation_status='proposed'")
    elif mode == "notes":
        parts.append("EXISTS(SELECT 1 FROM inventory_clarifications n WHERE n.object_id=o.id AND n.status='open')")
    else:
        parts.append("(o.confirmation_status='proposed' OR EXISTS(SELECT 1 FROM inventory_clarifications n WHERE n.object_id=o.id AND n.status='open'))")
    if kind in ("tree", "shrub"):
        parts.append("o.object_type='" + kind + "'")
    elif kind == "area":
        parts.append("o.object_type IN ('lawn','flowerbed','natural_community')")
    return " AND ".join(parts)


@router.get("/queue")
def queue(
    mode: Literal["all", "pending", "notes"]="all",
    kind: Literal["all", "tree", "shrub", "area"]="all",
    limit: int=Query(default=30, ge=1, le=100),
    offset: int=Query(default=0, ge=0, le=1000000),
    user=Depends(staff),
):
    condition = _queue_conditions(mode, kind)
    with connect() as con:
        total = con.execute(
            "SELECT COUNT(*) FROM inventory_objects o WHERE " + condition
        ).fetchone()[0]
        rows = con.execute("""
            SELECT o.id,o.object_type,o.confirmation_status,o.created_at,o.updated_at,
                   o.created_by,o.lat,o.lon,b.species_common,b.visible_condition,
                   (SELECT COUNT(*) FROM inventory_clarifications n
                    WHERE n.object_id=o.id AND n.status='open') AS open_notes
            FROM inventory_objects o
            LEFT JOIN inventory_basic b ON b.object_id=o.id
            WHERE """ + condition + """
            ORDER BY (SELECT COUNT(*) FROM inventory_clarifications n
                      WHERE n.object_id=o.id AND n.status='open') DESC,
                     o.created_at DESC, o.id DESC
            LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
        pending = con.execute(
            "SELECT COUNT(*) FROM inventory_objects WHERE confirmation_status='proposed'"
        ).fetchone()[0]
        open_notes = con.execute(
            "SELECT COUNT(*) FROM inventory_clarifications WHERE status='open'"
        ).fetchone()[0]
    return {
        "items": [dict(r) for r in rows],
        "total": total, "limit": limit, "offset": offset,
        "counts": {"proposed": pending, "open_notes": open_notes},
    }


@router.get("/objects/{object_id}/history")
def history(object_id: str, user=Depends(staff)):
    with connect() as con:
        exists = con.execute("SELECT 1 FROM inventory_objects WHERE id=?", (object_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "Объект не найден")
        rows = con.execute("""
            SELECT a.id,a.action,a.actor_id,u.display_name AS actor_name,
                   a.created_at,a.before_json,a.after_json
            FROM inventory_audit a
            LEFT JOIN users u ON u.id=a.actor_id
            WHERE a.object_id=?
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT 100
        """, (object_id,)).fetchall()
    events = []
    for row in rows:
        event = dict(row)
        for key in ("before_json", "after_json"):
            try:
                event[key.replace("_json", "")] = json.loads(event.pop(key) or "null")
            except (ValueError, TypeError):
                event[key.replace("_json", "")] = None
        events.append(event)
    return {"object_id": object_id, "events": events}


@router.post("/objects/{object_id}/review")
def review(object_id: str, payload: Decision, user=Depends(staff)):
    comment = payload.comment.strip()
    if payload.action == "request_changes" and len(comment) < 3:
        raise HTTPException(422, "Опишите, что требуется уточнить (минимум 3 символа)")
    now = int(time.time())
    with connect() as con:
        row = con.execute(
            "SELECT * FROM inventory_objects WHERE id=? FOR UPDATE", (object_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Объект не найден")
        obj = dict(row)
        if payload.action == "confirm":
            if not can_confirm_point(user["role"], obj):
                raise HTTPException(409, "Подтверждать можно только предложенные деревья и кустарники")
            con.execute("""
                UPDATE inventory_objects SET confirmation_status='confirmed',
                  confirmed_by=?,confirmed_at=?,updated_at=?
                WHERE id=?
            """, (user["id"], now, now, object_id))
            note_id = None
            event = "review_confirm"
        else:
            if obj["object_type"] not in POINT_TYPES or obj["confirmation_status"] != "proposed":
                raise HTTPException(409, "На уточнение отправляется только предложенное растение")
            note_id = secrets.token_hex(16)
            con.execute("""
                INSERT INTO inventory_clarifications
                  (id,object_id,author_id,message,status,created_at)
                VALUES(?,?,?,?,'open',?)
            """, (note_id,object_id,user["id"],comment,now))
            event = "request_changes"
        con.execute("""
            INSERT INTO inventory_audit
              (id,object_id,actor_id,action,before_json,after_json,created_at)
            VALUES(?,?,?,?,?,?,?)
        """, (secrets.token_hex(16),object_id,user["id"],event,
              json.dumps({"confirmation_status": obj["confirmation_status"]}),
              json.dumps({"action":payload.action,"comment":comment,"note_id":note_id},
                         ensure_ascii=False),now))
    return {"ok":True,"action":payload.action,"object_id":object_id,"note_id":note_id}
