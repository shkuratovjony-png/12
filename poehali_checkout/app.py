import hashlib, hmac, html, os, re, secrets, smtplib
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlsplit, quote
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import psycopg2, psycopg2.extras, requests
from flask import Flask, jsonify, abort, request, redirect, session, make_response
from werkzeug.middleware.proxy_fix import ProxyFix
from legal import docs
from funnel import register_funnel, lead_for_ref, record_event, mark_paid
from checkout_ui import checkout_document

app=Flask(__name__)
app.secret_key=os.getenv('SESSION_SECRET') or secrets.token_urlsafe(50)
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_SAMESITE='Lax',PERMANENT_SESSION_LIFETIME=timedelta(days=30))
app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=1)
PRICE=100; CC='643'; BANK='https://payapi.ozon.ru'
PAID={'COMPLETED','PAYMENT_COMPLETED','PAYMENT_COMPLETE','PAYMENT_SUCCESS','PAYMENT_CONFIRMED','PAID','PAYMENT_PAID','SUCCESS'}
def url(): return os.getenv('PUBLIC_BASE_URL','https://poehali-checkout.onrender.com').rstrip('/')
def signed_form(csrf, nonce, funnel_ref=''):
 return URLSafeTimedSerializer(app.secret_key, salt='poehali-checkout-form-v1').dumps({'csrf':csrf,'nonce':nonce,'ref':funnel_ref})
def signed_result(order):
 return URLSafeTimedSerializer(app.secret_key, salt='poehali-checkout-result-v1').dumps({'id':order['id'],'nonce':order['nonce']})
def checkout_problem(message, code=403):
 app.logger.warning('Poekhali form rejected: %s', message)
 return page('Проверка оформления', '<h1>Не удалось перейти к оплате</h1><p>'+html.escape({
  'form':'Страница оформления устарела или браузер не сохранил данные формы. Откройте её заново и повторите попытку.',
  'origin':'Браузер заблокировал проверку источника формы. Откройте оплату напрямую в обычном браузере.',
 }.get(message,'Откройте страницу оформления ещё раз.'))+'</p><a class="button" href="/checkout">Вернуться к оформлению — 1 ₽</a>'),code
def flags():
 return {'database':bool(os.getenv('DATABASE_URL')), 'bank':all(os.getenv(x) for x in ('OZON_PAY_ACCESS_KEY','OZON_PAY_SECRET_KEY','OZON_PAY_NOTIFICATION_SECRET_KEY')) and os.getenv('OZON_PAY_MODE')=='live','email':all(os.getenv(x) for x in ('SMTP_HOST','SMTP_USER','SMTP_PASSWORD','SMTP_FROM')),'receipts':os.getenv('POEHALI_FISCAL_CONFIRMED')=='1','seller':all(os.getenv(x) for x in ('SELLER_NAME','SELLER_INN','SELLER_EMAIL')),'session':len(os.getenv('SESSION_SECRET',''))>=32,'launch':os.getenv('POEHALI_SELLING_ENABLED')=='1' and os.getenv('POEHALI_LEGAL_CONFIRMED')=='1', 'data_ru':os.getenv('POEHALI_DATA_RU_CONFIRMED')=='1'}
def ready():
 f=flags()
 # Keep fiscal API, verified bank credentials, database and signed session checks.
 # A single seller switch controls whether new orders can be created.
 return (DB_OK and all(f[k] for k in ('database','bank','seller','session'))
         and os.getenv('POEHALI_SELLING_ENABLED')=='1'
         and os.getenv('POEHALI_FISCAL_ORDER_FLOW')=='1')
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
  db('ALTER TABLE poehali_orders ADD COLUMN IF NOT EXISTS accepted_terms_at TIMESTAMPTZ')
  db('ALTER TABLE poehali_orders ADD COLUMN IF NOT EXISTS consent_at TIMESTAMPTZ')
  db('ALTER TABLE poehali_orders ADD COLUMN IF NOT EXISTS legal_version TEXT')
  db('ALTER TABLE poehali_orders ADD COLUMN IF NOT EXISTS funnel_ref TEXT')
  return True
 except Exception:app.logger.exception('Database setup');return False
DB_OK=setup()
# Diagnostic booleans only; never log any tokens, email values, or database URLs.
app.logger.warning('Poekhali checkout readiness: db=%s bank=%s fiscal_order=%s selling=%s',
                   DB_OK,flags()['bank'],
                   os.getenv('POEHALI_FISCAL_ORDER_FLOW')=='1',
                   os.getenv('POEHALI_SELLING_ENABLED')=='1')
def sign(v):return hashlib.sha256((v+os.environ['OZON_PAY_ACCESS_KEY']+os.environ['OZON_PAY_SECRET_KEY']).encode()).hexdigest()
class BankCheckoutError(Exception):
 def __init__(self, http_status, provider_detail):
  self.http_status=http_status
  self.provider_detail=provider_detail
  super().__init__('Ozon rejected request')

def _safe_provider_detail(response):
 # No request body, API access keys, secrets, payment tokens or customer details
 # must ever be logged. Extract only Ozon's short diagnostic fields.
 try:
  body=response.json()
 except (ValueError,TypeError):
  return 'non_json_response'
 if not isinstance(body,dict):
  return 'non_object_response'
 bits=[]
 for key in ('code','errorCode','error_code','error','message','description','errorDescription','status'):
  value=body.get(key)
  if isinstance(value,(str,int,float)):
   snippet=str(value)
   for secret_name in ('OZON_PAY_ACCESS_KEY','OZON_PAY_SECRET_KEY','OZON_PAY_NOTIFICATION_SECRET_KEY','DATABASE_URL','SMTP_PASSWORD'):
    secret=os.getenv(secret_name,'')
    if secret:snippet=snippet.replace(secret,'[redacted]')
   snippet=re.sub(r'https?://\S+','[url]',snippet)
   snippet=re.sub(r'(?i)\b(?:bearer\s+)?[A-Za-z0-9_\-]{45,}\b','[redacted]',snippet)
   bits.append(key+':'+snippet[:180])
 return '; '.join(bits)[:400] or ('response_fields:'+','.join(k for k in body if isinstance(k,str))[:120])

def call(path,payload):
 r=requests.post(BANK+path,json=payload,timeout=(5,15),headers={'Accept':'application/json'})
 if not r.ok:
  safe=_safe_provider_detail(r)
  app.logger.error('Ozon Pay request declined: endpoint=%s http=%s detail=%s',path,r.status_code,safe)
  raise BankCheckoutError(r.status_code,safe)
 body=r.json()
 if not isinstance(body,dict):raise ValueError('Unexpected bank API response type')
 return body
def hosted(link):
 try:
  p=urlsplit(str(link));h=(p.hostname or '').lower().rstrip('.')
  return p.scheme=='https' and not p.username and not p.password and not p.port and bool(p.path) and (h.endswith('.ozon.ru') or h.endswith('.ozonpay.ru') or h=='qr.nspk.ru')
 except ValueError:return False
def get(oid):
 if not re.fullmatch('[0-9a-f]{32}',oid or ''):return None
 return db('SELECT * FROM poehali_orders WHERE id=%s',(oid,),True)
def ozon_fiscal_order_payload(o, sign_variant='expires'):
 # Create an actual fiscalized ORDER rather than a raw SBP transfer. The order
 # includes a line item and receipt recipient for Ozon's Online Receipts service.
 ext='poehali-fiscal-'+o['id']
 amount={'currencyCode':CC,'value':str(o['amount'])}
 expiry=(datetime.now(timezone.utc)+timedelta(minutes=30)).replace(microsecond=0).isoformat().replace('+00:00','Z')
 proof=quote(signed_result(o),safe='')
 success=url()+'/result/success?order='+o['id']+'&proof='+proof
 failure=url()+'/result/fail?order='+o['id']+'&proof='+proof
 fiscal_type='FISCAL_TYPE_SINGLE'
 algorithm='PAY_ALGO_SMS'
 access=os.environ['OZON_PAY_ACCESS_KEY'].strip()
 secret=os.environ['OZON_PAY_SECRET_KEY'].strip()
 # Two publicly used Ozon integration variants differ on whether expiresAt
 # participates in requestSign. Compare using unpaid intents before changing
 # production. All orders still carry expiresAt.
 if sign_variant not in ('expires','no_expires'):raise ValueError('Unsupported Ozon signature variant')
 fingerprint=access+(expiry if sign_variant=='expires' else '')+ext+fiscal_type+algorithm+CC+str(o['amount'])+secret
 body={
   'accessKey':access,
   'amount':amount,
   'enableFiscalization':True,
   'expiresAt':expiry,
   'extId':ext,
   'failUrl':failure,
   'fiscalizationType':fiscal_type,
   'items':[{
     'extId':'poehali-course-'+o['id'],
     'name':'Онлайн-курс «Поехали», электронный доступ',
     'price':amount,
     'quantity':1,
     'type':'TYPE_SERVICE',
     'unitType':'UNIT_PIECE',
     'vat':os.getenv('POEHALI_RECEIPT_VAT','VAT_NONE')
   }],
   'mode':'MODE_FULL',
   'paymentAlgorithm':algorithm,
   'requestSign':hashlib.sha256(fingerprint.encode()).hexdigest(),
   'successUrl':success,
   'notificationUrl':url()+'/ozon/notify',
   'receiptEmail':o['email']
 }
 return body

def fiscal_order_create(o, sign_variant=None):
 variant=sign_variant or os.getenv('POEHALI_FISCAL_SIGN_VARIANT','expires')
 body=ozon_fiscal_order_payload(o, sign_variant=variant)
 response=call('/v1/createOrder',body)
 order=response.get('order') or response.get('item') or {}
 if not isinstance(order,dict):raise ValueError('Missing bank order')
 link=order.get('payLink') or (order.get('item') or {}).get('payLink')
 if not hosted(link):raise ValueError('Invalid fiscal bank order URL')
 provider_id=str(order.get('id') or '')
 return link,provider_id,body['extId']

def bank_create(o, short_callback=False):
 if os.getenv('POEHALI_FISCAL_ORDER_FLOW')=='1':
  return fiscal_order_create(o)

 ext=o['extid'];amount={'currencyCode':CC,'value':str(o['amount'])}
 proof=quote(signed_result(o),safe='')
 back=url()+'/result/success?order='+o['id']
 failback=url()+'/result/fail?order='+o['id']
 if not short_callback:
  back+='&proof='+proof
  failback+='&proof='+proof
 body={'accessKey':os.environ['OZON_PAY_ACCESS_KEY'],'payType':'SBP','amount':amount,'extId':ext,'ttl':1800,'redirectUrl':back,'requestSign':sign(ext),'notificationUrl':url()+'/ozon/notify'}
 if o['method']=='card':
  body['order']={'extId':'poehali-order-'+o['id'],'amount':amount,'mode':'MODE_SHORTENED','paymentAlgorithm':'PAY_ALGO_SMS','expiresAt':(datetime.now(timezone.utc)+timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%S.000Z'),'successUrl':back,'failUrl':failback,'enableFiscalization':True}
 d=call('/v1/createPayment',body);details=d.get('paymentDetails') or {};order=d.get('order') or {}
 if o['method']=='card':link=(order.get('item') or {}).get('payLink') or order.get('payLink')
 else:link=order.get('payLink') or (details.get('sbp') or {}).get('payload')
 if not hosted(link):raise ValueError('Invalid bank URL')
 return link,details.get('paymentId') or '', 'poehali-order-'+o['id']

def _fiscal_order_probe_once():
 # Creates ONE unpaid Ozon order. Nothing is charged and the link is withheld.
 if os.getenv('POEHALI_FISCAL_PROBE_ONCE')!='1' or not DB_OK or not flags()['bank']:return
 oid=hashlib.sha256(b'poehali-fiscal-order-20261106-v2-unique-line-item').hexdigest()[:32]
 buyer=os.getenv('POEHALI_TEST_BUYER_EMAIL','').strip().lower()
 if not buyer:return
 try:
  o=db("""INSERT INTO poehali_orders(id,email,nonce,amount,method,state,extid)
       VALUES(%s,%s,%s,100,'sbp','probe-creating',%s)
       ON CONFLICT(id) DO NOTHING RETURNING *""",
       (oid,buyer,'probe-'+oid,'poehali-'+oid),True)
  if not o:return
  try:
   link,provider_id,provider_ext=fiscal_order_create(o)
   db("UPDATE poehali_orders SET state='probe-fiscal-accepted',paymentid=%s,orderext=%s WHERE id=%s",
      (provider_id,provider_ext,oid))
   app.logger.warning('Ozon fiscalized order 1 RUB probe accepted: bank_link_withheld=True')
  except BankCheckoutError as err:
   db("UPDATE poehali_orders SET state='probe-fiscal-rejected' WHERE id=%s",(oid,))
   app.logger.error('Ozon fiscalized order probe rejected: http=%s detail=%s',err.http_status,err.provider_detail)
  except Exception as err:
   db("UPDATE poehali_orders SET state='probe-fiscal-failed' WHERE id=%s",(oid,))
   app.logger.error('Ozon fiscalized order probe failed: type=%s',type(err).__name__)
 except Exception as err:
  app.logger.error('Ozon fiscalized order probe setup failed: type=%s',type(err).__name__)
# Historical bank recovery/probes are manual-only; never run during web startup.

def _verify_existing_fiscal_probe():
 if os.getenv('POEHALI_FISCAL_PROBE_VERIFY')!='1' or not flags()['bank'] or not DB_OK:return
 oid=hashlib.sha256(b'poehali-fiscal-order-20261106-v1').hexdigest()[:32]
 try:
  o=get(oid)
  if not o or o.get('state')!='probe-fiscal-accepted':
   app.logger.warning('Ozon fiscal probe status lookup skipped: no accepted probe')
   return
  d=call('/v1/getOrderDetails',{'accessKey':os.environ['OZON_PAY_ACCESS_KEY'],'extId':o['orderext']})
  item=d.get('item') or d.get('order') or {}
  if isinstance(item,dict):
   app.logger.warning('Ozon fiscal probe lookup accepted: status=%s has_id=%s has_amount=%s',str(item.get('status',''))[:40],bool(item.get('id')),bool(item.get('amount')))
  else:
   app.logger.warning('Ozon fiscal probe lookup returned no order object')
 except BankCheckoutError as e:
  app.logger.error('Ozon fiscal probe lookup error: http=%s detail=%s',e.http_status,e.provider_detail)
 except Exception as e:
  app.logger.error('Ozon fiscal probe lookup unexpected: type=%s',type(e).__name__)
# Historical bank recovery/probes are manual-only; never run during web startup.

def _one_time_bank_probe():
 # Only unpaid payment intents are created; no checkout links are shared.
 if os.getenv('POEHALI_BANK_PROBE_ONCE')!='1' or not DB_OK or not flags()['bank']:return
 for name,amount,method,short_callback in (
  ('card-1rub-short-return',100,'card',True),
  ('card-100rub-signed-return',10000,'card',False),
  ('sbp-1rub-signed-return',100,'sbp',False)
 ):
  oid=hashlib.sha256(('poehali-bank-probe-20261106-v2-'+name).encode()).hexdigest()[:32]
  try:
   row=db("""INSERT INTO poehali_orders(id,email,nonce,amount,method,state,extid)
      VALUES(%s,%s,%s,%s,%s,%s,%s)
      ON CONFLICT (id) DO NOTHING RETURNING *""",
      (oid,'probe@invalid.example','probe-'+oid,amount,method,'probe-creating','poehali-'+oid),True)
   if not row:continue
   try:
    link,pid,eid=bank_create(row,short_callback=short_callback)
    db("UPDATE poehali_orders SET state='probe-accepted' WHERE id=%s",(oid,))
    app.logger.warning('Ozon probe %s accepted (unpaid; payment link not exposed)',name)
   except BankCheckoutError as err:
    db("UPDATE poehali_orders SET state='probe-rejected' WHERE id=%s",(oid,))
    app.logger.error('Ozon probe %s rejected: http=%s detail=%s',name,err.http_status,err.provider_detail)
   except Exception as err:
    db("UPDATE poehali_orders SET state='probe-failed' WHERE id=%s",(oid,))
    app.logger.error('Ozon probe %s failed with %s',name,type(err).__name__)
  except Exception as err:
   app.logger.error('Ozon probe %s setup failed with %s',name,type(err).__name__)
# Historical bank recovery/probes are manual-only; never run during web startup.

def _diagnose_order_signatures_once():
 # Two idempotent, UNPAID fiscal order intents. No links are exposed or charged.
 if os.getenv('POEHALI_SIGNATURE_DIAG_RUN')!='sig-20261106-a' or not DB_OK or not flags()['bank']:return
 buyer=os.getenv('POEHALI_TEST_BUYER_EMAIL','').strip().lower()
 if not buyer:return
 for variant in ('expires','no_expires'):
  oid=hashlib.sha256(('poehali-signature-20261106a-'+variant).encode()).hexdigest()[:32]
  try:
   o=db("""INSERT INTO poehali_orders(id,email,nonce,amount,method,state,extid)
       VALUES(%s,%s,%s,100,'sbp','diag-creating',%s)
       ON CONFLICT(id) DO NOTHING RETURNING *""",
       (oid,buyer,'diag-'+oid,'poehali-'+oid),True)
   if not o:
    app.logger.warning('Ozon signature diagnostic %s already examined; skipping',variant)
    continue
   try:
    link,provider_id,provider_ext=fiscal_order_create(o, sign_variant=variant)
    db("UPDATE poehali_orders SET state='diag-accepted',paymentid=%s,orderext=%s WHERE id=%s",
       (provider_id,provider_ext,oid))
    app.logger.warning('Ozon signature diagnostic variant=%s ACCEPTED (unpaid link withheld)',variant)
   except BankCheckoutError as err:
    db("UPDATE poehali_orders SET state='diag-rejected' WHERE id=%s",(oid,))
    app.logger.error('Ozon signature diagnostic variant=%s REJECTED http=%s detail=%s',variant,err.http_status,err.provider_detail)
   except Exception as err:
    db("UPDATE poehali_orders SET state='diag-failed' WHERE id=%s",(oid,))
    app.logger.error('Ozon signature diagnostic variant=%s FAILED type=%s',variant,type(err).__name__)
  except Exception as err:
   app.logger.error('Ozon signature diagnostic variant=%s INSERT FAILED type=%s',variant,type(err).__name__)
_diagnose_order_signatures_once()

def _diagnose_nonfiscal_once():
 # Unpaid-only control request: same merchant and order, but no fiscalization.
 # Never output or redirect to this payment link.
 if os.getenv('POEHALI_NONFISCAL_DIAG_RUN')!='nonfiscal-20261106a' or not DB_OK or not flags()['bank']:return
 oid=hashlib.sha256(b'poehali-nonfiscal-20261106a-one-shot').hexdigest()[:32]
 buyer=os.getenv('POEHALI_TEST_BUYER_EMAIL','').strip().lower()
 if not buyer:return
 try:
  o=db("""INSERT INTO poehali_orders(id,email,nonce,amount,method,state,extid)
    VALUES(%s,%s,%s,100,'sbp','diag-nonfiscal-creating',%s)
    ON CONFLICT(id) DO NOTHING RETURNING *""",
    (oid,buyer,'nfdiag-'+oid,'poehali-'+oid),True)
  if not o:
   app.logger.warning('Ozon nonfiscal diagnostic already performed; not repeating')
   return
  b=ozon_fiscal_order_payload(o,sign_variant='expires')
  b['enableFiscalization']=False
  b.pop('receiptEmail',None)
  b['items'][0]['extId']='course-'+oid[:15]
  b['items'][0]['needMark']=False
  try:
   ans=call('/v1/createOrder',b)
   order=ans.get('order') or {}
   accepted=isinstance(order,dict) and bool(order.get('payLink'))
   db("UPDATE poehali_orders SET state=%s WHERE id=%s",('diag-nonfiscal-accepted' if accepted else 'diag-nonfiscal-incomplete',oid))
   app.logger.warning('Ozon nonfiscal diagnostic accepted=%s (unpaid link withheld)',accepted)
  except BankCheckoutError as err:
   db("UPDATE poehali_orders SET state='diag-nonfiscal-rejected' WHERE id=%s",(oid,))
   app.logger.error('Ozon nonfiscal diagnostic rejected: http=%s detail=%s',err.http_status,err.provider_detail)
 except Exception as err:
  app.logger.error('Ozon nonfiscal diagnostic setup failed: %s',type(err).__name__)
_diagnose_nonfiscal_once()

def check(o):
 if o['state']=='paid':
  mark_paid(o)
  return True
 if str(o.get('orderext') or '').startswith('poehali-fiscal-'):
  if not flags()['bank']:return False
  try:
   payload={'accessKey':os.environ['OZON_PAY_ACCESS_KEY'],'extId':o['orderext']}
   d=call('/v1/getOrderDetails',payload)
   item=d.get('item') or d.get('order') or {}
   if not isinstance(item,dict):return False
   status=str(item.get('status') or '').upper()
   # An order created by our server fixes its amount and receipt email before
   # the bank issues its payLink. Accept payment only for this exact extId.
   received_id=str(item.get('extId') or o['orderext'])
   if not hmac.compare_digest(received_id,o['orderext']):return False
   if item.get('id') and o.get('paymentid') and not hmac.compare_digest(str(item['id']),str(o['paymentid'])):return False
   amt=item.get('amount')
   if isinstance(amt,dict):
    if str(amt.get('currencyCode'))!=CC or int(amt.get('value'))!=int(o['amount']):return False
   app.logger.warning('Ozon fiscal order status=%s amount_provided=%s',status[:32],isinstance(amt,dict))
   if status in ('PAID','STATUS_PAID','PAYMENT_CONFIRMED','COMPLETED','ORDER_PAID'):
    db("UPDATE poehali_orders SET state='paid',paid_at=COALESCE(paid_at,now()) WHERE id=%s AND state!='paid'",(o['id'],))
    mark_paid(o)
    return True
  except (BankCheckoutError,ValueError,TypeError) as exc:
   app.logger.warning('Ozon fiscal order verification unavailable: %s',type(exc).__name__)
  return False
 if not flags()['bank']:return False
 # Ozon's SBP payment has no bank order; the previously fabricated
 # orderext made us bail on the first 400 instead of inspecting the payment.
 if o['method']=='sbp':
  candidates=[('id',o.get('paymentid')),('extId',o.get('extid'))]
 else:
  candidates=[('extId',o.get('orderext')),('id',o.get('paymentid')),('extId',o.get('extid'))]
 tried=set()
 for field,value in candidates:
  if not value or (field,value) in tried:continue
  tried.add((field,value))
  try:
   d=call('/v1/getPaymentDetails',{field:value,'accessKey':os.environ['OZON_PAY_ACCESS_KEY'],'requestSign':sign(value)})
  except BankCheckoutError as err:
   app.logger.warning('Ozon verification identifier %s rejected: http=%s safe_detail=%s',field,err.http_status,err.provider_detail)
   continue
  except Exception as err:
   app.logger.error('Ozon verification identifier %s failed: %s',field,type(err).__name__)
   continue
  items=d.get('items') or []
  if isinstance(items,list) and items:
   nodes=[x for x in items if isinstance(x,dict)]
  else:
   nodes=[x for x in (d.get('paymentDetails'),d.get('payment'),d) if isinstance(x,dict)]
  if not nodes:
   app.logger.warning('Ozon verification: %s returned no payment nodes; response keys=%s',field,list(d)[:12])
   continue
  for node in nodes:
   status=str(node.get('status') or node.get('paymentStatus') or '').upper()
   if not status:
    app.logger.warning('Ozon verification: %s no status, node keys=%s',field,list(node)[:12])
    continue
   amount=node.get('amount')
   try:
    if isinstance(amount,dict):
     actual=int(amount.get('value'));cc=str(amount.get('currencyCode') or CC)
    else:
     actual=int(amount);cc=str(node.get('currencyCode') or CC)
    amt_ok=(actual==int(o['amount']) and cc==CC)
   except (TypeError,ValueError):
    amt_ok=False
   app.logger.warning('Ozon status check: method=%s lookup=%s status=%s amount_matches=%s',o['method'],field,status[:40],amt_ok)
   if status in PAID and amt_ok:
    db("UPDATE poehali_orders SET state='paid',paid_at=COALESCE(paid_at,now()) WHERE id=%s AND state!='paid'",(o['id'],))
    mark_paid(o)
    return True
 return False

def email_access(o):
 # The free web-service runtime cannot reach SMTP port 587.
 # Never delay payment callbacks by attempting blocked SMTP connections.
 if os.getenv('POEHALI_SMTP_ENABLED')!='1':
  app.logger.info('Course access email deferred: SMTP transport unavailable')
  return False
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
def recover_recent_sbp():
 # A single, idempotent recovery for the owner's paid 1-ruble test.
 # No payment intent is created here. Reads pending orders and checks Ozon.
 recovery_id=os.getenv('POEHALI_RECOVERY_RUN','').strip()
 if not recovery_id or not DB_OK or not flags()['bank']:return
 if len(recovery_id)>80 or not re.fullmatch(r'[A-Za-z0-9_-]+',recovery_id):return
 try:
  db('CREATE TABLE IF NOT EXISTS poehali_recovery_runs(run_id TEXT PRIMARY KEY,created_at TIMESTAMPTZ NOT NULL DEFAULT now())')
  claimed=db('INSERT INTO poehali_recovery_runs(run_id) VALUES(%s) ON CONFLICT DO NOTHING RETURNING run_id',(recovery_id,),True)
  if not claimed:return
  buyer=os.getenv('POEHALI_TEST_BUYER_EMAIL','').strip().lower()
  with closing(conn()) as c:
   with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""SELECT * FROM poehali_orders WHERE email=%s AND method='sbp' AND amount=100
      AND state IN ('pending','paid') AND created_at >= now()-interval '3 days'
      ORDER BY created_at DESC LIMIT 20""",(buyer,))
    rows=cur.fetchall()
  app.logger.warning('Poekhali paid-test recovery examined %s candidate orders',len(rows))
  for o in rows:
   try:
    if check(o):
     sent=email_access(o)
     app.logger.warning('Poekhali paid-test recovery: verified_payment=True access_email_sent=%s',sent)
    else:
     app.logger.warning('Poekhali paid-test recovery: payment_not_verified')
   except Exception as err:
    app.logger.error('Poekhali paid-test recovery error %s',type(err).__name__)
 except Exception as err:
  app.logger.error('Poekhali paid-test recovery setup error %s',type(err).__name__)
# Historical bank recovery/probes are manual-only; never run during web startup.

def page(title,body):
 seller=html.escape(os.getenv('SELLER_NAME','Реквизиты продавца — до включения продаж'))
 return make_response('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>'+html.escape(title)+'</title><style>*{box-sizing:border-box}body{background:radial-gradient(circle at top,#fffdf4,#eff5ed);font:16px/1.6 system-ui;color:#19442d;margin:0;padding:26px}main{max-width:660px;margin:7vh auto;background:white;padding:clamp(25px,5vw,50px);border-radius:25px;box-shadow:0 25px 70px #29482a18;border:1px solid #e6ebe2}h1{font-size:clamp(30px,6vw,45px);line-height:1.1}a{color:#1f7142}input,select{display:block;width:100%;font:inherit;padding:13px;border-radius:10px;border:1px solid #d4dfd4;margin:7px 0 18px}.button,button{display:block;width:100%;background:#24583d;color:white;border:0;border-radius:12px;padding:17px 20px;font:700 16px system-ui;text-align:center;text-decoration:none;margin:22px 0;cursor:pointer}button:disabled{background:#a7b5a6}.price{font-size:56px;font-weight:850}label{font-weight:650;font-size:13px}.note{background:#f1f6ef;border-radius:13px;padding:16px}footer{font-size:12px;color:#799080;border-top:1px solid #e8eee5;padding-top:20px;margin-top:28px}.test-price-note{font-size:13px;color:#94632d;background:#fff8e9;padding:10px 12px;border-radius:11px;margin:8px 0 23px}.payment-pickers{margin:4px 0 20px;padding:0;border:0;min-width:0}.payment-pickers legend{font-weight:750;margin-bottom:12px;font-size:15px}.payment-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.pay-card{position:relative;display:flex;align-items:center;gap:13px;padding:15px 13px;min-height:92px;border-radius:17px;border:2px solid #dee7e0;background:#fcfefd;cursor:pointer;transition:border-color .15s,box-shadow .15s,background .15s}.pay-card:has(input:checked){border-color:#23834e;background:#f1fbf4;box-shadow:0 0 0 3px #c9ead4}.pay-card:focus-within{outline:3px solid #b1dac1;outline-offset:2px}.pay-card:has(input:disabled){cursor:default;opacity:.78}.pay-card input{position:absolute!important;opacity:0!important;width:1px!important;height:1px!important;padding:0!important;margin:0!important;pointer-events:none}.pay-symbol{width:53px;height:53px;display:grid;place-items:center;background:white;border:1px solid #e6eee9;border-radius:13px;flex:none}.pay-symbol svg{width:41px;height:41px}.pay-word{display:flex;flex-direction:column;gap:3px;line-height:1.2}.pay-word strong{font-size:17px;color:#173c29;letter-spacing:-.3px}.pay-word small{font-size:11px;color:#687b71;font-weight:500}.pay-card:has(input:checked):after{content:"✓";position:absolute;top:8px;right:10px;color:#208f4f;font-weight:800;font-size:15px}@media(max-width:390px){.payment-grid{grid-template-columns:1fr}.pay-card{min-height:75px}}</style><main><div style="color:#4c9b62;font-size:12px;letter-spacing:2px;font-weight:bold">ПОЕХАЛИ · РАННИЙ ДОСТУП</div>'+body+'<footer>'+seller+'<br><a href="/terms">Оферта</a> · <a href="/privacy">Конфиденциальность</a> · <a href="/consent">Согласие</a> · <a href="/refund">Возвраты</a> · <a href="/cookies">Cookie</a> · <a href="/contacts">Реквизиты</a> · <a href="https://poehali-lead-board.onrender.com/">Презентация</a></footer></main></html>')
@app.after_request
def headers(r):
 r.headers['X-Content-Type-Options']='nosniff'
 r.headers['Referrer-Policy']='no-referrer'
 # The always-on static lead magnet can prewarm the free payment backend.
 # Only the non-sensitive /health endpoint permits cross-origin requests.
 if request.path in ('/health','/funnel/event'):
  r.headers['Cache-Control']='no-store'
  if request.headers.get('Origin')=='https://poehali-lead-board.onrender.com':
   r.headers['Access-Control-Allow-Origin']='https://poehali-lead-board.onrender.com'
   r.headers['Vary']='Origin'
   if request.path=='/funnel/event':
    r.headers['Access-Control-Allow-Methods']='POST, OPTIONS'
    r.headers['Access-Control-Allow-Headers']='Content-Type'
 return r
@app.get('/health')
def health():
 f=flags()
 return jsonify(ok=True, db=DB_OK, checkout_ready=ready(), checks={k:bool(v) for k,v in f.items()},
               fiscal_order_enabled=os.getenv('POEHALI_FISCAL_ORDER_FLOW')=='1',
               telegram_funnel_ready=bool(os.getenv('TG_FUNNEL_BOT_TOKEN')))
@app.get('/')
def home():return redirect('/checkout')
@app.get('/checkout')
def form():
 # Each fresh checkout page is a new purchase attempt. Do not reuse the
 # nonce from the last paid order (or POST would redirect to /course).
 # A repeated POST of this same form still reuses its bank link safely.
 session.permanent=True
 session['csrf']=secrets.token_urlsafe(28)
 session['nonce']=secrets.token_urlsafe(30)
 funnel_ref=request.args.get('funnel','')
 lead=lead_for_ref(funnel_ref)
 if not lead or lead['product']!='poehali' or lead['purchased']:
  funnel_ref=''
 else:
  record_event(funnel_ref,'checkout_view')
 return make_response(checkout_document(
  enabled=ready(),
  csrf=session['csrf'],
  form_token=signed_form(session['csrf'],session['nonce'],funnel_ref),
  seller=os.getenv('SELLER_NAME','Продавец курса «Поехали»'),
  price_label='1 ₽',
 ))

@app.post('/checkout')
def purchase():
 if not (ready() and DB_OK):abort(503)
 # A short-lived signed form token survives lost session cookies in iOS in-app browsers.
 token=request.form.get('form_token','')
 try:
  state=URLSafeTimedSerializer(app.secret_key,salt='poehali-checkout-form-v1').loads(token,max_age=3600)
 except (BadSignature,SignatureExpired,ValueError,TypeError):
  return checkout_problem('form')
 csrf=request.form.get('csrf','')
 if not isinstance(state,dict) or not isinstance(state.get('csrf'),str) or not isinstance(state.get('nonce'),str) or not csrf or len(state['nonce'])<25 or not hmac.compare_digest(state['csrf'],csrf):
  return checkout_problem('form')
 session.permanent=True
 session['csrf']=csrf
 session['nonce']=state['nonce']
 # Clicking "Pay" expressly accepts the linked offer. Order email is used
 # for contract/legal duties, not as implied optional or marketing consent.
 email=request.form.get('email','').lower().strip()
 if len(email)>255 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[A-Za-zА-Яа-я]{2,}',email):abort(400)
 method='hosted'  # Buyer chooses SBP or bank card on the provider's page.
 # Signed form token is the CSRF safeguard, including for iOS in-app browsers.
 # Origin is not a reliable required value in embedded browsers.
 nonce=state['nonce']
 funnel_ref=state.get('ref','')
 lead=lead_for_ref(funnel_ref)
 if not lead or lead['product']!='poehali' or lead['purchased']:
  funnel_ref=''
 old=db('SELECT id,state,paylink FROM poehali_orders WHERE nonce=%s',(nonce,),True)
 if old:
  if old['state']=='paid':
   # A stale form may be resent by the browser. Never charge it twice, but
   # show an actionable new-checkout link instead of surprising course redirect.
   session['course_oid']=old['id']
   return page('Заказ уже оплачен','<h1>Этот заказ уже оплачен</h1><p>Для новой покупки откройте форму оформления.</p><a class="button" href="/checkout">Новая покупка — 1 ₽</a><p><a href="/course">Открыть уже купленный курс</a></p>')
  if old['state']=='pending' and hosted(old['paylink']):
   return redirect(old['paylink'],code=303)
  if old['state']=='creating':
   return page('Заказ обрабатывается','<h1>Заказ уже создаётся</h1><p>Не отправляйте повторно. Обновите страницу позже.</p>'),409
  session['nonce']=secrets.token_urlsafe(30);nonce=session['nonce']
 oid=secrets.token_hex(16);ext='poehali-'+oid
 db('INSERT INTO poehali_orders(id,email,nonce,amount,method,state,extid,accepted_terms_at,consent_at,legal_version,funnel_ref) VALUES(%s,%s,%s,%s,%s,%s,%s,now(),NULL,%s,%s)',(oid,email,nonce,PRICE,method,'creating',ext,'2026-11-06',funnel_ref or None))
 if funnel_ref:
  record_event(funnel_ref,'checkout_started')
 try:
  link,pid,eid=bank_create(get(oid))
  db("UPDATE poehali_orders SET state='pending',paylink=%s,paymentid=%s,orderext=%s WHERE id=%s",(link,pid,eid,oid))
 except BankCheckoutError as exc:
  db("UPDATE poehali_orders SET state='failed' WHERE id=%s",(oid,))
  user_message='Ozon Pay отклонил запрос на создание платежа. Деньги не списаны.'
  user_message+='<p>Код ответа банка: '+str(exc.http_status)+'. Попробуйте снова после устранения ошибки.</p>'
  return page('Ошибка банка','<h1>Не удалось создать заказ</h1><p>'+user_message+'</p><a class="button" href="/checkout">Вернуться к оплате</a>'),503
 except Exception:
  app.logger.exception('Could not create bank payment');db("UPDATE poehali_orders SET state='failed' WHERE id=%s",(oid,))
  return page('Ошибка банка','<h1>Не удалось создать заказ</h1><p>Деньги не списаны. Ошибка сервера зафиксирована для диагностики.</p><a class="button" href="/checkout">Вернуться к оплате</a>'),503
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
 proof=request.args.get('proof','')
 auth_ok=False
 if proof:
  try:
   signed=URLSafeTimedSerializer(app.secret_key,salt='poehali-checkout-result-v1').loads(proof,max_age=86400)
   auth_ok=isinstance(signed,dict) and hmac.compare_digest(str(signed.get('id','')),o['id']) and hmac.compare_digest(str(signed.get('nonce','')),o['nonce'])
  except (BadSignature,SignatureExpired,ValueError,TypeError):pass
 elif session.get('nonce'):
  auth_ok=hmac.compare_digest(session['nonce'],o['nonce'])
 if not auth_ok:return checkout_problem('form')
 session.permanent=True
 session['nonce']=o['nonce']
 proof_query='&proof='+quote(proof,safe='') if proof else ''
 if check(o):
  session['course_oid']=o['id']
  mailed=email_access(o) if os.getenv('POEHALI_SMTP_ENABLED')=='1' else False
  # Bank-confirmed access can be opened immediately in the same browser.
  if mailed:
   message='<p>Письмо с персональной ссылкой на курс отправлено на указанный email. Откройте его и перейдите по ссылке.</p>'
  else:
   message='<p>Оплата подтверждена банком. Письмо пока недоступно, но курс можно открыть прямо здесь. При закрытии браузера вернитесь к подтверждению оплаты. Поддержка: '+html.escape(os.getenv('SELLER_EMAIL',''))+'.</p>'
  return page('Оплата подтверждена','<h1>Оплата 1 ₽ подтверждена!</h1>'+message+'<a class="button" href="/course">Открыть курс</a>')
 if kind=='fail':
  return page('Оплата не подтверждена','<h1>Оплата пока не подтверждена</h1><p>Банк вернул вас на страницу неуспешной оплаты. Если деньги всё же списались, не платите повторно, пока мы не проверим статус.</p><a class="button" href="/result?order='+o['id']+proof_query+'">Проверить статус заказа</a><a href="/checkout">Вернуться к оформлению</a>')
 return page('Проверяем платёж','<h1>Проверяем оплату</h1><p>Ожидаем подтверждение Ozon. Не платите повторно.</p><a class="button" href="/result?order='+o['id']+proof_query+'">Проверить снова</a>')

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
 # Log only transport metadata, never webhook body, signatures or personal data.
 app.logger.warning('Ozon notification received: content_type=%s length=%s', request.mimetype, request.content_length)
 if request.content_length and request.content_length>10000:abort(413)
 data=request.get_json(silent=True)
 if not isinstance(data,dict):abort(400)
 secret=os.getenv('OZON_PAY_NOTIFICATION_SECRET_KEY','');access=os.getenv('OZON_PAY_ACCESS_KEY','')
 if not (secret and access):abort(503)
 amt=str(data.get('amount') or '');curr=str(data.get('currencyCode') or '');ext=str(data.get('extTransactionID') or '');exorder=str(data.get('extOrderID') or data.get('extOrderId') or '');orderid=str(data.get('orderID') or data.get('orderId') or '');tx=str(data.get('transactionID') or '')
 checks=[hashlib.sha256((access+'|||'+ext+'|'+amt+'|'+curr+'|'+secret).encode()).hexdigest(),hashlib.sha256((access+'|'+orderid+'|'+tx+'|'+exorder+'|'+amt+'|'+curr+'|'+secret).encode()).hexdigest()]
 supplied=str(data.get('requestSign') or '')
 if not supplied or not any(hmac.compare_digest(supplied,x) for x in checks):
  app.logger.warning('Ozon notification signature failed verification')
  abort(403)
 app.logger.warning('Ozon notification signature verified')
 m=re.search(r'poehali-(?:order-)?([0-9a-f]{32})',ext+' '+exorder)
 if m:
  o=get(m.group(1))
  if o and check(o):email_access(o)
 return jsonify(ok=True)
@app.get('/terms')
@app.get('/privacy')
@app.get('/consent')
@app.get('/refund')
@app.get('/cookies')
@app.get('/contacts')
def legal_page():
 key=request.path.strip('/')
 document=docs().get(key)
 if not document:abort(404)
 return page(document[0],document[1])
# The funnel's tables are scoped by product and do not share bot tokens.
register_funnel(app,conn,check,url())
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))