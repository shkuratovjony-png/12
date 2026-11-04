"""Web-only, single-response AI conversation coaching, 900 RUB.

No bank charge is created until SOVPALI_WEB_COACH_LIVE=1 and a working AI
API key exists. Each verified payment buys one personalized AI reply with
alternatives and rationale. The source message is never stored by Sovpali;
the completed report is encrypted at rest. A repeated request for the same
purchase replays the encrypted result, never charges or regenerates.
"""
import base64
import hashlib
import html
import json
import os
import secrets
from datetime import datetime,timezone
from urllib.parse import urlsplit

import requests
from cryptography.fernet import Fernet
from flask import abort,make_response,redirect,request,session
from coach_web import _authorized, _ids, coach_link
from pair_web import _ser

def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def live():
    return (os.getenv("SOVPALI_WEB_COACH_LIVE","0")=="1"
            and bool(os.getenv("OPENAI_API_KEY","").strip())
            and os.getenv("OZON_PAY_MODE","disabled").lower()=="live")

def _cipher(secret):
    key=base64.urlsafe_b64encode(hashlib.sha256(str(secret).encode()).digest())
    return Fernet(key)

def _schema(db):
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS web_coach_reports (
          billing_order_id TEXT PRIMARY KEY,
          encrypted_report TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        """)

def unspent(db,buyer,target):
    with db() as c:
        return c.execute("""SELECT b.billing_order_id FROM web_purchase_bindings b
             JOIN billing_web_orders o ON o.order_id=b.billing_order_id
             WHERE b.buyer_user_id=? AND b.target_user_id=? AND b.sku='coach'
               AND o.product_key='coach' AND o.amount_kopecks=90000
               AND o.currency_code='643' AND o.status='paid'
               AND b.binding_status='reserved'
             ORDER BY o.created_at ASC LIMIT 1""",
             (int(buyer),int(target))).fetchone()

def _ai_request(message,profile):
    """OpenAI Responses API, no stored conversation and no external tools."""
    key=os.getenv("OPENAI_API_KEY","").strip()
    if not key:raise ValueError("AI key not configured")
    model=os.getenv("SOVPALI_AI_MODEL","gpt-4.1-mini").strip()
    if not model or len(model)>90 or not all(ch.isalnum() or ch in "-_." for ch in model):
        raise ValueError("Invalid model name")
    instructions=(
       "Ты тактичный русскоязычный помощник для добровольного общения после знакомства. "
       "Собеседник ответил на сообщение. Не диагностируй, не утверждай, что знаешь скрытые чувства. "
       "Если в тексте отказ, просьба прекратить общение, насилие или грубые границы, предложи уважить отказ. "
       "Не помогай давить, обманывать, навязываться или преследовать. "
       "Ответ дай на русском, компактно: 1) что ответ означает буквально, без догадок, "
       "2) один естественный ответ своими словами, 3) два варианта по тону, "
       "4) одна рекомендация, когда вообще лучше не писать. "
       "Не используй личную информацию, кроме той, которую пользователь явно предоставил."
    )
    content=("Добровольно присланный пользователем текст ответа партнёра:\n"+
             str(message)+"\n\nКонтекст их совместимости: "+
             json.dumps(profile,ensure_ascii=False))
    payload={"model":model,"instructions":instructions,"input":content,
             "store":False,"max_output_tokens":700}
    response=requests.post("https://api.openai.com/v1/responses",
           headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},
           json=payload,timeout=(7,40))
    response.raise_for_status()
    data=response.json()
    if not isinstance(data,dict) or data.get("status") not in (None,"completed"):
        raise ValueError("AI response incomplete")
    chunks=[]
    for item in data.get("output",[]):
        if not isinstance(item,dict):continue
        for block in item.get("content",[]):
            if isinstance(block,dict) and block.get("type")=="output_text":
                chunks.append(str(block.get("text","")))
    text="\n".join(chunks).strip()
    if len(text)<40 or len(text)>9000:
        raise ValueError("AI returned no usable guidance")
    return text

def _page(ready,csrf,paid,token):
    bankready=ready and not paid
    return """<!doctype html><html lang='ru'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><meta name='robots' content='noindex,nofollow'>
<title>Персональный разбор ответа · Совпали</title><style>
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 20% 2%,#71344d66,transparent 55%),#181219;color:#f6e5eb;font:16px/1.7 system-ui}
header{padding:22px 6%;border-bottom:1px solid #ffffff27;font-size:27px;font-weight:800}header span{color:#ecb1b9}
main{max-width:710px;margin:7vh auto;padding:24px}h1{font-size:clamp(45px,8vw,74px);line-height:1.03;letter-spacing:-.06em}em{font:italic 1em Georgia,serif;color:#edb7bf}
.card{background:#ffffff08;border:1px solid #ffffff35;padding:28px}strong{font-size:37px}
li{margin:12px 0}.methods{display:flex;gap:28px;margin:20px 0}
input{accent-color:#f1b6be}button,.btn{display:block;background:#e8b4bd;color:#28191f;border:0;padding:17px 20px;width:100%;font:700 15px system-ui;text-decoration:none;text-align:center;margin-top:20px}
button:disabled{opacity:.48;cursor:not-allowed}.muted{font-size:12px;color:#c9b4c1}a{color:#eeb7c2}
</style></head><body><header>♡ совпали<span>.</span></header>
<main><p class='muted'>ПОМОЩНИК / ПОСЛЕ РЕАЛЬНОГО ОТВЕТА</p><h1>Что написать<br><em>дальше?</em></h1>
<div class='card'><p>Одно персональное продолжение диалога на основе реального ответа человека.</p>
<div><strong>900 ₽</strong> за один подробный разбор</div>
<ul><li>Основной ответ — без давления и манипуляций.</li><li>Два альтернативных варианта.</li><li>Объяснение, какой тон уместен.</li><li>Текст ответа будет отправлен в ИИ только после твоего отдельного нажатия.</li></ul>
""" + (
        "<p>Оплата подтверждена. Вернись в конструктор и вставь реальный ответ, чтобы получить разбор.</p>"
        "<a class='btn' href='/coach/t/"+html.escape(token,quote=True)+"'>Открыть оплаченный разбор</a>"
        if paid else
        "<form action='/billing/create' method='post'>"
        "<input type='hidden' name='sku' value='coach'>"
        "<input type='hidden' name='csrf' value='"+html.escape(csrf,quote=True)+"'>"
        "<div class='methods'><label><input type='radio' name='method' value='card' checked> Картой</label>"
        "<label><input type='radio' name='method' value='sbp'> Через СБП</label></div>"
        "<button "+("" if bankready else "disabled")+">Оплатить 900 ₽</button></form>"
        ) + """<p class='muted'>""" + (
        "ИИ и банк подключены. Оплата разовая, без автопродления."
        if ready else
        "Платный ИИ пока не включён. Списание 900 ₽ недоступно."
        ) + """</p></div></main></body></html>"""

def register_web_coach(app,ns):
    db=ns["db"]
    _schema(db)
    ns["web_coach_live"]=live
    ns["web_coach_validate"]=lambda token:_authorized(token,ns)
    ns["web_coach_unspent"]=lambda v,c:unspent(db,v,c)
    ns["web_coach_reports_ready"]=lambda v,c:live()

    @app.get("/billing/coach/<token>")
    def coach_checkout(token):
        v,c,a,b=_authorized(token,ns)
        pair_token=_ser(ns["FLASK_SECRET"]).dumps({"v":v,"c":c})
        if session.get("billing_coach_token")!=token:
            session["billing_nonce"]=secrets.token_urlsafe(32)
        session["billing_coach_token"]=token
        session["billing_pair_token"]=pair_token
        session["billing_csrf"]=session.get("billing_csrf") or secrets.token_urlsafe(32)
        # Authenticated buyer is required for paid AI report.
        claim=ns.get("web_owner_claim")
        if not callable(claim) or not claim(v):
            abort(403)
        bank_ready=ns.get("web_checkout_ready")
        html_data=_page(live() and callable(bank_ready) and bool(bank_ready()),
                        session["billing_csrf"],bool(unspent(db,v,c)),token)
        resp=make_response(html_data)
        resp.headers["Cache-Control"]="private,no-store"
        resp.headers["X-Robots-Tag"]="noindex,nofollow"
        return resp

    @app.post("/coach/api/ai/<token>")
    def coach_ai(token):
        if not live():abort(503)
        if request.content_length and request.content_length>3500:abort(413)
        origin=request.headers.get("Origin","").rstrip("/")
        if origin and origin!="https://one2-1o22.onrender.com":
            abort(403)
        if request.headers.get("Sec-Fetch-Site","") not in ("","same-origin","none"):
            abort(403)
        v,c,a,b=_authorized(token,ns)
        if session.get("billing_coach_token")!=token or not ns.get("web_owner_verified",lambda uid:False)(v):
            abort(403)
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict) or payload.get("consent") is not True:
            abort(400)
        received=payload.get("reply")
        if not isinstance(received,str):abort(400)
        received=received.strip()
        if not 3<=len(received)<=1600:abort(400)
        csrf=payload.get("csrf","")
        expected=session.get("billing_csrf","")
        if not csrf or not expected or not isinstance(csrf,str) or not __import__("hmac").compare_digest(csrf,expected):
            abort(403)
        row=unspent(db,v,c)
        if not row:
            return {"ok":False,"message":"Оплаченный разбор не найден. Открой оплату из своей анкеты."},402
        order_id=row["billing_order_id"]
        with db() as cdb:
            claimed=cdb.execute("""UPDATE web_purchase_bindings SET
                binding_status='processing',updated_at=? WHERE billing_order_id=?
                AND binding_status='reserved' RETURNING billing_order_id""",
                (_utc(),order_id)).fetchone()
        if not claimed:
            return {"ok":False,"message":"Разбор уже формируется. Обнови страницу позже."},409
        context={"candidate_goal":str(b["goal"])[:90],
                 "candidate_priority":str(b["priority"])[:90],
                 "requester_goal":str(a["goal"])[:90]}
        try:
            report=_ai_request(received,context)
            cipher=_cipher(ns["FLASK_SECRET"]).encrypt(report.encode()).decode()
            with db() as cdb:
                cdb.execute("""INSERT INTO web_coach_reports
                  (billing_order_id,encrypted_report,created_at) VALUES(?,?,?)""",
                  (order_id,cipher,_utc()))
                cdb.execute("""UPDATE web_purchase_bindings SET
                  binding_status='delivered',delivered_at=?,updated_at=?
                  WHERE billing_order_id=? AND binding_status='processing'""",
                  (_utc(),_utc(),order_id))
                cdb.execute("""INSERT INTO web_product_grants
                  (billing_order_id,buyer_user_id,sku,granted_at,details)
                  VALUES(?,?,'coach',?,'AI response delivered') ON CONFLICT(billing_order_id) DO NOTHING""",
                  (order_id,v,_utc()))
        except (requests.RequestException,ValueError,Exception) as exc:
            app.logger.warning("Coach AI completion failed: %s",type(exc).__name__)
            with db() as cdb:
                cdb.execute("""UPDATE web_purchase_bindings SET binding_status='reserved',
                     updated_at=? WHERE billing_order_id=? AND binding_status='processing'""",
                     (_utc(),order_id))
            return {"ok":False,"message":"ИИ пока не ответил. Оплата сохранена; повтори запрос без доплаты."},503
        response=make_response({"ok":True,"report":report,"message":"Персональный разбор готов."})
        response.headers["Cache-Control"]="private,no-store"
        return response

    @app.get("/coach/api/report/<token>")
    def coach_saved_report(token):
        v,c,a,b=_authorized(token,ns)
        if not ns.get("web_owner_verified",lambda uid:False)(v):
            abort(403)
        with db() as cdb:
            report=cdb.execute("""SELECT r.encrypted_report
                FROM web_coach_reports r
                JOIN web_purchase_bindings b ON b.billing_order_id=r.billing_order_id
                JOIN billing_web_orders o ON o.order_id=b.billing_order_id
                WHERE b.buyer_user_id=? AND b.target_user_id=? AND b.sku='coach'
                  AND b.binding_status='delivered' AND o.status='paid'
                  AND o.amount_kopecks=90000 AND o.currency_code='643'
                ORDER BY r.created_at DESC LIMIT 1""",(v,c)).fetchone()
        if not report:
            return {"ok":False,"report":None},404
        try:
            guidance=_cipher(ns["FLASK_SECRET"]).decrypt(
                report["encrypted_report"].encode()).decode()
        except Exception:
            abort(503)
        response=make_response({"ok":True,"report":guidance})
        response.headers["Cache-Control"]="private,no-store"
        return response
