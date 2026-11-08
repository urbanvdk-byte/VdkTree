"""VdkTree v1.1.0: public registry search, facets, professional details and 2.4 XLSX."""
import io
import json
import hashlib
import hmac
import secrets
import time
import unittest
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import app
from pgdb import connect


def init_data(uid):
    import os
    fields = {"auth_date":str(int(time.time())),
              "user":json.dumps({"id":uid,"first_name":"Смотритель"},separators=(",",":"))}
    k=hmac.new(b"WebAppData",os.environ["MAX_BOT_TOKEN"].encode(),hashlib.sha256).digest()
    msg="\n".join(k+"="+v for k,v in sorted(fields.items()))
    fields["hash"]=hmac.new(k,msg.encode(),hashlib.sha256).hexdigest()
    return urlencode(fields)


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(app)
        uid=secrets.randbelow(1_600_000_000)+200_000
        r=cls.client.post("/api/auth/max",json={"init_data":init_data(uid)})
        assert r.status_code==200,r.text
        cls.header={"Authorization":"Bearer "+r.json()["token"]}
        with connect() as db:
            db.execute("UPDATE users SET role='admin' WHERE id=?",(r.json()["user"]["id"],))
        cls.tag="Реестр_"+secrets.token_hex(5)
        cls.ids=[]
        for i,(kind,common,height,score,diameter) in enumerate([
            ("tree",cls.tag+" дуб",12.5,3,31.2),
            ("tree",cls.tag+" клён",8.1,1,14.6),
            ("shrub",cls.tag+" шиповник",2.3,2,4.5),
        ]):
            point=cls.client.post("/api/v2/objects",headers=cls.header,json={
                "object_type":kind,"lat":43.121+i*0.002,"lon":131.901+i*0.002,
                "species_common":common,"visible_condition":"looks_healthy",
                "comment":"Реальный тестовый объект"
            })
            assert point.status_code==201,point.text
            oid=point.json()["id"]
            cls.ids.append(oid)
            edit=cls.client.patch("/api/v2/objects/"+oid+"/expert",
                headers=cls.header,json={
                    "botanical_species":"Quercus mongolica" if i==0 else "Acer" if i==1 else "Rosa",
                    "height_m":height,"sanitary_condition_score":score,
                    "trunk_diameter_130_cm":diameter,
                    "plot_number":"100" if i<2 else "101",
                    "life_form":"дерево" if kind=="tree" else "кустарник",
                    "quantity":1,
                    "slope_protection":i==0,
                    "endemic_or_relict":i==1,
                    "trunk_lean_degrees":23 if i==0 else 0,
                    "defects":"=1+2" if i==0 else "",
                    "care_recommendations":"Обрезка" if i==0 else "",
                })
            assert edit.status_code==200,edit.text

    def test_public_meta_and_listing_are_tree_shrub_only(self):
        r=self.client.get("/api/v2/registry/meta")
        self.assertEqual(r.status_code,200,r.text)
        fields={x["key"]:x for x in r.json()["fields"]}
        self.assertEqual(fields["height_m"]["kind"],"number")
        self.assertTrue(fields["species_common"]["facet"])
        self.assertTrue(fields["slope_protection"]["facet"])
        self.assertIn("sanitary_condition_score",fields)
        listed=self.client.get("/api/v2/registry",params={
            "contains_species_common":self.tag,"sort":"height_m","direction":"desc"
        })
        self.assertEqual(listed.status_code,200,listed.text)
        self.assertEqual(listed.json()["total"],3)
        items=listed.json()["items"]
        self.assertEqual([x["id"] for x in items],[self.ids[0],self.ids[1],self.ids[2]])
        self.assertTrue(all(x["object_type"] in ("tree","shrub") for x in items))
        self.assertTrue(all("password_hash" not in x for x in items))

    def test_combined_filters_facets_multi_choice_and_ranges(self):
        params={"contains_species_common":self.tag,
                "f_object_type":["tree","shrub"],
                "min_height_m":"5","max_height_m":"13",
                "f_sanitary_condition_score":["3","1"],
                "f_plot_number":["100"]}
        r=self.client.get("/api/v2/registry",params=params)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["total"],2)
        self.assertEqual({x["id"] for x in r.json()["items"]},set(self.ids[:2]))
        facet=self.client.get("/api/v2/registry/facets",params={
            "contains_species_common":self.tag,
            "f_object_type":"tree"
        })
        self.assertEqual(facet.status_code,200,facet.text)
        self.assertIn("species_common",facet.json()["facets"])
        scores={x["value"]:x["count"] for x in facet.json()["facets"]["sanitary_condition_score"]}
        self.assertEqual(scores.get("1"),1)
        self.assertEqual(scores.get("3"),1)
        age=self.client.get("/api/v2/registry",params={"q":self.tag+" клён"})
        self.assertEqual(age.status_code,200,age.text)
        self.assertEqual(age.json()["total"],1)
        self.assertEqual(age.json()["items"][0]["id"],self.ids[1])

    def test_sort_paging_and_reject_invalid_filter_names(self):
        a=self.client.get("/api/v2/registry",params={
            "contains_species_common":self.tag,"limit":1,"sort":"height_m","direction":"asc"
        })
        self.assertEqual(a.status_code,200,a.text)
        self.assertEqual(a.json()["items"][0]["id"],self.ids[2])
        b=self.client.get("/api/v2/registry",params={
            "contains_species_common":self.tag,"limit":1,"offset":1,
            "sort":"height_m","direction":"asc"
        })
        self.assertEqual(b.status_code,200,b.text)
        self.assertEqual(b.json()["items"][0]["id"],self.ids[1])
        invalids=[
            {"sort":"height_m;DROP TABLE users"},
            {"direction":"sideways"},
            {"min_plot_number":"3"},
            {"f_height_m":"5"},
            {"contains_height_m":"10"},
            {"max_height_m":"NaN"},
            {"min_observed_on":"not-a-date"},
            {"limit":"200"},
            {"f_does_not_exist":"x"},
        ]
        for query in invalids:
            with self.subTest(query=query):
                r=self.client.get("/api/v2/registry",params=query)
                self.assertEqual(r.status_code,422,r.text)
        self.assertEqual(self.client.get("/api/v2/registry",params={
            "contains_species_common":"%_","q":"anything"
        }).status_code,200)

    def test_details_regulation_xlsx_and_no_fabricated_values(self):
        oid=self.ids[0]
        detail=self.client.get("/api/v2/registry/"+oid)
        self.assertEqual(detail.status_code,200,detail.text)
        self.assertEqual(detail.json()["object"]["trunk_diameter_130_cm"],31.2)
        self.assertTrue(detail.json()["object"]["slope_protection"])
        self.assertIsInstance(detail.json()["photos"],list)
        file=self.client.get("/api/v2/registry/"+oid+"/sheet.xlsx")
        self.assertEqual(file.status_code,200,file.text[:100])
        self.assertIn("spreadsheetml",file.headers["content-type"])
        wb=load_workbook(io.BytesIO(file.content),data_only=True)
        self.assertEqual(wb.sheetnames,["Ведомость 2.4","Доп. сведения"])
        ws=wb["Ведомость 2.4"]
        self.assertIn("Таблица 2.4",ws["A2"].value)
        self.assertEqual([ws.cell(7,i).value for i in range(1,14)],list(range(1,14)))
        self.assertEqual(ws["G8"].value,1)
        self.assertEqual(ws["H8"].value,31.2)
        self.assertEqual(ws["I8"].value,12.5)
        self.assertIsNone(ws["K8"].value) # No fabricated Х/У/Н from six point score.
        self.assertIn("Обрезка",ws["M8"].value)
        self.assertTrue(ws["L8"].value.startswith("'=1+2")) # no Excel formula injection
        extra=wb["Доп. сведения"]
        self.assertIn(3,[extra.cell(row,2).value for row in range(2,extra.max_row+1)])
        self.assertEqual(self.client.get("/api/v2/registry/not-an-id/sheet.xlsx").status_code,404)

    def test_admin_inventory_number_patch_permission_and_uniqueness(self):
        oid=self.ids[0]
        path="/api/v2/registry/"+oid+"/inventory-number"
        self.assertEqual(self.client.patch(path,
            json={"inventory_number":"X-1"}).status_code,401)
        value="VL-test-"+secrets.token_hex(5)
        r=self.client.patch(path,headers=self.header,json={"inventory_number":value})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get("/api/v2/registry/"+oid).json()["object"]["inventory_number"],value)
        duplicate=self.client.patch("/api/v2/registry/"+self.ids[1]+"/inventory-number",
            headers=self.header,json={"inventory_number":value})
        self.assertEqual(duplicate.status_code,409,duplicate.text)
        self.assertEqual(self.client.patch(path,headers=self.header,
            json={"inventory_number":value}).status_code,409)
        self.assertEqual(self.client.patch(path,headers=self.header,
            json={"inventory_number":"BAD NUMBER WITH SPACES"}).status_code,422)
        cleared=self.client.patch(path,headers=self.header,json={"inventory_number":None})
        self.assertEqual(cleared.status_code,200,cleared.text)
        self.assertIsNone(cleared.json()["inventory_number"])

    def test_separate_html_and_health(self):
        r=self.client.get("/registry")
        self.assertEqual(r.status_code,200,r.text)
        self.assertIn("Реестр зелёных насаждений",r.text)
        self.assertIn("v1.1.0",r.text)
        self.assertEqual(self.client.get("/registry.html").status_code,200)
        health=self.client.get("/api/health")
        self.assertEqual(health.json()["version"],"1.1.0")


if __name__=="__main__":
    unittest.main()
