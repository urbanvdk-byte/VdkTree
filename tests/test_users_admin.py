"""VdkTree v1.0.3 — admin users RBAC, account restrictions and audit regressions."""
import hashlib
import hmac
import json
import os
import secrets
import time
import unittest
from urllib.parse import urlencode

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import app
from pgdb import connect
from users_admin_api import BOOTSTRAP_ID, _protected


def signed_max(max_id):
    fields = {
        "auth_date":str(int(time.time())),
        "user":json.dumps({"id":max_id,"first_name":"Участник"},
                          ensure_ascii=False,separators=(",",":"))
    }
    key=hmac.new(b"WebAppData",os.environ["MAX_BOT_TOKEN"].encode(),
                 hashlib.sha256).digest()
    body="\n".join(k+"="+v for k,v in sorted(fields.items()))
    fields["hash"]=hmac.new(key,body.encode(),hashlib.sha256).hexdigest()
    return urlencode(fields)


class UsersAdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(app)

    def login(self,role="user"):
        max_id=secrets.randbelow(2_000_000_000)+100_000
        response=self.client.post("/api/auth/max",
                                  json={"init_data":signed_max(max_id)})
        self.assertEqual(response.status_code,200,response.text)
        u=response.json()["user"]
        if role!="user":
            with connect() as db:
                db.execute("UPDATE users SET role=? WHERE id=?",(role,u["id"]))
        return ({"Authorization":"Bearer "+response.json()["token"]},
                u,signed_max(max_id))

    def test_savenko_one_time_bootstrap_and_public_schema_untouched(self):
        # GitHub Actions seeds this account BEFORE app import on a fresh DB.
        with connect() as db:
            marker=db.execute("""
                SELECT target_id,outcome FROM admin_bootstrap_history WHERE marker=?
            """,(BOOTSTRAP_ID,)).fetchone()
            self.assertIsNotNone(marker)
            self.assertEqual(marker["outcome"],"promoted")
            user=db.execute("SELECT id,role FROM users WHERE lower(login)='savenko'").fetchone()
            self.assertIsNotNone(user)
            self.assertEqual(user["role"],"admin")
            self.assertEqual(marker["target_id"],user["id"])
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM admin_user_audit WHERE target_id=? AND action='bootstrap_admin'",
                (user["id"],)).fetchone()[0],1)
        with connect() as db:
            # setup must NOT re-promote if an admin later demotes this account.
            from users_admin_api import setup
            setup()
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM admin_bootstrap_history WHERE marker=?",
                (BOOTSTRAP_ID,)).fetchone()[0],1)

    def test_permissions_listing_search_and_details(self):
        admin,admin_user,_=self.login("admin")
        user,ordinary,_=self.login()
        moderator,_,_=self.login("moderator")
        endpoint="/api/v2/admin/users"
        self.assertEqual(self.client.get(endpoint).status_code,401)
        self.assertEqual(self.client.get(endpoint,headers=user).status_code,403)
        self.assertEqual(self.client.get(endpoint,headers=moderator).status_code,403)
        listing=self.client.get(endpoint,headers=admin)
        self.assertEqual(listing.status_code,200,listing.text)
        self.assertGreaterEqual(listing.json()["counts"]["admins"],1)
        self.assertTrue(any(x["id"]==admin_user["id"] for x in listing.json()["users"]))
        self.assertTrue(all("password_hash" not in x for x in listing.json()["users"]))
        q=self.client.get(endpoint,headers=admin,params={"q":str(ordinary["id"]),"limit":101})
        self.assertEqual(q.status_code,422)
        # Search by MAX ID, name or unique case-insensitive login.
        with connect() as db:
            max_id=db.execute("SELECT max_id FROM users WHERE id=?",
                              (ordinary["id"],)).fetchone()["max_id"]
        search=self.client.get(endpoint,headers=admin,params={"q":max_id})
        self.assertEqual(search.status_code,200,search.text)
        self.assertTrue(any(x["id"]==ordinary["id"] for x in search.json()["users"]))
        detail=self.client.get(endpoint+"/"+ordinary["id"],headers=admin)
        self.assertEqual(detail.status_code,200,detail.text)
        self.assertEqual(detail.json()["user"]["id"],ordinary["id"])
        self.assertIn("sessions_count",detail.json())
        self.assertEqual(self.client.get(endpoint+"/not_existing_id",headers=admin).status_code,404)
        self.assertEqual(self.client.get(endpoint,headers=admin,
            params={"role":"unknown"}).status_code,422)

    def test_role_changes_are_immediate_and_audited(self):
        admin,admin_user,_=self.login("admin")
        target,target_user,_=self.login()
        url="/api/v2/admin/users/"+target_user["id"]
        self.assertEqual(self.client.patch(url,headers=target,
            json={"role":"admin","reason":"Self promotion"}).status_code,403)
        self.assertEqual(self.client.patch(url,headers=admin,
            json={"role":"superadmin","reason":"Bad"}).status_code,422)
        self.assertEqual(self.client.patch(url,headers=admin,
            json={"role":"moderator","reason":"  "}).status_code,422)
        self.assertEqual(self.client.patch(url,headers=admin,
            json={"reason":"No role given"}).status_code,422)
        updated=self.client.patch(url,headers=admin,
            json={"role":"moderator","reason":"Помощник по модерации"})
        self.assertEqual(updated.status_code,200,updated.text)
        self.assertEqual(updated.json()["user"]["role"],"moderator")
        # Existing bearer session now has moderator rights (DB consulted every request).
        self.assertEqual(self.client.get("/api/v2/moderation/queue",
            headers=target).status_code,200)
        self.assertEqual(self.client.get(url+"/history",headers=admin).status_code,200)
        history=self.client.get(url+"/history",headers=admin).json()["events"]
        self.assertTrue(any(x["action"]=="role_and_access" and
          x["after"]["role"]=="moderator" for x in history))
        self.assertEqual(self.client.patch(url,headers=admin,
            json={"role":"moderator","reason":"Nothing"}).status_code,409)
        downgraded=self.client.patch(url,headers=admin,
            json={"role":"user","reason":"Срок модерации завершён"})
        self.assertEqual(downgraded.status_code,200,downgraded.text)
        self.assertEqual(self.client.get("/api/v2/moderation/queue",
            headers=target).status_code,403)

    def test_block_prevents_max_password_and_existing_sessions(self):
        admin,_,_=self.login("admin")
        target,u,proof=self.login()
        url="/api/v2/admin/users/"+u["id"]
        blocked=self.client.patch(url,headers=admin,
            json={"is_blocked":True,"reason":"Нарушение правил сообщества"})
        self.assertEqual(blocked.status_code,200,blocked.text)
        self.assertTrue(blocked.json()["user"]["is_blocked"])
        self.assertEqual(self.client.get("/api/auth/me",headers=target).status_code,401)
        self.assertEqual(self.client.post("/api/auth/max",
            json={"init_data":proof}).status_code,403)
        self.assertEqual(self.client.patch(url,headers=admin,
            json={"is_blocked":True,"reason":"same"}).status_code,409)
        unblocked=self.client.patch(url,headers=admin,
            json={"is_blocked":False,"reason":"Проверка завершена"})
        self.assertEqual(unblocked.status_code,200,unblocked.text)
        self.assertFalse(unblocked.json()["user"]["is_blocked"])
        login=self.client.post("/api/auth/max",json={"init_data":proof})
        self.assertEqual(login.status_code,200,login.text)
        audit=self.client.get(url+"/history",headers=admin).json()["events"]
        self.assertEqual(sum(x["action"]=="role_and_access" for x in audit),2)

    def test_revoke_sessions_and_reset_credentials(self):
        admin,_,_=self.login("admin")
        user,account,_=self.login()
        url="/api/v2/admin/users/"+account["id"]
        self.assertEqual(self.client.post(url+"/revoke-sessions",headers=user,
            json={"reason":"not allowed"}).status_code,403)
        revoked=self.client.post(url+"/revoke-sessions",headers=admin,
            json={"reason":"Приостановка доступа"})
        self.assertEqual(revoked.status_code,200,revoked.text)
        self.assertGreaterEqual(revoked.json()["revoked"],1)
        self.assertEqual(self.client.get("/api/auth/me",headers=user).status_code,401)
        user,account2,proof=self.login()
        name="u_"+secrets.token_hex(6)
        self.assertEqual(self.client.post("/api/auth/credentials",headers=user,
            json={"login":name,"password":"qwerty123"}).status_code,200)
        url2="/api/v2/admin/users/"+account2["id"]
        wiped=self.client.post(url2+"/reset-credentials",headers=admin,
            json={"reason":"Восстановление через MAX"})
        self.assertEqual(wiped.status_code,200,wiped.text)
        with connect() as db:
            row=db.execute("SELECT login,password_hash FROM users WHERE id=?",
                (account2["id"],)).fetchone()
        self.assertIsNone(row["login"])
        self.assertIsNone(row["password_hash"])
        self.assertEqual(self.client.get("/api/auth/me",headers=user).status_code,401)
        self.assertEqual(self.client.post("/api/auth/max",
            json={"init_data":proof}).status_code,200)

    def test_admin_cannot_modify_self_or_last_admin(self):
        admin,actor,_=self.login("admin")
        url="/api/v2/admin/users/"+actor["id"]
        self.assertEqual(self.client.patch(url,headers=admin,
            json={"role":"user","reason":"Self downgrade"}).status_code,403)
        self.assertEqual(self.client.patch(url,headers=admin,
            json={"is_blocked":True,"reason":"Self block"}).status_code,403)
        self.assertEqual(self.client.post(url+"/reset-credentials",headers=admin,
            json={"reason":"Self reset"}).status_code,403)
        class ZeroAdminDB:
            def execute(self,*args):
                class R:
                    def fetchone(self):
                        return [0]
                return R()
        mock={"id":"last-admin","role":"admin","is_blocked":False}
        with self.assertRaises(HTTPException) as ex:
            _protected(ZeroAdminDB(),"actor",mock,"user",False)
        self.assertEqual(ex.exception.status_code,409)
        with self.assertRaises(HTTPException):
            _protected(ZeroAdminDB(),"actor",mock,"admin",True)


if __name__=="__main__":
    unittest.main()
