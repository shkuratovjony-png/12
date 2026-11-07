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
import jwt
from jwt import PyJWKClient
from flask import abort, jsonify, redirect, request

PRODUCTS = {
    "poehali": {
        "name": "Поехали",
        "landing": "https://poehali-lead-board.onrender.com/",
        "amount": "1 ₽",
        "series": [
            "Смотри, какая история.\n\nПарень создал Telegram-бота, который помогает людям составлять планы тренировок. В этой истории — 6,5 млн рублей за месяц.\n\nМеня зацепили не только деньги. Продукт очень простой для покупателя: несколько вопросов о цели, времени и оборудовании — и готовый план занятий.\n\nЯ понял одну вещь: люди платят не за сам «бот», а за конкретный результат. Попробуй сегодня найти одну проблему, которую люди решают снова и снова.\n\nЯ подготовил курс, где показываю весь путь от идеи до работающей системы. Бесплатную схему можно посмотреть по кнопке ниже 👇",
            "Ещё одна история, которой хочу поделиться.\n\nЖенщина в 54 года сделала бота с рецептами. В этой истории он приносит около миллиона рублей в месяц — без заранее раскрученных аккаунтов.\n\nИдея понятная: человек говорит, что есть дома, сколько людей нужно накормить и какой у него бюджет. Бот предлагает блюда и составляет меню.\n\nПервый рецепт можно дать бесплатно. Полное меню на неделю — платно. Человек сразу видит, за что платит.\n\nПопробуй попросить GPT: «Придумай три продукта, где я бесплатно покажу часть результата, а полный результат сделаю платным».\n\nЯ разбираю создание таких продуктов по шагам в курсе. В бесплатной схеме показан весь маршрут, а на сайте можно приобрести курс по кнопке ниже 👇",
            "Есть идея, которая мне особенно нравится.\n\nДевушка создала бота, превращающего обычные фотографии в старинные портреты. Эта история — о том, как она заработала на квартиру.\n\nЧеловек загружает фото, получает красивый пример и, если нравится, покупает дополнительные варианты. Вот и весь продукт с точки зрения покупателя.\n\nНо дальше появляется главный вопрос: бот готов, приём денег настроен. Где взять людей, если бюджета на рекламу вообще нет?\n\nИменно эту задачу я решал в своём проекте. В курсе показываю, как выстроить регулярное продвижение без покупки рекламных размещений. Здесь не буду раскрывать механизм — он разобран по шагам внутри.\n\nНажми «Приобрести курс» ниже — расскажу про всю систему на сайте 👇",
            "Соберу всё в одну картину — коротко.\n\n1. Находишь одну понятную проблему.\n2. Просишь GPT помочь создать бота и страницу.\n3. Показываешь маленький результат бесплатно.\n4. Подключаешь оплату и автоматическую выдачу.\n5. Настраиваешь привлечение людей без покупки рекламных размещений.\n\n«А если я ничего не умею программировать?» Для этого я и сделал курс с готовыми запросами, которые можно копировать в GPT, и проверками каждого шага.\n\nЕсли хочешь повторить мою схему — нажми «Приобрести курс» ниже, все условия на сайте. Это последнее сообщение моей серии, дальше продавать в личку не буду.\n\nРезультат зависит от спроса, качества продукта и настройки системы. Доход не гарантирован."
        ]
    }
}
# Delay until first message, then intervals between the remaining three.
DELAYS = (4 * 3600, 20 * 3600, 48 * 3600, 72 * 3600)
_CONN = None
_CHECK_PAYMENT = None
_ROOT = None
_INITIALIZED = False
_JWKS = PyJWKClient('https://token.actions.githubusercontent.com/.well-known/jwks',cache_jwk_set=True,lifespan=3600,timeout=8)


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
    if _CONN is None or not os.getenv('DATABASE_URL') or not os.getenv('TG_FUNNEL_BOT_TOKEN'):
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
        _sql("""CREATE TABLE IF NOT EXISTS funnel_course_deliveries (
            order_id TEXT PRIMARY KEY REFERENCES poehali_orders(id),
            chat_id BIGINT NOT NULL,
            product TEXT NOT NULL,
            sent_at TIMESTAMPTZ,
            lease_until TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
        _sql("""CREATE INDEX IF NOT EXISTS funnel_course_delivery_due_idx
                 ON funnel_course_deliveries(created_at)
                 WHERE sent_at IS NULL""")
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
    """Stop marketing and send a course link only after bank-confirmed payment.

    This is a *fulfilment* message, not a marketing follow-up.
    The payment flow, amount and Ozon settings are unchanged.
    """
    ref = order.get("funnel_ref")
    oid = order.get("id")
    lead = lead_for_ref(ref) if ref else None
    if not lead or not isinstance(oid,str) or not re.fullmatch(r'[0-9a-f]{32}',oid):
        return
    try:
        # Check the database, not a return URL or an untrusted webhook claim.
        paid_order = _sql("""SELECT id FROM poehali_orders
            WHERE id=%s AND funnel_ref=%s AND state='paid'""",(oid,ref),one=True)
        if not paid_order:
            return
        updated = _sql("""UPDATE funnel_leads SET stage='paid', purchased=TRUE,
                opted_in=FALSE, next_at=NULL, lease_until=NULL, updated_at=now()
                WHERE ref=%s AND NOT purchased RETURNING ref""",(ref,),one=True)
        if updated:
            _sql("""INSERT INTO funnel_events(chat_id,product,kind)
                    VALUES(%s,%s,'purchase_verified')""",
                 (lead['chat_id'],lead['product']))
        # One delivery record per paid order; repeated bank callbacks are safe.
        _sql("""INSERT INTO funnel_course_deliveries(order_id,chat_id,product)
                VALUES(%s,%s,%s) ON CONFLICT(order_id) DO NOTHING""",
             (oid,lead['chat_id'],lead['product']))
        _deliver_course_access(oid)
    except Exception as error:
        # A temporary Telegram/DB failure must never break bank confirmation.
        print('Course Telegram fulfilment deferred:',type(error).__name__)


def _deliver_course_access(order_id):
    """Send a plain permanent course URL after confirmed payment."""
    record = _sql("""UPDATE funnel_course_deliveries d
        SET lease_until=now()+interval '90 seconds'
        WHERE d.order_id=%s AND d.sent_at IS NULL
          AND (d.lease_until IS NULL OR d.lease_until<now())
          AND EXISTS (SELECT 1 FROM poehali_orders o
                      WHERE o.id=d.order_id AND o.state='paid')
        RETURNING d.order_id,d.chat_id""",(order_id,),one=True)
    if not record:
        return False
    try:
        _send(record['chat_id'], "Оплата прошла. Держи курс.\n\n" + _ROOT + "/course")
        _sql("""UPDATE funnel_course_deliveries
                SET sent_at=now(),lease_until=NULL
                WHERE order_id=%s AND sent_at IS NULL""",(order_id,))
        return True
    except Exception:
        # The existing scheduled dispatcher can retry a temporary TG failure.
        _sql("""UPDATE funnel_course_deliveries SET lease_until=NULL
                WHERE order_id=%s AND sent_at IS NULL""",(order_id,))
        raise


def _dispatch_course_deliveries(max_items=12):
    pending=_sql("""SELECT d.order_id FROM funnel_course_deliveries d
        JOIN poehali_orders o ON o.id=d.order_id
        WHERE d.sent_at IS NULL AND o.state='paid'
          AND (d.lease_until IS NULL OR d.lease_until<now())
        ORDER BY d.created_at LIMIT %s""",(max_items,),all_rows=True)
    sent=0
    for row in pending:
        try:
            if _deliver_course_access(row['order_id']):
                sent+=1
        except Exception as error:
            print('Course Telegram fulfilment retry deferred:',type(error).__name__)
    return sent


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


def _buttons(lead, stage='welcome'):
    # Welcome: one free-scheme CTA. Follow-ups: one course CTA via landing.
    # Payment never starts directly from Telegram.
    if lead.get('purchased'):
        return []
    url = PRODUCTS[lead['product']]['landing'] + '?ft=' + lead['ref']
    if stage == 'touch':
        return [[{'text':'Приобрести курс', 'url':url + '#access'}]]
    return [[{'text':'Смотреть схему', 'url':url}]]


def _welcome(lead):
    if lead['purchased']:
        return ("Оплата прошла. Держи курс.\n\n" + _ROOT + "/course")
    return "Привет! Я Евгений 👋\n\nСразу самое интересное: в моей схеме заложено продвижение продукта БЕЗ покупки рекламы. Даже если на рекламу сейчас вообще нет денег.\n\nС помощью GPT можно создать Telegram-бота, сделать его платным, подключить платежи и автоматическую выдачу. Но главное — как потом привести к нему людей, не оплачивая рекламу у блогеров и в каналах? Эту задачу я тоже разобрал.\n\nСам я сейчас создаю проект «Совпали»: знакомство по целям и интересам, а также астрологии и нумерологии. И хочу поделиться с тобой своей схемой — простыми словами и на конкретных примерах.\n\nНе буду долго мучить. Вся схема создания продукта — бесплатно. Жми «Смотреть схему» 👇\n\nВ ближайшие дни я пришлю ещё четыре коротких сообщения с примерами. Если они не нужны, в меню бота есть «Отказаться от рассылки»."


def _start(chat_id, product):
    if product not in PRODUCTS or not _INITIALIZED:
        return
    lead = _sql("SELECT * FROM funnel_leads WHERE chat_id=%s AND product=%s",
                (chat_id, product), one=True)
    if not lead:
        ref = secrets.token_urlsafe(32)
        lead = _sql("""INSERT INTO funnel_leads(chat_id,product,ref,opted_in,next_at)
                    VALUES(%s,%s,%s,TRUE,now()+interval '4 hours') RETURNING *""",
                    (chat_id, product, ref), one=True)
        _sql("INSERT INTO funnel_events(chat_id,product,kind) VALUES(%s,%s,'started')",
             (chat_id,product))
    # A new /start enrolls the four-touch sequence once; never override /stop.
    # Re-entering /start does not reset completed or in-progress touches.
    if not lead['purchased'] and not lead['stopped'] and not lead['opted_in'] and int(lead['step']) == 0:
        refreshed = _sql("""UPDATE funnel_leads SET opted_in=TRUE,
            next_at=now()+interval '4 hours',lease_until=NULL,updated_at=now()
            WHERE chat_id=%s AND product=%s AND NOT purchased AND NOT stopped
              AND NOT opted_in AND step=0 RETURNING *""",(chat_id,product),one=True)
        if refreshed:
            lead = refreshed
    _send(chat_id, _welcome(lead), _buttons(lead))


def _subscribe(chat_id, product='poehali'):
    """Enable the four-message series only after the subscriber requests it."""
    if product not in PRODUCTS or not _INITIALIZED:
        return
    lead=_sql("SELECT * FROM funnel_leads WHERE chat_id=%s AND product=%s",
              (chat_id,product),one=True)
    if not lead:
        _start(chat_id,product)
        lead=_sql("SELECT * FROM funnel_leads WHERE chat_id=%s AND product=%s",
                  (chat_id,product),one=True)
    if not lead:
        return
    if lead['purchased']:
        _send(chat_id,"Курс уже оплачен. Дополнительные сообщения не нужны.")
        return
    if lead['opted_in'] and not lead['stopped']:
        _send(chat_id,"Серия из четырёх сообщений уже подключена. "
              "Отказаться можно через «Меню» → «Отказаться от рассылки».")
        return
    updated=_sql("""UPDATE funnel_leads SET opted_in=TRUE,stopped=FALSE,
                step=0,next_at=now()+interval '4 hours',lease_until=NULL,
                updated_at=now()
                WHERE chat_id=%s AND product=%s AND NOT purchased RETURNING ref""",
                 (chat_id,product),one=True)
    if updated:
        _sql("INSERT INTO funnel_events(chat_id,product,kind) VALUES(%s,%s,'optin')",
             (chat_id,product))
        _send(chat_id,"Хорошо! Пришлю четыре коротких сообщения с идеями и примерами. "
              "Первое — примерно через четыре часа. Если станет неактуально, "
              "«Меню» → «Отказаться от рассылки».",
              _buttons(lead))


def _callback(chat_id, query):
    data = str(query.get('data',''))
    # Old preview buttons from earlier messages no longer reveal any stages.
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
        # Backward compatibility with already-sent opt-in buttons.
        _subscribe(chat_id,product)
    elif action == "bought":
        # Self-report only silences marketing. It never grants access to a course.
        _stop(chat_id,product)
        _sql("""INSERT INTO funnel_events(chat_id,product,kind)
                VALUES(%s,%s,'purchase_self_reported')""",(chat_id,product))
        _send(chat_id, "Остановил напоминания. Если деньги уже списались, а доступ не открылся, "
              "напиши в поддержку с почты заказа: "+os.getenv('SELLER_EMAIL','контакт указан на сайте')+".")
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
    # Transactional course access is retried independently of marketing opt-in.
    stats["access_sent"]=_dispatch_course_deliveries()
    for lead in _claim_due():
        try:
            # Orders marked 'paid' are authoritative only after bank verification.
            paid = _sql("""SELECT id,funnel_ref FROM poehali_orders
                WHERE funnel_ref=%s AND state='paid' LIMIT 1""",(lead['ref'],),one=True)
            if paid:
                mark_paid(paid)
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
            text=PRODUCTS[lead['product']]['series'][int(lead['step'])]
            if lead['stage']=='checkout_started' and int(lead['step'])==0:
                text += ("\n\nP.S. Если ты уже заплатил, не оплачивай повторно. "
                         "Напиши в поддержку с почты заказа, и мы проверим доступ.")
            # Payment or /stop may arrive while this follow-up is being prepared.
            latest=_sql("SELECT purchased,opted_in,stopped FROM funnel_leads "
                        "WHERE chat_id=%s AND product=%s",
                        (lead['chat_id'],lead['product']),one=True)
            if not latest or latest['purchased'] or latest['stopped'] or not latest['opted_in']:
                _advance(lead,False,snooze=True)
                stats['suppressed']+=1
                continue
            _send(lead['chat_id'],text,_buttons(lead,stage='touch'))
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

    @app.get('/funnel/start')
    def funnel_start():
        if not os.getenv('TG_FUNNEL_BOT_TOKEN'):
            return ("Telegram-бот для бесплатной схемы ещё подключается.",503)
        try:
            info=_tg('getMe',{})
            username=str(info.get('username',''))
            if not re.fullmatch(r'[A-Za-z0-9_]{5,40}',username):
                raise ValueError('Invalid Telegram bot username')
            return redirect('https://t.me/'+username+'?start=poehali',code=302)
        except Exception as exc:
            app.logger.warning('Funnel entry unavailable: %s',type(exc).__name__)
            return ("Не удалось открыть Telegram-бота. Попробуйте позднее.",503)

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
                elif raw.startswith('/subscribe'):
                    _subscribe(chat_id)
                elif raw.startswith('/stop'):
                    _stop(chat_id)
                    _send(chat_id,"Напоминания выключены. /start — получить схему снова.")
                elif raw.startswith('/help'):
                    _send(chat_id,"/start — смотреть бесплатную схему\n"
                          "/stop — отказаться от рассылки\n"
                          "Курс можно приобрести только на сайте бесплатной схемы.")
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
        authorization=request.headers.get('Authorization','')
        if not authorization.startswith('Bearer ') or len(authorization)>10000:
            abort(403)
        try:
            token=authorization[7:]
            key=_JWKS.get_signing_key_from_jwt(token).key
            claims=jwt.decode(token,key,algorithms=['RS256'],
                issuer='https://token.actions.githubusercontent.com',
                audience='poehali-funnel',
                options={'require':['exp','iat','iss','aud']})
        except Exception as exc:
            app.logger.warning('Funnel scheduler authentication rejected: %s',
                               type(exc).__name__)
            abort(403)
        if (claims.get('repository')!='shkuratovjony-png/12' or
            claims.get('ref')!='refs/heads/main' or
            claims.get('workflow_ref')!='shkuratovjony-png/12/.github/workflows/poehali-funnel-dispatch.yml@refs/heads/main' or
            claims.get('event_name') not in ('schedule','workflow_dispatch','push')):
            abort(403)
        return jsonify(ok=True,**dispatch())

    @app.get('/funnel/health')
    def funnel_health():
        # Public diagnostics expose no credentials and no buyer data.
        configured=bool(os.getenv('TG_FUNNEL_BOT_TOKEN'))
        telegram_valid=False
        webhook_matches=False
        public_username=None
        check_error=None
        if configured:
            try:
                identity=_tg('getMe',{})
                public_username=str(identity.get('username') or '')[:40]
                telegram_valid=bool(identity.get('is_bot') and public_username)
                if telegram_valid:
                    wh=_tg('getWebhookInfo',{})
                    webhook_matches=(wh.get('url')==_ROOT+'/funnel/telegram/webhook')
            except Exception as error:
                check_error=type(error).__name__
        return jsonify(ok=True,db=_INITIALIZED,
                       telegram_configured=configured,
                       telegram_valid=telegram_valid,
                       webhook_matches=webhook_matches,
                       bot_username=public_username,
                       verification_error=check_error,
                       scheduler_configured=True)

    # setWebhook is idempotent; only attempt when a bot token exists. A future
    # owner-supplied Telegram token activates this without another code change.
    token=os.getenv('TG_FUNNEL_BOT_TOKEN','')
    if token and os.getenv('SESSION_SECRET') and _INITIALIZED:
        try:
            bot=_tg('getMe',{})
            app.logger.info("Telegram funnel bot token verified, username=%s",str(bot.get('username') or '')[:40])
            secret=hmac.new(os.environ['SESSION_SECRET'].encode(),
                            b'poehali-funnel-webhook-v1',hashlib.sha256).hexdigest()
            _tg('setWebhook',{
                'url':_ROOT+'/funnel/telegram/webhook',
                'secret_token':secret,
                'allowed_updates':['message','callback_query'],
                'max_connections':5
            })
            app.logger.info("Telegram funnel webhook configured")
            try:
                _tg('setMyCommands',{'commands':[
                    {'command':'start','description':'Смотреть схему'},
                    {'command':'stop','description':'Отказаться от рассылки'}
                ],'language_code':'ru'})
            except Exception as error:
                app.logger.warning('Telegram bot commands update failed: %s',type(error).__name__)
        except Exception as exc:
            app.logger.warning("Telegram funnel webhook setup failed: %s",type(exc).__name__)
