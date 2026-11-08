"""Standalone web checkout for Sovpali (NOT a Telegram in-app purchase).

Creates individual Ozon Pay orders from server-held credentials, records amounts
in kopecks, validates hosted redirects and reconciles payment status with Ozon.
No services are auto-unlocked: product fulfillment is deliberately fail-closed
until it has been implemented and tested independently.
"""
import hashlib
import hmac
import html
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests
from flask import abort, make_response, redirect, request, session

API_DEFAULT = "https://payapi.ozon.ru"
CURRENCY = "643"
PRODUCTS = {
    "workshop": {"price": 500, "title": "Эмулятор общения", "description": "Первое сообщение и тренировка диалога для вашей пары.", "sellable": False},
    "test100": {"price": 100, "title": "Проверка платежа", "description": "Реальное списание 100 ₽ со своей карты или через СБП. Никакие функции бота не открываются.", "sellable": True},
    "contact": {"price": 100, "title": "Запрос на знакомство", "description": "Покупается только с персональной страницы пары. Контакт открывается после взаимного согласия.", "sellable": False},
    "coach": {"price": 900, "title": "Помощник в переписке", "description": "Персональные подсказки и продолжение диалога.", "sellable": False},
    "premium": {"price": 1200, "title": "Премиум на месяц", "description": "Расширенные функции сервиса.", "sellable": False},
}
_LOCK = threading.RLock()
PAID = {"COMPLETED", "PAYMENT_COMPLETED", "PAYMENT_COMPLETE", "PAYMENT_SUCCESS", "PAID", "PAYMENT_PAID", "SUCCESS"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mode():
    return os.getenv("OZON_PAY_MODE", "disabled").strip().lower()


def _api_base():
    raw = os.getenv("OZON_PAY_API_URL", API_DEFAULT).strip().rstrip("/")
    try:
        p = urlsplit(raw)
        host = (p.hostname or "").lower()
        if p.scheme != "https" or p.username or p.password or p.port or p.path or p.query or p.fragment:
            return ""
        if host != "payapi.ozon.ru" and not (host.endswith(".ozon.ru") and host != "ozon.ru"):
            return ""
        if _mode() == "test" and host == "payapi.ozon.ru":
            return ""  # Never send sandbox keys to production accidentally.
        return raw
    except ValueError:
        return ""


def _ready():
    return (_mode() in ("live", "test") and bool(_api_base()) and
            bool(os.getenv("OZON_PAY_ACCESS_KEY", "").strip()) and
            bool(os.getenv("OZON_PAY_SECRET_KEY", "").strip()))


def _sales_ready():
    """Never accept a new charge before fiscal receipts are configured.

    Keep _ready() unchanged for reconciliation of already existing charges:
    payment status and service delivery must NOT stop when sales are paused.
    The flag may be activated only after a real KKT/OFD or NPD receipt
    integration has been independently tested with the merchant's legal status.
    """
    return (_ready() and
            os.getenv("SOVPALI_FISCAL_RECEIPTS_ENABLED", "0").strip() == "1")


def _sign(value):
    key = os.getenv("OZON_PAY_ACCESS_KEY", "").strip()
    secret = os.getenv("OZON_PAY_SECRET_KEY", "").strip()
    return hashlib.sha256((value + key + secret).encode()).hexdigest()


def _hosted(url):
    """Only redirect customers to a real bank/network checkout, never arbitrary URL."""
    try:
        p = urlsplit(str(url or ""))
        host = (p.hostname or "").lower().rstrip(".")
        return (str(url).startswith("https://") and p.scheme == "https" and not
                (p.username or p.password or p.port or p.fragment) and
                (host == "qr.nspk.ru" or host.endswith(".ozon.ru") or
                 host.endswith(".ozonpay.ru")) and bool(p.path))
    except ValueError:
        return False


def _post(path, payload):
    response = requests.post(_api_base() + path, json=payload, timeout=(5, 15),
                             headers={"Accept": "application/json"})
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Invalid bank response")
    return data


def _create(order_id, sku, method, amount_kopecks, site_base):
    """Ozon /v1/createPayment, using distinct payment and order extIds."""
    access = os.getenv("OZON_PAY_ACCESS_KEY", "").strip()
    ext_id = "sovpali-" + order_id
    order_ext_id = "sovpali-order-" + order_id
    amount = {"currencyCode": CURRENCY, "value": str(amount_kopecks)}
    return_to = site_base + "/billing/return?order=" + order_id
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {
        "accessKey": access,
        "payType": "SBP",
        "amount": amount,
        "extId": ext_id,
        "redirectUrl": return_to,
        "ttl": 1800,
        "requestSign": _sign(ext_id),
    }
    if os.getenv("OZON_PAY_NOTIFICATION_SECRET_KEY", "").strip():
        body["notificationUrl"] = site_base + "/billing/ozon/notify"
    if method == "card":
        body["order"] = {
            "extId": order_ext_id,
            "amount": amount,
            "paymentAlgorithm": "PAY_ALGO_SMS",
            "mode": "MODE_SHORTENED",
            "expiresAt": expiry,
            "successUrl": return_to,
            "failUrl": return_to,
            # This flag instructs Ozon Pay to fiscalize the card checkout.
            # The merchant must ALSO activate "Онлайн-чеки" in Ozon Pay.
            # New purchases are blocked by _sales_ready until setup is verified.
            "enableFiscalization": True,
        }
    data = _post("/v1/createPayment", body)
    details = data.get("paymentDetails") or {}
    if not isinstance(details, dict):
        raise ValueError("Invalid paymentDetails")
    order = data.get("order") or {}
    if not isinstance(order, dict):
        raise ValueError("Invalid order")
    payment_id = str(details.get("paymentId") or "")[:200]
    if method == "card":
        item = order.get("item") or {}
        checkout = (item.get("payLink") if isinstance(item, dict) else None) or order.get("payLink")
    else:
        sbp = details.get("sbp") or {}
        checkout = order.get("payLink") or (sbp.get("payload") if isinstance(sbp, dict) else None)
    if not checkout or not _hosted(checkout):
        raise ValueError("Provider returned no trusted checkout link")
    return checkout, payment_id, order_ext_id


def _schema(db):
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS billing_web_orders (
          order_id TEXT PRIMARY KEY,
          browser_nonce TEXT UNIQUE NOT NULL,
          product_key TEXT NOT NULL,
          amount_kopecks INTEGER NOT NULL,
          currency_code TEXT NOT NULL,
          method TEXT NOT NULL,
          status TEXT NOT NULL,
          checkout_url TEXT,
          provider_payment_id TEXT,
          provider_order_ext_id TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          paid_at TEXT
        );
        """)


def _verify(order, db):
    """Fail closed: only bank-to-server status with exact amount confirms a charge."""
    if not _ready() or order["status"] == "paid" or not order["checkout_url"]:
        return str(order["status"])
    order_id = order["order_id"]
    candidates = [
        ("extId", order["provider_order_ext_id"]) if order["method"] == "card" else ("id", order["provider_payment_id"]),
        ("id", order["provider_payment_id"]),
        ("extId", "sovpali-" + order_id),
        ("extId", order["provider_order_ext_id"]),
    ]
    tried = set()
    for key, val in candidates:
        if not val or val in tried:
            continue
        tried.add(val)
        try:
            data = _post("/v1/getPaymentDetails", {
                key: val, "accessKey": os.getenv("OZON_PAY_ACCESS_KEY", "").strip(),
                "requestSign": _sign(val),
            })
        except (requests.RequestException, ValueError):
            return "checking"
        items = data.get("items") or []
        node = items[0] if isinstance(items, list) and items else {}
        if not isinstance(node, dict) or not node:
            node = data.get("paymentDetails") or data.get("payment") or {}
        if not isinstance(node, dict):
            continue
        status = str(node.get("status") or "").upper()
        if not status:
            continue
        if status not in PAID:
            return "pending"
        actual = node.get("amount")
        if isinstance(actual, dict):
            cc = str(actual.get("currencyCode") or CURRENCY)
            actual = actual.get("value")
        else:
            cc = str(node.get("currencyCode") or CURRENCY)
        try:
            matched = int(actual) == int(order["amount_kopecks"]) and cc == CURRENCY
        except (TypeError, ValueError):
            matched = False
        if not matched:
            return "mismatch"
        ts = _now()
        with db() as c:
            c.execute("UPDATE billing_web_orders SET status='paid',paid_at=?,updated_at=? WHERE order_id=? AND status='pending'",
                      (ts, ts, order_id))
        return "paid"
    return "checking"


def _csrf_ok():
    """Check a one-time form secret AND the public HTTPS origin.

    Render terminates HTTPS at its proxy; request.host_url can be HTTP
    internally even when the customer's browser uses HTTPS. Comparing
    those two strings caused genuine checkout clicks to get 403.
    """
    provided = request.form.get("csrf", "")
    expected = session.get("billing_csrf", "")
    if not provided or not expected or not hmac.compare_digest(provided, expected):
        return False
    origin = request.headers.get("Origin", "").rstrip("/")
    if not origin:
        return True   # Browsers can omit Origin; the form CSRF secret is still required.
    public = "https://one2-1o22.onrender.com"
    configured = os.getenv("WEBHOOK_BASE_URL", "").strip().rstrip("/")
    allowed = {public}
    if configured.startswith("https://"):
        allowed.add(configured)
    return origin in allowed


def _html(ready, csrf, message=""):
    options = []
    for key, value in PRODUCTS.items():
        disabled = "" if value["sellable"] else ' data-notready="1"'
        options.append(
            '<button type="button" class="product' + (' active' if key == "test100" else "") +
            '" data-sku="' + key + '"' + disabled + '><span><b>' +
            html.escape(value["title"]) + '</b><small>' +
            html.escape(value["description"]) + '</small></span><strong>' +
            f'{value["price"]:,}'.replace(",", " ") + ' ₽</strong></button>'
        )
    status = ("Эквайринг подключён. Списание настоящее — сверь сумму на стороне Ozon Pay."
              if ready else
              "Новые списания временно закрыты до подключения фискальных чеков. Ранее оплаченные заказы продолжают проверяться.")
    if message:
        status = message
    button_disabled = "" if ready else " disabled"
    return """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#161118"><meta name="robots" content="noindex,nofollow"><title>Оплата · Совпали</title>
<style>
:root{--bg:#161118;--fg:#fff0ee;--muted:#ad9ba9;--accent:#efb9bd;--line:#ffffff28}*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 30% 0%,#61334280,transparent 52%),var(--bg);font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:var(--fg)}
header{padding:24px 5%;border-bottom:1px solid var(--line);font-size:26px;font-weight:800;letter-spacing:-1.2px}header span{color:var(--accent)}
main{max-width:1120px;margin:0 auto;padding:64px 5%;display:grid;grid-template-columns:1fr 1fr;gap:60px;align-items:start}
.kicker{font-size:11px;letter-spacing:2px;color:var(--accent);font-weight:700;text-transform:uppercase}
h1{font-size:clamp(47px,7vw,87px);letter-spacing:-.065em;line-height:.99;font-weight:600;margin:24px 0}
h1 em{font-weight:400;color:var(--accent);font-family:Georgia,serif}
.lead{max-width:470px;color:var(--muted);font-size:16px;line-height:1.9}.how{margin-top:43px;border-top:1px solid var(--line)}
.how p{padding:16px 0;border-bottom:1px solid var(--line);font-size:13px;color:#d9c4cf;margin:0}.how b{color:var(--accent);margin-right:16px}
.panel{background:linear-gradient(140deg,#30232f,#211b24);border:1px solid #ffffff38;padding:34px;box-shadow:0 25px 100px #0005}
.panel-title{font-size:11px;letter-spacing:1.6px;color:var(--accent);font-weight:750;margin-bottom:24px}.products{display:grid;gap:8px}
.product{border:1px solid #ffffff30;background:#ffffff08;width:100%;display:flex;justify-content:space-between;align-items:center;gap:14px;text-align:left;padding:17px;color:var(--fg);cursor:pointer}
.product.active{background:#c7829921;border-color:var(--accent)}.product b{font-size:15px}.product small{display:block;color:var(--muted);line-height:1.5;font-size:11px;margin-top:6px}.product strong{white-space:nowrap;font-size:20px}.product[data-notready]{opacity:.6}
.row{border-top:1px solid #ffffff29;margin-top:25px;padding-top:20px;display:flex;align-items:center;justify-content:space-between}.row span{color:var(--muted)}.row strong{font-size:37px;letter-spacing:-1.3px}
fieldset{border:0;padding:0;margin:23px 0 0}legend{font-size:11px;font-weight:750;color:#ead6db;letter-spacing:1.2px;margin-bottom:12px}
.methods{display:grid;grid-template-columns:1fr 1fr;gap:10px}.methods label{border:1px solid #ffffff3b;padding:16px 12px;display:flex;gap:9px;align-items:center;font-size:14px;cursor:pointer}
input[type=radio]{accent-color:#efb9bd}.cta{background:var(--accent);color:#251923;width:100%;border:0;padding:19px;font-weight:800;font-size:14px;margin-top:20px;cursor:pointer}.cta:disabled{opacity:.55;cursor:not-allowed}
.note{font-size:11px;color:var(--muted);line-height:1.7;margin:13px 0 0}.status{margin-top:21px;color:#ebc3c4;line-height:1.7;font-size:12px}
footer{border-top:1px solid var(--line);padding:24px 5%;font-size:11px;color:var(--muted)}
@media(max-width:850px){main{grid-template-columns:1fr;padding-top:40px;gap:34px}.how{display:none}.panel{max-width:630px;width:100%;padding:25px}}
</style></head><body><header>♡ совпали<span>.</span></header>
<main><section><div class="kicker">Безопасная оплата · сайт «Совпали»</div><h1>Следующий шаг<br><em>навстречу.</em></h1>
<p class="lead">Выберите услугу и удобный способ оплаты. Банковская карта и СБП обрабатываются Ozon Pay. Мы не получаем и не храним реквизиты карты.</p>
<div class="how"><p><b>01</b>Проверьте стоимость</p><p><b>02</b>Подтвердите платёж на стороне банка</p><p><b>03</b>Вернитесь для проверки результата</p></div></section>
<section class="panel"><div class="panel-title">ОФОРМЛЕНИЕ ПОКУПКИ</div><div class="products">""" + "".join(options) + """</div>
<div class="row"><span>Итого</span><strong id="total">100 ₽</strong></div>
<form id="checkout" method="post" action="/billing/create"><input type="hidden" name="csrf" value=\"""" + html.escape(csrf, quote=True) + """\"><input type="hidden" name="sku" id="sku" value="test100">
<fieldset><legend>СПОСОБ ОПЛАТЫ</legend><div class="methods">
<label><input type="radio" name="method" value="card" checked> Картой</label>
<label><input type="radio" name="method" value="sbp"> Через СБП</label></div></fieldset>
<button type="submit" class="cta" id="submit" """ + button_disabled + """>ПЕРЕЙТИ К ОПЛАТЕ 100 ₽</button></form>
<p class="note">Оплата 100 ₽ — только личная проверка эквайринга. Она не предоставляет контакт или премиум. Повторное нажатие не создаст второй заказ в этой сессии.</p>
<p class="status" id="status" role="status">""" + html.escape(status) + """</p></section></main>
<footer>СОВПАЛИ · HTTPS · БАНКОВСКИЕ ПЛАТЕЖИ ЧЕРЕЗ OZON PAY</footer>
<script>(function(){
const b=document.getElementById('submit'),s=document.getElementById('status'),sku=document.getElementById('sku');
document.querySelectorAll('.product').forEach(function(el){el.addEventListener('click',function(){
document.querySelectorAll('.product').forEach(x=>x.classList.remove('active'));el.classList.add('active');
const id=el.dataset.sku;sku.value=id;
const price=id==='test100'?100:id==='coach'?900:id==='workshop'?500:1200;
document.getElementById('total').textContent=price.toLocaleString('ru-RU')+' ₽';
b.disabled=el.hasAttribute('data-notready')||""" + ("false" if ready else "true") + """;
b.textContent=el.hasAttribute('data-notready')?'ПРОДАЖА ПОКА НЕ ОТКРЫТА':'ПЕРЕЙТИ К ОПЛАТЕ '+price+' ₽';
s.textContent=el.hasAttribute('data-notready')?'Покупка этой услуги будет доступна после подключения её автоматической выдачи.':'""" + html.escape(status).replace("'", "&#39;") + """';
});});
document.getElementById('checkout').addEventListener('submit',function(){b.disabled=true;b.textContent='СОЗДАЁМ ЗАКАЗ…';});
})();</script></body></html>"""


def register_ozon_web_checkout(app, ns):
    db = ns["db"]
    ns["web_checkout_ready"] = _sales_ready
    print("[billing] startup readiness mode=" + _mode() +
          " valid_api=" + str(bool(_api_base())) +
          " access_key_present=" + str(bool(os.getenv("OZON_PAY_ACCESS_KEY", "").strip())) +
          " secret_key_present=" + str(bool(os.getenv("OZON_PAY_SECRET_KEY", "").strip())) +
          " notify_key_present=" + str(bool(os.getenv("OZON_PAY_NOTIFICATION_SECRET_KEY", "").strip())) +
          " bank_ready=" + str(bool(_ready())) +
          " new_charges_allowed=" + str(bool(_sales_ready())), flush=True)
    with app.app_context():
        _schema(db)

    @app.before_request
    def billing_legacy_redirect():
        # Existing bookmarks must never land on the old disabled preview.
        if request.method == "GET" and request.path == "/billing/demo":
            return redirect("/billing/pay", code=302)

    def respond(body, status=200):
        res = make_response(body, status)
        res.headers["Cache-Control"] = "private, no-store"
        res.headers["Referrer-Policy"] = "no-referrer"
        res.headers["X-Robots-Tag"] = "noindex,nofollow"
        res.headers["X-Content-Type-Options"] = "nosniff"
        return res

    @app.get("/billing/pay")
    def billing_pay():
        if request.args.get("new") == "1":
            session.pop("billing_nonce", None)
        csrf = session.setdefault("billing_csrf", secrets.token_urlsafe(32))
        session.setdefault("billing_nonce", secrets.token_urlsafe(32))
        return respond(_html(_sales_ready(), csrf))

    @app.post("/billing/create")
    def billing_create():
        if not _csrf_ok():
            abort(403)
        if not _sales_ready():
            return respond(_html(False, session["billing_csrf"],
                "Новые платежи временно закрыты: сначала подключаем и проверяем фискальные чеки."), 503)
        sku = request.form.get("sku")
        method = request.form.get("method")
        if sku not in PRODUCTS or method not in ("card", "sbp"):
            abort(400)
        context = None
        if sku == "contact":
            # Pair-specific website order: never sold by the generic demo form.
            if not callable(ns.get("web_contact_live")) or not ns["web_contact_live"]():
                abort(403)
            token = session.get("billing_pair_token")
            if not token or not callable(ns.get("web_contact_validate")):
                abort(403)
            from web_product_access import premium_active
            buyer, target, _, _ = ns["web_contact_validate"](token)
            verified = ns.get("web_owner_verified")
            if not callable(verified) or not verified(buyer):
                abort(403)
            if premium_active(db, buyer):
                return respond("У вас уже есть Premium. Не оплачивайте знакомство повторно.", 409)
            existing_fn = ns.get("cr_between")
            existing = existing_fn(buyer, target) if callable(existing_fn) else None
            if existing and str(existing["status"]) in ("pending", "accepted"):
                return respond("Запрос уже существует — повторная оплата не нужна.", 409)
            context = (buyer,target)
        elif sku == "workshop":
            if not ns.get("web_workshop_live",lambda:False)():abort(403)
            token=session.get("billing_workshop_token")
            validate=ns.get("web_workshop_validate")
            if not token or not callable(validate):abort(403)
            buyer,target,_,_=validate(token)
            if not ns.get("web_owner_verified",lambda _:False)(buyer):abort(403)
            if ns["web_workshop_paid"](buyer,target):
                return respond("Эмулятор уже оплачен. Повторная покупка не нужна.",409)
            context=(buyer,target)
        elif sku == "coach":
            if not callable(ns.get("web_coach_live")) or not ns["web_coach_live"]():
                abort(403)
            token=session.get("billing_coach_token")
            if not token or not callable(ns.get("web_coach_validate")):
                abort(403)
            buyer,target,_,_=ns["web_coach_validate"](token)
            verified=ns.get("web_owner_verified")
            if not callable(verified) or not verified(buyer):
                abort(403)
            existing=ns.get("web_coach_unspent")
            if callable(existing) and existing(buyer,target):
                return respond("У тебя уже есть оплаченный разбор. Открой помощник без повторной оплаты.",409)
            context=(buyer,target)
        elif sku == "premium":
            if not callable(ns.get("web_premium_live")) or not ns["web_premium_live"]():
                abort(403)
            token=session.get("billing_pair_token")
            if not token or not callable(ns.get("web_contact_validate")):
                abort(403)
            buyer,_,_,_=ns["web_contact_validate"](token)
            verified=ns.get("web_owner_verified")
            if not callable(verified) or not verified(buyer):
                abort(403)
            context=(buyer,None)
        elif not PRODUCTS[sku]["sellable"]:
            abort(400)
        nonce = session.get("billing_nonce")
        if not nonce:
            abort(403)
        with _LOCK:
            with db() as c:
                previous = c.execute("SELECT * FROM billing_web_orders WHERE browser_nonce=?", (nonce,)).fetchone()
            if previous:
                # Once the bank confirmed an order, never send this session
                # back to its old charge form on another click.
                if previous["status"] == "paid":
                    return redirect("/billing/return?order="+previous["order_id"],code=303)
                url = previous["checkout_url"]
                if url and _hosted(url):
                    return redirect(url, code=303)
                return respond("<h2>Заказ уже создан, но банк не вернул ссылку.</h2><p>Проверьте операции банка перед повтором.</p><a href='/billing/pay?new=1'>Новый заказ</a>", 409)
            intro_id = None
            if sku == "contact":
                reserve = ns.get("ip_reserve_intro")
                if not callable(reserve):
                    return respond("Резервирование пары временно недоступно.", 503)
                result, reserved = reserve(context[0], context[1], 100)
                if result != "reserved" or not reserved:
                    return respond("Эта пара уже ожидает ответ или другое знакомство. Деньги не списаны.", 409)
                intro_id = int(reserved["id"])
            order_id = secrets.token_hex(16)
            now = _now()
            amount = PRODUCTS[sku]["price"] * 100
            try:
                with db() as c:
                    c.execute("""INSERT INTO billing_web_orders
                      (order_id,browser_nonce,product_key,amount_kopecks,currency_code,method,status,created_at,updated_at)
                      VALUES(?,?,?,?,? ,?,'initiating',?,?)""",
                      (order_id, nonce, sku, amount, CURRENCY, method, now, now))
                if context is not None:
                    from web_product_access import bind_order
                    bind_order(db,order_id,context[0],sku,
                               target_id=context[1],linked_intro_id=intro_id)
            except Exception:
                if intro_id is not None:
                    ns["ip_close"](intro_id)
                app.logger.exception("Could not reserve a bank order")
                return respond("Создание заказа недоступно. Оплата не начата.", 503)
            try:
                site_base = os.getenv("WEBHOOK_BASE_URL", "").strip().rstrip("/")
                if not site_base.startswith("https://") or urlsplit(site_base).hostname != "one2-1o22.onrender.com":
                    raise ValueError("Configured public site URL is missing or invalid")
                url, payment_id, order_ext_id = _create(order_id, sku, method, amount, site_base)
            except (requests.RequestException, ValueError) as exc:
                app.logger.warning("Ozon payment initialization failed: %s", type(exc).__name__)
                with db() as c:
                    c.execute("UPDATE billing_web_orders SET status='init_failed',updated_at=? WHERE order_id=?", (_now(), order_id))
                if intro_id is not None:
                    ns["ip_close"](intro_id)
                return respond("<h2>Не удалось открыть оплату</h2><p>Банк не подтвердил создание заказа. Списание не подтверждено.</p><a href='/billing/pay?new=1'>Попробовать новый заказ</a>", 503)
            with db() as c:
                c.execute("""UPDATE billing_web_orders SET status='pending',checkout_url=?,
                    provider_payment_id=?,provider_order_ext_id=?,updated_at=? WHERE order_id=?""",
                    (url, payment_id, order_ext_id, _now(), order_id))
        res = redirect(url, code=303)
        res.headers["Cache-Control"] = "private, no-store"
        res.headers["Referrer-Policy"] = "no-referrer"
        return res

    def _verify_and_fulfill(order):
        state = _verify(order, db)
        # Only bank-verified paid product orders can earn referrals.
        # Noncritical ledger failures cannot block delivery; partner dashboard
        # independently recovers any missing confirmed awards.
        if state == "paid" and ns.get("affiliate_active") and order["product_key"] in ("contact","premium","coach","workshop"):
            try:
                from affiliate_program import accrue_paid_order
                with db() as c:
                    accrue_paid_order(c,order["order_id"])
            except Exception as exc:
                app.logger.warning("Affiliate accrual deferred: %s",type(exc).__name__)
        delivery = None
        if state == "paid" and order["product_key"] == "contact":
            from web_intro_fulfillment import fulfill_intro
            delivery = fulfill_intro(ns, order["order_id"])
        if state == "paid" and order["product_key"] == "premium":
            from web_product_access import grant_premium
            delivery = "premium_delivered" if grant_premium(db,order["order_id"]) else "support_required"
        if state == "paid" and order["product_key"] == "workshop":
            from web_workshop import fulfill
            delivery = "workshop_delivered" if fulfill(db,order["order_id"]) else "support_required"
        if state == "paid" and order["product_key"] == "coach":
            delivery = "coach_ready"  # Report is created only on explicit user consent.
        return state, delivery

    @app.get("/billing/return")
    def billing_return():
        oid = request.args.get("order", "")
        if not re.fullmatch(r"[a-f0-9]{32}", oid):
            abort(404)
        with db() as c:
            order = c.execute("SELECT * FROM billing_web_orders WHERE order_id=?", (oid,)).fetchone()
        if not order:
            abort(404)
        state, delivery = _verify_and_fulfill(order)
        title = "Оплата подтверждена" if state == "paid" else "Проверяем платёж"
        next_url="/billing/pay?new=1"
        next_label="На страницу оплаты"
        sku=order["product_key"]
        if state == "paid" and sku == "contact":
            if delivery == "delivered":
                body=("Ozon Pay подтвердил 100 ₽. Запрос отправлен второму человеку в Telegram. "
                      "Теперь переключись на второй аккаунт и нажми «Да, хочу общаться» или «Не сейчас». "
                      "Контакт появится только при согласии.")
            elif delivery == "credit_issued":
                body=("Банк подтвердил 100 ₽, но время бронирования этой пары истекло до завершения платежа. "
                      "Оплата сохранена как один повторный запрос без доплаты — выбери следующую подходящую анкету.")
            else:
                body=("Банк подтвердил 100 ₽. Доставка запроса ещё проверяется. "
                      "Не оплачивай повторно. Обнови эту страницу для проверки результата.")
        elif state == "paid" and sku == "premium":
            body=("Ozon Pay подтвердил 1 200 ₽. Premium действует 30 дней без автоматического продления."
                  if delivery == "premium_delivered" else
                  "Платёж подтверждён, но доступ ещё проверяется. Не оплачивай повторно.")
        elif state == "paid" and sku == "workshop":
            body="Банк подтвердил 500 ₽. Эмулятор общения для вашей пары открыт."
        elif state == "paid" and sku == "coach":
            body="Ozon Pay подтвердил 900 ₽. Вернись в конструктор и вставь реальный ответ для оплаченного разбора."
        elif state == "paid":
            body="Банк подтвердил 100 ₽. Это личный тест эквайринга, без выдачи услуги."
        else:
            body="Подтверждение банка ещё не получено. Не оплачивай повторно, пока операция проверяется."
            next_url="/billing/return?order="+oid
            next_label="Обновить статус платежа"

        # Show private next steps only when the verified Telegram owner
        # matches this exact bank order; a bare return URL never grants access.
        if state=="paid" and sku in ("contact","premium","coach","workshop"):
            with db() as c:
                binding=c.execute("""SELECT buyer_user_id,target_user_id
                        FROM web_purchase_bindings WHERE billing_order_id=?""",
                        (oid,)).fetchone()
            if binding and callable(ns.get("web_owner_verified")) and ns["web_owner_verified"](int(binding["buyer_user_id"])):
                if sku in ("contact","premium"):
                    token=session.get("billing_pair_token")
                    try:
                        v,t,*_=ns["web_contact_validate"](token) if token else (None,None)
                        if int(v)==int(binding["buyer_user_id"]) and (
                            sku=="premium" or int(t)==int(binding["target_user_id"])
                        ):
                            next_url=("/s/m/" if sku=="contact" else "/billing/premium/")+token
                            next_label=("Вернуться к вашей паре" if sku=="contact" else
                                        "Открыть возможности Premium")
                    except (ValueError,TypeError,KeyError):
                        pass
                elif sku=="workshop":
                    token=session.get("billing_workshop_token")
                    try:
                        v,t,*_=ns["web_workshop_validate"](token) if token else (None,None)
                        if int(v)==int(binding["buyer_user_id"]) and int(t)==int(binding["target_user_id"]):
                            next_url="/coach/t/"+token
                            next_label="Открыть эмулятор общения"
                    except (ValueError,TypeError,KeyError):
                        pass
                elif sku=="coach":
                    token=session.get("billing_coach_token")
                    try:
                        v,t,*_=ns["web_coach_validate"](token) if token else (None,None)
                        if int(v)==int(binding["buyer_user_id"]) and int(t)==int(binding["target_user_id"]):
                            next_url="/coach/t/"+token
                            next_label="Открыть конструктор общения"
                    except (ValueError,TypeError,KeyError):
                        pass
        # All URLs are internally constructed from server-validated tokens.
        from urllib.parse import quote
        safe_next=html.escape(next_url,quote=True)
        return respond("<!doctype html><html lang='ru'><meta charset='utf-8'>"
          "<meta name='viewport' content='width=device-width,initial-scale=1'>"
          "<meta name='robots' content='noindex,nofollow'><title>Совпали · Результат</title>"
          "<style>body{background:radial-gradient(circle at 10% 0%,#673b4a80,transparent 60%),#161118;"
          "color:#ffeced;font:17px/1.7 system-ui;max-width:650px;margin:10vh auto;padding:28px}"
          "h1{font-size:clamp(36px,7vw,55px);line-height:1.1}"
          "a.btn{display:block;background:#edb8c0;color:#2b1720;text-decoration:none;"
          "padding:17px 22px;margin-top:29px;font-weight:700;text-align:center}"
          "small{color:#bca7b3}</style><h1>"+html.escape(title)+"</h1>"
          "<p>"+html.escape(body)+"</p>"
          "<small>Заказ: "+html.escape(oid)+"</small>"
          "<a class='btn' href='"+safe_next+"'>"+html.escape(next_label)+"</a>"
          "</html>")

    @app.get("/billing/status/<oid>")
    def billing_status(oid):
        if not re.fullmatch(r"[a-f0-9]{32}", oid):
            abort(404)
        if not session.get("billing_nonce"):
            abort(403)
        with db() as c:
            order = c.execute("SELECT * FROM billing_web_orders WHERE order_id=? AND browser_nonce=?", (oid, session["billing_nonce"])).fetchone()
        if not order:
            abort(404)
        result, delivery = _verify_and_fulfill(order)
        return respond({"order_id": oid, "status": result, "delivery": delivery})

    @app.post("/billing/ozon/notify")
    def billing_ozon_notify():
        if request.content_length and request.content_length > 10000:
            abort(413)
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400)
        secret = os.getenv("OZON_PAY_NOTIFICATION_SECRET_KEY", "").strip()
        if not secret:
            abort(503)
        supplied = str(data.get("requestSign") or "")
        amount = str(data.get("amount") or "")
        currency = str(data.get("currencyCode") or "")
        ext_tx = str(data.get("extTransactionID") or "")
        ext_ord = str(data.get("extOrderID") or data.get("extOrderId") or "")
        order_id = str(data.get("orderID") or data.get("orderId") or "")
        tx_id = str(data.get("transactionID") or "")
        access = os.getenv("OZON_PAY_ACCESS_KEY", "").strip()
        checks = [
            hashlib.sha256((access + "|||" + ext_tx + "|" + amount + "|" + currency + "|" + secret).encode()).hexdigest(),
            hashlib.sha256((access + "|" + order_id + "|" + tx_id + "|" + ext_ord + "|" + amount + "|" + currency + "|" + secret).encode()).hexdigest(),
        ]
        if not supplied or not any(hmac.compare_digest(supplied, x) for x in checks):
            abort(403)
        match = re.search(r"sovpali-(?:order-)?([a-f0-9]{32})", ext_tx + " " + ext_ord)
        if match:
            with db() as c:
                order = c.execute("SELECT * FROM billing_web_orders WHERE order_id=?", (match.group(1),)).fetchone()
            if order:
                _verify_and_fulfill(order)  # Signed notification is only a hint, NEVER payment proof.
        return respond({"ok": True})

    def _reconcile_paid_intros():
        """Bank card callbacks can be missed. Recheck only recent unfinished orders."""
        while True:
            time.sleep(120)
            contacts = callable(ns.get("web_contact_live")) and ns["web_contact_live"]()
            premium = callable(ns.get("web_premium_live")) and ns["web_premium_live"]()
            coach = callable(ns.get("web_coach_live")) and ns["web_coach_live"]()
            if not (contacts or premium or coach):
                continue
            try:
                try:
                    ns["ip_cleanup_expired"]()
                except Exception:
                    pass
                # A pending bank checkout can settle late (within 3 hours).
                # A bank-paid introduction not yet delivered must be recoverable
                # even after 24h recipient timeout, when it becomes a free
                # repeat attempt instead of remaining frozen forever.
                pending_cutoff=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat(timespec="seconds")
                with db() as c:
                    rows=c.execute("""SELECT o.* FROM billing_web_orders o
                        WHERE o.product_key IN ('contact','premium','coach','workshop')
                          AND ((o.status='pending' AND o.created_at>?) OR
                            (o.status='paid' AND EXISTS(
                                SELECT 1 FROM web_purchase_bindings b
                                WHERE b.billing_order_id=o.order_id AND
                                      b.binding_status IN ('reserved','retry'))))
                        ORDER BY o.created_at LIMIT 30""",(pending_cutoff,)).fetchall()
                for order in rows:
                    try:
                        _verify_and_fulfill(order)
                    except Exception as exc:
                        app.logger.warning("Bank reconciliation deferred: %s",type(exc).__name__)
                from web_intro_fulfillment import grant_expired_credits
                grant_expired_credits(ns)
            except Exception as exc:
                app.logger.warning("Web intro reconciliation deferred: %s",type(exc).__name__)

    threading.Thread(target=_reconcile_paid_intros,daemon=True,
                     name="web-intro-bank-reconcile").start()
