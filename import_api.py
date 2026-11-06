"""VdkTree v1.0.0 — admin-only CSV/XLSX preview, validation and atomic PostgreSQL import."""
import csv
import hashlib
import io
import json
import math
import re
import secrets
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from openpyxl import load_workbook
from pydantic import ValidationError

from auth_backend import current_session
from expert_api import ExpertPatch, EXPERT_FIELDS, _store
from inventory_model import InventoryValidationError, POINT_TYPES, validate_object
from pgdb import connect

router = APIRouter(prefix="/api/v2/admin/imports", tags=["admin-import"])
SCHEMA = Path(__file__).parent / "inventory" / "schema_import_v100.sql"
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 5000
TEMPLATE = Path(__file__).parent / "inventory" / "import_template_v1.csv"
NUM_FLOAT = frozenset(("trunk_diameter_130_cm","height_m","trunk_lean_degrees"))
NUM_INT = frozenset(("quantity","approx_age_years","sanitary_condition_score"))
BOOL = frozenset(("slope_protection","endemic_or_relict"))
TEXT_FIELDS = frozenset(("object_type","latitude","longitude","species_common",
                         "comment","external_id","import_source","inventory_number",
                         "observed_on")) | frozenset(EXPERT_FIELDS)


def initialize():
    with connect() as con:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))


initialize()


def admin(user=Depends(current_session)):
    if user["role"] != "admin":
        raise HTTPException(403, "Импорт доступен только администратору")
    return user


def _sheet_rows(filename, raw):
    ext = Path(filename).suffix.lower()
    if ext not in (".csv", ".xlsx"):
        raise HTTPException(422, "Нужен файл CSV или XLSX (не XLS)")
    if ext == ".csv":
        try:
            decoded = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            decoded = raw.decode("cp1251")
        if "\x00" in decoded:
            raise HTTPException(422, "Недопустимый CSV")
        try:
            dialect = csv.Sniffer().sniff(decoded[:8192], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(decoded, newline=""), dialect)
        try:
            header = next(reader)
        except StopIteration:
            raise HTTPException(422, "Пустой файл")
        return header, reader, None
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 60 * 1024 * 1024:
                raise HTTPException(413, "Слишком большой XLSX после распаковки")
        book = load_workbook(io.BytesIO(raw),read_only=True,data_only=True,keep_links=False)
        sheet = book.worksheets[0]
        values = sheet.iter_rows(values_only=True)
        header = next(values,None)
        if header is None:
            book.close()
            raise HTTPException(422,"Пустая таблица")
        return header, values, book
    except HTTPException:
        raise
    except (ValueError, KeyError, zipfile.BadZipFile, OSError, IndexError) as exc:
        raise HTTPException(422, "Файл XLSX повреждён или не поддерживается") from exc


def _text(value):
    if value is None:
        return ""
    if isinstance(value,(date,datetime)):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def _decimal(value, name):
    try:
        number = float(_text(value).replace(" ", "").replace(",","."))
        if not math.isfinite(number):
            raise ValueError("not finite")
        return number
    except (ValueError,TypeError) as exc:
        raise ValueError(name + ": ожидается число") from exc


def _normalize(row, source):
    if row.get("import_source") and row["import_source"].strip() != source:
        raise ValueError("import_source в строке отличается от источника загрузки")
    kind = row.get("object_type") or "tree"
    if kind not in POINT_TYPES:
        raise ValueError("CSV/XLSX: поддерживаются только дерево и кустарник")
    obj = validate_object({
        "object_type":kind,
        "lat":_decimal(row.get("latitude"),"latitude"),
        "lon":_decimal(row.get("longitude"),"longitude"),
        "species_common":row.get("species_common",""),
        "comment":row.get("comment",""),
        "visible_condition":"unknown",
    })
    details = {}
    for name in EXPERT_FIELDS:
        raw = row.get(name,"").strip()
        if not raw:
            continue
        if name in NUM_FLOAT:
            details[name] = _decimal(raw,name)
        elif name in NUM_INT:
            value = _decimal(raw,name)
            if not value.is_integer():
                raise ValueError(name+": требуется целое число")
            details[name] = int(value)
        elif name in BOOL:
            value=raw.lower()
            if value in ("1","true","yes","да"):details[name]=True
            elif value in ("0","false","no","нет"):details[name]=False
            else:raise ValueError(name+": ожидается да/нет или 1/0")
        else:
            details[name]=raw
    try:
        validated=ExpertPatch.model_validate(details).model_dump(exclude_unset=True)
    except ValidationError as exc:
        field = ".".join(str(p) for p in exc.errors()[0].get("loc",()))
        raise ValueError("Недопустимое экспертное поле: "+field) from exc
    inventory_number = row.get("inventory_number","").strip() or None
    if inventory_number and len(inventory_number)>120:
        raise ValueError("Инвентарный номер длиннее 120 символов")
    ext = row.get("external_id","").strip()
    if len(ext)>120:
        raise ValueError("external_id длиннее 120 символов")
    if not ext:
        fingerprint = "|".join((kind,f"{obj['lat']:.6f}",f"{obj['lon']:.6f}",
                                obj.get("species_common","").casefold()))
        ext = "auto-"+hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:32]
    observed = row.get("observed_on","").strip()
    if observed:
        try:
            observed = date.fromisoformat(observed).isoformat()
        except ValueError as exc:
            raise ValueError("Дата наблюдения должна быть ГГГГ-ММ-ДД") from exc
    return {"basic":obj,"expert":validated,"external_id":ext,
            "inventory_number":inventory_number,"observed_on":observed or None}


def _existing(con, source, item):
    if con.execute("""
        SELECT id FROM inventory_objects WHERE import_source=? AND external_id=?
    """,(source,item["external_id"])).fetchone():
        return "Внешний идентификатор уже импортирован"
    if item["inventory_number"] and con.execute(
        "SELECT id FROM inventory_objects WHERE inventory_number=?",
        (item["inventory_number"],)
    ).fetchone():
        return "Инвентарный номер уже существует"
    obj=item["basic"]
    near=con.execute("""
        SELECT o.id FROM inventory_objects o
        LEFT JOIN inventory_basic b ON b.object_id=o.id
        WHERE o.object_type=? AND o.lat BETWEEN ? AND ? AND o.lon BETWEEN ? AND ?
          AND lower(COALESCE(b.species_common,''))=lower(?)
        LIMIT 1
    """,(obj["object_type"],obj["lat"]-0.000001,obj["lat"]+0.000001,
         obj["lon"]-0.000001,obj["lon"]+0.000001,obj.get("species_common",""))).fetchone()
    if near:
        return "Уже есть объект с тем же видом и координатами (точность около 10 см)"
    return None


def _summary(batch,con,offset=0):
    report=json.loads(batch["report_json"] or "{}")
    rows=con.execute("""
        SELECT row_number,row_state,external_id,errors_json,payload_json,created_object_id
        FROM inventory_import_rows WHERE batch_id=?
        ORDER BY row_number LIMIT 50 OFFSET ?
    """,(batch["id"],offset)).fetchall()
    preview=[]
    for row in rows:
        item=dict(row)
        payload=json.loads(item.pop("payload_json") or "{}")
        item["errors"]=json.loads(item.pop("errors_json") or "[]")
        item["species_common"]=payload.get("basic",{}).get("species_common","")
        item["latitude"]=payload.get("basic",{}).get("lat")
        item["longitude"]=payload.get("basic",{}).get("lon")
        item["object_type"]=payload.get("basic",{}).get("object_type")
        preview.append(item)
    return {
        "batch_id":batch["id"],"state":batch["state"],
        "filename":batch["filename"],"created_at":batch["started_at"],
        "total_rows":batch["total_rows"],"imported_rows":batch["imported_rows"],
        "rejected_rows":batch["rejected_rows"],
        "ready":report.get("ready",0),"invalid":report.get("invalid",0),
        "duplicates":report.get("duplicates",0),"source":report.get("source",""),
        "rows":preview,"offset":offset
    }


def _batch(con, batch_id):
    row=con.execute("SELECT * FROM inventory_import_batches WHERE id=?",(batch_id,)).fetchone()
    if not row:
        raise HTTPException(404,"Пакет импорта не найден")
    return dict(row)


@router.get("/template")
def template(user=Depends(admin)):
    return Response(TEMPLATE.read_bytes(),media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":'attachment; filename="VdkTree-import-template.csv"'})


@router.post("/preview",status_code=201)
async def preview(
    file: UploadFile=File(...),
    import_source: str=Form(...),
    user=Depends(admin),
):
    source=import_source.strip()
    if not re.fullmatch(r"[0-9A-Za-zА-Яа-яЁё_.\-]{2,80}",source):
        raise HTTPException(422,"Имя источника: 2–80 букв, цифр, точек, подчёркиваний или дефисов")
    raw=await file.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:
        raise HTTPException(413,"Файл больше 8 МБ")
    if not raw:
        raise HTTPException(422,"Файл пуст")
    header, rows, book=_sheet_rows(file.filename or "",raw)
    try:
        keys=[_text(x).strip().lower() for x in header]
        if not {"latitude","longitude"}.issubset(keys):
            raise HTTPException(422,"Нужны столбцы latitude и longitude")
        if len(keys)>40 or len(keys)!=len(set(keys)) or not all(keys):
            raise HTTPException(422,"В заголовках есть дубликаты/пустоты или больше 40 столбцов")
        # Unrecognized columns are errors: a misspelling must not silently lose data.
        unknown=set(keys)-TEXT_FIELDS
        if unknown:
            raise HTTPException(422,"Неизвестные столбцы: "+", ".join(sorted(unknown)[:10]))
        count=0
        ready=invalid=duplicates=0
        seen=set()
        batch_id=secrets.token_hex(16)
        now=int(time.time())
        with connect() as con:
            con.execute("""
                INSERT INTO inventory_import_batches
                  (id,created_by,filename,state,started_at)
                VALUES(?,?,?,'uploaded',?)
            """,(batch_id,user["id"],Path(file.filename or "import").name[:120],now))
            for number,values in enumerate(rows,start=2):
                if not any(_text(c) for c in values):
                    continue
                count+=1
                if count>MAX_ROWS:
                    raise HTTPException(413,"За одну загрузку допускается до 5000 строк")
                errors=[]
                payload=None
                ext=None
                state="ready"
                if len(values)!=len(keys):
                    errors.append("Количество ячеек не соответствует заголовкам")
                else:
                    row=dict(zip(keys,(_text(x) for x in values)))
                    try:
                        payload=_normalize(row,source)
                        ext=payload["external_id"]
                        if ext in seen:
                            state="duplicate"
                            errors.append("Повтор external_id внутри файла")
                        else:
                            duplicate=_existing(con,source,payload)
                            if duplicate:
                                state="duplicate"
                                errors.append(duplicate)
                        seen.add(ext)
                    except (InventoryValidationError,ValueError) as exc:
                        errors.append(str(exc))
                if errors and state=="ready":
                    state="invalid"
                if state=="ready":ready+=1
                elif state=="duplicate":duplicates+=1
                else:invalid+=1
                con.execute("""
                    INSERT INTO inventory_import_rows
                      (batch_id,row_number,row_state,external_id,payload_json,errors_json)
                    VALUES(?,?,?,?,?,?)
                """,(batch_id,number,state,ext,
                     json.dumps(payload,ensure_ascii=False) if payload else None,
                     json.dumps(errors,ensure_ascii=False)))
            if count==0:
                raise HTTPException(422,"В файле нет строк с объектами")
            report={"source":source,"ready":ready,"invalid":invalid,"duplicates":duplicates}
            con.execute("""
                UPDATE inventory_import_batches
                  SET state='validated',total_rows=?,rejected_rows=?,report_json=?
                WHERE id=?
            """,(count,invalid+duplicates,json.dumps(report,ensure_ascii=False),batch_id))
            result=_summary(_batch(con,batch_id),con)
        return result
    finally:
        if book:
            book.close()


@router.get("/{batch_id}")
def get_batch(batch_id: str, offset: int=0, user=Depends(admin)):
    if offset<0 or offset>MAX_ROWS:
        raise HTTPException(422,"Недопустимое смещение")
    with connect() as con:
        return _summary(_batch(con,batch_id),con,offset)


@router.get("/")
def list_batches(user=Depends(admin)):
    with connect() as con:
        batches=con.execute("""
            SELECT id,filename,state,total_rows,imported_rows,rejected_rows,started_at,completed_at
            FROM inventory_import_batches ORDER BY started_at DESC LIMIT 30
        """).fetchall()
    return {"batches":[dict(row) for row in batches]}


@router.post("/{batch_id}/commit")
def commit(batch_id: str, user=Depends(admin)):
    now=int(time.time())
    with connect() as con:
        batch=con.execute("SELECT * FROM inventory_import_batches WHERE id=? FOR UPDATE",
                          (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(404,"Пакет импорта не найден")
        if batch["state"]=="finished":
            raise HTTPException(409,"Этот пакет уже загружен")
        if batch["state"]!="validated":
            raise HTTPException(409,"Пакет ещё не проверен")
        report=json.loads(batch["report_json"] or "{}")
        source=report["source"]
        rows=con.execute("""
            SELECT row_number,payload_json FROM inventory_import_rows
            WHERE batch_id=? AND row_state='ready' ORDER BY row_number
        """,(batch_id,)).fetchall()
        if not rows:
            raise HTTPException(422,"Нет подходящих строк для импорта")
        con.execute("UPDATE inventory_import_batches SET state='importing' WHERE id=?",(batch_id,))
        ids=[]
        for row in rows:
            data=json.loads(row["payload_json"])
            obj=data["basic"]
            # The database may have changed since preview: refuse instead of silently duplicating.
            duplicate=_existing(con,source,data)
            if duplicate:
                raise HTTPException(409,"Сведения изменились после предварительной проверки. Создайте новую загрузку: "+duplicate)
            identifier=secrets.token_hex(16)
            con.execute("""
                INSERT INTO inventory_objects
                  (id,object_type,geometry_type,lat,lon,confirmation_status,
                   created_by,created_at,updated_at,observed_on,source_type,
                   import_batch_id,import_source,external_id,inventory_number)
                VALUES(?,?,'Point',?,?,'proposed',?,?,?,?, 'bulk_import',?,?,?,?)
            """,(identifier,obj["object_type"],obj["lat"],obj["lon"],user["id"],
                 now,now,data.get("observed_on"),batch_id,source,
                 data["external_id"],data.get("inventory_number")))
            con.execute("""
                INSERT INTO inventory_basic
                  (object_id,species_common,visible_condition,visible_damage_json,comment)
                VALUES(?,?,'unknown','[]',?)
            """,(identifier,obj.get("species_common",""),obj.get("comment","")))
            if data["expert"]:
                fields=tuple(EXPERT_FIELDS)
                _store(con,"inventory_expert",fields,identifier,data["expert"])
            con.execute("""
                INSERT INTO inventory_audit
                  (id,object_id,actor_id,action,after_json,created_at)
                VALUES(?,?,?,'bulk_import',?,?)
            """,(secrets.token_hex(16),identifier,user["id"],
                 json.dumps({"batch_id":batch_id,"row_number":row["row_number"],
                             "source":source},ensure_ascii=False),now))
            con.execute("""
                UPDATE inventory_import_rows SET row_state='imported',created_object_id=?
                WHERE batch_id=? AND row_number=?
            """,(identifier,batch_id,row["row_number"]))
            ids.append(identifier)
        con.execute("""
            UPDATE inventory_import_batches
            SET state='finished',imported_rows=?,completed_at=? WHERE id=?
        """,(len(ids),now,batch_id))
    return {"ok":True,"batch_id":batch_id,"state":"finished",
            "imported":len(ids),"skipped":batch["rejected_rows"]}
