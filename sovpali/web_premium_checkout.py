"""Personal Premium purchase page and member-only explicit-interest list.

No charge is enabled until SOVPALI_WEB_PREMIUM_LIVE=1 and Ozon API is ready.
One purchase grants 30 calendar days (no automatic recurring billing).
"""
import html
import os
import secrets
from flask import abort, make_response, request, session
from web_contact_checkout import _pair, _no_cache
from web_product_access import premium_active, premium_expires

def live():
    return os.getenv("SOVPALI_WEB_PREMIUM_LIVE","0")=="1"

def _page(token,ns,uid,csrf):
    db=ns["db"]
    expiry=premium_expires(db,uid)
    already=premium_active(db,uid)
    ready=bool(ns.get("web_checkout_ready",lambda:False)()) and live()
    if already:
        price="<strong>Premium активен</strong>"
        form=("<p>Доступ действует до "+html.escape(str(expiry)[:10])+ ".</p>"
              "<a class='btn' href='/billing/premium/interests/"+html.escape(token,quote=True)+"'>Посмотреть, кто проявил интерес</a>")
    else:
        price="<strong>1 200 ₽</strong> <small>за 30 дней</small>"
        form=(
            "<form method='post' action='/billing/create'>"
            "<input type='hidden' name='csrf' value='"+html.escape(csrf,quote=True)+"'>"
            "<input type='hidden' name='sku' value='premium'>"
            "<label><input type='radio' name='method' value='card' checked> Картой</label>"
            "<label><input type='radio' name='method' value='sbp'> СБП</label>"
            "<button "+("" if ready else "disabled")+">Оформить Premium</button></form>")
    status=("Premium подключён: защищённый доступ к контактным запросам и явно проявившим интерес."
            if already else "Оплата Premium пока не включена. Деньги за этот продукт не списываются."
            if not ready else "Стоимость 1 200 ₽ за 30 дней без автоматического продления.")
    return """<!doctype html><html lang='ru'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><meta name='robots' content='noindex,nofollow'><title>Premium · Совпали</title>
<style>*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 75% 4%,#6234495e,transparent 50%),#171119;color:#f5e7ec;font:16px/1.7 system-ui}
header{padding:24px 6%;font-size:28px;font-weight:800;border-bottom:1px solid #ffffff2c}header span{color:#edb5bc}
main{max-width:720px;margin:7vh auto;padding:26px}h1{font-size:clamp(50px,8vw,81px);letter-spacing:-.06em;line-height:1.02}
h1 em{font:400 italic 1em Georgia,serif;color:#ebb1bc}.card{background:#ffffff08;border:1px solid #ffffff30;padding:30px}
strong{font-size:37px}small{font-size:13px;color:#bfaebb}li{margin:12px 0}label{margin:0 20px 0 0;display:inline-block}
button,.btn{display:block;background:#e9b3bc;color:#281c23;padding:16px 22px;text-decoration:none;border:0;margin-top:24px;font:700 16px system-ui;cursor:pointer;text-align:center}
button:disabled{opacity:.5;cursor:not-allowed}p.note{font-size:12px;color:#bbaab6}a{color:#eeb6bd}
</style></head><body><header>♡ совпали<span>.</span></header><main><h1>Больше возможностей.<br><em>Без спешки.</em></h1>
<div class='card'><div>PREMIUM / 30 ДНЕЙ</div>""" + price + """
<ul><li>Запросы на знакомство без отдельной оплаты, пока действует подписка.</li>
<li>Список пользователей, которые явно предложили тебе знакомство.</li>
<li>Контакты открываются только после взаимного согласия.</li>
</ul><p class='note'>""" + html.escape(status) + """</p>""" + form + """
<p class='note'>Оплата разовая, без автоматического списания в следующем месяце. Это услуга веб-сервиса.</p>
</div></main></body></html>"""

def register_web_premium(app,ns):
    db=ns["db"]
    ns["web_premium_live"]=live

    @app.get("/billing/premium/<token>")
    def premium_checkout(token):
        uid,target,a,b=_pair(ns,token)
        if session.get("billing_pair_token")!=token:
            session["billing_nonce"]=secrets.token_urlsafe(32)
        session["billing_pair_token"]=token
        session["billing_csrf"]=session.get("billing_csrf") or secrets.token_urlsafe(32)
        claim=ns.get("web_owner_claim")
        if not callable(claim) or not claim(uid):
            abort(403)
        return _no_cache(make_response(_page(token,ns,uid,session["billing_csrf"])))

    @app.get("/billing/premium/interests/<token>")
    def premium_interests(token):
        uid,target,a,b=_pair(ns,token)
        if session.get("billing_pair_token")!=token or not ns.get("web_owner_verified",lambda uid:False)(uid):
            abort(403)
        if not premium_active(db,uid):
            abort(403)
        one=ns["many"]
        requests=one("""SELECT cr.requester_user_id, cr.status, p.name,p.city
                FROM communication_requests cr
                JOIN profiles p ON p.user_id=cr.requester_user_id
                WHERE cr.target_user_id=? AND cr.status IN ('pending','accepted')
                ORDER BY cr.created_at DESC LIMIT 50""",(uid,))
        cards=[]
        for r in requests:
            name=html.escape(str(r["name"])[:80])
            city=html.escape(str(r["city"])[:80])
            state="Согласие уже подтверждено" if r["status"]=="accepted" else "Хочет познакомиться"
            cards.append("<li><b>"+name+"</b> · "+city+"<p>"+state+"</p></li>")
        if not cards:
            cards=["<li>Пока никто не отправлял тебе запрос. Когда появится явный интерес, он будет здесь.</li>"]
        markup="""<!doctype html><html lang='ru'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<meta name='robots' content='noindex,nofollow'><title>Интересующиеся · Совпали</title>
<style>body{background:#181219;color:#f5e6e9;font:16px/1.7 system-ui;max-width:680px;margin:8vh auto;padding:24px}a{color:#eeb5be}li{padding:18px;border-bottom:1px solid #ffffff35}</style>
<h1>Кто проявил интерес</h1><p>Показываем только людей, которые сами отправили запрос на знакомство.</p><ul>"""+ "".join(cards) + "</ul><a href='/billing/premium/"+html.escape(token,quote=True)+"'>Назад к Premium</a>"
        return _no_cache(make_response(markup))
