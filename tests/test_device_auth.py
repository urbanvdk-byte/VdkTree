"""v1.0.2: PostgreSQL MAX-to-browser one-time pairing and 8-char credentials."""
import hashlib
import hmac
import json
import os
import secrets
import time
import unittest
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from app import app
from pgdb import connect


def signed_max(max_id):
    fields={
        "auth_date":str(int(time.time())),
        "user":json.dumps({"id":max_id,"first_name":"MAX Test"},
                          ensure_ascii=False,separators=(",",":"))
    }
    key=hmac.new(b"WebAppData",os.environ["MAX_BOT_TOKEN"].encode(),hashlib.sha256).digest()
    text="\n".join(k+"="+v for k,v in sorted(fields.items()))
    fields["hash"]=hmac.new(key,text.encode(),hashlib.sha256).hexdigest()
    return urlencode(fields)


class BrowserMAXPairingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(app)

    def max_account(self):
        max_id=secrets.randbelow(900_000_000)+100_000
        proof=signed_max(max_id)
        r=self.client.post("/api/auth/max",json={"init_data":proof})
        self.assertEqual(r.status_code,200,r.text)
        return proof,r.json()

    def challenge(self):
        r=self.client.post("/api/auth/device/start")
        self.assertEqual(r.status_code,201,r.text)
        data=r.json()
        self.assertEqual(len(data["code"]),8)
        self.assertEqual(data["expires_in"],300)
        self.assertEqual(len(data["request_id"]),32)
        self.assertNotIn("token",data)
        return data

    def test_full_flow_invalid_proof_and_single_use(self):
        proof,account=self.max_account()
        data=self.challenge()
        endpoint="/api/auth/device/"
        polling={"request_id":data["request_id"],"verifier":data["verifier"]}
        self.assertEqual(self.client.post(endpoint+"poll",json=polling).json()["status"],"pending")
        self.assertEqual(self.client.post(endpoint+"poll",json={
            **polling,"verifier":"invalidverifier"*4
        }).status_code,401)
        invalid=self.client.post(endpoint+"approve",json={
            "code":data["code"],"init_data":proof.replace("MAX+Test","MAX+Hacker")
        })
        self.assertIn(invalid.status_code,(401,422),invalid.text)
        self.assertEqual(self.client.post(endpoint+"poll",json=polling).json()["status"],"pending")
        approval=self.client.post(endpoint+"approve",json={"code":data["code"],"init_data":proof})
        self.assertEqual(approval.status_code,200,approval.text)
        self.assertNotIn("token",approval.json())
        self.assertEqual(self.client.post(endpoint+"approve",json={
            "code":data["code"],"init_data":proof
        }).status_code,400)
        authorized=self.client.post(endpoint+"poll",json=polling)
        self.assertEqual(authorized.status_code,200,authorized.text)
        self.assertEqual(authorized.json()["status"],"authenticated")
        self.assertEqual(authorized.json()["user"]["id"],account["user"]["id"])
        token=authorized.json()["token"]
        self.assertEqual(self.client.get("/api/auth/me",headers={
            "Authorization":"Bearer "+token
        }).status_code,200)
        self.assertEqual(self.client.post(endpoint+"poll",json=polling).status_code,410)

    def test_expired_code_and_unregistered_identity(self):
        proof,_=self.max_account()
        data=self.challenge()
        with connect() as db:
            db.execute("UPDATE browser_login_requests SET expires_at=? WHERE id=?",
                       (int(time.time())-1,data["request_id"]))
        self.assertEqual(self.client.post("/api/auth/device/poll",json={
            "request_id":data["request_id"],"verifier":data["verifier"]
        }).status_code,410)
        self.assertEqual(self.client.post("/api/auth/device/approve",json={
            "code":data["code"],"init_data":proof
        }).status_code,400)

    def test_unique_case_insensitive_login_and_eight_character_password(self):
        proof,account=self.max_account()
        headers={"Authorization":"Bearer "+account["token"]}
        name="tree_"+secrets.token_hex(6)
        short=self.client.post("/api/auth/credentials",headers=headers,
            json={"login":name,"password":"1234567"})
        self.assertEqual(short.status_code,422,short.text)
        good=self.client.post("/api/auth/credentials",headers=headers,
            json={"login":name,"password":"12345678"})
        self.assertEqual(good.status_code,200,good.text)
        login=self.client.post("/api/auth/password",json={
            "login":name.upper(),"password":"12345678"
        })
        self.assertEqual(login.status_code,200,login.text)
        self.assertEqual(login.json()["user"]["id"],account["user"]["id"])
        self.assertEqual(self.client.post("/api/auth/password",json={
            "login":name,"password":"87654321"
        }).status_code,401)
        another_proof,another=self.max_account()
        second=self.client.post("/api/auth/credentials",headers={
            "Authorization":"Bearer "+another["token"]
        },json={"login":name.upper(),"password":"12345678"})
        self.assertEqual(second.status_code,409,second.text)


if __name__=="__main__":
    unittest.main()
