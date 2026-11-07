"""VdkTree v1.0.3 — admin-only users, roles, suspension and audit.

First deployment also grants admin to the ALREADY REGISTERED 'savenko' login,
once. A durable marker is written even if that login does not exist yet:
future registrations cannot become administrators by taking that username.
No existing PostgreSQL data is deleted.
"""
import json
import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from auth_backend import current_session, public_user
from pgdb import connect

router = APIRouter(prefix="/api/v2/admin/users", tags=["admin-users"])
Role = Literal["user", "moderator", "admin"]
BOOTSTRAP_ID = "v1.0.3:existing-login:savenko"
BOOTSTRAP_LOGIN = "savenko"
ROLE_LOCK_ID = 103001  # serializes concurrent admin/blocked changes


def setup():
    with connect() as db:
        # All tables stay inside the dedicated vdktree PostgreSQL schema.
        db.executescript("""
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS last_login_at INTEGER;

        CREATE TABLE IF NOT EXISTS admin_user_audit (
            id TEXT PRIMARY KEY,
            actor_id TEXT REFERENCES users(id),
            target_id TEXT NOT NULL REFERENCES users(id),
            action TEXT NOT NULL,
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS admin_user_audit_target_idx
            ON admin_user_audit(target_id,created_at DESC);

        CREATE TABLE IF NOT EXISTS admin_bootstrap_history (
            marker TEXT PRIMARY KEY,
            target_id TEXT REFERENCES users(id),
            outcome TEXT NOT NULL,
            executed_at INTEGER NOT NULL
        );
        """)
        # Inserting marker under an exclusive lock makes this a one-time
        # migration, even if multiple BotHost worker processes start together.
        db.execute("SELECT pg_advisory_xact_lock(?)", (ROLE_LOCK_ID,))
        if db.execute(
            "SELECT 1 FROM admin_bootstrap_history WHERE marker=?", (BOOTSTRAP_ID,)
        ).fetchone():
            return
        now = int(time.time())
        target = db.execute(
            "SELECT id,login,role,is_blocked FROM users WHERE lower(login)=? FOR UPDATE",
            (BOOTSTRAP_LOGIN,),
        ).fetchone()
        target_id = target["id"] if target else None
        if target and not target["is_blocked"]:
            if target["role"] != "admin":
                db.execute("UPDATE users SET role='admin' WHERE id=?", (target_id,))
                db.execute("""
                    INSERT INTO admin_user_audit
                      (id,actor_id,target_id,action,before_json,after_json,reason,created_at)
                    VALUES (?,NULL,?,'bootstrap_admin',?,?,?,?)
                """, (
                    secrets.token_hex(16), target_id,
                    json.dumps({"role":target["role"],"is_blocked":target["is_blocked"]}),
                    json.dumps({"role":"admin","is_blocked":False}),
                    "Единовременное назначение существующего savenko по распоряжению владельца",
                    now,
                ))
                outcome = "promoted"
            else:
                outcome = "already_admin"
        else:
            # Permanently mark as checked, even if no savenko was registered.
            # A later account using this login cannot inherit elevated rights.
            outcome = "blocked" if target else "not_found"
        db.execute("""
            INSERT INTO admin_bootstrap_history(marker,target_id,outcome,executed_at)
            VALUES(?,?,?,?)
        """, (BOOTSTRAP_ID,target_id,outcome,now))


setup()


def admin_only(user=Depends(current_session)):
    if user["role"] != "admin":
        raise HTTPException(403,"Управление пользователями доступно только администратору")
    return user


def _serialize(row):
    return {
        "id":row["id"],
        "max_id":row["max_id"],
        "login":row["login"],
        "display_name":row["display_name"],
        "role":row["role"],
        "is_blocked":bool(row["is_blocked"]),
        "created_at":row["created_at"],
        "last_login_at":row["last_login_at"],
        "plants_count":row.get("plants_count",0),
        "notes_count":row.get("notes_count",0),
    }


def _user(db,user_id,lock=False):
    suffix = " FOR UPDATE" if lock else ""
    row=db.execute("SELECT * FROM users WHERE id=?"+suffix, (user_id,)).fetchone()
    if not row:
        raise HTTPException(404,"Пользователь не найден")
    return row


def _audit(db,actor_id,target_id,action,before,after,reason):
    db.execute("""
        INSERT INTO admin_user_audit
          (id,actor_id,target_id,action,before_json,after_json,reason,created_at)
        VALUES(?,?,?,?,?,?,?,?)
    """, (secrets.token_hex(16),actor_id,target_id,action,
          json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False),
          reason.strip(),int(time.time())))


def _protected(db, actor_id, current_target, new_role, new_blocked):
    if actor_id == current_target["id"]:
        raise HTTPException(403,"Нельзя менять собственные права или блокировать себя")
    if current_target["role"]=="admin" and not current_target["is_blocked"]:
        if new_role!="admin" or new_blocked:
            remaining=db.execute("""
                SELECT COUNT(*) FROM users
                WHERE id<>? AND role='admin' AND is_blocked=FALSE
            """,(current_target["id"],)).fetchone()[0]
            if remaining == 0:
                raise HTTPException(409,"Нельзя отключить или понизить последнего администратора")


@router.get("")
def list_users(
    q: str=Query(default="", max_length=100),
    role: Literal["all","user","moderator","admin"]="all",
    status: Literal["all","active","blocked"]="all",
    limit: int=Query(default=30, ge=1, le=100),
    offset: int=Query(default=0, ge=0, le=1000000),
    admin=Depends(admin_only),
):
    where=["1=1"]
    params=[]
    query=q.strip()
    if query:
        # Escape SQL LIKE metacharacters; all values remain bound parameters.
        escaped=query.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
        where.append("""(lower(COALESCE(u.login,'')) LIKE lower(?) ESCAPE '\\'
                  OR lower(u.display_name) LIKE lower(?) ESCAPE '\\'
                  OR u.max_id LIKE ? ESCAPE '\\')""")
        params.extend(["%"+escaped+"%"]*3)
    if role!="all":
        where.append("u.role=?")
        params.append(role)
    if status!="all":
        where.append("u.is_blocked=?")
        params.append(status=="blocked")
    predicate=" AND ".join(where)
    with connect() as db:
        total=db.execute("SELECT COUNT(*) FROM users u WHERE "+predicate,params).fetchone()[0]
        rows=db.execute("""
            SELECT u.id,u.max_id,u.login,u.display_name,u.role,
                   u.is_blocked,u.created_at,u.last_login_at,
                   (SELECT COUNT(*) FROM inventory_objects o
                      WHERE o.created_by=u.id) AS plants_count,
                   (SELECT COUNT(*) FROM inventory_clarifications n
                      WHERE n.author_id=u.id) AS notes_count
            FROM users u WHERE """+predicate+"""
            ORDER BY u.created_at DESC,u.id DESC
            LIMIT ? OFFSET ?
        """, (*params,limit,offset)).fetchall()
        counts=db.execute("""
            SELECT COUNT(*) AS total,
              COUNT(*) FILTER (WHERE role='admin' AND NOT is_blocked) AS admins,
              COUNT(*) FILTER (WHERE role='moderator' AND NOT is_blocked) AS moderators,
              COUNT(*) FILTER (WHERE is_blocked) AS blocked
            FROM users
        """).fetchone()
    return {"users":[_serialize(row) for row in rows],
            "total":total,"offset":offset,"limit":limit,
            "counts":dict(counts)}


@router.get("/{user_id}")
def detail(user_id:str,admin=Depends(admin_only)):
    with connect() as db:
        row=_user(db,user_id)
        stats=db.execute("""
            SELECT
              (SELECT COUNT(*) FROM inventory_objects WHERE created_by=?) AS plants_count,
              (SELECT COUNT(*) FROM inventory_clarifications WHERE author_id=?) AS notes_count,
              (SELECT COUNT(*) FROM sessions WHERE user_id=? AND expires_at>?) AS sessions_count
        """,(user_id,user_id,user_id,int(time.time()))).fetchone()
    return {"user":_serialize({**dict(row),**dict(stats)}),
            "sessions_count":stats["sessions_count"]}


@router.get("/{user_id}/history")
def history(user_id:str,limit:int=Query(default=30,ge=1,le=100),
            admin=Depends(admin_only)):
    with connect() as db:
        _user(db,user_id)
        rows=db.execute("""
            SELECT e.id,e.action,e.before_json,e.after_json,e.reason,e.created_at,
                   a.login AS actor_login,a.display_name AS actor_name
            FROM admin_user_audit e
            LEFT JOIN users a ON a.id=e.actor_id
            WHERE e.target_id=?
            ORDER BY e.created_at DESC,e.id DESC LIMIT ?
        """,(user_id,limit)).fetchall()
    return {"events":[{
        "id":r["id"],"action":r["action"],
        "before":json.loads(r["before_json"]),
        "after":json.loads(r["after_json"]),
        "reason":r["reason"],"created_at":r["created_at"],
        "actor_login":r["actor_login"],"actor_name":r["actor_name"],
    } for r in rows]}


class UpdateUser(BaseModel):
    model_config=ConfigDict(extra="forbid")
    role: Role | None = None
    is_blocked: bool | None = None
    reason: str = Field(min_length=3,max_length=500)


@router.patch("/{user_id}")
def update_user(user_id:str, body:UpdateUser,admin=Depends(admin_only)):
    if body.role is None and body.is_blocked is None:
        raise HTTPException(422,"Нужно выбрать роль или состояние доступа")
    reason=body.reason.strip()
    if len(reason)<3:
        raise HTTPException(422,"Укажите причину изменения (от 3 символов)")
    with connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(?)",(ROLE_LOCK_ID,))
        target=_user(db,user_id,lock=True)
        role=body.role if body.role is not None else target["role"]
        blocked=body.is_blocked if body.is_blocked is not None else target["is_blocked"]
        if role==target["role"] and blocked==target["is_blocked"]:
            raise HTTPException(409,"Изменений нет")
        _protected(db,admin["id"],target,role,blocked)
        db.execute("UPDATE users SET role=?,is_blocked=? WHERE id=?",
                   (role,blocked,user_id))
        before={"role":target["role"],"is_blocked":target["is_blocked"]}
        after={"role":role,"is_blocked":blocked}
        _audit(db,admin["id"],user_id,"role_and_access",before,after,reason)
        if blocked:
            db.execute("DELETE FROM sessions WHERE user_id=?",(user_id,))
        updated=_user(db,user_id)
    return {"ok":True,"user":_serialize(updated)}


class Reason(BaseModel):
    reason: str=Field(min_length=3,max_length=500)


@router.post("/{user_id}/revoke-sessions")
def revoke_sessions(user_id:str,body:Reason,admin=Depends(admin_only)):
    reason=body.reason.strip()
    if len(reason)<3:raise HTTPException(422,"Укажите причину")
    if user_id==admin["id"]:
        raise HTTPException(403,"Используйте обычную кнопку выхода для своей сессии")
    with connect() as db:
        _user(db,user_id)
        count=db.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?",(user_id,)).fetchone()[0]
        db.execute("DELETE FROM sessions WHERE user_id=?",(user_id,))
        _audit(db,admin["id"],user_id,"revoke_sessions",
               {"sessions":count},{"sessions":0},reason)
    return {"ok":True,"revoked":count}


@router.post("/{user_id}/reset-credentials")
def reset_credentials(user_id:str,body:Reason,admin=Depends(admin_only)):
    reason=body.reason.strip()
    if len(reason)<3:raise HTTPException(422,"Укажите причину")
    if user_id==admin["id"]:
        raise HTTPException(403,"Нельзя сбрасывать свои учётные данные из админки")
    with connect() as db:
        target=_user(db,user_id,lock=True)
        db.execute("UPDATE users SET login=NULL,password_hash=NULL WHERE id=?",(user_id,))
        db.execute("DELETE FROM sessions WHERE user_id=?",(user_id,))
        _audit(db,admin["id"],user_id,"reset_credentials",
               {"had_login":bool(target["login"]),"had_password":bool(target["password_hash"])},
               {"had_login":False,"had_password":False},
               reason)
    return {"ok":True,"message":"Логин и пароль сброшены; участник должен заново войти через MAX"}
