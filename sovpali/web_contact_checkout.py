"""Separate first paid product: web-initiated 100-RUB introduction.

Feature-flagged off until verified delivery, fallback and checkout terms are
fully tested. Never sells a Telegram in-app invoice and never discloses a
contact without the other person's explicit consent.
"""
import html
import os
import secrets
import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from flask import abort, make_response, request, session, redirect
from web_product_access import available_intro_credit, redeem_intro_credit, restore_intro_credit
from pair_web import _load as load_pair_token
from web_product_access import ensure_schema, premium_active

def live():
    return os.getenv("SOVPALI_WEB_CONTACTS_LIVE", "0") == "1"

def _pair(ns, token):
    if not isinstance(token,str) or len(token)>1200:abort(404)
    try:
        viewer,target=load_pair_token(token,ns["FLASK_SECRET"])
    except Exception:
        abort(404)
    if viewer == target:abort(404)
    viewer_profile,target_profile=ns["profile"](viewer),ns["profile"](target)
    if not viewer_profile or not target_profile:abort(404)
    if not ns["eligible"](viewer_profile,target_profile):abort(404)
    for uid in (viewer,target):
        obj=ns["user"](uid)
        if not obj or int(obj["is_banned"]):abort(404)
    return viewer,target,viewer_profile,target_profile

def _receipt_page(buyer,target,free,ready,csrf,token):
    name=html.escape(str(target["name"])[:55])
    city=html.escape(str(target["city"])[:55])
    status=("Ты уже пользуешься Premium: отдельная оплата не нужна." if free else
           "Сервис оплаты доступен. Ты увидишь точную сумму на странице Ozon Pay." if ready else
           "Оплата временно недоступна. Запрос не отправлен и деньги не списаны.")
    form=(
        '<form action="/billing/create" method="post">'
        '<input type="hidden" name="sku" value="contact">'
        '<input type="hidden" name="csrf" value="'+html.escape(csrf,quote=True)+'">'
        '<div class="methods"><label><input name="method" value="card" type="radio" checked> Картой</label>'
        '<label><input name="method" value="sbp" type="radio"> Через СБП</label></div>'
        '<button type="submit" '+('' if ready and not free else 'disabled')+'>Оплатить 100 ₽</button></form>'
        if not free else
        '<form method="post" action="/billing/contact/redeem/'+html.escape(token,quote=True)+'">'
        '<input type="hidden" name="csrf" value="'+html.escape(csrf,quote=True)+'">'
        '<button type="submit">Отправить запрос без оплаты</button></form>'
    )
    return ('''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>Открыть знакомство · Совпали</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;color:#f7ebee;background:radial-gradient(ellipse at 10% 2%,#6a354b60,transparent 54%),#17111a;font:15px/1.65 system-ui,Arial}
header{padding:22px 6%;border-bottom:1px solid #ffffff2b;font-size:26px;font-weight:750}header span{color:#ecb5bc}
main{max-width:680px;margin:auto;padding:55px 6% 85px}h1{font-size:clamp(44px,8vw,70px);line-height:1.04;letter-spacing:-.06em}h1 em{font-family:Georgia,serif;font-weight:400;color:#ecb5bc}
.intro{font-size:17px;color:#dccbd4}.card{border:1px solid #ffffff35;background:#ffffff0a;padding:28px;margin-top:28px}
.price{font-size:48px;font-weight:700;color:#f4c0c6;margin:5px 0 20px}li{margin:12px 0}label{cursor:pointer}
.methods{display:flex;gap:22px;margin:25px 0}input{accent-color:#efb5ba}button{background:#e8aeb8;padding:18px 24px;width:100%;border:0;color:#271820;font:700 15px system-ui;cursor:pointer}
button:disabled{opacity:.5;cursor:not-allowed}.note{color:#c0acb6;font-size:12px}a{color:#f5c1c5}
</style></head><body><header>♡ совпали<span>.</span></header><main>
<p class="note">ПЕРСОНАЛЬНОЕ ЗНАКОМСТВО · ВЕБ-СЕРВИС</p><h1>Первый шаг<br><em>навстречу.</em></h1>
<p class="intro">Предложи знакомство: <b>''' + name + '''</b>, '''+city+'''.</p>
<div class="card"><div class="note">ЗАПРОС НА ЗНАКОМСТВО</div><div class="price">''' + ("0 ₽" if free else "100 ₽") + '''</div>
<ul><li>После подтверждения платежа запрос отправится второй стороне.</li>
<li>Контакт откроется только при её добровольном согласии.</li>
<li>При отказе или отсутствии ответа в течение 24 часов предоставим один повторный запрос без доплаты. Возврат денег — по условиям оферты.</li></ul>
<p class="note">'''+html.escape(status)+'''</p>'''+form+'''<p class="note">Оформляя заказ, ты подтверждаешь согласие с условиями покупки. Сервис не гарантирует взаимности.</p>
<p><a href="/billing/premium/''' + html.escape(token,quote=True) + '''">Узнать про Premium · 1 200 ₽ / 30 дней</a></p></div></main></body></html>''')

def register_contact_product(app,ns):
    db=ns["db"]
    ensure_schema(db)
    ns["web_contact_validate"] = lambda token: _pair(ns,token)
    ns["web_contact_live"] = live
    ns["web_premium_active"] = lambda uid: premium_active(db, uid)
    ns["web_contact_credit_available"] = lambda uid: bool(available_intro_credit(db,uid))

    @app.get("/billing/contact/<token>")
    def web_contact_checkout(token):
        v,c,a,b=_pair(ns,token)
        # This page can be opened by a Telegram deep link, but is a
        # standalone website purchase, not a Telegram in-app checkout.
        previous=ns.get("cr_between")
        row=previous(v,c) if callable(previous) else None
        if row and str(row["status"]) in ("pending","accepted"):
            return _no_cache(make_response(
                "<!doctype html><meta charset='utf-8'><h2>Запрос уже существует</h2>"
                "<p>Повторно оплачивать его не нужно.</p>"
                "<a href='/s'>На сайт «Совпали»</a>"))
        if session.get("billing_pair_token")!=token:
            session["billing_nonce"]=secrets.token_urlsafe(32)
        session["billing_pair_token"]=token
        session["billing_csrf"]=session.get("billing_csrf") or secrets.token_urlsafe(32)
        session["billing_after_auth"]="/billing/contact/"+token
        if live() and not ns.get("web_owner_verified",lambda uid:False)(v):
            auth=ns.get("web_owner_auth_page")
            if callable(auth):
                return auth(token, bool(session.get("web_auth_last_sent")))
            return _no_cache(make_response("Подтверждение владельца временно недоступно.",503))
        free=premium_active(db,v) or bool(available_intro_credit(db,v))
        ready=bool(ns.get("web_checkout_ready",lambda:False)()) and live()
        return _no_cache(make_response(_receipt_page(v,b,free,ready,session["billing_csrf"],token)))

    @app.post("/billing/contact/redeem/<token>")
    def redeem_web_contact(token):
        if not live():
            abort(403)
        from ozon_web_checkout import _csrf_ok
        if not _csrf_ok() or session.get("billing_pair_token")!=token:
            abort(403)
        buyer,target,a,b=_pair(ns,token)
        if not ns.get("web_owner_verified",lambda uid:False)(buyer):
            abort(403)
        existing=ns.get("cr_between")
        active=existing(buyer,target) if callable(existing) else None
        if active and str(active["status"]) in ("pending","accepted"):
            return _no_cache(make_response("Запрос уже существует. Повтор не требуется.",409))
        membership=premium_active(db,buyer)
        if not membership and not available_intro_credit(db,buyer):
            return _no_cache(make_response("Нет доступного повторного запроса.",403))
        status, reserved=ns["ip_reserve_intro"](buyer,target,100)
        if status!="reserved" or not reserved:
            return _no_cache(make_response("Пара временно занята. Ничего не списано.",409))
        intro_id=int(reserved["id"])
        claim="web-credit-"+str(intro_id)
        source=None
        if not membership:
            source=redeem_intro_credit(db,buyer,claim)
            if not source:
                ns["ip_close"](intro_id)
                return _no_cache(make_response("Повторный запрос уже использован.",409))
        try:
            if not ns["ready"].wait(timeout=4):
                raise RuntimeError("bot unavailable")
            fut=asyncio.run_coroutine_threadsafe(
                ns["cr_send_request"](SimpleNamespace(bot=ns["bot"].bot),
                                       buyer,target,int(ns["score"](a,b))),
                ns["loop"])
            state,req_id=fut.result(timeout=25)
            if state not in ("sent","pending","accepted"):
                raise RuntimeError("delivery not confirmed")
            # Voucher and Premium are free entitlements, not bank-paid orders.
            # Keep the recipient's consent window, but never forge paid_at.
            expires=ns["ip_iso"](ns["ip_now"]()+timedelta(hours=24))
            ns["execute"]("""UPDATE intro_orders SET status='awaiting_response',
                             reservation_expires_at=NULL,response_expires_at=?
                             WHERE id=? AND status='reserved'""",(expires,intro_id))
            try:
                ns["audit"](buyer,"web_free_intro_delivered",{
                    "target_user_id":target,"intro_id":intro_id,"premium":membership,
                    "source_order_id":source,"request_id":req_id})
            except Exception:
                pass
            return redirect("/s/m/"+token+"#sx-start",code=303)
        except Exception as exc:
            print("[web-intro] free request delivery failed "+type(exc).__name__,flush=True)
            if source:
                restore_intro_credit(db,buyer,source,claim)
            ns["ip_close"](intro_id)
            return _no_cache(make_response(
                "Не удалось подтвердить отправку. Право на повтор сохранено, попробуй ещё раз.",503))

def _no_cache(resp):
    resp.headers["Cache-Control"]="private,no-store"
    resp.headers["Referrer-Policy"]="no-referrer"
    resp.headers["X-Robots-Tag"]="noindex,nofollow"
    resp.headers["X-Content-Type-Options"]="nosniff"
    return resp
