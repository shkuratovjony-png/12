"""Offline Mini App -> Ozon no-intermediary checkout regression.

No actual Ozon charge or Telegram user is contacted.
"""
import os,sqlite3,tempfile
from contextlib import contextmanager
from unittest.mock import patch
from flask import Flask
from miniapp_direct_checkout import register_miniapp_checkout
from web_product_access import ensure_schema

with tempfile.TemporaryDirectory() as tmp:
    path=tmp+"/miniapp-checkout.sqlite"
    @contextmanager
    def db():
        c=sqlite3.connect(path);c.row_factory=sqlite3.Row
        try:
            yield c;c.commit()
        except:
            c.rollback();raise
        finally:c.close()
    with db() as c:
        c.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY,tg_id INTEGER,is_banned INTEGER);
            INSERT INTO users VALUES (1,20001,0);
            CREATE TABLE billing_web_orders (
              order_id TEXT PRIMARY KEY,browser_nonce TEXT UNIQUE,product_key TEXT,
              amount_kopecks INTEGER,currency_code TEXT,method TEXT,status TEXT,
              checkout_url TEXT,provider_payment_id TEXT,provider_order_ext_id TEXT,
              created_at TEXT,updated_at TEXT,paid_at TEXT
            );
        """)
    ensure_schema(db)
    app=Flask(__name__)
    app.secret_key="test-secret"
    def one(sql,params=()):
        with db() as c:return c.execute(sql,params).fetchone()
    reservations=[]
    def reserve(a,b,amount):
        reservations.append((a,b,amount))
        return "reserved",{"id":1001}
    ns={
        "db":db,"one":one,"TOKEN":"test-token",
        "web_contact_live":lambda:True,
        "web_premium_active":lambda uid:False,
        "web_contact_credit_available":lambda uid:False,
        "mp_candidates":lambda uid,n:[(93,{"user_id":2})],
        "cr_between":lambda a,b:None,
        "ip_reserve_intro":reserve,
        "ip_close":lambda oid:None,
    }
    register_miniapp_checkout(app,ns)
    client=app.test_client()
    payload={"candidate_id":2,"email":"receipt@example.ru","intent":"ff12aa22bb33cc44dd55ee66"}
    headers={"X-Telegram-Init-Data":"valid-stub","Origin":"http://localhost"}
    checkout_url="https://checkout.ozon.ru/payment/testorder"
    env={"WEBHOOK_BASE_URL":"https://one2-1o22.onrender.com"}
    with patch.dict(os.environ,env):
        with patch("miniapp_direct_checkout._sales_ready",return_value=True), \
             patch("miniapp_direct_checkout.validate_init_data",return_value=20001), \
             patch("pair_cabinet.history_ids",return_value=[]), \
             patch("pair_cabinet.can_open",return_value=True), \
             patch("miniapp_direct_checkout._create",return_value=(checkout_url,"payment-test","order-test")) as mock_bank:
            missing=client.post("/s/app/api/checkout/contact",json=payload)
            # JSON can have a fake initData but the signature is validated
            # server-side (mock stands in for valid Telegram).
            assert missing.status_code==200,(missing.status_code,missing.get_json())
            assert missing.get_json()["url"]==checkout_url
            assert "receipt@example.ru" not in str(missing.get_json())
            assert mock_bank.call_count==1
            again=client.post("/s/app/api/checkout/contact",json=payload,headers=headers)
            assert again.status_code==200,again.get_json()
            assert again.get_json()["reused"] is True
            assert mock_bank.call_count==1,"Repeated click must not create another Ozon order"
            other={**payload,"intent":"77aa88bb99cc00dd11ee22ff"}
            another=client.post("/s/app/api/checkout/contact",json=other,headers=headers)
            assert another.status_code==200 and another.get_json()["reused"]
            assert mock_bank.call_count==1,"Different form intent must still reuse same-pair pending order"
            bad=client.post("/s/app/api/checkout/contact",json={**payload,"email":"invalid email"},headers=headers)
            assert bad.status_code==400
            forbidden=client.post("/s/app/api/checkout/contact",json={**payload,"candidate_id":3},headers=headers)
            assert forbidden.status_code==409
            with db() as c:
                rows=c.execute("SELECT * FROM billing_web_orders").fetchall()
                assert len(rows)==1 and rows[0]["amount_kopecks"]==10000
                assert rows[0]["method"]=="card" and rows[0]["status"]=="pending"
                receipts=c.execute("SELECT * FROM billing_receipt_contacts").fetchall()
                assert len(receipts)==1 and receipts[0]["receipt_email"]=="receipt@example.ru"
                assert c.execute("SELECT COUNT(*) FROM web_purchase_bindings").fetchone()[0]==1
            assert reservations==[(1,2,100)]
    # Unauthorized client cannot create an Ozon order.
    with patch("miniapp_direct_checkout._sales_ready",return_value=True), \
         patch("miniapp_direct_checkout.validate_init_data",side_effect=ValueError("signature")):
        res=client.post("/s/app/api/checkout/contact",json=payload)
        assert res.status_code==401
print("[test] signed Mini App checkout direct to Ozon, email recorded, no duplicate charges, server-owned pair PASS",flush=True)
