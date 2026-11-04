import os, sqlite3, uuid, time
from pathlib import Path
from contextlib import contextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR", str(BASE / "data")))
DATA.mkdir(parents=True, exist_ok=True)
PHOTOS = DATA / "photos"
PHOTOS.mkdir(exist_ok=True)
DB = DATA / "trees.sqlite3"
app = FastAPI(title="VdkTree", version="0.1.0")

@contextmanager
def db():
    con = sqlite3.connect(DB, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()

with db() as con:
    con.execute("""CREATE TABLE IF NOT EXISTS trees (
        id TEXT PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL,
        species TEXT NOT NULL, condition TEXT NOT NULL,
        height REAL, diameter REAL, comment TEXT NOT NULL DEFAULT '',
        photo TEXT, created_at INTEGER NOT NULL)""")

app.mount("/photos", StaticFiles(directory=PHOTOS), name="photos")

@app.get("/")
def home():
    return FileResponse(BASE / "index.html")

@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.1.0"}

@app.get("/api/trees")
def trees(min_lat: float = 42, max_lat: float = 44, min_lon: float = 130, max_lon: float = 134):
    if not (-90 <= min_lat <= max_lat <= 90 and -180 <= min_lon <= max_lon <= 180):
        raise HTTPException(400, "Invalid bounds")
    with db() as con:
        rows = con.execute("SELECT * FROM trees WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? ORDER BY created_at DESC LIMIT 5000", (min_lat,max_lat,min_lon,max_lon)).fetchall()
        return [dict(row) for row in rows]

@app.post("/api/trees", status_code=201)
async def add_tree(lat: float = Form(...), lon: float = Form(...), species: str = Form(...), condition: str = Form(...), height: str = Form(""), diameter: str = Form(""), comment: str = Form(""), photo: UploadFile | None = File(None)):
    if not (42 <= lat <= 44 and 130 <= lon <= 134):
        raise HTTPException(400, "Координаты за пределами региона")
    if condition not in ("healthy", "damaged", "dead") or not (1 <= len(species.strip()) <= 80) or len(comment) > 1000:
        raise HTTPException(400, "Некорректные данные")
    try:
        h = float(height) if height.strip() else None
        d = float(diameter) if diameter.strip() else None
    except ValueError:
        raise HTTPException(400, "Высота и диаметр должны быть числами")
    if (h is not None and not 0 < h <= 100) or (d is not None and not 0 < d <= 1000):
        raise HTTPException(400, "Некорректные размеры")
    image_path = None
    if photo and photo.filename:
        # Check actual file signature, not client-provided MIME type.
        blob = await photo.read(5 * 1024 * 1024 + 1)
        if len(blob) > 5 * 1024 * 1024:
            raise HTTPException(413, "Максимум 5 МБ")
        ext = ".jpg" if blob.startswith(b"\\xff\\xd8\\xff") else ".png" if blob.startswith(b"\\x89PNG\\r\\n\\x1a\\n") else ".webp" if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP" else None
        if not ext:
            raise HTTPException(400, "Только JPG, PNG, WebP")
        name = uuid.uuid4().hex + ext
        (PHOTOS / name).write_bytes(blob)
        image_path = "/photos/" + name
    record = dict(id=uuid.uuid4().hex, lat=lat, lon=lon, species=species.strip(), condition=condition, height=h, diameter=d, comment=comment.strip(), photo=image_path, created_at=int(time.time()))
    try:
        with db() as con:
            con.execute("INSERT INTO trees (id,lat,lon,species,condition,height,diameter,comment,photo,created_at) VALUES (:id,:lat,:lon,:species,:condition,:height,:diameter,:comment,:photo,:created_at)", record)
    except Exception:
        if image_path:
            (PHOTOS / image_path.split("/")[-1]).unlink(missing_ok=True)
        raise
    return record
