"""Offline tests for monetization ledger: no real bank or personal data involved."""
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from web_product_access import (
    ensure_schema, bind_order, binding, grant_premium, premium_active, premium_expires,
    credit_intro, redeem_intro_credit, CATALOG,
)

with tempfile.TemporaryDirectory() as d:
    path=d+"/ledger.sqlite"
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
             order_id TEXT PRIMARY KEY, product_key TEXT, amount_kopecks INTEGER,
             currency_code TEXT, status TEXT)""")
    with db() as c:c.execute("CREATE TABLE intro_orders(id INTEGER PRIMARY KEY,status TEXT)")
    ensure_schema(db)
    now=datetime(2026,11,4,tzinfo=timezone.utc)

    def order(oid,sku,paid=True,amount=None):
        with db() as c:
            c.execute("""INSERT INTO billing_web_orders
                  (order_id,product_key,amount_kopecks,currency_code,status)
                  VALUES(?,?,?,?,?)""",(oid,sku,CATALOG[sku]["kopecks"] if amount is None else amount,"643",
                                         "paid" if paid else "pending"))

    bind_order(db,"premium-1",10,"premium")
    order("premium-1","premium",paid=False)
    assert not grant_premium(db,"premium-1",now)
    with db() as c:c.execute("UPDATE billing_web_orders SET status='paid' WHERE order_id='premium-1'")
    assert grant_premium(db,"premium-1",now)
    first=premium_expires(db,10)
    assert premium_active(db,10,now+timedelta(days=29))
    assert not premium_active(db,10,now+timedelta(days=31))
    assert grant_premium(db,"premium-1",now+timedelta(days=7))
    assert premium_expires(db,10)==first  # repeated event no extra month

    bind_order(db,"premium-2",10,"premium")
    order("premium-2","premium")
    assert grant_premium(db,"premium-2",now+timedelta(days=1))
    assert premium_active(db,10,now+timedelta(days=59))
    assert not premium_active(db,10,now+timedelta(days=61))

    bind_order(db,"contact-1",10,"contact",target_id=20,linked_intro_id=101)
    order("contact-1","contact")
    assert not grant_premium(db,"contact-1")
    assert credit_intro(db,"contact-1",now)
    assert credit_intro(db,"contact-1",now)
    assert redeem_intro_credit(db,11,"replacement",now) is None
    assert redeem_intro_credit(db,10,"replacement",now)=="contact-1"
    assert redeem_intro_credit(db,10,"replacement",now)=="contact-1" # idempotent
    assert redeem_intro_credit(db,10,"other",now) is None

    bind_order(db,"contact-2",10,"contact",target_id=21,linked_intro_id=102)
    order("contact-2","contact",amount=30000)
    assert not credit_intro(db,"contact-2") # wrong amount cannot create a credit
    try:
        bind_order(db,"contact-fake",10,"contact",target_id=10)
        raise AssertionError("same-user contact should be invalid")
    except ValueError: pass

    with db() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM web_product_grants").fetchone()["n"]==2
        assert c.execute("SELECT COUNT(*) AS n FROM web_intro_credits").fetchone()["n"]==1
print("[test] paid product entitlements: 30-day premium, bank evidence, no repeat grants, one-time intro credits PASS",flush=True)
