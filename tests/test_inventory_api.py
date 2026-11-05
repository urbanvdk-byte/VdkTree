"""v0.6.0 — shared inventory API permissions, notes, polygon, photo and legacy safety."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import unittest
from urllib.parse import urlencode

os.environ.setdefault("MAX_BOT_TOKEN", "test-bot-token-never-real")
from fastapi.testclient import TestClient
from app import app, DB as LEGACY_DB
from auth_backend import connect as auth_connect
from inventory_api import connect as inventory_connect, migrate_legacy


def signed_max(max_id):
    data = {"auth_date": str(int(time.time())), "user": json.dumps({
        "id":max_id, "first_name":"Испытатель"},ensure_ascii=False,separators=(",",":"))}
    secret = hmac.new(b"WebAppData",os.environ["MAX_BOT_TOKEN"].encode(),hashlib.sha256).digest()
    sign = "\n".join(k+"="+v for k,v in sorted(data.items()))
    data["hash"] = hmac.new(secret,sign.encode(),hashlib.sha256).hexdigest()
    return urlencode(data)


class SharedInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def login(self,role="user"):
        max_id = secrets.randbelow(1000000000)+100000
        response=self.client.post("/api/auth/max",json={"init_data":signed_max(max_id)})
        self.assertEqual(response.status_code,200,response.text)
        user=response.json()["user"]
        if role!="user":
            with auth_connect() as db:
                db.execute("UPDATE users SET role=? WHERE id=?",(role,user["id"]))
        return ({"Authorization":"Bearer "+response.json()["token"]},user)

    def create_tree(self,auth,kind="tree"):
        r=self.client.post("/api/v2/objects",headers=auth,json={
            "object_type":kind,"lat":43.115,"lon":131.885,
            "species_common":"Дуб монгольский","visible_condition":"damaged",
            "comment":"Растет во дворе",
            "approx_height_band":"5_10m"
        })
        self.assertEqual(r.status_code,201,r.text)
        return r.json()

    def test_public_read_and_anonymous_write_forbidden(self):
        self.assertEqual(self.client.get("/api/v2/objects").status_code,200)
        self.assertEqual(self.client.post("/api/v2/objects",json={
            "object_type":"tree","lat":43.115,"lon":131.88}).status_code,401)
        user,_=self.login()
        obj=self.create_tree(user)
        public=self.client.get("/api/v2/objects/"+obj["id"])
        self.assertEqual(public.status_code,200,public.text)
        self.assertEqual(public.json()["confirmation_status"],"proposed")
        self.assertEqual(public.json()["approx_height_band"],"5_10m")
        self.assertTrue(any(x["id"]==obj["id"] for x in self.client.get("/api/v2/objects").json()["objects"]))

    def test_shrub_blue_and_edit_seven_day_permissions(self):
        first,u1=self.login()
        other,_=self.login()
        shrub=self.create_tree(first,"shrub")
        self.assertEqual(shrub["object_type"],"shrub")
        self.assertEqual(self.client.patch("/api/v2/objects/"+shrub["id"],headers=other,
            json={"species_common":"Неизвестен"}).status_code,403)
        patch=self.client.patch("/api/v2/objects/"+shrub["id"],headers=first,
            json={"species_common":"Сирень", "visible_condition":"looks_healthy"})
        self.assertEqual(patch.status_code,200,patch.text)
        with inventory_connect() as db:
            db.execute("UPDATE inventory_objects SET created_at=? WHERE id=?",
                       (int(time.time())-8*24*3600,shrub["id"]))
        self.assertEqual(self.client.patch("/api/v2/objects/"+shrub["id"],headers=first,
            json={"species_common":"Сирень"}).status_code,403)

    def test_moderation_and_independent_red_note(self):
        owner,_=self.login()
        moderator,_=self.login("moderator")
        admin,_=self.login("admin")
        obj=self.create_tree(owner)
        url="/api/v2/objects/"+obj["id"]
        self.assertEqual(self.client.post(url+"/confirm",headers=owner).status_code,403)
        self.assertEqual(self.client.patch(url,headers=moderator,json={"species_common":"Клён"}).status_code,200)
        self.assertEqual(self.client.post(url+"/confirm",headers=moderator).status_code,200)
        self.assertEqual(self.client.patch(url,headers=moderator,json={"species_common":"Клён"}).status_code,403)
        self.assertEqual(self.client.patch(url,headers=owner,json={"species_common":"Клён"}).status_code,403)
        note=self.client.post(url+"/notes",headers=owner,json={"message":"Спустя три года дерево усохло"})
        self.assertEqual(note.status_code,201,note.text)
        checked=self.client.get(url).json()
        self.assertTrue(checked["needs_clarification"])
        self.assertEqual(checked["confirmation_status"],"confirmed")
        self.assertEqual(self.client.post(url+"/notes/"+note.json()["id"]+"/close",headers=owner,
            json={"resolution":"Проверено"}).status_code,403)
        finished=self.client.post(url+"/notes/"+note.json()["id"]+"/close",headers=moderator,
            json={"resolution":"Замечание проверено, осмотр завершён"})
        self.assertEqual(finished.status_code,200,finished.text)
        self.assertFalse(self.client.get(url).json()["needs_clarification"])
        self.assertEqual(self.client.patch(url,headers=admin,
            json={"comment":"Проверено администратором"}).status_code,200)
        self.assertEqual(self.client.get(url).json()["confirmation_status"],"confirmed")

    def test_polygon_only_staff_and_photo_upload(self):
        person,_=self.login()
        moderator,moderator_user=self.login("moderator")
        other_moderator,_=self.login("moderator")
        admin,_=self.login("admin")
        polygon={"type":"Polygon","coordinates":[[
            [131.88,43.11],[131.881,43.11],[131.881,43.111],[131.88,43.11]
        ]]}
        payload={"object_type":"lawn","geometry":polygon,"comment":"Газон"}
        self.assertEqual(self.client.post("/api/v2/objects",headers=person,json=payload).status_code,403)
        r=self.client.post("/api/v2/objects",headers=moderator,json=payload)
        self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(r.json()["geometry"]["type"],"Polygon")
        area_id=r.json()["id"]
        area_url="/api/v2/objects/"+area_id
        self.assertEqual(self.client.patch(area_url,headers=moderator,
            json={"comment":"Уточнённая площадь"}).status_code,200)
        self.assertEqual(self.client.patch(area_url,headers=other_moderator,
            json={"comment":"Чужая площадь"}).status_code,403)
        self.assertEqual(self.client.patch(area_url,headers=person,
            json={"comment":"Чужая площадь"}).status_code,403)
        self.assertEqual(self.client.patch(area_url,headers=admin,
            json={"comment":"Исправлено администратором"}).status_code,200)
        self.assertEqual(self.client.post("/api/v2/objects",headers=person,json={
            "object_type":"lawn","lat":43.11,"lon":131.88}).status_code,403)
        tree=self.create_tree(person)
        png=bytes.fromhex("89504e470d0a1a0a")+b"little-image-test"
        r=self.client.post("/api/v2/objects/"+tree["id"]+"/photos",headers=person,
             files={"photo":("a.png",png,"image/png")})
        self.assertEqual(r.status_code,201,r.text)
        self.assertTrue(self.client.get("/api/v2/objects/"+tree["id"]).json()["photos"])
        self.assertEqual(self.client.post("/api/v2/objects/"+tree["id"]+"/photos",
             files={"photo":("a.png",png,"image/png")}).status_code,401)

    def test_invalid_input_rejected_and_attempts_rate_limited(self):
        user,_=self.login()
        self.assertEqual(self.client.post("/api/v2/objects",headers=user,json={
            "object_type":"tree","lat":0,"lon":131.88}).status_code,422)
        self.assertEqual(self.client.post("/api/v2/objects",headers=user,json={
            "object_type":"tree","lat":43.115,"lon":131.88,
            "confirmation_status":"confirmed"}).status_code,422)
        obj=self.create_tree(user)
        url="/api/v2/objects/"+obj["id"]+"/notes"
        self.assertEqual(self.client.post(url,headers=user,json={"message":"Первое замечание"}).status_code,201)
        self.assertEqual(self.client.post(url,headers=user,json={"message":"Второе замечание"}).status_code,429)

    def test_legacy_rows_copied_without_deletion(self):
        identifier="legacy-"+secrets.token_hex(8)
        with sqlite3.connect(LEGACY_DB) as old:
            old.execute("""
              INSERT INTO trees(id,lat,lon,species,condition,created_at,author_id)
              VALUES(?,43.111,131.89,'Липа','healthy',?,NULL)
            """,(identifier,int(time.time())))
        migrated=migrate_legacy(LEGACY_DB)
        self.assertGreaterEqual(migrated,1)
        self.assertEqual(migrate_legacy(LEGACY_DB),0)
        self.assertEqual(self.client.get("/api/v2/objects/"+identifier).json()["confirmation_status"],"proposed")
        with sqlite3.connect(LEGACY_DB) as old:
            self.assertEqual(old.execute("SELECT COUNT(*) FROM trees WHERE id=?",(identifier,)).fetchone()[0],1)


if __name__=="__main__":
    unittest.main()
