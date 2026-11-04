"""Idempotent, verified-after-bank fulfillment for standalone web introductions."""
import asyncio
import os
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from web_product_access import CATALOG, credit_intro

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _row(db, order_id):
    with db() as c:
        return c.execute("""SELECT b.*, o.status AS bank_status,
                           o.amount_kopecks,o.currency_code,o.product_key
                           FROM web_purchase_bindings b
                           JOIN billing_web_orders o ON o.order_id=b.billing_order_id
                           WHERE b.billing_order_id=?""",(str(order_id),)).fetchone()

def fulfill_intro(ns, order_id):
    """Called ONLY after Ozon server-side status has been checked."""
    db=ns["db"]
    record=_row(db,order_id)
    if not record or record["sku"]!="contact" or record["product_key"]!="contact":
        return "not_contact"
    if record["bank_status"]!="paid" or str(record["currency_code"])!="643" or int(record["amount_kopecks"])!=CATALOG["contact"]["kopecks"]:
        return "unverified"
    if record["binding_status"]=="delivered":
        return "delivered"
    if not record["linked_intro_id"]:
        return "support_required"
    # A crashed worker's 'sending' claim can be safely retried after 5 minutes;
    # cr_send_request checks the persistent delivery receipt before resending.
    cutoff=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat(timespec="seconds")
    with db() as c:
        claimed=c.execute("""UPDATE web_purchase_bindings
                    SET binding_status='sending',updated_at=?
                    WHERE billing_order_id=? AND
                          (binding_status IN ('reserved','retry')
                           OR (binding_status='sending' AND updated_at < ?))
                    RETURNING billing_order_id""",(_now(),str(order_id),cutoff)).fetchone()
    if not claimed:
        return "already_processing"
    try:
        paid=ns["ip_mark_paid"](int(record["linked_intro_id"]),str(order_id))
        if not paid:
            # A charge can settle after the 30-minute pair reservation expires.
            # Never silently strand a verified buyer in a permanent retry loop.
            prior=ns["one"]("SELECT status FROM intro_orders WHERE id=?",
                            (int(record["linked_intro_id"]),))
            if prior and str(prior["status"]) in ("expired","closed"):
                if credit_intro(db,order_id):
                    with db() as c:
                        c.execute("""UPDATE web_purchase_bindings SET binding_status='credited',
                           delivered_at=?,updated_at=? WHERE billing_order_id=? AND
                           binding_status='sending'""",(_now(),_now(),str(order_id)))
                    return "credit_issued"
            raise RuntimeError("reserved introduction not eligible")
        if not ns["ready"].wait(timeout=4):
            raise RuntimeError("Telegram bot not ready")
        buyer,target=int(record["buyer_user_id"]),int(record["target_user_id"])
        a,b=ns["profile"](buyer),ns["profile"](target)
        if not a or not b or not ns["eligible"](a,b):
            raise RuntimeError("pair no longer eligible")
        future=asyncio.run_coroutine_threadsafe(
            ns["cr_send_request"](SimpleNamespace(bot=ns["bot"].bot),
                                  buyer,target,int(ns["score"](a,b))),
            ns["loop"])
        status,request_id=future.result(timeout=25)
        if status not in ("sent","pending","accepted"):
            raise RuntimeError("Telegram did not confirm delivery")
        ns["ip_mark_request_sent"](int(record["linked_intro_id"]))
        with db() as c:
            c.execute("""UPDATE web_purchase_bindings SET binding_status='delivered',
                         delivered_at=?,updated_at=? WHERE billing_order_id=?
                         AND binding_status='sending'""",(_now(),_now(),str(order_id)))
        try:
            ns["audit"](buyer,"web_paid_intro_delivered",{
                "order_id":order_id,"target_user_id":target,
                "request_id":request_id,"delivery_status":status})
        except Exception:
            pass
        return "delivered"
    except Exception as exc:
        # Do not claim a completed service when Telegram was down. The order
        # stays bank-paid, so customer support can recover without recharging.
        print("[web-intro] fulfillment pending retry: "+type(exc).__name__,flush=True)
        with db() as c:
            c.execute("""UPDATE web_purchase_bindings SET binding_status='retry',
                         updated_at=? WHERE billing_order_id=?
                         AND binding_status='sending'""",(_now(),str(order_id)))
        return "retry"

def resolve_intro(ns, buyer, target, accepted):
    """Called on recipient's Telegram accept/decline; free requests are unaffected."""
    db=ns["db"]
    with db() as c:
        bound=c.execute("""SELECT b.* FROM web_purchase_bindings b
            JOIN billing_web_orders o ON o.order_id=b.billing_order_id
            WHERE b.sku='contact' AND b.buyer_user_id=? AND b.target_user_id=?
              AND b.binding_status='delivered' AND o.status='paid'
              AND o.amount_kopecks=10000 AND o.currency_code='643'
            ORDER BY b.delivered_at DESC LIMIT 1""",(int(buyer),int(target))).fetchone()
    if not bound:
        return False
    record=ns["one"]("SELECT status FROM intro_orders WHERE id=?",
                     (int(bound["linked_intro_id"]),))
    if not record or str(record["status"]) not in ("awaiting_response","paid"):
        return False
    ns["ip_finish"](int(bound["linked_intro_id"]),bool(accepted))
    if not accepted:
        credit_intro(db,bound["billing_order_id"])
    return True

def grant_expired_credits(ns):
    """Grant exactly one replacement attempt when a paid recipient never replies."""
    db=ns["db"]
    with db() as c:
        items=c.execute("""SELECT b.billing_order_id FROM web_purchase_bindings b
            JOIN intro_orders i ON i.id=b.linked_intro_id
            JOIN billing_web_orders o ON o.order_id=b.billing_order_id
            WHERE b.sku='contact' AND b.binding_status='delivered'
              AND i.status='expired' AND i.credit_reissued=1
              AND o.status='paid' AND o.amount_kopecks=10000
              AND o.currency_code='643' LIMIT 30""").fetchall()
    n=0
    for r in items:
        if credit_intro(db,r["billing_order_id"]):n+=1
    return n

def verify_and_fulfill(ns, order_id):
    from ozon_web_checkout import _verify
    with ns["db"]() as c:
        order=c.execute("SELECT * FROM billing_web_orders WHERE order_id=?",
                        (str(order_id),)).fetchone()
    if not order:return "missing"
    state=_verify(order,ns["db"])
    if state=="paid":
        record=_row(ns["db"],order_id)
        if record and record["sku"]=="contact":
            return fulfill_intro(ns,order_id)
        if record and record["sku"]=="premium":
            from web_product_access import grant_premium
            return "premium_delivered" if grant_premium(ns["db"],order_id) else "premium_failed"
    return state
