"""Telegram nurture funnel for Poekhali and future independently tracked courses.

No bot token is stored in the repository. Opt-in is required for timed marketing
messages. Checkout attribution uses an opaque, unguessable ref; a paid order is
recognized only after Ozon verification in app.py.
"""
import hashlib
import hmac
import os
import re
import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import psycopg2.extras
import requests
from flask import abort, jsonify, redirect, request

PRODUCTS = {
    "poehali": {
        "name": "Поехали",
        "landing": "https://poehali-lead-board.onrender.com/",
        "amount": "1 ₽",
        "series": [
            "💡 Идея продукта без рекламного бюджета\n\nНачни не с кода, а с конкретной проблемы аудитории. Напиши: «Помоги найти 10 вопросов, за решение которых люди готовы платить». Выбери один, затем проверь спрос разговорами с реальными людьми.\n\nВ курсе показываю, как связать идею, бота и оплату.",
            "🤖 Что именно делает бот после покупки?\n\nСхема: человек нажимает кнопку → платёж подтверждается банком → бот открывает нужные материалы. Не нужно вручную проверять переводы и пересылать ссылки.\n\nВажно: автоматизация требует настройки и проверки платежей.",
            "🎬 А как приводить людей без съёмки лица?\n\nОдин короткий ролик = один вопрос аудитории, наглядное решение и один понятный следующий шаг. Сначала протестируй 3 темы, а не создавай сразу 30 роликов.\n\nПродвижение может требовать времени и не гарантирует продаж.",
            "🧩 Вся система в пяти шагах\n\n1. Найти конкретную проблему.\n2. Подготовить полезный продукт.\n3. Подключить Telegram-бота.\n4. Настроить оплату и выдачу.\n5. Приводить аудиторию полезным контентом.\n\nНа этом серия подсказок закончена. Схема и курс остаются доступны по кнопкам ниже."
        ]
    }
}
# Delay until first message, then intervals between the remaining three.
DELAYS = (4 * 3600, 20 * 3600, 48 * 3600, 72 * 3600)
_CONN = None
_CHECK_PAYMENT = None
_ROOT = None
_INITIALIZED = False


def _sql(statement, values=(), one=False, all_rows=False):
    with closing(_CONN()) as conn:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(statement, values)
                if all_rows:
                    return [dict(r) for r in cur.fetchall()]
                if one:
                    obj = cur.fetchone()
                    return dict(obj) if obj else None


def setup():
    global _INITIALIZED
    if _CONN is None:
        return False
    try:
        _sql("""CREATE TABLE IF NOT EXISTS funnel_leads(
            chat_id BIGINT NOT NULL, product TEXT NOT NULL,
            ref TEXT NOT NULL UNIQUE, stage TEXT NOT NULL DEFAULT 'welcome',
            opted_in BOOLEAN NOT NULL DEFAULT FALSE,
            stopped BOOLEAN NOT NULL DEFAULT FALSE,
            purchased BOOLEAN NOT NULL DEFAULT FALSE,
            step INTEGER NOT NULL DEFAULT 0,
            next_at TIMESTAMPTZ, lease_until TIMESTAMPTZ,
            first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(chat_id,product))""")
        _sql("""CREATE TABLE IF NOT EXISTS funnel_events(
            id BIGSERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL, product TEXT NOT NULL, kind TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        _sql("""CREATE TABLE IF NOT EXISTS funnel_telegram_updates(
            update_id BIGINT PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        _sql("ALTER TABLE poehali_orders ADD COLUMN IF NOT EXISTS funnel_ref TEXT")
        _sql("CREATE INDEX IF NOT EXISTS poehali_funnel_ref_idx ON poehali_orders(funnel_ref)")
        _sql("CREATE INDEX IF NOT EXISTS funnel_leads_due_idx ON funnel_leads(next_at) WHERE opted_in AND NOT stopped AND NOT purchased")
        _INITIALIZED = True
        return True
    except Exception as exc:
        # Do not expose database credentials or any customer data.
        print("funnel schema unavailable:", type(exc).__name__)
        return False


def lead_for_ref(ref):
    if not _INITIALIZED or not isinstance(ref, str) or not re.fullmatch(r'[A-Za-z0-9_-]{30,70}', ref):
        return None
    try:
        return _sql("SELECT chat_id,product,ref,stage,purchased FROM funnel_leads WHERE ref=%s", (ref,), one=True)
    except Exception:
        return None


def record_event(ref, kind):
    lead = lead_for_ref(ref)
    if not lead or lead['purchased'] or kind not in ("landing", "checkout_view", "checkout_started"):
        return False
    _sql("""INSERT INTO funnel_events(chat_id,product,kind)
            VALUES(%s,%s,%s)""", (lead["chat_id"], lead["product"], kind))
    if kind == "checkout_started":
        _sql("""UPDATE funnel_leads SET stage='checkout_started',updated_at=now()
                WHERE ref=%s AND NOT purchased""", (ref,))
    elif kind == "checkout_view":
        _sql("""UPDATE funnel_leads SET stage='checkout_view',updated_at=now()
                WHERE ref=%s AND NOT purchased AND stage NOT IN ('checkout_started','paid')""", (ref,))
    elif kind == "landing":
        _sql("""UPDATE funnel_leads SET stage='landing',updated_at=now()
                WHERE ref=%s AND stage='welcome'""", (ref,))
    return True


def mark_paid(order):
    """Stop this course's follow-ups after *verified* Ozon payment only."""
    ref = order.get("funnel_ref")
    lead = lead_for_ref(ref) if ref else None
    if not lead:
        return
    updated = _sql("""UPDATE funnel_leads SET stage='paid', purchased=TRUE, opted_in=FALSE,
            next_at=NULL, lease_until=NULL, updated_at=now()
            WHERE ref=%s AND NOT purchased RETURNING ref""", (ref,),one=True)
    if updated:
        _sql("""INSERT INTO funnel_events(chat_id,product,kind)
                VALUES(%s,%s,'purchase_verified')""", (lead['chat_id'],lead['product']))


def _tg(method, payload):
    token = os.getenv("TG_FUNNEL_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("Telegram funnel token not configured")
    # Avoid logging request URLs: they contain Telegram bot credentials.
    response = requests.post(
        "https://api.telegram.org/bot" + token + "/" + method,
        json=payload, timeout=(4, 12))
    try:
        reply = response.json()
    except ValueError:
        raise RuntimeError("Telegram invalid response") from None
    if not reply.get("ok"):
        raise RuntimeError("Telegram response " + str(reply.get("error_code", response.status_code)))
    return reply.get("result")


def _send(chat_id, text, rows=None):
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if rows:
        payload["reply_markup"] = {"inline_keyboard": rows}
    return _tg("sendMessage", payload)


def _buttons(lead, include_optin=True):
    config = PRODUCTS[lead['product']]
    ref = lead['ref']
    buttons = [
        [{"text": "📋 Посмотреть схему и презентацию",
          "url": config['landing'] + "?ft=" + ref}],
        [{"text": "💳 Открыть курс за " + config['amount'],
          "url": _ROOT + "/checkout?funnel=" + ref}],
    ]
    if include_optin and not lead.get('purchased'):
        buttons.append([{"text":"🔔 Получить 4 полезные подсказки",
                         "callback_data":"on:" + lead["product"]}])
    if lead.get('opted_in'):
        buttons.append([{"text":"🔕 Не напоминать",
                         "callback_data":"off:" + lead["product"]}])
    return buttons


def _welcome(lead):
    if lead['purchased']:
        return ("✅ Покупка курса «Поехали» подтверждена.\n\n"
                "Прогрев для этого курса остановлен. "
                "Для восстановления доступа напиши в поддержку с почты заказа.")
    return ("Привет! 👋 Я помощник курса «Поехали».\n\n"
            "Хочешь собрать небольшую систему, где GPT помогает создать продукт, "
            "Telegram-бот показывает предложение, принимает подтверждение оплаты "
            "и выдаёт материалы?\n\n"
            "Вот бесплатная схема:\n"
            "① Найти проблему аудитории → ② собрать полезный продукт → "
            "③ создать Telegram-бота → ④ подключить оплату и выдачу → "
            "⑤ привести людей через короткий контент.\n\n"
            "Нажми кнопку, чтобы посмотреть наглядную презентацию с озвучкой. "
            "Курс продаётся отдельно.\n\n"
            "Если хочешь, включи серию из четырёх полезных подсказок за 6 дней. "
            "Без подписки на сообщения их не будет.")


def _start(chat_id, product):
    if product not in PRODUCTS or not _INITIALIZED:
        return
    lead = _sql("SELECT * FROM funnel_leads WHERE chat_id=%s AND product=%s",
                (chat_id, product), one=True)
    if not lead:
        ref = secrets.token_urlsafe(32)
        lead = _sql("""INSERT INTO funnel_leads(chat_id,product,ref)
                    VALUES(%s,%s,%s) RETURNING *""", (chat_id, product, ref), one=True)
        _sql("INSERT INTO funnel_events(chat_id,product,kind) VALUES(%s,%s,'started')",
             (chat_id,product))
    _send(chat_id, _welcome(lead), _buttons(lead, include_optin=not lead['opted_in']))


def _callback(chat_id, query):
    data = str(query.get('data',''))
    if ':' not in data:
        return
    action, product = data.split(':', 1)
    if product not in PRODUCTS:
        return
    lead = _sql("SELECT * FROM funnel_leads WHERE chat_id=%s AND product=%s",
                (chat_id,product), one=True)
    if not lead:
        _start(chat_id, product)
        return
    if action == "on" and not lead['purchased']:
        _sql("""UPDATE funnel_leads SET opted_in=TRUE, stopped=FALSE,
                step=0, next_at=now()+interval '4 hours',
                lease_until=NULL,updated_at=now()
                WHERE chat_id=%s AND product=%s""", (chat_id,product))
        _sql("INSERT INTO funnel_events(chat_id,product,kind) VALUES(%s,%s,'optin')", (chat_id,product))
        _send(chat_id, "Готово! За следующие 6 дней пришлю четыре практические подсказки. "
              "Остановить их можно в любой момент командой /stop.")
    elif action == "off":
        _stop(chat_id, product)
        _send(chat_id, "Отключил сообщения по курсу «" + PRODUCTS[product]['name'] +
              "». Бесплатная схема остаётся доступна.")


def _stop(chat_id, product=None):
    if product:
        _sql("""UPDATE funnel_leads SET opted_in=FALSE,stopped=TRUE,
                next_at=NULL,lease_until=NULL,updated_at=now()
                WHERE chat_id=%s AND product=%s""", (chat_id,product))
    else:
        _sql("""UPDATE funnel_leads SET opted_in=FALSE,stopped=TRUE,
                next_at=NULL,lease_until=NULL,updated_at=now()
                WHERE chat_id=%s""", (chat_id,))


def _claim_due(max_items=12):
    with closing(_CONN()) as conn:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""SELECT * FROM funnel_leads
                    WHERE opted_in AND NOT stopped AND NOT purchased
                      AND next_at<=now() AND (lease_until IS NULL OR lease_until<now())
                    ORDER BY next_at LIMIT %s FOR UPDATE SKIP LOCKED""", (max_items,))
                rows=[dict(r) for r in cur.fetchall()]
                for row in rows:
                    cur.execute("""UPDATE funnel_leads SET lease_until=now()+interval '2 minutes'
                               WHERE chat_id=%s AND product=%s""",
                               (row['chat_id'],row['product']))
                return rows


def _advance(lead, success, blocked=False, snooze=False):
    if blocked:
        _stop(lead['chat_id'],lead['product'])
    elif snooze:
        _sql("""UPDATE funnel_leads SET next_at=now()+interval '3 hours',lease_until=NULL
                WHERE chat_id=%s AND product=%s""",(lead['chat_id'],lead['product']))
    elif not success:
        _sql("""UPDATE funnel_leads SET next_at=now()+interval '20 minutes',lease_until=NULL
                WHERE chat_id=%s AND product=%s""",(lead['chat_id'],lead['product']))
    else:
        step=int(lead['step'])+1
        if step>=len(PRODUCTS[lead['product']]['series']):
            _sql("""UPDATE funnel_leads SET step=%s,next_at=NULL,lease_until=NULL,
                opted_in=FALSE,updated_at=now() WHERE chat_id=%s AND product=%s""",
                (step,lead['chat_id'],lead['product']))
        else:
            _sql("""UPDATE funnel_leads SET step=%s,
                next_at=now()+(%s * interval '1 second'),
                lease_until=NULL,updated_at=now()
                WHERE chat_id=%s AND product=%s""",
                (step,DELAYS[step],lead['chat_id'],lead['product']))


def dispatch():
    if not _INITIALIZED or not os.getenv('TG_FUNNEL_BOT_TOKEN'):
        return {"sent":0,"reason":"not configured"}
    stats={"sent":0,"suppressed":0,"failed":0}
    for lead in _claim_due():
        try:
            # Orders marked 'paid' are authoritative only after bank verification.
            paid = _sql("""SELECT id FROM poehali_orders
                WHERE funnel_ref=%s AND state='paid' LIMIT 1""",(lead['ref'],),one=True)
            if paid:
                mark_paid({"funnel_ref":lead['ref']})
                stats["suppressed"]+=1
                continue
            # If bank status is still pending, check it before any marketing.
            pending = _sql("""SELECT * FROM poehali_orders
                WHERE funnel_ref=%s AND state IN ('creating','pending')
                  AND created_at>now()-interval '72 hours'
                ORDER BY created_at DESC LIMIT 1""",(lead['ref'],),one=True)
            if pending:
                if pending['state']=='pending' and _CHECK_PAYMENT(pending):
                    paid_order=_sql("SELECT * FROM poehali_orders WHERE id=%s",
                                    (pending['id'],),one=True)
                    mark_paid(paid_order)
                else:
                    _advance(lead,False,snooze=True)
                stats["suppressed"]+=1
                continue
            # Do not send automated marketing at night (Moscow reference zone).
            hour=int(datetime.now(timezone.utc).astimezone(
                __import__('zoneinfo').ZoneInfo('Europe/Moscow')).hour)
            if hour<10 or hour>=20:
                _advance(lead,False,snooze=True)
                stats["suppressed"]+=1
                continue
            if int(lead['step']) >= len(PRODUCTS[lead['product']]['series']):
                _advance(lead,True)
                continue
            if lead['stage']=='checkout_started':
                text=("Похоже, оформление курса осталось незавершённым.\n\n"
                      "Если банк уже списал деньги, ничего повторно оплачивать не нужно: "
                      "напиши в поддержку, и проверим заказ. Если оплата не состоялась, "
                      "можно снова открыть страницу курса.")
            else:
                text=PRODUCTS[lead['product']]['series'][int(lead['step'])]
            _send(lead['chat_id'],text,_buttons(lead,include_optin=False))
            _sql("INSERT INTO funnel_events(chat_id,product,kind) VALUES(%s,%s,%s)",
                 (lead['chat_id'],lead['product'],"touch_"+str(lead['step']+1)))
            _advance(lead,True)
            stats['sent']+=1
        except Exception as exc:
            if "Telegram response 403" in str(exc):
                _advance(lead,False,blocked=True)
            else:
                _advance(lead,False)
            stats['failed']+=1
    return stats


def register_funnel(app, connect, check_payment, root):
    global _CONN,_CHECK_PAYMENT,_ROOT
    _CONN=connect
    _CHECK_PAYMENT=check_payment
    _ROOT=root.rstrip('/')
    setup()

    @app.post('/funnel/telegram/webhook')
    def telegram_webhook():
        if not os.getenv('TG_FUNNEL_BOT_TOKEN') or not _INITIALIZED:
            abort(503)
        secret=os.getenv('SESSION_SECRET','')
        if not secret:
            abort(503)
        expected=hmac.new(secret.encode(),b'poehali-funnel-webhook-v1',
                          hashlib.sha256).hexdigest()
        incoming=request.headers.get('X-Telegram-Bot-Api-Secret-Token','')
        if not hmac.compare_digest(incoming,expected):
            abort(403)
        data=request.get_json(silent=True)
        if not isinstance(data,dict):
            abort(400)
        update_id=data.get('update_id')
        if not isinstance(update_id,int):
            abort(400)
        if not _sql("""INSERT INTO funnel_telegram_updates(update_id) VALUES(%s)
                    ON CONFLICT DO NOTHING RETURNING update_id""",(update_id,),one=True):
            return jsonify(ok=True)
        msg=data.get('message') or {}
        cb=data.get('callback_query') or {}
        if cb:
            user=cb.get('from') or {}
            chat=(cb.get('message') or {}).get('chat') or {}
            if chat.get('type')=='private' and user.get('id')==chat.get('id'):
                _callback(int(chat['id']),cb)
            try:
                _tg('answerCallbackQuery',{'callback_query_id':cb['id']})
            except Exception:
                pass
        elif msg.get('chat',{}).get('type')=='private':
            chat_id=msg['chat'].get('id')
            raw=str(msg.get('text') or '').strip()
            if isinstance(chat_id,int):
                if raw.startswith('/start'):
                    parameter=(raw.split(maxsplit=1)[1] if len(raw.split(maxsplit=1))>1 else 'poehali').split('_',1)[0]
                    _start(chat_id,parameter if parameter in PRODUCTS else 'poehali')
                elif raw.startswith('/stop'):
                    _stop(chat_id)
                    _send(chat_id,"Напоминания выключены. /start — получить схему снова.")
                elif raw.startswith('/help'):
                    _send(chat_id,"/start — бесплатная схема\n/stop — отключить подсказки\n"
                          "Покупка курса — по кнопке в приветственном сообщении.")
        return jsonify(ok=True)

    @app.post('/funnel/event')
    def landing_event():
        if not _INITIALIZED:
            abort(503)
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict) or data.get('kind')!='landing':
            abort(400)
        token=data.get('ref','')
        if isinstance(token,str):
            record_event(token,'landing')
        response=jsonify(ok=True)
        response.headers['Access-Control-Allow-Origin']='https://poehali-lead-board.onrender.com'
        return response

    @app.route('/funnel/event',methods=['OPTIONS'])
    def landing_preflight():
        response=app.make_response(('',204))
        response.headers['Access-Control-Allow-Origin']='https://poehali-lead-board.onrender.com'
        response.headers['Access-Control-Allow-Methods']='POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers']='Content-Type'
        return response

    @app.post('/funnel/dispatch')
    def funnel_dispatch():
        secret=os.getenv('FUNNEL_CRON_SECRET','')
        supplied=request.headers.get('Authorization','')
        if not secret or not hmac.compare_digest(supplied,'Bearer '+secret):
            abort(403)
        return jsonify(ok=True,**dispatch())

    @app.get('/funnel/health')
    def funnel_health():
        return jsonify(ok=True,db=_INITIALIZED,
                       telegram_configured=bool(os.getenv('TG_FUNNEL_BOT_TOKEN')),
                       scheduler_configured=bool(os.getenv('FUNNEL_CRON_SECRET')))

    # setWebhook is idempotent; only attempt when a bot token exists. A future
    # owner-supplied Telegram token activates this without another code change.
    token=os.getenv('TG_FUNNEL_BOT_TOKEN','')
    if token and os.getenv('SESSION_SECRET'):
        try:
            secret=hmac.new(os.environ['SESSION_SECRET'].encode(),
                            b'poehali-funnel-webhook-v1',hashlib.sha256).hexdigest()
            _tg('setWebhook',{
                'url':_ROOT+'/funnel/telegram/webhook',
                'secret_token':secret,
                'allowed_updates':['message','callback_query'],
                'max_connections':5
            })
            app.logger.info("Telegram funnel webhook configured")
        except Exception as exc:
            app.logger.warning("Telegram funnel webhook setup failed: %s",type(exc).__name__)
