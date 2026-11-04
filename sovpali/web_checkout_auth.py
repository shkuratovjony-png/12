"""Bank checkout owner verification by a one-time code sent to the user's Telegram.

Each browser gets a cryptographically random session ID and a one-time code.
OTP is never logged or returned to the browser; DB limits resend frequency
per Telegram user, not just per browser. Used for web purchases and credits.
"""
import hashlib
import hmac
import html
import os
import secrets
import asyncio
from datetime import datetime, timezone, timedelta
from flask import abort, redirect, request, session, make_response

def _now():return datetime.now(timezone.utc)
def _iso(dt):return dt.isoformat(timespec="seconds")
def _hash(secret, sessid, uid, code):
    return hmac.new(str(secret).encode(), f"{sessid}|{uid}|{code}".encode(), hashlib.sha256).hexdigest()

def _schema(db):
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS web_checkout_auth_codes(
           browser_id TEXT PRIMARY KEY,
           buyer_user_id BIGINT NOT NULL,
           code_hash TEXT NOT NULL,
           sent_at TEXT NOT NULL,
           expires_at TEXT NOT NULL,
           tries INTEGER NOT NULL DEFAULT 0,
           verified_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_web_checkout_auth_buyer
           ON web_checkout_auth_codes(buyer_user_id,sent_at);
        """)

def is_verified(buyer_id):
    if session.get("billing_authenticated_uid") != int(buyer_id):
        return False
    try:
        exp=datetime.fromisoformat(session.get("billing_auth_until",""))
        return exp > _now()
    except (TypeError,ValueError):
        return False

def _headers(resp):
    resp.headers["Cache-Control"]="private,no-store"
    resp.headers["X-Robots-Tag"]="noindex,nofollow"
    return resp

def login_form(token, csrf, sent=False):
    action="/billing/auth/start/"+token
    verify="/billing/auth/verify/"+token
    return """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Подтверждение · Совпали</title>
<meta name="robots" content="noindex,nofollow">
<style>*{box-sizing:border-box}body{margin:0;background:#181219;color:#f8e6ec;font:16px system-ui}
main{max-width:490px;margin:13vh auto;padding:26px}h1{font-size:37px;line-height:1.14}
p{color:#beadb7;line-height:1.8}form{margin:24px 0}button{border:0;background:#e5adb6;padding:15px 19px;font:700 15px system-ui;cursor:pointer;width:100%}
input{width:100%;padding:15px;font-size:22px;letter-spacing:6px;background:#282029;border:1px solid #e5adb680;color:#fff;margin-bottom:13px}
small{color:#baabb5}</style></head><body><main><div>♡ совпали.</div>
<h1>Подтверди, что это твоя анкета</h1>
<p>Код придёт в личный чат с ботом «Совпали». Его не нужно никому пересылать.
Деньги до подтверждения не списываются.</p>""" + (
        """<form method="post" action=\"""" + html.escape(verify,quote=True) +
        """\"><input type="hidden" name="csrf" value=\"""" + html.escape(csrf,quote=True) +
        """\"><label for="code">Код из Telegram</label><input id="code" name="code" type="text"
        inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required autocomplete="one-time-code">
        <button type="submit">Подтвердить и перейти к покупке</button></form>"""
        if sent else
        """<form method="post" action=\"""" + html.escape(action,quote=True) +
        """\"><input type="hidden" name="csrf" value=\"""" + html.escape(csrf,quote=True) +
        """\"><button type="submit">Получить код в Telegram</button></form>"""
    ) + """<small>Код действует 10 минут. Действия подтверждаются в защищённой веб-сессии.</small>
</main></body></html>"""

def register_web_checkout_auth(app,ns):
    db=ns["db"]
    _schema(db)
    ns["web_owner_verified"]=is_verified

    def context(token):
        from web_contact_checkout import _pair
        if session.get("billing_pair_token") != token:
            abort(403)
        return _pair(ns,token)

    def check_csrf():
        from ozon_web_checkout import _csrf_ok
        if not _csrf_ok():
            abort(403)

    def auth_page(token, sent=False):
        return _headers(make_response(login_form(token,session.get("billing_csrf",""),sent)))

    ns["web_owner_auth_page"]=auth_page

    @app.post("/billing/auth/start/<token>")
    def auth_start(token):
        check_csrf()
        uid,_,_,_=context(token)
        browser_id=session.setdefault("web_auth_browser_id",secrets.token_urlsafe(32))
        n=_now()
        hour=_iso(n-timedelta(hours=1))
        with db() as c:
            rows=c.execute("""SELECT sent_at FROM web_checkout_auth_codes
                       WHERE buyer_user_id=? AND sent_at>? ORDER BY sent_at DESC""",
                       (uid,hour)).fetchall()
            if len(rows)>=5:
                return _headers(make_response("Слишком много попыток. Повтори позже.",429))
            if rows:
                last=datetime.fromisoformat(rows[0]["sent_at"])
                if (n-last).total_seconds()<60:
                    return _headers(make_response("Код уже отправляли. Проверь Telegram.",429))
        if not ns["ready"].wait(timeout=5):
            return _headers(make_response("Telegram временно недоступен.",503))
        code=f"{secrets.randbelow(1000000):06d}"
        secret=ns["FLASK_SECRET"]
        code_hash=_hash(secret,browser_id,uid,code)
        expires=_iso(n+timedelta(minutes=10))
        with db() as c:
            c.execute("""INSERT INTO web_checkout_auth_codes
               (browser_id,buyer_user_id,code_hash,sent_at,expires_at,tries)
               VALUES(?,?,?,?,?,0) ON CONFLICT(browser_id)
               DO UPDATE SET buyer_user_id=excluded.buyer_user_id,code_hash=excluded.code_hash,
                 sent_at=excluded.sent_at,expires_at=excluded.expires_at,tries=0,verified_at=NULL""",
              (browser_id,uid,code_hash,_iso(n),expires))
        try:
            tg=ns["user"](uid)
            message=("🔐 Код подтверждения «Совпали»: <b>"+code+"</b>\\n\\n"
                     "Введи его на сайте, чтобы привязать покупку к своей анкете.\\n"
                     "Никому не сообщай этот код.")
            future=asyncio.run_coroutine_threadsafe(
                ns["bot"].bot.send_message(int(tg["tg_id"]),message,parse_mode="HTML"),
                ns["loop"])
            future.result(timeout=12)
        except Exception as exc:
            print("[checkout-auth] Telegram code send failed "+type(exc).__name__,flush=True)
            with db() as c:
                c.execute("DELETE FROM web_checkout_auth_codes WHERE browser_id=?",(browser_id,))
            return _headers(make_response("Не удалось отправить код. Попробуй ещё раз.",503))
        session["web_auth_last_sent"]="1"
        return redirect(session.get("billing_after_auth") or "/billing/contact/"+token,code=303)

    @app.post("/billing/auth/verify/<token>")
    def auth_verify(token):
        check_csrf()
        uid,_,_,_=context(token)
        code=request.form.get("code","")
        if len(code)!=6 or not code.isdigit():
            abort(400)
        browser_id=session.get("web_auth_browser_id","")
        if not browser_id:
            abort(403)
        with db() as c:
            row=c.execute("""SELECT * FROM web_checkout_auth_codes WHERE browser_id=?
                       AND buyer_user_id=?""",(browser_id,uid)).fetchone()
            if not row:abort(403)
            if row["verified_at"] or int(row["tries"])>=5 or datetime.fromisoformat(row["expires_at"])<=_now():
                abort(403)
            c.execute("UPDATE web_checkout_auth_codes SET tries=tries+1 WHERE browser_id=?",(browser_id,))
            valid=hmac.compare_digest(row["code_hash"],_hash(ns["FLASK_SECRET"],browser_id,uid,code))
            if not valid:
                return _headers(make_response("Неверный код. Проверь сообщение от бота.",403))
            c.execute("UPDATE web_checkout_auth_codes SET verified_at=? WHERE browser_id=?",(_iso(_now()),browser_id))
        session["billing_authenticated_uid"]=uid
        session["billing_auth_until"]=_iso(_now()+timedelta(hours=12))
        return redirect(session.get("billing_after_auth") or "/billing/contact/"+token,code=303)
