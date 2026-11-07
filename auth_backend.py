"""VdkTree v1.0.2: PostgreSQL-backed MAX identity and password sign-in."""
import hashlib
import hmac
import json
import os
import re
import secrets
import psycopg
import time
from pgdb import connect
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)
SESSION_LIFETIME = 7 * 24 * 3600
MAX_LOGIN_MAX_AGE = 15 * 60
LOGIN_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{4,32}$")


def setup():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            max_id TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            login TEXT,
            password_hash TEXT,
            role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','moderator','admin')),
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL,
            via_max INTEGER NOT NULL DEFAULT 0
        );
        CREATE UNIQUE INDEX IF NOT EXISTS users_login_lower_idx ON users (lower(login));
        CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
        CREATE TABLE IF NOT EXISTS login_limits (
            key_hash TEXT PRIMARY KEY,
            failures INTEGER NOT NULL,
            reset_at INTEGER NOT NULL
        );
        """)
setup()


def verify_max_init_data(init_data: str) -> dict:
    token = os.environ.get("MAX_BOT_TOKEN", "")
    if not token:
        raise HTTPException(503, "MAX_BOT_TOKEN не настроен")
    if not init_data or len(init_data) > 8192:
        raise HTTPException(401, "Некорректные данные MAX")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True, max_num_fields=40)
        params = dict(pairs)
        if len(pairs) != len(params) or "hash" not in params or "user" not in params:
            raise ValueError("Missing or duplicate fields")
        given = params.pop("hash")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", given):
            raise ValueError("Invalid signature format")
        check_string = "\n".join(f"{key}={params[key]}" for key in sorted(params))
        secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
        expected = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, given.lower()):
            raise ValueError("Bad signature")
        auth_date = int(params["auth_date"])
        if abs(int(time.time()) - auth_date) > MAX_LOGIN_MAX_AGE:
            raise ValueError("Expired init data")
        user = json.loads(params["user"])
        uid = user.get("id")
        if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0:
            raise ValueError("Invalid MAX user ID")
        return {"max_id": str(uid), "display_name": (
            str(user.get("first_name") or "") + " " + str(user.get("last_name") or "")
        ).strip()[:120] or ("MAX " + str(uid))}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(401, "Не удалось подтвердить вход через MAX")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    result = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + "$" + result.hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt, digest = encoded.split("$", 1)
        candidate = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
        return hmac.compare_digest(candidate, bytes.fromhex(digest))
    except (TypeError, ValueError):
        return False


def public_user(row):
    return {
        "id": row["id"], "display_name": row["display_name"], "role": row["role"],
        "login": row["login"], "has_password": bool(row["password_hash"])
    }


def create_session(db, user_id: str, via_max: bool):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    db.execute("INSERT INTO sessions(token_hash,user_id,expires_at,via_max) VALUES(?,?,?,?)",
               (hashlib.sha256(token.encode()).hexdigest(), user_id, now + SESSION_LIFETIME, int(via_max)))
    return token


class MaxLogin(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)


class PasswordLogin(BaseModel):
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class NewCredentials(BaseModel):
    login: str = Field(min_length=4, max_length=32)
    password: str = Field(min_length=8, max_length=128)


def current_session(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Требуется вход")
    token = credentials.credentials
    if len(token) > 160:
        raise HTTPException(401, "Недействительная сессия")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with connect() as db:
        row = db.execute("""
            SELECT u.*, s.via_max FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.expires_at>?
        """, (token_hash, int(time.time()))).fetchone()
    if not row:
        raise HTTPException(401, "Сессия истекла или недействительна")
    return dict(row)


@router.post("/max")
def max_login(payload: MaxLogin):
    max_user = verify_max_init_data(payload.init_data)
    with connect() as db:
        user = db.execute("SELECT * FROM users WHERE max_id=?", (max_user["max_id"],)).fetchone()
        if not user:
            db.execute("INSERT INTO users(id,max_id,display_name,created_at) VALUES(?,?,?,?) ON CONFLICT (max_id) DO NOTHING",
                       (secrets.token_hex(16), max_user["max_id"], max_user["display_name"], int(time.time())))
        else:
            db.execute("UPDATE users SET display_name=? WHERE id=?",
                       (max_user["display_name"], user["id"]))
        user = db.execute("SELECT * FROM users WHERE max_id=?", (max_user["max_id"],)).fetchone()
        session = create_session(db, user["id"], True)
    return {"token": session, "user": public_user(user)}


@router.post("/password")
def password_login(payload: PasswordLogin, request: Request):
    login = payload.login.lower().strip()
    source = (request.client.host if request.client else "unknown") + "|" + login
    key = hashlib.sha256(source.encode()).hexdigest()
    now = int(time.time())
    with connect() as db:
        limit = db.execute("SELECT failures,reset_at FROM login_limits WHERE key_hash=?", (key,)).fetchone()
        if limit and limit["reset_at"] > now and limit["failures"] >= 5:
            raise HTTPException(429, "Слишком много попыток. Попробуйте позже.")
        user = db.execute("SELECT * FROM users WHERE lower(login)=?", (login,)).fetchone()
        if not user or not user["password_hash"] or not verify_password(payload.password, user["password_hash"]):
            if limit and limit["reset_at"] > now:
                db.execute("UPDATE login_limits SET failures=failures+1 WHERE key_hash=?", (key,))
            else:
                db.execute("INSERT INTO login_limits(key_hash,failures,reset_at) VALUES(?,?,?) ON CONFLICT(key_hash) DO UPDATE SET failures=excluded.failures,reset_at=excluded.reset_at",
                           (key, 1, now + 600))
            db.commit()  # Persist rate limit even though the request ends with HTTP 401.
            raise HTTPException(401, "Неправильный логин или пароль")
        db.execute("DELETE FROM login_limits WHERE key_hash=?", (key,))
        session = create_session(db, user["id"], False)
    return {"token": session, "user": public_user(user)}


@router.get("/me")
def me(user=Depends(current_session)):
    return {"user": public_user(user)}


@router.post("/credentials")
def set_credentials(payload: NewCredentials, user=Depends(current_session)):
    if not user["via_max"]:
        raise HTTPException(403, "Создать логин и пароль можно только после входа через MAX")
    if not LOGIN_PATTERN.fullmatch(payload.login):
        raise HTTPException(400, "Логин: 4–32 латинские буквы, цифры, _ или -")
    if len(payload.password.encode("utf-8")) > 256:
        raise HTTPException(400, "Слишком длинный пароль")
    pwd = hash_password(payload.password)
    try:
        with connect() as db:
            result = db.execute("""
                UPDATE users SET login=?, password_hash=?
                WHERE id=? AND login IS NULL AND password_hash IS NULL
            """, (payload.login.lower(), pwd, user["id"]))
            if result.rowcount == 0:
                raise HTTPException(409, "Логин и пароль уже созданы. Для изменения обратитесь к администратору.")
            row = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "Этот логин занят")
    return {"user": public_user(row)}


@router.post("/logout")
def logout(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials and credentials.scheme.lower() == "bearer":
        with connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?",
                       (hashlib.sha256(credentials.credentials.encode()).hexdigest(),))
    return {"ok": True}
