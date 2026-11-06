import hashlib, hmac, html, os, re, secrets, smtplib
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlsplit
import psycopg2, psycopg2.extras, requests
from flask import Flask, jsonify, abort, request, redirect, session, make_response
from werkzeug.middleware.proxy_fix import ProxyFix

app=Flask(__name__)
app.secret_key=os.getenv('SESSION_SECRET') or secrets.token_urlsafe(50)
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_SAMESITE='Lax',PERMANENT_SESSION_LIFETIME=timedelta(days=30))
app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=1)
PRICE=100; CC='643'; BANK='https://payapi.ozon.ru'
PAID={'COMPLETED','PAYMENT_COMPLETED','PAYMENT_COMPLETE','PAYMENT_SUCCESS','PAID','PAYMENT_PAID','SUCCESS'}
def url(): return os.getenv('PUBLIC_BASE_URL','https://poehali-checkout.onrender.com').rstrip('/')
def flags():
 return {'database':bool(os.getenv('DATABASE_URL')), 'bank':all(os.getenv(x) for x in ('OZON_PAY_ACCESS_KEY','OZON_PAY_SECRET_KEY','OZON_PAY_NOTIFICATION_SECRET_KEY')) and os.getenv('OZON_PAY_MODE')=='live','email':all(os.getenv(x) for x in ('SMTP_HOST','SMTP_USER','SMTP_PASSWORD','SMTP_FROM')),'receipts':os.getenv('POEHALI_FISCAL_CONFIRMED')=='1','seller':all(os.getenv(x) for x in ('SELLER_NAME','SELLER_INN','SELLER_EMAIL')),'session':len(os.getenv('SESSION_SECRET',''))>=32,'launch':os.getenv('POEHALI_SELLING_ENABLED')=='1' and os.getenv('POEHALI_LEGAL_CONFIRMED')=='1'}
def ready():
 f=flags()
 # Temporary one-ruble test checkout: only the explicitly authorized buyer can pay.
 return all(f[k] for k in ('database','bank','email','seller','session')) and os.getenv('POEHALI_TEST_PAYMENT_ENABLED')=='1' and bool(os.getenv('POEHALI_TEST_BUYER_EMAIL','').strip()) and DB_OK
def conn(): return psycopg2.connect(os.environ['DATABASE_URL'],connect_timeout=7)
def db(sql,args=(),fetch=False):
 with closing(conn()) as c:
  with c:
   with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute(sql,args)
    if fetch:
     row=cur.fetchone();return dict(row) if row else None
def setup():
 if not os.getenv('DATABASE_URL'):return False
 try:
  db('CREATE TABLE IF NOT EXISTS poehali_orders(id TEXT PRIMARY KEY,email TEXT NOT NULL,nonce TEXT NOT NULL,amount INTEGER NOT NULL,method TEXT NOT NULL,state TEXT NOT NULL,extid TEXT NOT NULL UNIQUE,paymentid TEXT,orderext TEXT,paylink TEXT,paid_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),access_sent_at TIMESTAMPTZ)')
  db('CREATE TABLE IF NOT EXISTS poehali_tokens(sha TEXT PRIMARY KEY,oid TEXT NOT NULL REFERENCES poehali_orders(id),expires_at TIMESTAMPTZ NOT NULL,used_at TIMESTAMPTZ)')
  db('CREATE UNIQUE INDEX IF NOT EXISTS poehali_orders_nonce_uq ON poehali_orders(nonce)')
  return True
 except Exception:app.logger.exception('Database setup');return False
DB_OK=setup()
def sign(v):return hashlib.sha256((v+os.environ['OZON_PAY_ACCESS_KEY']+os.environ['OZON_PAY_SECRET_KEY']).encode()).hexdigest()
def call(path,payload):
 r=requests.post(BANK+path,json=payload,timeout=(5,15));r.raise_for_status();return r.json()
def hosted(link):
 try:
  p=urlsplit(str(link));h=(p.hostname or '').lower().rstrip('.')
  return p.scheme=='https' and not p.username and not p.password and not p.port and bool(p.path) and (h.endswith('.ozon.ru') or h.endswith('.ozonpay.ru') or h=='qr.nspk.ru')
 except ValueError:return False
def get(oid):
 if not re.fullmatch('[0-9a-f]{32}',oid or ''):return None
 return db('SELECT * FROM poehali_orders WHERE id=%s',(oid,),True)
def bank_create(o):
 ext=o['extid'];amount={'currencyCode':CC,'value':str(PRICE)};back=url()+'/result/success?order='+o['id'];failback=url()+'/result/fail?order='+o['id']
 body={'accessKey':os.environ['OZON_PAY_ACCESS_KEY'],'payType':'SBP','amount':amount,'extId':ext,'ttl':1800,'redirectUrl':back,'requestSign':sign(ext),'notificationUrl':url()+'/ozon/notify'}
 if o['method']=='card':
  body['order']={'extId':'poehali-order-'+o['id'],'amount':amount,'mode':'MODE_SHORTENED','paymentAlgorithm':'PAY_ALGO_SMS','expiresAt':(datetime.now(timezone.utc)+timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%S.000Z'),'successUrl':back,'failUrl':failback,'enableFiscalization':True}
 d=call('/v1/createPayment',body);details=d.get('paymentDetails') or {};order=d.get('order') or {}
 if o['method']=='card':link=(order.get('item') or {}).get('payLink') or order.get('payLink')
 else:link=order.get('payLink') or (details.get('sbp') or {}).get('payload')
 if not hosted(link):raise ValueError('Invalid bank URL')
 return link,details.get('paymentId') or '', 'poehali-order-'+o['id']
def check(o):
 if o['state']=='paid':return True
 if not flags()['bank']:return False
 for field,value in [('extId',o['orderext']),('id',o['paymentid']),('extId',o['extid'])]:
  if not value:continue
  try:d=call('/v1/getPaymentDetails',{field:value,'accessKey':os.environ['OZON_PAY_ACCESS_KEY'],'requestSign':sign(value)})
  except Exception:app.logger.exception('Bank status');return False
  items=d.get('items') or []; node=items[0] if isinstance(items,list) and items else (d.get('paymentDetails') or d.get('payment') or {})
  if not isinstance(node,dict):continue
  status=str(node.get('status') or '').upper()
  if not status:continue
  if status not in PAID:return False
  amount=node.get('amount')
  try:
   if isinstance(amount,dict):actual=int(amount.get('value'));cc=str(amount.get('currencyCode'))
   else:actual=int(amount);cc=str(node.get('currencyCode'))
  except (TypeError,ValueError):return False
  if actual!=int(o['amount']) or cc!=CC:return False
  db("UPDATE poehali_orders SET state='paid',paid_at=now() WHERE id=%s AND state!='paid'",(o['id'],))
  return True
 return False
def email_access(o):
 o=get(o['id'])
 if not o or o['state']!='paid':return False
 if o['access_sent_at']:return True
 token=secrets.token_urlsafe(38);sha=hashlib.sha256(token.encode()).hexdigest()
 db("INSERT INTO poehali_tokens(sha,oid,expires_at) VALUES(%s,%s,now()+interval '7 days')",(sha,o['id']))
 msg=EmailMessage();msg['Subject']='Поехали — доступ к курсу';msg['From']=os.environ['SMTP_FROM'];msg['To']=o['email']
 msg.set_content('Оплата 1 ₽ подтверждена. Войти в курс: '+url()+'/login/'+token+'\nСсылка одноразовая, действует 7 дней. Если вы не совершали покупку — проигнорируйте письмо.')
 try:
  with smtplib.SMTP(os.environ['SMTP_HOST'],int(os.getenv('SMTP_PORT','587')),timeout=20) as m:m.starttls();m.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD']);m.send_message(msg)
  db('UPDATE poehali_orders SET access_sent_at=now() WHERE id=%s AND access_sent_at IS NULL',(o['id'],))
  return True
 except Exception:
  app.logger.exception('Email delivery failed');db('DELETE FROM poehali_tokens WHERE sha=%s',(sha,))
  return False
def page(title,body):
 seller=html.escape(os.getenv('SELLER_NAME','Реквизиты продавца — до включения продаж'))
 return make_response('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>'+html.escape(title)+'</title><style>*{box-sizing:border-box}body{background:radial-gradient(circle at top,#fffdf4,#eff5ed);font:16px/1.6 system-ui;color:#19442d;margin:0;padding:26px}main{max-width:660px;margin:7vh auto;background:white;padding:clamp(25px,5vw,50px);border-radius:25px;box-shadow:0 25px 70px #29482a18;border:1px solid #e6ebe2}h1{font-size:clamp(30px,6vw,45px);line-height:1.1}a{color:#1f7142}input,select{display:block;width:100%;font:inherit;padding:13px;border-radius:10px;border:1px solid #d4dfd4;margin:7px 0 18px}.button,button{display:block;width:100%;background:#24583d;color:white;border:0;border-radius:12px;padding:17px 20px;font:700 16px system-ui;text-align:center;text-decoration:none;margin:22px 0;cursor:pointer}button:disabled{background:#a7b5a6}.price{font-size:56px;font-weight:850}label{font-weight:650;font-size:13px}.note{background:#f1f6ef;border-radius:13px;padding:16px}footer{font-size:12px;color:#799080;border-top:1px solid #e8eee5;padding-top:20px;margin-top:28px}.test-price-note{font-size:13px;color:#94632d;background:#fff8e9;padding:10px 12px;border-radius:11px;margin:8px 0 23px}.payment-pickers{margin:4px 0 20px;padding:0;border:0;min-width:0}.payment-pickers legend{font-weight:750;margin-bottom:12px;font-size:15px}.payment-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.pay-card{position:relative;display:flex;align-items:center;gap:13px;padding:15px 13px;min-height:92px;border-radius:17px;border:2px solid #dee7e0;background:#fcfefd;cursor:pointer;transition:border-color .15s,box-shadow .15s,background .15s}.pay-card:has(input:checked){border-color:#23834e;background:#f1fbf4;box-shadow:0 0 0 3px #c9ead4}.pay-card:focus-within{outline:3px solid #b1dac1;outline-offset:2px}.pay-card:has(input:disabled){cursor:default;opacity:.78}.pay-card input{position:absolute!important;opacity:0!important;width:1px!important;height:1px!important;padding:0!important;margin:0!important;pointer-events:none}.pay-symbol{width:53px;height:53px;display:grid;place-items:center;background:white;border:1px solid #e6eee9;border-radius:13px;flex:none}.pay-symbol svg{width:41px;height:41px}.pay-word{display:flex;flex-direction:column;gap:3px;line-height:1.2}.pay-word strong{font-size:17px;color:#173c29;letter-spacing:-.3px}.pay-word small{font-size:11px;color:#687b71;font-weight:500}.pay-card:has(input:checked):after{content:"✓";position:absolute;top:8px;right:10px;color:#208f4f;font-weight:800;font-size:15px}@media(max-width:390px){.payment-grid{grid-template-columns:1fr}.pay-card{min-height:75px}}</style><main><div style="color:#4c9b62;font-size:12px;letter-spacing:2px;font-weight:bold">ПОЕХАЛИ · РАННИЙ ДОСТУП</div>'+body+'<footer>'+seller+'<br><a href="/terms">Условия</a> · <a href="/privacy">Данные</a> · <a href="https://poehali-lead-board.onrender.com/">Презентация</a></footer></main></html>')
@app.after_request
def headers(r):r.headers['X-Content-Type-Options']='nosniff';r.headers['Referrer-Policy']='no-referrer';return r
@app.get('/health')
def health():
 f=flags()
 return jsonify(ok=True, db=DB_OK, checkout_ready=ready(), checks={k:bool(v) for k,v in f.items()}, test_mode=True, test_email_configured=bool(os.getenv('POEHALI_TEST_BUYER_EMAIL','').strip()), test_payment_enabled=os.getenv('POEHALI_TEST_PAYMENT_ENABLED')=='1')
@app.get('/')
def home():return redirect('/checkout')
def payment_methods(enabled):
 disabled='' if enabled else ' disabled'
 return f'''<fieldset class="payment-pickers"><legend>Выберите способ оплаты</legend>
 <div class="payment-grid">
 <label class="pay-card"><input type="radio" name="method" value="sbp" checked required{disabled}>
 <span class="pay-symbol" aria-hidden="true"><svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
 <path d="M5 9L20 24L5 39" stroke="#16A96E" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
 <path d="M21 9L36 24L21 39" stroke="#2383DA" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
 <circle cx="39" cy="12" r="4" fill="#EA5B54"/><circle cx="39" cy="36" r="4" fill="#F4C54D"/></svg></span>
 <span class="pay-word"><strong>СБП</strong><small>Оплата через банк</small></span></label>
 <label class="pay-card"><input type="radio" name="method" value="card" required{disabled}>
 <span class="pay-symbol" aria-hidden="true"><svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
 <rect x="3" y="8" width="42" height="32" rx="6" fill="#3655B3"/><path d="M3 17h42v7H3z" fill="#92BCE8"/>
 <rect x="9" y="28" width="11" height="7" rx="2" fill="#FFE098"/><rect x="28" y="31" width="11" height="3" rx="1.5" fill="#E8F2FF"/></svg></span>
 <span class="pay-word"><strong>Банковская карта</strong><small>МИР и другие карты</small></span></label>
 </div></fieldset>'''
@app.get('/checkout')
def form():
 session.permanent=True;session.setdefault('csrf',secrets.token_urlsafe(28));session.setdefault('nonce',secrets.token_urlsafe(30))
 body='<h1>Создай своего Telegram-бота с GPT</h1><p>Интерактивный курс, готовые промпты, оплата и автопродвижение.</p><div class="price">1 ₽</div><div class="test-price-note"><b>Тестовая цена 1 ₽.</b> Проверяем оплату, электронный чек и письмо с доступом. Пока не для публичной продажи.</div>'
 if not ready():
  body+='<label>Email для электронного чека и ссылки на курс</label><input type="email" placeholder="name@example.com" autocomplete="email" disabled>'+payment_methods(False)+'<div class="note"><b>Тестовая оплата пока не активирована.</b><p>Система не списывает деньги, пока не настроены база, банк, почта и доступ только для тестового покупателя.</p></div>'
 else:
  body+='<form method="post"><input type="hidden" name="csrf" value="'+html.escape(session['csrf'])+'"><label>Email для электронного чека и ссылки на курс</label><input name="email" type="email" autocomplete="email" maxlength="255" required>'+payment_methods(True)+'<label><input type="checkbox" name="agree" value="yes" required style="display:inline;width:auto">Я принимаю <a href="/terms">условия</a> и <a href="/privacy">политику данных</a></label><button>Оплатить тестовые 1 ₽ через Ozon Pay</button></form>'
 return page('Оформление курса «Поехали»',body)
@app.post('/checkout')
def purchase():
 if not (ready() and DB_OK):abort(503)
 if not hmac.compare_digest(session.get('csrf',''),request.form.get('csrf','')):abort(403)
 if request.form.get('agree')!='yes':abort(400)
 email=request.form.get('email','').lower().strip();method=request.form.get('method','')
 if len(email)>255 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[A-Za-zА-Яа-я]{2,}',email) or method not in ('card','sbp'):abort(400)
 if not hmac.compare_digest(email,os.getenv('POEHALI_TEST_BUYER_EMAIL','').strip().lower()):abort(403)
 origin=request.headers.get('Origin','')
 if origin and origin!=url():abort(403)
 nonce=session.get('nonce');
 if not nonce:abort(403)
 old=db('SELECT id,state,paylink FROM poehali_orders WHERE nonce=%s',(nonce,),True)
 if old:
  if old['state']=='paid':
   session['course_oid']=old['id'];return redirect('/course',code=303)
  if old['state']=='pending' and hosted(old['paylink']):
   return redirect(old['paylink'],code=303)
  if old['state']=='creating':
   return page('Заказ обрабатывается','<h1>Заказ уже создаётся</h1><p>Не отправляйте повторно. Обновите страницу позже.</p>'),409
  session['nonce']=secrets.token_urlsafe(30);nonce=session['nonce']
 oid=secrets.token_hex(16);ext='poehali-'+oid
 db('INSERT INTO poehali_orders(id,email,nonce,amount,method,state,extid) VALUES(%s,%s,%s,%s,%s,%s,%s)',(oid,email,nonce,PRICE,method,'creating',ext))
 try:
  link,pid,eid=bank_create(get(oid))
  db("UPDATE poehali_orders SET state='pending',paylink=%s,paymentid=%s,orderext=%s WHERE id=%s",(link,pid,eid,oid))
 except Exception:
  app.logger.exception('Could not create bank payment');db("UPDATE poehali_orders SET state='failed' WHERE id=%s",(oid,))
  return page('Ошибка банка','<h1>Не удалось создать заказ</h1><p>Деньги не списаны. Попробуйте позже.</p>'),503
 session['order']=oid;return redirect(link,code=303)
@app.get('/result')
@app.get('/result/success')
@app.get('/result/fail')
def result():
 # The URLs configured in Ozon Pay are landing pages, not proof of payment.
 # A direct visit (no prior checkout/session/order) must never show a 404 or a fake success.
 kind='fail' if request.path.endswith('/fail') else 'success'
 order_arg=request.args.get('order','')
 oid=order_arg or session.get('order') or ''
 if not oid:
  body='<h1>Страница возврата из Ozon Pay</h1><p>Это служебный адрес, который банк открывает после оплаты курса.</p><p>У вас пока нет заказа, привязанного к этому браузеру. Для покупки начните с оформления.</p><a class="button" href="/checkout">Перейти к оформлению — 1 ₽</a>'
  return page('Возврат после оплаты',body)
 if not re.fullmatch('[0-9a-f]{32}',oid):abort(404)
 if not DB_OK:
  return page('Проверка оплаты','<h1>Проверка пока недоступна</h1><p>Сервис платежей ещё на настройке. Если деньги списаны, не оплачивайте повторно — обратитесь в поддержку с номером заказа.</p>'),503
 o=get(oid)
 if not o:abort(404)
 if not session.get('nonce') or not hmac.compare_digest(session['nonce'],o['nonce']):abort(403)
 if check(o):
  session['course_oid']=o['id']
  mailed=email_access(o)
  message='<p>Курс открыт на этом устройстве.</p>'
  if mailed:message+='<p>Персональная ссылка отправлена на ваш email.</p>'
  else:message+='<p>Письмо с доступом пока не подтверждено. Курс доступен вам в этом браузере; сохраните номер заказа для восстановления.</p>'
  return page('Оплата подтверждена','<h1>Оплата 1 ₽ подтверждена!</h1>'+message+'<a class="button" href="/course">Открыть курс</a>')
 if kind=='fail':
  return page('Оплата не подтверждена','<h1>Оплата пока не подтверждена</h1><p>Банк вернул вас на страницу неуспешной оплаты. Если деньги всё же списались, не платите повторно, пока мы не проверим статус.</p><a class="button" href="/result?order='+o['id']+'">Проверить статус заказа</a><a href="/checkout">Вернуться к оформлению</a>')
 return page('Проверяем платёж','<h1>Проверяем оплату</h1><p>Ожидаем подтверждение Ozon. Не платите повторно.</p><a class="button" href="/result?order='+o['id']+'">Проверить снова</a>')

@app.get('/login/<token>')
def magic(token):
 if len(token)>150:abort(404)
 sha=hashlib.sha256(token.encode()).hexdigest()
 row=db("UPDATE poehali_tokens t SET used_at=now() FROM poehali_orders o WHERE t.oid=o.id AND t.sha=%s AND t.used_at IS NULL AND t.expires_at>now() AND o.state='paid' RETURNING t.oid",(sha,),True)
 if not row:abort(404)
 session.permanent=True;session['course_oid']=row['oid'];return redirect('/course',code=303)
@app.get('/course')
def course():
 o=get(session.get('course_oid',''))
 if not o or o['state']!='paid':return redirect('/checkout',code=303)
 try:
  with open('course.html',encoding='utf8') as f:content=f.read()
 except OSError:return page('Уроки временно недоступны','<h1>Свяжитесь с поддержкой</h1>'),503
 r=make_response(content);r.headers['Content-Type']='text/html; charset=utf-8';r.headers['Cache-Control']='private, no-store';r.headers['X-Robots-Tag']='noindex, nofollow';return r
@app.post('/ozon/notify')
def notify():
 if request.content_length and request.content_length>10000:abort(413)
 data=request.get_json(silent=True)
 if not isinstance(data,dict):abort(400)
 secret=os.getenv('OZON_PAY_NOTIFICATION_SECRET_KEY','');access=os.getenv('OZON_PAY_ACCESS_KEY','')
 if not (secret and access):abort(503)
 amt=str(data.get('amount') or '');curr=str(data.get('currencyCode') or '');ext=str(data.get('extTransactionID') or '');exorder=str(data.get('extOrderID') or data.get('extOrderId') or '');orderid=str(data.get('orderID') or data.get('orderId') or '');tx=str(data.get('transactionID') or '')
 checks=[hashlib.sha256((access+'|||'+ext+'|'+amt+'|'+curr+'|'+secret).encode()).hexdigest(),hashlib.sha256((access+'|'+orderid+'|'+tx+'|'+exorder+'|'+amt+'|'+curr+'|'+secret).encode()).hexdigest()]
 supplied=str(data.get('requestSign') or '')
 if not supplied or not any(hmac.compare_digest(supplied,x) for x in checks):abort(403)
 m=re.search(r'poehali-(?:order-)?([0-9a-f]{32})',ext+' '+exorder)
 if m:
  o=get(m.group(1))
  if o and check(o):email_access(o)
 return jsonify(ok=True)
@app.get('/terms')
def terms():return page('Условия','<h1>Условия покупки</h1><p>Курс «Поехали», тестовая версия, стоимость 1 ₽ на период внутреннего тестирования. Доступ предоставляется после подтверждения оплаты, отправка ссылки на email. Результаты по доходу не гарантируются.</p><p>Юридические реквизиты, правила возврата и полная оферта должны быть опубликованы до начала приёма платежей.</p>')
@app.get('/privacy')
def privacy():return page('Персональные данные','<h1>Обработка данных</h1><p>Для покупки и выдачи курса требуется email. Банковские данные обрабатывает Ozon Pay. Полную политику с оператором данных и сроками хранения требуется опубликовать до запуска оплаты.</p>')
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))