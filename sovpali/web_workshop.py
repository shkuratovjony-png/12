"""500 RUB conversation workshop, sold only for a mutually accepted pair.
Uses the existing bank ledger and signed ownership; never sends messages.
"""
import html
import os
import secrets
from flask import abort, make_response, redirect, request, session
from coach_web import _authorized
from pair_web import _ser


def paid(db, uid, cid):
    with db() as c:
        return bool(c.execute("""SELECT 1 FROM web_purchase_bindings b
          JOIN billing_web_orders o ON o.order_id=b.billing_order_id
          WHERE b.buyer_user_id=? AND b.target_user_id=?
            AND o.product_key=b.sku AND o.status='paid' AND o.currency_code='643'
            AND ((b.sku='workshop' AND o.amount_kopecks=50000)
              OR (b.sku='coach' AND o.amount_kopecks=90000)) LIMIT 1""",(uid,cid)).fetchone())


def register_workshop(app, ns):
    ns['web_workshop_live']=lambda:os.getenv('SOVPALI_WEB_WORKSHOP_LIVE','0')=='1'
    ns['web_workshop_validate']=lambda token:_authorized(token,ns)
    ns['web_workshop_paid']=lambda uid,cid:paid(ns['db'],uid,cid)

    def claim(token):
        uid,cid,a,b=_authorized(token,ns)
        session['billing_pair_token']=_ser(ns['FLASK_SECRET']).dumps({'v':uid,'c':cid})
        if not ns.get('web_owner_claim',lambda _:False)(uid):abort(403)
        return uid,cid,a,b

    @app.before_request
    def protect_workshop():
        # Demo stays public. Personal workshop requires verified ownership and payment.
        prefix=next((x for x in ('/coach/t/','/coach/api/prepare/') if request.path.startswith(x)),None)
        if not prefix:return
        token=request.path[len(prefix):]
        uid,cid,_,_=claim(token)
        if not paid(ns['db'],uid,cid):
            if request.method=='GET':return redirect('/billing/workshop/'+token,303)
            return {'ok':False,'message':'Сначала оплати доступ к эмулятору для этой пары.'},402

    @app.get('/billing/workshop/<token>')
    def workshop_checkout(token):
        uid,cid,a,b=claim(token)
        context='workshop:'+token
        if session.get('billing_product_context')!=context:
            session['billing_nonce']=secrets.token_urlsafe(32)
        session['billing_product_context']=context
        session['billing_workshop_token']=token
        session['billing_csrf']=session.get('billing_csrf') or secrets.token_urlsafe(32)
        owned=paid(ns['db'],uid,cid)
        ready=ns['web_workshop_live']() and ns.get('web_checkout_ready',lambda:False)()
        esc=lambda x:html.escape(str(x),quote=True)
        action=("<a class='button' href='/coach/t/"+esc(token)+"'>Открыть эмулятор</a>" if owned else
            "<form method='post' action='/billing/create'><input type='hidden' name='sku' value='workshop'>"
            "<input type='hidden' name='csrf' value='"+esc(session['billing_csrf'])+"'>"
            "<label><input type='radio' name='method' value='card' checked> Картой</label> "
            "<label><input type='radio' name='method' value='sbp'> СБП</label>"
            "<button "+('' if ready else 'disabled')+">Открыть доступ · 500 ₽</button></form>")
        status='Доступ уже оплачен. Повторная покупка не нужна.' if owned else ('Разовая оплата. Без подписки и автосписаний.' if ready else 'Оплата временно недоступна. Деньги не списываются.')
        page="""<!doctype html><html lang='ru'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Эмулятор общения · Совпали</title>
<style>*{box-sizing:border-box}body{background:#f7f5f2;color:#302930;font:16px/1.7 system-ui;margin:0}main{max-width:580px;margin:40px auto;padding:25px}h1{font-size:38px;line-height:1.1}section{background:white;border:1px solid #e6dce1;border-radius:24px;padding:26px}strong{font-size:30px;color:#9b566b}button,.button{display:block;width:100%;background:#9b566b;color:white;border:0;border-radius:15px;padding:17px;text-align:center;text-decoration:none;font-size:16px;margin-top:22px}button:disabled{opacity:.5}small{color:#8b7b83}li{margin:10px 0}</style><main><p>♡ СОВПАЛИ</p><h1>Начни общение уверенно.</h1><section><h2>Эмулятор общения</h2><p>Для знакомства с """+esc(b['name'])+""".</p><strong>500 ₽</strong><ul><li>Три вопроса о твоей цели и стиле общения.</li><li>Первое сообщение с учётом анкет вашей пары.</li><li>Тренировка продолжения диалога по сценариям.</li><li>Сохранённый план — можно вернуться к нему позже.</li></ul><p>Подсказки формируются по правилам. Это не живой собеседник и не прогноз его ответа. Сообщения другому человеку не отправляются.</p>"""+action+'<p><small>'+status+'</small></p></section></main></html>'
        r=make_response(page);r.headers['Cache-Control']='private,no-store';r.headers['Referrer-Policy']='no-referrer';return r


def fulfill(db, order_id):
    """Record delivery only for the exact immutable bank-confirmed product."""
    with db() as c:
        row=c.execute("""SELECT b.buyer_user_id FROM web_purchase_bindings b
          JOIN billing_web_orders o ON o.order_id=b.billing_order_id
          WHERE b.billing_order_id=? AND b.sku='workshop' AND o.product_key='workshop'
            AND o.status='paid' AND o.amount_kopecks=50000 AND o.currency_code='643'""",(order_id,)).fetchone()
        if not row:return False
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc).isoformat(timespec='seconds')
        c.execute("""INSERT INTO web_product_grants(billing_order_id,buyer_user_id,sku,granted_at,details)
          VALUES(?,?,'workshop',?,'Conversation workshop access') ON CONFLICT(billing_order_id) DO NOTHING""",(order_id,row['buyer_user_id'],now))
        c.execute("UPDATE web_purchase_bindings SET binding_status='delivered',delivered_at=?,updated_at=? WHERE billing_order_id=?",(now,now,order_id))
    return True
