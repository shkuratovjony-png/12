"""Offline regression: one-tap browser checkout bridge + signed status.

No real Ozon payment or Telegram message is sent.
"""
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from unittest.mock import patch
from flask import Flask
from miniapp_direct_checkout import register_miniapp_checkout
from web_product_access import ensure_schema

with tempfile.TemporaryDirectory() as tmp:
    filename=tmp+"/checkout-bridge.sqlite"
    @contextmanager
    def db():
        conn=sqlite3.connect(filename)
        conn.row_factory=sqlite3.Row
        try:
            yield conn
            conn.commit()
        except:
            conn.rollback()
            raise
        finally:
            conn.close()
    with db() as c:
        c.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY,tg_id INTEGER,is_banned INTEGER);
            INSERT INTO users VALUES (1,20001,0);
            INSERT INTO users VALUES (3,20002,0);
            CREATE TABLE billing_web_orders (
              order_id TEXT PRIMARY KEY,browser_nonce TEXT UNIQUE,
              product_key TEXT,amount_kopecks INTEGER,currency_code TEXT,
              method TEXT,status TEXT,checkout_url TEXT,
              provider_payment_id TEXT,provider_order_ext_id TEXT,
              created_at TEXT,updated_at TEXT,paid_at TEXT);
        """)
    ensure_schema(db)
    reservations=[]
    def one(query,params=()):
        with db() as c:
            return c.execute(query,params).fetchone()
    def reserve(buyer,target,amount):
        reservations.append((buyer,target,amount))
        return "reserved",{"id":123}
    ns={
        "db":db,"one":one,"TOKEN":"test-token",
        "profile":lambda uid:{"user_id":uid,"name":"Пользователь"},
        "web_contact_live":lambda:True,
        "web_premium_live":lambda:True,
        "web_premium_active":lambda uid:False,
        "web_contact_credit_available":lambda uid:False,
        "mp_candidates":lambda uid,n:[(10,{"user_id":2})],
        "cr_between":lambda a,b:None,
        "ip_reserve_intro":reserve,
        "ip_close":lambda oid:None,
    }
    app=Flask(__name__)
    app.secret_key="secret"
    register_miniapp_checkout(app,ns)
    client=app.test_client()
    headers={"X-Telegram-Init-Data":"valid-stub"}
    url="https://checkout.ozon.ru/payment/testorder"
    with patch.dict(os.environ,{"WEBHOOK_BASE_URL":"https://one2-1o22.onrender.com"}):
      with patch("miniapp_direct_checkout.validate_init_data",return_value=20001), \
           patch("miniapp_direct_checkout._sales_ready",return_value=True), \
           patch("miniapp_direct_checkout._create_fiscal",
                 return_value=(url,"bank-id","bank-ext")) as bank, \
           patch("pair_cabinet.history_ids",return_value=[]), \
           patch("pair_cabinet.can_open",return_value=True):
        contact={"sku":"contact","candidate_id":2,"email":"receipt@example.ru",
                 "intent":"aabbccdd0011223344556677"}
        staged=client.post("/s/app/api/checkout/prepare",json=contact,headers=headers)
        assert staged.status_code==200,staged.get_json()
        ticket=staged.json["ticket"]
        assert len(ticket)==32
        assert staged.json["url"]=="https://one2-1o22.onrender.com/billing/ozon/launch/"+ticket
        assert bank.call_count==0 and reservations==[],"Preparation must not reserve pair or charge"
        with db() as c:
            assert c.execute("SELECT count(*) FROM billing_web_orders").fetchone()[0]==0

        launch=client.get("/billing/ozon/launch/"+ticket)
        assert launch.status_code==303 and launch.location==url
        assert launch.headers["Referrer-Policy"]=="no-referrer"
        assert bank.call_count==1 and reservations==[(1,2,100)]
        again=client.get("/billing/ozon/launch/"+ticket)
        assert again.status_code==303 and bank.call_count==1,"Reopening must reuse same Ozon order"

        with patch("web_intro_fulfillment.verify_and_fulfill",return_value="pending"):
            pending=client.post("/s/app/api/checkout/status",json={"ticket":ticket},headers=headers)
        assert pending.status_code==200 and pending.json["paid"] is False
        assert pending.json["has_order"] is True and pending.json["payment_url"]==url
        blocked_cancel=client.post("/s/app/api/checkout/cancel",json={"ticket":ticket},headers=headers)
        assert blocked_cancel.status_code==409
        assert blocked_cancel.json["has_order"] is True
        assert bank.call_count==1,"Cancel must never create duplicate Ozon charge"
        with db() as c:
            c.execute("UPDATE billing_web_orders SET status='paid' WHERE product_key='contact'")
        with patch("web_intro_fulfillment.verify_and_fulfill",return_value="delivered"):
            paid=client.post("/s/app/api/checkout/status",json={"ticket":ticket},headers=headers)
        assert paid.status_code==200 and paid.json["paid"] and paid.json["delivered"]
        with patch("miniapp_direct_checkout.validate_init_data",return_value=20002):
            cross=client.post("/s/app/api/checkout/status",json={"ticket":ticket},headers=headers)
        assert cross.status_code==404,"Another Telegram account cannot inspect the checkout"

        unused={"sku":"premium","candidate_id":None,"email":"first@example.ru",
                "intent":"11223344aabbccdd55667788"}
        unused_response=client.post("/s/app/api/checkout/prepare",json=unused,headers=headers)
        assert unused_response.status_code==200
        unused_token=unused_response.json["ticket"]
        cancelled=client.post("/s/app/api/checkout/cancel",
             json={"ticket":unused_token},headers=headers)
        assert cancelled.status_code==200 and cancelled.json["cancelled"] is True
        assert client.get("/billing/ozon/launch/"+unused_token).status_code==410
        assert bank.call_count==1,"Cancelling an unused checkout must not call Ozon"

        premium={"sku":"premium","candidate_id":None,"email":"vip@example.ru",
                 "intent":"ffeeddccbbaa998877665544"}
        prepared_vip=client.post("/s/app/api/checkout/prepare",json=premium,headers=headers)
        assert prepared_vip.status_code==200,prepared_vip.json
        assert bank.call_count==1
        vip=client.get("/billing/ozon/launch/"+prepared_vip.json["ticket"])
        assert vip.status_code==303 and vip.location==url
        assert client.post("/s/app/api/checkout/cancel",
            json={"ticket":prepared_vip.json["ticket"]},headers=headers).status_code==409
        assert bank.call_count==2
        assert bank.call_args.args[1:3]==("premium",120000)
        with db() as c:
            c.execute("UPDATE billing_checkout_tickets SET created_at='2000-01-01T00:00:00+00:00' WHERE token=?",
                      (prepared_vip.json["ticket"],))
        old=client.get("/billing/ozon/launch/"+prepared_vip.json["ticket"])
        assert old.status_code==410
        assert bank.call_count==2

print("[test] external checkout, signed status, Safari retry link, safe unused-ticket cancel and paid-order protection PASS")
