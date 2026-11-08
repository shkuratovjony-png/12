"""One 100-ruble bank payment buys one successful introduction:
multiple declined/expired free attempts restore the SAME paid entitlement.
No bank API, Telegram bot or real data is contacted.
"""
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from web_product_access import (
    ensure_schema,bind_order,available_intro_credit,redeem_intro_credit,
    reconcile_intro_credits,
)
from web_intro_fulfillment import resolve_intro

with tempfile.TemporaryDirectory() as tmp:
    path=os.path.join(tmp,"credits.sqlite3")
    @contextmanager
    def db():
        c=sqlite3.connect(path)
        c.row_factory=sqlite3.Row
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:c.close()
    with db() as c:
        c.executescript("""
        CREATE TABLE billing_web_orders (
            order_id TEXT PRIMARY KEY,product_key TEXT,amount_kopecks INTEGER,
            currency_code TEXT,status TEXT
        );
        CREATE TABLE intro_orders (
            id INTEGER PRIMARY KEY,buyer_user_id INTEGER,target_user_id INTEGER,
            status TEXT
        );
        """)
    ensure_schema(db)
    bind_order(db,"paid-100",1,"contact",target_id=2,linked_intro_id=100)
    with db() as c:
        c.execute("INSERT INTO billing_web_orders VALUES ('paid-100','contact',10000,'643','paid')")
        c.execute("INSERT INTO intro_orders VALUES (100,1,2,'awaiting_response')")
        c.execute("UPDATE web_purchase_bindings SET binding_status='delivered' WHERE billing_order_id='paid-100'")
    def one(sql,params=()):
        with db() as c:return c.execute(sql,params).fetchone()
    settlements=[]
    def finish(intro_id,accepted):
        with db() as c:
            r=c.execute("""UPDATE intro_orders SET status=? WHERE id=?
                AND status IN ('paid','awaiting_response')
                RETURNING id""",("accepted" if accepted else "declined",int(intro_id))).fetchone()
            assert r,"Cannot settle a non-active introduction"
        settlements.append((intro_id,accepted))
    ns={"db":db,"one":one,"ip_finish":finish}

    # The original bank-paid request is declined. One voucher is earned.
    assert resolve_intro(ns,1,2,False)
    assert available_intro_credit(db,1)=="paid-100"
    assert not resolve_intro(ns,1,2,False),"Duplicate callback is not a second credit"

    # Two separate people decline subsequent FREE attempts, same voucher reused.
    for intro_id,target in ((101,3),(102,4)):
        with db() as c:
            c.execute("INSERT INTO intro_orders VALUES (?,?,?,'awaiting_response')",(intro_id,1,target))
        claim="web-credit-"+str(intro_id)
        assert redeem_intro_credit(db,1,claim)=="paid-100"
        assert redeem_intro_credit(db,1,claim)=="paid-100","Idempotent duplicate redemption"
        assert available_intro_credit(db,1) is None,"No second concurrent free request"
        assert resolve_intro(ns,1,target,False)
        assert available_intro_credit(db,1)=="paid-100","Declined repeat must restore voucher"

    # Third FREE attempt receives no answer for 24h; scheduler marks expired.
    with db() as c:
        c.execute("INSERT INTO intro_orders VALUES (103,1,5,'awaiting_response')")
    assert redeem_intro_credit(db,1,"web-credit-103")=="paid-100"
    assert available_intro_credit(db,1) is None
    with db() as c:
        c.execute("UPDATE intro_orders SET status='expired' WHERE id=103")
    assert reconcile_intro_credits(db)==1,"Expired attempt restores voucher"
    assert reconcile_intro_credits(db)==0,"No duplicate restore"
    assert available_intro_credit(db,1)=="paid-100"

    # Fourth FREE attempt is accepted; the paid entitlement is finally used.
    with db() as c:
        c.execute("INSERT INTO intro_orders VALUES (104,1,6,'awaiting_response')")
    assert redeem_intro_credit(db,1,"web-credit-104")=="paid-100"
    assert resolve_intro(ns,1,6,True)
    assert available_intro_credit(db,1) is None,"Consent consumes voucher permanently"
    assert redeem_intro_credit(db,1,"web-credit-105") is None
    with db() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM web_intro_credits").fetchone()["n"]==1
        row=c.execute("SELECT redeemed_for_order FROM web_intro_credits").fetchone()
        assert row["redeemed_for_order"]=="web-credit-104"
    assert settlements==[(100,False),(101,False),(102,False),(104,True)]

print("[test] one bank-paid 100-RUB introduction survives multiple refusals + timeout until first acceptance PASS",flush=True)
