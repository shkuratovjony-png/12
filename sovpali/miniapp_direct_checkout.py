"""Verified Mini App payment creation without merchant intermediary page."""
import os,re,secrets,requests,html
from datetime import datetime, timezone
from urllib.parse import urlsplit
from flask import request,jsonify,redirect,make_response
from pair_miniapp import validate_init_data
from ozon_web_checkout import _create_fiscal,_sales_ready,_hosted,_now,_LOCK,CURRENCY

EMAIL=re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")

def valid_email(value):
    return (isinstance(value,str) and 5<=len(value)<=120 and
            value==value.strip() and EMAIL.fullmatch(value) is not None and
            ".." not in value and " " not in value)

def register_miniapp_checkout(app,ns):
    db=ns["db"]
    with db() as c:
        c.executescript("""
          CREATE TABLE IF NOT EXISTS billing_receipt_contacts (
            billing_order_id TEXT PRIMARY KEY,
            buyer_user_id BIGINT NOT NULL,
            receipt_email TEXT NOT NULL,
            created_at TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS billing_checkout_tickets (
            token TEXT PRIMARY KEY,
            buyer_user_id BIGINT NOT NULL,
            sku TEXT NOT NULL,
            candidate_id BIGINT,
            receipt_email TEXT NOT NULL,
            intent TEXT NOT NULL,
            created_at TEXT NOT NULL
          );
        """)

    def reply(data,status=200):
        res=jsonify(data);res.status_code=status
        res.headers["Cache-Control"]="private, no-store"
        res.headers["Referrer-Policy"]="no-referrer"
        res.headers["X-Content-Type-Options"]="nosniff"
        return res

    def _new_contact_order(uid,cid,email,intent):
        from pair_cabinet import history_ids,can_open
        available={int(p["user_id"]) for _,p in ns["mp_candidates"](uid,3)}
        if cid not in available and cid not in set(history_ids(ns,uid)):
            return reply({"message":"Анкета больше недоступна. Обнови подбор."},409)
        if not can_open(ns,uid,cid):
            return reply({"message":"Эта пара недоступна."},409)
        if ns.get("web_premium_active",lambda _:False)(uid):
            return reply({"message":"Тебе доступно знакомство по Premium без доплаты."},409)
        if ns.get("web_contact_credit_available",lambda _:False)(uid):
            return reply({"message":"У тебя уже есть оплаченный запрос без доплаты."},409)
        existing=ns["cr_between"](uid,cid)
        if existing and str(existing["status"]) in ("pending","accepted"):
            return reply({"message":"Запрос уже существует, повторная оплата не нужна."},409)

        nonce="mini-"+str(uid)+"-"+intent
        with _LOCK:
            with db() as c:
                previous=c.execute("SELECT * FROM billing_web_orders WHERE browser_nonce=?",(nonce,)).fetchone()
                # A bank-rejected attempt never yielded a payment link.
                # Preserve its order/audit row, but do not let its stable Mini App
                # intent block a fresh attempt forever. Other active orders are
                # still checked below and reused, preventing duplicate checkout.
                if previous and previous["status"]=="init_failed" and not previous["checkout_url"] and not previous["provider_payment_id"]:
                    previous=None
                    nonce += "-retry-" + secrets.token_hex(8)
                if not previous:
                    previous=c.execute("""SELECT o.* FROM billing_web_orders o
                      JOIN web_purchase_bindings b ON b.billing_order_id=o.order_id
                      WHERE b.buyer_user_id=? AND b.target_user_id=? AND b.sku='contact'
                        AND o.status IN ('initiating','pending','paid')
                      ORDER BY o.created_at DESC LIMIT 1""",(uid,cid)).fetchone()
            if previous:
                if previous["status"]=="paid":
                    return reply({"message":"Оплата уже подтверждена, проверь статус."},409)
                if previous["checkout_url"] and _hosted(previous["checkout_url"]):
                    return reply({"url":previous["checkout_url"],"reused":True})
                return reply({"message":"Заказ уже создаётся. Проверь оплату перед повтором."},409)

            result,reserved=ns["ip_reserve_intro"](uid,cid,100)
            if result!="reserved" or not reserved:
                return reply({"message":"Анкета временно занята, деньги не списаны."},409)
            intro_id=int(reserved["id"])
            order_id=secrets.token_hex(16)
            created=_now()
            try:
                with db() as c:
                    c.execute("""INSERT INTO billing_web_orders(
                      order_id,browser_nonce,product_key,amount_kopecks,
                      currency_code,method,status,created_at,updated_at)
                      VALUES(?,?,'contact',10000,?,'fiscal','initiating',?,?)""",
                      (order_id,nonce,CURRENCY,created,created))
                from web_product_access import bind_order
                bind_order(db,order_id,uid,"contact",target_id=cid,linked_intro_id=intro_id)
                with db() as c:
                    c.execute("""INSERT INTO billing_receipt_contacts(
                        billing_order_id,buyer_user_id,receipt_email,created_at)
                        VALUES(?,?,?,?)""",(order_id,uid,email,created))
            except Exception as exc:
                ns["ip_close"](intro_id)
                app.logger.warning("Mini App checkout preparation failed: %s",type(exc).__name__)
                return reply({"message":"Не удалось создать заказ. Деньги не списаны."},503)
            try:
                base=os.getenv("WEBHOOK_BASE_URL","").strip().rstrip("/")
                if not base.startswith("https://") or urlsplit(base).hostname!="one2-1o22.onrender.com":
                    raise ValueError("Invalid public payment domain")
                # Fiscal order carries the actual buyer receipt email and item.
                url,payment_id,order_ext_id=_create_fiscal(order_id,"contact",10000,base,email)
            except (requests.RequestException,ValueError) as exc:
                app.logger.warning("Mini App Ozon create failed: %s",type(exc).__name__)
                with db() as c:
                    c.execute("UPDATE billing_web_orders SET status='init_failed',updated_at=? WHERE order_id=?",
                              (_now(),order_id))
                ns["ip_close"](intro_id)
                return reply({"message":"Ozon не открыл оплату, деньги не списаны. Попробуй снова."},503)
            with db() as c:
                c.execute("""UPDATE billing_web_orders SET status='pending',checkout_url=?,
                    provider_payment_id=?,provider_order_ext_id=?,updated_at=?
                    WHERE order_id=?""",(url,payment_id,order_ext_id,_now(),order_id))
        return reply({"url":url,"order_id":order_id,"receipt_email_recorded":True})


    @app.post("/s/app/api/checkout/contact")
    def miniapp_checkout_contact():
        if (request.content_length or 0)>4096:
            return reply({"message":"Слишком большой запрос."},413)
        if not _sales_ready() or not ns.get("web_contact_live",lambda:False)():
            return reply({"message":"Оплата временно недоступна."},503)
        origin=request.headers.get("Origin","")
        if origin and urlsplit(origin).netloc!=urlsplit(request.host_url).netloc:
            return reply({"message":"Открой оплату из Telegram."},403)
        try:
            tg_id=validate_init_data(request.headers.get("X-Telegram-Init-Data",""),
                                     ns.get("TOKEN") or os.getenv("BOT_TOKEN",""))
        except (ValueError,TypeError,KeyError):
            return reply({"message":"Открой приложение заново из Telegram."},401)
        user=ns["one"]("SELECT * FROM users WHERE tg_id=?",(int(tg_id),))
        if not user or int(user["is_banned"] or 0):
            return reply({"message":"Профиль недоступен."},403)
        uid=int(user["id"])
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)!={"candidate_id","email","intent"}:
            return reply({"message":"Неверные данные."},400)
        cid,email,intent=body["candidate_id"],body["email"],body["intent"]
        if type(cid) is not int or cid<=0 or uid==cid or not valid_email(email):
            return reply({"message":"Проверь email для чека."},400)
        if not isinstance(intent,str) or re.fullmatch(r"[a-zA-Z0-9_-]{16,64}",intent) is None:
            return reply({"message":"Обнови экран оплаты."},400)

        return _new_contact_order(uid,cid,email,intent)

    def _new_premium_order(uid,email,intent):
        nonce="mini-premium-"+str(uid)+"-"+intent
        with _LOCK:
            with db() as c:
                previous=c.execute("SELECT * FROM billing_web_orders WHERE browser_nonce=?",(nonce,)).fetchone()
                if previous and previous["status"]=="init_failed" and not previous["checkout_url"] and not previous["provider_payment_id"]:
                    previous=None
                    nonce += "-retry-" + secrets.token_hex(8)
                if not previous:
                    previous=c.execute("""SELECT o.* FROM billing_web_orders o
                      JOIN web_purchase_bindings b ON b.billing_order_id=o.order_id
                      WHERE b.buyer_user_id=? AND b.sku='premium'
                        AND o.status IN ('initiating','pending')
                      ORDER BY o.created_at DESC LIMIT 1""",(uid,)).fetchone()
            if previous:
                if previous["status"]=="paid":
                    return reply({"message":"Premium уже оплачен. Проверь статус подписки."},409)
                if previous["checkout_url"] and _hosted(previous["checkout_url"]):
                    return reply({"url":previous["checkout_url"],"reused":True})
                return reply({"message":"Заказ уже создаётся. Не оплачивай повторно."},409)
            if ns.get("web_premium_active",lambda _:False)(uid):
                return reply({"message":"Premium уже активен. Продление можно оформить после окончания срока."},409)
            order_id=secrets.token_hex(16)
            now=_now()
            try:
                with db() as conn:
                    conn.execute("""INSERT INTO billing_web_orders(
                      order_id,browser_nonce,product_key,amount_kopecks,
                      currency_code,method,status,created_at,updated_at)
                      VALUES(?,?,'premium',120000,?,'fiscal','initiating',?,?)""",
                      (order_id,nonce,CURRENCY,now,now))
                from web_product_access import bind_order
                bind_order(db,order_id,uid,"premium")
                with db() as conn:
                    conn.execute("""INSERT INTO billing_receipt_contacts(
                      billing_order_id,buyer_user_id,receipt_email,created_at)
                      VALUES(?,?,?,?)""",(order_id,uid,email,now))
            except Exception as exc:
                app.logger.warning("Premium Mini App order preparation failed: %s",type(exc).__name__)
                return reply({"message":"Не удалось создать заказ. Деньги не списаны."},503)
            try:
                base=os.getenv("WEBHOOK_BASE_URL","").strip().rstrip("/")
                if not base.startswith("https://") or urlsplit(base).hostname!="one2-1o22.onrender.com":
                    raise ValueError("Invalid public payment domain")
                url,payment_id,order_ext_id=_create_fiscal(order_id,"premium",120000,base,email)
            except (requests.RequestException,ValueError) as exc:
                app.logger.warning("Mini App Ozon Premium create failed: %s",type(exc).__name__)
                with db() as conn:
                    conn.execute("UPDATE billing_web_orders SET status='init_failed',updated_at=? WHERE order_id=?",
                                 (_now(),order_id))
                return reply({"message":"Ozon не открыл оплату. Деньги не списаны."},503)
            with db() as conn:
                conn.execute("""UPDATE billing_web_orders SET status='pending',
                    checkout_url=?,provider_payment_id=?,provider_order_ext_id=?,
                    updated_at=? WHERE order_id=?""",
                    (url,payment_id,order_ext_id,_now(),order_id))
        return reply({"url":url,"order_id":order_id,"receipt_email_recorded":True})


    @app.post("/s/app/api/checkout/premium")
    def miniapp_checkout_premium():
        """1200 RUB / 30 days, initiated from the same native email sheet."""
        if (request.content_length or 0)>4096:
            return reply({"message":"Слишком большой запрос."},413)
        if not _sales_ready() or not ns.get("web_premium_live",lambda:False)():
            return reply({"message":"Premium временно недоступен."},503)
        origin=request.headers.get("Origin","")
        if origin and urlsplit(origin).netloc!=urlsplit(request.host_url).netloc:
            return reply({"message":"Открой оформление из Telegram."},403)
        try:
            tg_id=validate_init_data(request.headers.get("X-Telegram-Init-Data",""),
                                     ns.get("TOKEN") or os.getenv("BOT_TOKEN",""))
        except (ValueError,TypeError,KeyError):
            return reply({"message":"Открой приложение заново из Telegram."},401)
        user=ns["one"]("SELECT * FROM users WHERE tg_id=?",(int(tg_id),))
        if not user or int(user["is_banned"] or 0):
            return reply({"message":"Профиль недоступен."},403)
        uid=int(user["id"])
        if not ns["profile"](uid):
            return reply({"message":"Сначала заполни анкету."},409)
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)!={"email","intent"}:
            return reply({"message":"Неверные данные заказа."},400)
        email,intent=body["email"],body["intent"]
        if not valid_email(email):
            return reply({"message":"Проверь email для чека."},400)
        if not isinstance(intent,str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}",intent):
            return reply({"message":"Обнови оформление Premium."},400)
        return _new_premium_order(uid,email,intent)


    def _bridge_owner():
        origin=request.headers.get("Origin","")
        if origin and urlsplit(origin).netloc!=urlsplit(request.host_url).netloc:
            return None
        try:
            tg_id=validate_init_data(request.headers.get("X-Telegram-Init-Data",""),
                                     ns.get("TOKEN") or os.getenv("BOT_TOKEN",""))
        except (ValueError,TypeError,KeyError):
            return None
        user=ns["one"]("SELECT id,is_banned FROM users WHERE tg_id=?",(int(tg_id),))
        return int(user["id"]) if user and not int(user["is_banned"] or 0) else None

    def _bridge_ticket(token, uid=None, max_age_seconds=86400):
        if not isinstance(token,str) or not re.fullmatch(r"[a-f0-9]{32}",token):
            return None
        with db() as c:
            row=c.execute("SELECT * FROM billing_checkout_tickets WHERE token=?",(token,)).fetchone()
        if not row or (uid is not None and int(row["buyer_user_id"])!=int(uid)):
            return None
        try:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(str(row["created_at"]))).total_seconds()
        except ValueError:
            return None
        return row if -30<=age<=max_age_seconds else None

    @app.post("/s/app/api/checkout/prepare")
    def miniapp_checkout_prepare():
        """Stage an opaque browser ticket. No Ozon order or pair reservation yet."""
        if (request.content_length or 0)>4096:
            return reply({"message":"Слишком большой запрос."},413)
        uid=_bridge_owner()
        if uid is None:
            return reply({"message":"Открой приложение заново из Telegram."},401)
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)!={"sku","candidate_id","email","intent"}:
            return reply({"message":"Неверные данные оформления."},400)
        sku,cid,email,intent=(body[k] for k in ("sku","candidate_id","email","intent"))
        if not isinstance(sku,str) or sku not in ("contact","premium") or not valid_email(email):
            return reply({"message":"Проверь email для чека."},400)
        if not isinstance(intent,str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}",intent):
            return reply({"message":"Обнови оформление."},400)
        if not _sales_ready() or not ns.get("web_"+sku+"_live",lambda:False)():
            return reply({"message":"Оплата временно недоступна."},503)
        if not ns["profile"](uid):
            return reply({"message":"Сначала заполни анкету."},409)
        if sku=="contact":
            if type(cid) is not int or cid<=0 or uid==cid:
                return reply({"message":"Анкета недоступна."},400)
            from pair_cabinet import history_ids,can_open
            available={int(p["user_id"]) for _,p in ns["mp_candidates"](uid,3)}
            if (cid not in available and cid not in set(history_ids(ns,uid))) or not can_open(ns,uid,cid):
                return reply({"message":"Анкета больше недоступна. Обнови подбор."},409)
            if ns.get("web_premium_active",lambda _:False)(uid) or ns.get("web_contact_credit_available",lambda _:False)(uid):
                return reply({"message":"У тебя уже есть возможность отправить запрос без доплаты."},409)
            existing=ns["cr_between"](uid,cid)
            if existing and str(existing["status"]) in ("pending","accepted"):
                return reply({"message":"Запрос уже отправлен. Повторная оплата не нужна."},409)
        elif cid is not None:
            return reply({"message":"Неверные данные Premium."},400)
        elif ns.get("web_premium_active",lambda _:False)(uid):
            return reply({"message":"Premium уже активен."},409)
        base=os.getenv("WEBHOOK_BASE_URL","").strip().rstrip("/")
        if not base.startswith("https://") or urlsplit(base).hostname!="one2-1o22.onrender.com":
            return reply({"message":"Платёжный сервис временно недоступен."},503)
        token=secrets.token_hex(16)
        with db() as c:
            c.execute("""INSERT INTO billing_checkout_tickets
                (token,buyer_user_id,sku,candidate_id,receipt_email,intent,created_at)
                VALUES(?,?,?,?,?,?,?)""",(token,uid,sku,cid,email,intent,_now()))
        return reply({"ticket":token,"url":base+"/billing/ozon/launch/"+token})

    @app.get("/billing/ozon/launch/<token>")
    def miniapp_ozon_browser_launch(token):
        """External browser follows a 303 to Ozon hosted payment without an intermediate page."""
        ticket=_bridge_ticket(token,max_age_seconds=900)
        if not ticket:
            return make_response("Ссылка оформления устарела. Вернись в «Совпали» и открой оплату заново.",410)
        uid,sku,email,intent=(int(ticket["buyer_user_id"]),str(ticket["sku"]),
                              str(ticket["receipt_email"]),str(ticket["intent"]))
        user=ns["one"]("SELECT id,is_banned FROM users WHERE id=?",(uid,))
        if not user or int(user["is_banned"] or 0):
            return make_response("Анкета недоступна.",403)
        if not _sales_ready():
            return make_response("Оформление временно недоступно. Деньги не списаны.",503)
        if sku=="contact":
            result=_new_contact_order(uid,int(ticket["candidate_id"]),email,intent)
        elif sku=="premium":
            result=_new_premium_order(uid,email,intent)
        else:
            return make_response("Неизвестный продукт.",400)
        payload=result.get_json(silent=True) or {}
        if result.status_code!=200 or not _hosted(payload.get("url")):
            reason=html.escape(str(payload.get("message") or "Не удалось создать платёж."),quote=True)
            r=make_response("<!doctype html><html lang='ru'><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>Совпали · Оплата</title><body style='font:18px/1.6 system-ui;padding:30px'>"
                "<h2>Оплата не открылась</h2><p>"+reason+"</p>"
                "<p>Вернись в Telegram → «Совпали» и проверь статус заказа.</p></body></html>",
                result.status_code if result.status_code>=400 else 503)
            r.headers["Cache-Control"]="private, no-store"
            r.headers["Referrer-Policy"]="no-referrer"
            return r
        res=redirect(payload["url"],code=303)
        res.headers["Cache-Control"]="private, no-store"
        res.headers["Referrer-Policy"]="no-referrer"
        return res

    @app.post("/s/app/api/checkout/status")
    def miniapp_checkout_status():
        """Reconcile Ozon server-side, never believe a client-side paid flag."""
        if (request.content_length or 0)>4096:
            return reply({"message":"Слишком большой запрос."},413)
        uid=_bridge_owner()
        if uid is None:
            return reply({"message":"Открой приложение заново из Telegram."},401)
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)!={"ticket"}:
            return reply({"message":"Неверные данные."},400)
        ticket=_bridge_ticket(body["ticket"],uid=uid)
        if not ticket:
            return reply({"message":"Ссылка заказа истекла. Обнови приложение."},404)
        sku=str(ticket["sku"])
        with db() as c:
            if sku=="contact":
                order=c.execute("""SELECT o.* FROM billing_web_orders o
                    JOIN web_purchase_bindings b ON b.billing_order_id=o.order_id
                    WHERE b.buyer_user_id=? AND b.target_user_id=? AND b.sku='contact'
                    AND o.status IN ('initiating','pending','paid')
                    ORDER BY o.created_at DESC LIMIT 1""",
                    (uid,int(ticket["candidate_id"]))).fetchone()
            elif sku=="premium":
                order=c.execute("""SELECT o.* FROM billing_web_orders o
                    JOIN web_purchase_bindings b ON b.billing_order_id=o.order_id
                    WHERE b.buyer_user_id=? AND b.sku='premium'
                    AND o.status IN ('initiating','pending','paid')
                    ORDER BY o.created_at DESC LIMIT 1""",(uid,)).fetchone()
            else:
                return reply({"message":"Неизвестный продукт."},400)
        if not order:
            return reply({"status":"preparing","paid":False,"delivered":False,"sku":sku})
        from web_intro_fulfillment import verify_and_fulfill
        delivery=verify_and_fulfill(ns,order["order_id"])
        with db() as c:
            checked=c.execute("SELECT status FROM billing_web_orders WHERE order_id=?",
                              (order["order_id"],)).fetchone()
        paid=bool(checked and checked["status"]=="paid")
        return reply({"status":"paid" if paid else str(checked["status"] if checked else "pending"),
                      "paid":paid,"delivered":delivery in ("delivered","premium_delivered"),
                      "delivery":delivery if paid else None,"sku":sku})


    @app.post("/s/app/api/checkout/redeem")
    def miniapp_redeem_contact():
        """Send a Premium/free-repeat introduction without any external page."""
        import asyncio
        from datetime import timedelta
        from types import SimpleNamespace
        if (request.content_length or 0)>4096:
            return reply({"message":"Слишком большой запрос."},413)
        origin=request.headers.get("Origin","")
        if origin and urlsplit(origin).netloc!=urlsplit(request.host_url).netloc:
            return reply({"message":"Открой запрос из Telegram."},403)
        try:
            tg_id=validate_init_data(request.headers.get("X-Telegram-Init-Data",""),
                                     ns.get("TOKEN") or os.getenv("BOT_TOKEN",""))
        except (ValueError,TypeError,KeyError):
            return reply({"message":"Открой приложение заново из Telegram."},401)
        user=ns["one"]("SELECT * FROM users WHERE tg_id=?",(int(tg_id),))
        if not user or int(user["is_banned"] or 0):
            return reply({"message":"Профиль недоступен."},403)
        uid=int(user["id"])
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)!={"candidate_id"}:
            return reply({"message":"Неверные данные."},400)
        cid=body["candidate_id"]
        if type(cid) is not int or cid<=0 or cid==uid:
            return reply({"message":"Анкета недоступна."},400)
        from pair_cabinet import history_ids,can_open
        available={int(p["user_id"]) for _,p in ns["mp_candidates"](uid,3)}
        if cid not in available and cid not in set(history_ids(ns,uid)):
            return reply({"message":"Анкета недоступна. Обнови подбор."},409)
        if not can_open(ns,uid,cid):
            return reply({"message":"Эта пара больше недоступна."},409)
        from web_product_access import redeem_intro_credit,restore_intro_credit
        membership=bool(ns.get("web_premium_active",lambda _:False)(uid))
        credit=bool(ns.get("web_contact_credit_available",lambda _:False)(uid))
        if not membership and not credit:
            return reply({"message":"Для запроса нужна оплата 100 ₽ или Premium."},402)
        existing=ns["cr_between"](uid,cid)
        if existing and str(existing["status"]) in ("pending","accepted"):
            return reply({"message":"Запрос уже отправлен. Повторно платить не нужно.","status":"pending"},409)
        reserved_status,reserved=ns["ip_reserve_intro"](uid,cid,100)
        if reserved_status!="reserved" or not reserved:
            msg="Дневной лимит Premium — 3 запроса. Попробуй завтра." if reserved_status=="daily_cap" and membership else "Анкета временно занята или дневной лимит достигнут."
            return reply({"message":msg},409)
        intro_id=int(reserved["id"])
        claim="web-credit-"+str(intro_id)
        source=None
        if not membership:
            source=redeem_intro_credit(db,uid,claim)
            if not source:
                ns["ip_close"](intro_id)
                return reply({"message":"Оплаченный повторный запрос сейчас недоступен."},409)
        try:
            if not ns["ready"].wait(timeout=4):
                raise RuntimeError("Telegram bot not ready")
            a,b=ns["profile"](uid),ns["profile"](cid)
            if not a or not b:
                raise RuntimeError("One of the profiles disappeared")
            fut=asyncio.run_coroutine_threadsafe(
                ns["cr_send_request"](SimpleNamespace(bot=ns["bot"].bot),uid,cid,int(ns["score"](a,b))),
                ns["loop"])
            state,req_id=fut.result(timeout=25)
            if state not in ("sent","pending","accepted"):
                raise RuntimeError("Telegram delivery not confirmed")
            deadline=ns["ip_iso"](ns["ip_now"]()+timedelta(hours=24))
            ns["execute"]("""UPDATE intro_orders SET status='awaiting_response',
                reservation_expires_at=NULL,response_expires_at=?
                WHERE id=? AND status='reserved'""",(deadline,intro_id))
            try:
                ns["audit"](uid,"miniapp_free_intro_delivered",
                    {"target_user_id":cid,"intro_id":intro_id,
                     "premium":membership,"source_order_id":source,"request_id":req_id})
            except Exception:
                pass
            return reply({"status":"pending","message":"Предложение отправлено! Ответ придёт в Telegram. Повторная оплата не требуется."})
        except Exception as exc:
            app.logger.warning("Mini App free intro delivery failed: %s",type(exc).__name__)
            if source:
                restore_intro_credit(db,uid,source,claim)
            ns["ip_close"](intro_id)
            return reply({"message":"Запрос не подтвердился. Право на знакомство сохранено. Попробуй ещё раз."},503)
