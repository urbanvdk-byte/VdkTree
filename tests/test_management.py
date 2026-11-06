"""VdkTree v1.0.0: integration checks for moderator/expert/import on real CI PostgreSQL."""
import hashlib
import hmac
import io
import json
import secrets
import time
import unittest
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app import app
from pgdb import connect


def credentials(max_id):
    from os import environ
    fields={
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id":max_id,"first_name":"Тест"},
                           ensure_ascii=False,separators=(",",":"))
    }
    key=hmac.new(b"WebAppData",environ["MAX_BOT_TOKEN"].encode(),hashlib.sha256).digest()
    msg="\n".join(key+"="+value for key,value in sorted(fields.items()))
    fields["hash"]=hmac.new(key,msg.encode(),hashlib.sha256).hexdigest()
    return urlencode(fields)


class ManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(app)

    def login(self,role="user"):
        max_id=secrets.randbelow(2_000_000_000)+100_000
        r=self.client.post("/api/auth/max",json={"init_data":credentials(max_id)})
        self.assertEqual(r.status_code,200,r.text)
        u=r.json()["user"]
        if role!="user":
            with connect() as db:
                db.execute("UPDATE users SET role=? WHERE id=?",(role,u["id"]))
        return {"Authorization":"Bearer "+r.json()["token"]},u

    def tree(self,auth,lat=43.12345,lon=131.93215,kind="tree"):
        r=self.client.post("/api/v2/objects",headers=auth,json={
            "object_type":kind,"lat":lat,"lon":lon,
            "species_common":"Клён маньчжурский","visible_condition":"unknown"})
        self.assertEqual(r.status_code,201,r.text)
        return r.json()

    def area(self,auth):
        obj={"object_type":"lawn","geometry":{"type":"Polygon","coordinates":[[
            [131.78,43.08],[131.781,43.08],[131.781,43.081],[131.78,43.08]
        ]]}}
        r=self.client.post("/api/v2/objects",headers=auth,json=obj)
        self.assertEqual(r.status_code,201,r.text)
        return r.json()

    def test_moderation_queue_permissions_decisions_and_history(self):
        owner,_=self.login()
        other,_=self.login()
        mod,_=self.login("moderator")
        obj=self.tree(owner)
        prefix="/api/v2/moderation/"
        self.assertEqual(self.client.get(prefix+"queue").status_code,401)
        self.assertEqual(self.client.get(prefix+"queue",headers=owner).status_code,403)
        self.assertEqual(self.client.get(prefix+"queue",headers=mod,params={"limit":101}).status_code,422)
        q=self.client.get(prefix+"queue",headers=mod,params={"mode":"pending","kind":"tree"})
        self.assertEqual(q.status_code,200,q.text)
        self.assertTrue(any(x["id"]==obj["id"] for x in q.json()["items"]))
        url=prefix+"objects/"+obj["id"]
        self.assertEqual(self.client.post(url+"/review",headers=owner,
            json={"action":"confirm"}).status_code,403)
        self.assertEqual(self.client.post(url+"/review",headers=mod,
            json={"action":"request_changes","comment":" "}).status_code,422)
        review=self.client.post(url+"/review",headers=mod,
            json={"action":"request_changes","comment":"Уточните породу и высоту"})
        self.assertEqual(review.status_code,200,review.text)
        note_id=review.json()["note_id"]
        public=self.client.get("/api/v2/objects/"+obj["id"]).json()
        self.assertTrue(public["needs_clarification"])
        self.assertEqual(public["confirmation_status"],"proposed")
        self.assertEqual(self.client.get(prefix+"queue",headers=mod,
            params={"mode":"notes"}).status_code,200)
        self.assertEqual(self.client.get(url+"/history",headers=other).status_code,403)
        history=self.client.get(url+"/history",headers=mod)
        self.assertEqual(history.status_code,200,history.text)
        self.assertIn("request_changes",[x["action"] for x in history.json()["events"]])
        ok=self.client.post(url+"/review",headers=mod,json={"action":"confirm"})
        self.assertEqual(ok.status_code,200,ok.text)
        self.assertEqual(self.client.post(url+"/review",headers=mod,
            json={"action":"confirm"}).status_code,409)
        self.assertEqual(self.client.get("/api/v2/objects/"+obj["id"]).json()["confirmation_status"],"confirmed")
        self.assertEqual(self.client.post("/api/v2/objects/"+obj["id"]+
            "/notes/"+note_id+"/close",headers=mod,json={"resolution":"Уточнено"}).status_code,200)
        self.assertFalse(self.client.get("/api/v2/objects/"+obj["id"]).json()["needs_clarification"])

    def test_expert_fields_and_permissions_preserve_confirmed_state(self):
        owner,_=self.login()
        mod,_=self.login("moderator")
        admin,_=self.login("admin")
        obj=self.tree(owner)
        url="/api/v2/objects/"+obj["id"]+"/expert"
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.get(url).json()["data"],{})
        fields={"botanical_species":"Acer mandshuricum",
                "trunk_diameter_130_cm":41.5,"height_m":12.1,
                "approx_age_years":45,"sanitary_condition_score":3,
                "defects":"Сухие ветви","care_recommendations":"Осмотр",
                "slope_protection":True,"endemic_or_relict":False}
        self.assertEqual(self.client.patch(url,json=fields).status_code,401)
        self.assertEqual(self.client.patch(url,headers=owner,json=fields).status_code,403)
        self.assertEqual(self.client.patch(url,headers=mod,
            json={"sanitary_condition_score":7}).status_code,422)
        self.assertEqual(self.client.patch(url,headers=mod,
            json={"trunk_lean_degrees":92}).status_code,422)
        self.assertEqual(self.client.patch(url,headers=mod,
            json={"super_secret":"x"}).status_code,422)
        saved=self.client.patch(url,headers=mod,json=fields)
        self.assertEqual(saved.status_code,200,saved.text)
        detail=self.client.get(url).json()
        self.assertEqual(detail["data"]["botanical_species"],"Acer mandshuricum")
        self.assertEqual(detail["data"]["sanitary_condition_score"],3)
        self.assertEqual(detail["data"]["slope_protection"],1)
        self.assertEqual(detail["data"]["endemic_or_relict"],0)
        self.assertEqual(self.client.post("/api/v2/objects/"+obj["id"]+"/confirm",
            headers=mod).status_code,200)
        self.assertEqual(self.client.patch(url,headers=mod,
            json={"height_m":15.5}).status_code,403)
        self.assertEqual(self.client.patch(url,headers=admin,
            json={"height_m":15.5,"defects":None}).status_code,200)
        final=self.client.get(url).json()["data"]
        self.assertEqual(final["height_m"],15.5)
        self.assertIsNone(final["defects"])
        self.assertEqual(self.client.get("/api/v2/objects/"+obj["id"]).json()["confirmation_status"],"confirmed")
        audit=self.client.get("/api/v2/moderation/objects/"+obj["id"]+"/history",headers=admin).json()
        self.assertIn("expert_edit",[a["action"] for a in audit["events"]])

    def test_professional_area_details_limited_to_owner_moderator_or_admin(self):
        mod,_=self.login("moderator")
        another,_=self.login("moderator")
        admin,_=self.login("admin")
        lawn=self.area(mod)
        url="/api/v2/objects/"+lawn["id"]+"/area-details"
        self.assertEqual(self.client.patch(url,headers=another,
            json={"area_m2":123.4}).status_code,403)
        self.assertEqual(self.client.patch(url,headers=mod,
            json={"lawn_type":"slope","area_m2":123.4,"area_condition":"good"}).status_code,200)
        self.assertEqual(self.client.get("/api/v2/objects/"+lawn["id"]+"/expert").json()["data"]["area_m2"],123.4)
        self.assertEqual(self.client.patch(url,headers=admin,
            json={"area_condition":"satisfactory"}).status_code,200)
        self.assertEqual(self.client.patch(url,headers=admin,
            json={"area_m2":-1}).status_code,422)
        self.assertEqual(self.client.patch("/api/v2/objects/"+lawn["id"]+"/expert",
            headers=admin,json={"height_m":10}).status_code,422)

    def test_import_csv_preview_errors_duplicates_atomic_commit(self):
        admin,_=self.login("admin")
        mod,_=self.login("moderator")
        source="Vedomost_"+secrets.token_hex(5)
        data=("object_type;latitude;longitude;species_common;external_id;sanitary_condition_score;botanical_species;quantity\n"
              "tree;43,410015;132,410015;Дуб монгольский;oak-1;3;Quercus mongolica;1\n"
              "shrub;43,410500;132,410500;Сирень;shrub-2;2;Syringa;1\n"
              "tree;99;132,421;Ошибка;bad-3;2;Quercus;1\n"
              "tree;43,410018;132,410016;Дуб монгольский;oak-1;3;Quercus;1\n")
        file={"file":("inventory.csv",data.encode("utf-8-sig"),"text/csv")}
        self.assertEqual(self.client.post("/api/v2/admin/imports/preview",
            files=file,data={"import_source":source}).status_code,401)
        self.assertEqual(self.client.post("/api/v2/admin/imports/preview",headers=mod,
            files=file,data={"import_source":source}).status_code,403)
        pre=self.client.post("/api/v2/admin/imports/preview",headers=admin,
            files=file,data={"import_source":source})
        self.assertEqual(pre.status_code,201,pre.text)
        obj=pre.json()
        self.assertEqual((obj["ready"],obj["invalid"],obj["duplicates"]),(2,1,1))
        self.assertEqual(obj["total_rows"],4)
        batch=obj["batch_id"]
        self.assertEqual(self.client.get("/api/v2/admin/imports/"+batch,headers=admin).status_code,200)
        self.assertEqual(self.client.get("/api/v2/admin/imports/template",headers=admin).status_code,200)
        self.assertEqual(self.client.get("/api/v2/admin/imports/template",headers=mod).status_code,403)
        commit=self.client.post("/api/v2/admin/imports/"+batch+"/commit",headers=admin)
        self.assertEqual(commit.status_code,200,commit.text)
        self.assertEqual(commit.json()["imported"],2)
        self.assertEqual(commit.json()["skipped"],2)
        self.assertEqual(self.client.post("/api/v2/admin/imports/"+batch+"/commit",
            headers=admin).status_code,409)
        with connect() as db:
            rows=db.execute("""
                SELECT id,object_type,confirmation_status,source_type FROM inventory_objects
                WHERE import_source=? ORDER BY object_type
            """,(source,)).fetchall()
        self.assertEqual(len(rows),2)
        self.assertEqual({r["source_type"] for r in rows},{"bulk_import"})
        self.assertEqual({r["confirmation_status"] for r in rows},{"proposed"})
        self.assertEqual(self.client.get("/api/v2/objects/"+rows[0]["id"]+"/expert")
                         .json()["data"]["sanitary_condition_score"],2)
        another=self.client.post("/api/v2/admin/imports/preview",headers=admin,
            files=file,data={"import_source":source})
        self.assertEqual(another.status_code,201,another.text)
        self.assertEqual(another.json()["ready"],0)
        self.assertGreaterEqual(another.json()["duplicates"],3)
        self.assertEqual(self.client.post("/api/v2/admin/imports/"+
            another.json()["batch_id"]+"/commit",headers=admin).status_code,422)

    def test_import_xlsx_and_validation(self):
        admin,_=self.login("admin")
        source="Excel_"+secrets.token_hex(5)
        wb=Workbook()
        ws=wb.active
        ws.append(["object_type","latitude","longitude","species_common",
                   "external_id","height_m","approx_age_years"])
        ws.append(["tree",43.511011,132.511011,"Пихта","fir-1",17.8,50])
        buffer=io.BytesIO();wb.save(buffer)
        r=self.client.post("/api/v2/admin/imports/preview",headers=admin,
            data={"import_source":source},
            files={"file":("list.xlsx",buffer.getvalue(),
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(r.json()["ready"],1)
        committed=self.client.post("/api/v2/admin/imports/"+
            r.json()["batch_id"]+"/commit",headers=admin)
        self.assertEqual(committed.status_code,200,committed.text)
        self.assertEqual(committed.json()["imported"],1)
        bad=self.client.post("/api/v2/admin/imports/preview",headers=admin,
            data={"import_source":source},
            files={"file":("bad.csv",b"latitude,longitude,bogus\n43.1,131.8,oops",
                           "text/csv")})
        self.assertEqual(bad.status_code,422)
        self.assertEqual(self.client.post("/api/v2/admin/imports/preview",headers=admin,
            data={"import_source":"a"},
            files={"file":("test.csv",b"latitude,longitude\n43.1,131.8","text/csv")}).status_code,422)


if __name__=="__main__":
    unittest.main()
