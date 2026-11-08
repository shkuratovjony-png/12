"""Sovpali referral program: 30% of verified RUB product charges, lifetime of the invited account.

Never pays on a browser redirect, test order, repeated callback, or unbound purchase.
Manual verified bank payouts only; no bank details or tax documents in Telegram.
"""
import html
import re
import secrets
import threading
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from flask import request,abort,make_response,session
from pair_miniapp import validate_init_data

RATE=30
HOLD_DAYS=14
MIN_PAYOUT_KOPECKS=100000
PRODUCTS={"contact":10000,"premium":120000,"coach":90000,"workshop":50000}
LOCK=threading.RLock()

def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def add_days(iso,n):
    try:return (datetime.fromisoformat(str(iso)).replace(tzinfo=timezone.utc)+timedelta(days=n)).isoformat(timespec="seconds")
    except (ValueError,TypeError):return (datetime.now(timezone.utc)+timedelta(days=n)).isoformat(timespec="seconds")

def ensure_schema(db):
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS affiliate_codes(
          partner_user_id BIGINT PRIMARY KEY, code TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS affiliate_referrals(
          referred_user_id BIGINT PRIMARY KEY, partner_user_id BIGINT NOT NULL,
          registered_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS affiliate_referrals_partner ON affiliate_referrals(partner_user_id);
        CREATE TABLE IF NOT EXISTS affiliate_rewards(
          billing_order_id TEXT PRIMARY KEY, partner_user_id BIGINT NOT NULL,
          buyer_user_id BIGINT NOT NULL, sku TEXT NOT NULL,
          amount_kopecks BIGINT NOT NULL, commission_kopecks BIGINT NOT NULL,
          accrued_at TEXT NOT NULL, available_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'earned',
          payout_request_id TEXT
        );
        CREATE INDEX IF NOT EXISTS affiliate_rewards_partner ON affiliate_rewards(partner_user_id);
        CREATE TABLE IF NOT EXISTS affiliate_payout_requests(
          request_id TEXT PRIMARY KEY, partner_user_id BIGINT NOT NULL,
          amount_kopecks BIGINT NOT NULL, legal_status TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'requested',
          requested_at TEXT NOT NULL, completed_at TEXT, bank_reference TEXT
        );
        CREATE INDEX IF NOT EXISTS affiliate_payout_partner ON affiliate_payout_requests(partner_user_id);
        """)

def ensure_code(db,uid):
    uid=int(uid)
    with db() as c:
        row=c.execute("SELECT code FROM affiliate_codes WHERE partner_user_id=?",(uid,)).fetchone()
        if row:return row["code"]
        code=secrets.token_urlsafe(9)
        c.execute("""INSERT INTO affiliate_codes(partner_user_id,code,created_at)
                     VALUES(?,?,?) ON CONFLICT(partner_user_id) DO NOTHING""",(uid,code,utc()))
        row=c.execute("SELECT code FROM affiliate_codes WHERE partner_user_id=?",(uid,)).fetchone()
        return row["code"]

def register_start(db,user,args):
    """First /start from a freshly registered account only; first touch wins."""
    if not args or len(args)!=1 or not re.fullmatch(r"ref_[A-Za-z0-9_-]{8,18}",str(args[0])):return False
    created=str(user["created_at"] or "")
    seen=str(user["last_seen_at"] or "")
    if created!=seen:return False
    try:
        age=(datetime.now()-datetime.fromisoformat(created)).total_seconds()
        if not -5<=age<=180:return False
    except (ValueError,TypeError):return False
    uid=int(user["id"])
    with db() as c:
        existing=c.execute("SELECT 1 FROM profiles WHERE user_id=?",(uid,)).fetchone()
        if existing:return False
        owner=c.execute("SELECT partner_user_id FROM affiliate_codes WHERE code=?",(str(args[0])[4:],)).fetchone()
        if not owner or int(owner["partner_user_id"])==uid:return False
        owner_id=int(owner["partner_user_id"])
        c.execute("""INSERT INTO affiliate_referrals(referred_user_id,partner_user_id,registered_at)
                     VALUES(?,?,?) ON CONFLICT(referred_user_id) DO NOTHING""",(uid,owner_id,utc()))
        return True

def accrue_paid_order(c,order_id):
    """Runs INSIDE the verified bank-status transaction, exactly once per order."""
    order=c.execute("""SELECT o.order_id,o.product_key,o.amount_kopecks,o.currency_code,o.paid_at,
           b.buyer_user_id,b.sku,r.partner_user_id
           FROM billing_web_orders o
           JOIN web_purchase_bindings b ON b.billing_order_id=o.order_id
           JOIN affiliate_referrals r ON r.referred_user_id=b.buyer_user_id
           WHERE o.order_id=? AND o.status='paid'""",(str(order_id),)).fetchone()
    if not order:return False
    sku=str(order["product_key"])
    amount=int(order["amount_kopecks"])
    if sku not in PRODUCTS or str(order["sku"])!=sku or amount!=PRODUCTS[sku] or str(order["currency_code"])!="643":
        return False
    if int(order["partner_user_id"])==int(order["buyer_user_id"]):return False
    now=utc()
    c.execute("""INSERT INTO affiliate_rewards(
       billing_order_id,partner_user_id,buyer_user_id,sku,amount_kopecks,
       commission_kopecks,accrued_at,available_at,status)
       VALUES(?,?,?,?,?,?,?,?,'earned')
       ON CONFLICT(billing_order_id) DO NOTHING""",
       (str(order_id),int(order["partner_user_id"]),int(order["buyer_user_id"]),sku,amount,
        amount*RATE//100,now,add_days(order["paid_at"] or now,HOLD_DAYS)))
    return True

def sync_partner(db,uid):
    """Recover missed notifications from already bank-verified and linked orders."""
    with db() as c:
        rows=c.execute("""SELECT o.order_id FROM billing_web_orders o
           JOIN web_purchase_bindings b ON b.billing_order_id=o.order_id
           JOIN affiliate_referrals r ON r.referred_user_id=b.buyer_user_id
           WHERE r.partner_user_id=? AND o.status='paid'
           ORDER BY o.paid_at DESC LIMIT 1000""",(int(uid),)).fetchall()
        for row in rows:accrue_paid_order(c,row["order_id"])
        # If a bank refund has been recorded in the payment table,
        # remove untransferred awards from available balance.
        c.execute("""UPDATE affiliate_rewards SET status='reversed'
          WHERE partner_user_id=? AND status='earned'
          AND EXISTS(SELECT 1 FROM billing_web_orders o
                     WHERE o.order_id=affiliate_rewards.billing_order_id AND o.status<>'paid')""",(int(uid),))

def overview(db,uid,username):
    ensure_schema(db)
    code=ensure_code(db,uid)
    sync_partner(db,uid)
    with db() as c:
        num=c.execute("SELECT COUNT(*) AS n FROM affiliate_referrals WHERE partner_user_id=?",(int(uid),)).fetchone()
        rewards=c.execute("""SELECT status,commission_kopecks,available_at,payout_request_id
                    FROM affiliate_rewards WHERE partner_user_id=?""",(int(uid),)).fetchall()
        payouts=c.execute("""SELECT request_id,amount_kopecks,status,requested_at
                   FROM affiliate_payout_requests WHERE partner_user_id=?
                   ORDER BY requested_at DESC LIMIT 12""",(int(uid),)).fetchall()
    now=utc()
    available=pending=requested=paid=total=0
    for item in rewards:
        status=str(item["status"])
        amount=int(item["commission_kopecks"])
        if status=="reversed":continue
        total+=amount
        if status=="paid":paid+=amount
        elif status=="requested" or item["payout_request_id"]:requested+=amount
        elif str(item["available_at"])<=now:available+=amount
        else:pending+=amount
    safe_username=str(username or "")
    url="https://t.me/"+safe_username+"?start=ref_"+code if re.fullmatch(r"[A-Za-z0-9_]{5,32}",safe_username) else ""
    return {"referral_url":url,"rate_percent":RATE,"invited_count":int(num["n"]),
            "total_kopecks":total,"available_kopecks":available,
            "pending_kopecks":pending,"requested_kopecks":requested,
            "paid_kopecks":paid,"hold_days":HOLD_DAYS,
            "minimum_payout_kopecks":MIN_PAYOUT_KOPECKS,
            "payout_requests":[dict(x) for x in payouts]}

def request_payout(db,uid,legal_status):
    if legal_status not in ("ip","company"):
        return None,"Для выплаты нужен договор с ИП или юридическим лицом. Другие формы сотрудничества требуют отдельного оформления."
    ensure_schema(db)
    sync_partner(db,uid)
    with LOCK:
        with db() as c:
            free=c.execute("""SELECT COALESCE(SUM(commission_kopecks),0) AS amount
              FROM affiliate_rewards WHERE partner_user_id=? AND status='earned'
              AND payout_request_id IS NULL AND available_at<=?""",(uid,utc())).fetchone()
            if int(free["amount"])<MIN_PAYOUT_KOPECKS:
                return None,"Для заявки нужно минимум 1 000 ₽ доступного вознаграждения."
            rid=secrets.token_hex(12)
            rows=c.execute("""UPDATE affiliate_rewards SET status='requested',payout_request_id=?
              WHERE partner_user_id=? AND status='earned' AND payout_request_id IS NULL
              AND available_at<=? RETURNING commission_kopecks""",(rid,uid,utc())).fetchall()
            amount=sum(int(row["commission_kopecks"]) for row in rows)
            if amount<MIN_PAYOUT_KOPECKS:raise RuntimeError("Concurrent payout claim below minimum")
            c.execute("""INSERT INTO affiliate_payout_requests
              (request_id,partner_user_id,amount_kopecks,legal_status,status,requested_at)
              VALUES(?,?,?,?,'requested',?)""",(rid,uid,amount,utc()))
    return {"id":rid,"amount_kopecks":amount,"status":"requested"},None

def mount(app,ns):
    db=ns["db"]
    ensure_schema(db)
    ns["affiliate_active"]=True
    def identity():
        try:
            tid=validate_init_data(request.headers.get("X-Telegram-Init-Data",""),ns["TOKEN"])
        except (ValueError,TypeError,KeyError):abort(401)
        user=ns["one"]("SELECT * FROM users WHERE tg_id=?",(tid,))
        if not user or int(user["is_banned"] or 0):abort(403)
        return int(user["id"])
    def safe(data,status=200):
        response=make_response(data,status)
        response.headers["Cache-Control"]="private, no-store"
        return response
    @app.post("/s/app/api/affiliate")
    def affiliate_dashboard():
        uid=identity()
        username=ns.get("MINIAPP_BOT_USERNAME") or getattr(getattr(ns.get("bot"),"bot",None),"username","")
        return safe(overview(db,uid,username))
    @app.post("/s/app/api/affiliate/request")
    def affiliate_request():
        uid=identity()
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)!={"legal_status"}:
            return safe({"message":"Неверные данные заявки."},400)
        result,error=request_payout(db,uid,body["legal_status"])
        return safe({"message":error},400) if error else safe({"request":result})
    @app.get("/admin/affiliates")
    def affiliate_admin():
        if not session.get("a"):abort(403)
        ensure_schema(db)
        csrf=session.setdefault("affiliate_admin_csrf",secrets.token_urlsafe(24))
        with db() as c:
            rows=c.execute("""SELECT p.*,u.tg_id,u.username
                 FROM affiliate_payout_requests p
                 JOIN users u ON u.id=p.partner_user_id
                 ORDER BY p.requested_at DESC LIMIT 100""").fetchall()
        parts=["<html><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Партнерские выплаты</title><style>body{font:15px system-ui;max-width:900px;margin:30px auto;padding:18px}article{padding:20px;border:1px solid #ddd;margin:16px 0;border-radius:14px}input,button{padding:10px}</style><h1>Партнёрские выплаты</h1><p>Ручная отметка после перевода с расчётного счёта и проверки документов.</p>"]
        for row in rows:
            userlabel=html.escape(str(row["username"] or row["tg_id"]))
            rub=f'{int(row["amount_kopecks"])/100:,.2f}'
            parts.append("<article><b>"+userlabel+"</b> · "+html.escape(row["legal_status"])+" · "+rub+" ₽"+
                         "<p>Статус: "+html.escape(row["status"])+"</p>")
            if row["status"]=="requested":
                parts.append("<form method='post' action='/admin/affiliates/pay'><input type='hidden' name='csrf' value='"+csrf+"'><input type='hidden' name='request_id' value='"+html.escape(row["request_id"])+"'><input required name='bank_reference' placeholder='Номер платёжного поручения'><button>Отметить выплаченной</button></form>")
            parts.append("</article>")
        return safe("".join(parts)+"</html>")
    @app.post("/admin/affiliates/pay")
    def affiliate_admin_pay():
        if not session.get("a"):abort(403)
        token=str(request.form.get("csrf") or "")
        expected=session.get("affiliate_admin_csrf")
        if not expected or not secrets.compare_digest(token,expected):abort(403)
        rid=str(request.form.get("request_id") or "")
        ref=str(request.form.get("bank_reference") or "").strip()
        if not re.fullmatch(r"[a-f0-9]{24}",rid) or not 3<=len(ref)<=80:abort(400)
        with db() as c:
            claim=c.execute("""UPDATE affiliate_payout_requests
              SET status='paid',completed_at=?,bank_reference=?
              WHERE request_id=? AND status='requested'
              RETURNING request_id""",(utc(),ref,rid)).fetchone()
            if not claim:abort(409)
            c.execute("""UPDATE affiliate_rewards SET status='paid'
              WHERE payout_request_id=? AND status='requested'""",(rid,))
        return safe("Отмечено. <a href='/admin/affiliates'>К списку выплат</a>")
