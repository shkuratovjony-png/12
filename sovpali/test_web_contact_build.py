"""Offline signed-pair web checkout and verified introduction delivery tests."""
import asyncio
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask
from pair_web import _ser
from web_contact_checkout import register_contact_product
from web_product_access import bind_order
from web_intro_fulfillment import fulfill_intro, resolve_intro

with tempfile.TemporaryDirectory() as temp:
    path=temp+"/contact.sqlite"
    @contextmanager
    def db():
        c=sqlite3.connect(path)
        c.row_factory=sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    with db() as c:
        c.execute("""CREATE TABLE billing_web_orders(
            order_id TEXT PRIMARY KEY, product_key TEXT,amount_kopecks INTEGER,
            currency_code TEXT,status TEXT, created_at TEXT)""")
        c.execute("""CREATE TABLE intro_orders(
            id INTEGER PRIMARY KEY,status TEXT)""")
    app=Flask(__name__)
    app.secret_key="secret"
    profiles={1:{"user_id":1,"name":"Вы","city":"Владивосток"},
              2:{"user_id":2,"name":"Мария","city":"Владивосток"}}
    ns={"db":db,"FLASK_SECRET":"signed-pair-test","profile":lambda uid:profiles.get(uid),
        "user":lambda uid:{"is_banned":0,"tg_id":uid},
        "eligible":lambda a,b:True,
        "web_checkout_ready":lambda:True,
        "cr_between":lambda a,b:None}
    register_contact_product(app,ns)
    client=app.test_client()
    token=_ser("signed-pair-test").dumps({"v":1,"c":2})
    with patch.dict(os.environ,{"SOVPALI_WEB_CONTACTS_LIVE":"0"}):
        page=client.get("/billing/contact/"+token)
        assert page.status_code==200
        assert 'disabled' in page.get_data(as_text=True)
        assert "Мария" in page.get_data(as_text=True)
        assert client.get("/billing/contact/invalid").status_code==404
    with patch.dict(os.environ,{"SOVPALI_WEB_CONTACTS_LIVE":"1"}):
        page=client.get("/billing/contact/"+token)
        assert page.status_code==200
        assert 'Оплатить 100 ₽' in page.get_data(as_text=True)
        with client.session_transaction() as ss:
            assert ss["billing_pair_token"]==token
            assert ss["billing_csrf"] and ss["billing_nonce"]

    # Simulate a bank-verified (not merely redirected) payment. No real bank used.
    with db() as c:
        c.execute("INSERT INTO billing_web_orders VALUES('bank-ok','contact',10000,'643','paid','now')")
        c.execute("INSERT INTO intro_orders VALUES(1,'reserved')")
    bind_order(db,"bank-ok",1,"contact",target_id=2,linked_intro_id=1)

    loop=asyncio.new_event_loop()
    worker=threading.Thread(target=lambda:(asyncio.set_event_loop(loop),loop.run_forever()),daemon=True)
    worker.start()
    ready=threading.Event()
    ready.set()
    deliveries=[]
    finishes=[]
    async def deliver(ctx, buyer, target, score):
        deliveries.append((buyer,target,score))
        return ("sent", 11)
    def mark_paid(oid,provider_id):
        with db() as c:c.execute("UPDATE intro_orders SET status='paid' WHERE id=?",(oid,))
        return {"id":oid}
    def mark_sent(oid):
        with db() as c:c.execute("UPDATE intro_orders SET status='awaiting_response' WHERE id=?",(oid,))
    def finish(oid,accepted):
        finishes.append((oid,accepted))
        with db() as c:c.execute("UPDATE intro_orders SET status=? WHERE id=?",
                    ("accepted" if accepted else "declined",oid))
    ns.update({"ip_mark_paid":mark_paid,"ip_mark_request_sent":mark_sent,
               "ip_finish":finish,"ready":ready,"bot":SimpleNamespace(bot=object()),
               "loop":loop,"cr_send_request":deliver,"score":lambda a,b:93,
               "audit":lambda *args:None,
               "one":lambda q,p: _one(db,q,p)})
    def get(q,p):
        with db() as c:return c.execute(q,p).fetchone()
    ns["one"]=get
    assert fulfill_intro(ns,"bank-ok")=="delivered"
    assert fulfill_intro(ns,"bank-ok")=="delivered"
    assert deliveries == [(1,2,93)]
    assert resolve_intro(ns,1,2,False)
    assert finishes==[(1,False)]
    with db() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM web_intro_credits").fetchone()["n"] == 1
    loop.call_soon_threadsafe(loop.stop)
    worker.join(1)
    loop.close()

print("[test] web contact: signed pair, gated checkout, bank-verified delivery only once, decline credit PASS",flush=True)
