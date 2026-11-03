"""Offline Premium web checkout and incoming-interest benefit tests."""
import sqlite3
import os
import tempfile
from contextlib import contextmanager
from unittest.mock import patch
from flask import Flask
from pair_web import _ser
from web_premium_checkout import register_web_premium
from web_product_access import ensure_schema, bind_order, grant_premium

with tempfile.TemporaryDirectory() as temp:
    path=temp+"/premium.sqlite"
    @contextmanager
    def db():
        c=sqlite3.connect(path)
        c.row_factory=sqlite3.Row
        try:
            yield c;c.commit()
        except Exception:
            c.rollback();raise
        finally:c.close()
    with db() as c:
        c.execute("""CREATE TABLE billing_web_orders(
                    order_id TEXT PRIMARY KEY,product_key TEXT,amount_kopecks INTEGER,
                    currency_code TEXT,status TEXT)""")
    ensure_schema(db)
    app=Flask(__name__);app.secret_key="premium-test-cookie"
    profiles={1:{"name":"Лена","user_id":1,"city":"Владивосток"},2:{"name":"Иван","user_id":2,"city":"Владивосток"}}
    ns={"db":db,"FLASK_SECRET":"premium-test-signature",
        "profile":lambda u:profiles.get(u),"user":lambda u:{"is_banned":0},
        "eligible":lambda a,b:True,"web_owner_verified":lambda u:True,
        "web_checkout_ready":lambda:True,
        "many":lambda q,p:[{"name":"Аня <script>","city":"Артём","status":"pending"}]}
    register_web_premium(app,ns)
    client=app.test_client()
    token=_ser("premium-test-signature").dumps({"v":1,"c":2})
    with patch.dict(os.environ,{"SOVPALI_WEB_PREMIUM_LIVE":"0"}):
        page=client.get("/billing/premium/"+token)
        assert page.status_code==200
        assert "disabled" in page.get_data(as_text=True)
    with patch.dict(os.environ,{"SOVPALI_WEB_PREMIUM_LIVE":"1"}):
        page=client.get("/billing/premium/"+token)
        assert page.status_code==200
        assert "1 200 ₽" in page.get_data(as_text=True)
        assert "<button >Оформить Premium</button>" in page.get_data(as_text=True)
        assert client.get("/billing/premium/interests/"+token).status_code==403
    bind_order(db,"premium-order",1,"premium")
    with db() as c:
        c.execute("INSERT INTO billing_web_orders VALUES('premium-order','premium',120000,'643','paid')")
    assert grant_premium(db,"premium-order")
    active=client.get("/billing/premium/"+token)
    assert "Premium активен" in active.get_data(as_text=True)
    interest=client.get("/billing/premium/interests/"+token)
    assert interest.status_code==200
    assert "&lt;script&gt;" in interest.get_data(as_text=True)
    assert "<script>" not in interest.get_data(as_text=True)
print("[test] Premium: access gated, 1200-RUB price, 30-day grant, verified interest privacy and escaping PASS",flush=True)
