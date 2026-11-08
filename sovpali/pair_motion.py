"""Server-side bridge between Telegram profiles and Sovpali Motion UI.

No Telegram bot token or Telegram file_id is sent to the browser. A signed pair
link is a bearer capability; images are proxied only for that pair. Payments
are intentionally disabled until acquiring and legal compliance are reviewed.
"""
from datetime import datetime
from types import SimpleNamespace
from concurrent.futures import TimeoutError as FutureTimeout
from urllib.parse import urlsplit
from pathlib import Path
import html
import json
import os
import re

import requests
from flask import Response, abort, make_response, send_from_directory, request, redirect
from pair_web import _load as load_pair_token


MOTION_DIST = Path(__file__).with_name("motion_site") / "dist"
VERSION = "calendar-20261108-1"


def _value(row, field, default=""):
    try:
        v = row[field]
        return v if v is not None else default
    except (TypeError, KeyError, IndexError):
        return default


def _age(value):
    try:
        born = datetime.strptime(str(value), "%d.%m.%Y").date()
        now = datetime.now().date()
        return now.year-born.year-((now.month,now.day)<(born.month,born.day))
    except (ValueError, TypeError):
        return None


def _plain(value):
    value = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.I)
    return html.unescape(re.sub(r"<[^>]*>", "", value)).strip()


def _number(fn, a, b, fallback=0):
    try:
        return max(0, min(100, int(fn(a,b))))
    except Exception:
        return fallback


def _data_for_pair(a, b, token, ns, *, demo=False):
    get = lambda r,k: str(_value(r,k,"")).strip()
    score = _number(ns["score"], a, b)
    reasons = []
    try:
        reasons = [str(x).strip().capitalize() for x in ns["reasons"](a,b) if str(x).strip()][:5]
    except Exception:
        pass

    goal_same = bool(get(a,"goal")) and get(a,"goal")==get(b,"goal")
    priority_same = bool(get(a,"priority")) and get(a,"priority")==get(b,"priority")
    hub_same = get(a,"city").casefold() == get(b,"city").casefold()

    astro_fn = ns.get("pc_astro_pct")
    num_fn = ns.get("pc_num_pct")
    astro_score = _number(astro_fn,a,b,0) if callable(astro_fn) else 0
    num_score = _number(num_fn,a,b,0) if callable(num_fn) else 0

    astro_text = num_text = ""
    try:
        if callable(ns.get("pc_astro_copy")):
            astro_text = _plain(ns["pc_astro_copy"](a,b))
    except Exception:
        pass
    try:
        if callable(ns.get("pc_num_copy")):
            num_text = _plain(ns["pc_num_copy"](a,b))
    except Exception:
        pass

    factors=[
        dict(n="01",tag="Цели отношений",score=100 if goal_same else 0,
             title="Вы смотрите в одну сторону." if goal_same else "У вас разные цели.",
             copy=(f"Вы оба выбрали: «{get(a,'goal')}». Это общий ориентир для начала разговора."
                   if goal_same else f"Ты ищешь «{get(a,'goal')}», а человек указал «{get(b,'goal')}». Важно обсудить ожидания до знакомства."),
             basis="Реальные ответы двух анкет · совпадает / отличается"),
        dict(n="02",tag="Главные ценности",score=100 if priority_same else 0,
             title="Важное для вас совпадает." if priority_same else "Приоритеты различаются.",
             copy=(f"В обоих профилях в приоритете «{get(a,'priority')}»."
                   if priority_same else f"Твой приоритет — «{get(a,'priority')}», у партнёра — «{get(b,'priority')}». Это тема для открытого разговора."),
             basis="Реальные приоритеты двух анкет · совпадает / отличается"),
        dict(n="03",tag="Астрология",score=astro_score,
             title="Астрологический разбор пары",
             copy=astro_text or "По этой паре пока нет подробного астрологического описания.",
             basis="Символическая интерпретация дат рождения · не научный прогноз"),
        dict(n="04",tag="Нумерология",score=num_score,
             title="Нумерологический разбор пары",
             copy=num_text or "По этой паре пока нет подробного нумерологического описания.",
             basis="Символическая интерпретация дат рождения · не научный прогноз"),
    ]
    if not reasons:
        reasons=["Сравнение анкет выполнено по действующей модели Совпали."]
    viewer_id, candidate_id = _value(a,"user_id"), _value(b,"user_id")
    def person(row,uid,role):
        return {
            "name":get(row,"name"),
            "initial":get(row,"name")[:1].upper() or "♡",
            "age":_age(_value(row,"birth_date")),
            "city":get(row,"city"),
            "goal":get(row,"goal"),
            "priority":get(row,"priority"),
            "photo": f"/s/m/photo/{token}/{role}" if token and get(row,"photo_file_id") else None,
        }
    status="ready"
    if not demo and token:
        try:
            get_existing=ns.get("cr_between")
            existing=get_existing(viewer_id,candidate_id) if callable(get_existing) else None
            if existing:
                stage=str(_value(existing,"status",""))
                if stage=="accepted":status="accepted"
                elif stage=="pending":
                    if int(_value(existing,"requester_user_id",0))!=int(viewer_id):
                        status="incoming"
                    else:
                        # Older builds could save a pending DB row BEFORE
                        # Telegram confirmed sending its approval buttons.
                        # Re-enable the website action so the original sender
                        # can safely retry, using the same request ID.
                        receipt_fn=ns.get("one")
                        receipt=(receipt_fn(
                          "SELECT 1 FROM communication_request_deliveries WHERE request_id=?",
                          (int(_value(existing,"id",0)),)
                        ) if callable(receipt_fn) else None)
                        status="pending" if receipt else "ready"
        except Exception as exc:
            print("[web-request] status check "+type(exc).__name__,flush=True)
            status="error"
    paid_intros=False
    credit_available=False
    if not demo and token:
        try:
            switch=ns.get("web_contact_live")
            membership=ns.get("web_premium_active")
            credit=ns.get("web_contact_credit_available")
            paid_intros=(bool(switch()) if callable(switch) else False) and not (
                bool(membership(viewer_id)) if callable(membership) else False)
            credit_available=bool(credit(viewer_id)) if callable(credit) else False
        except Exception as exc:
            print("[web-intro] paid display gate "+type(exc).__name__,flush=True)
    return {
        "demo":bool(demo),"score":score,"reasons":reasons,
        "viewer":person(a,viewer_id,"viewer"),
        "candidate":person(b,candidate_id,"candidate"),
        "factors":factors,"astro":astro_text,"numerology":num_text,
        "same_city":hub_same,
        "request_status":status,
        "request_path":f"/s/m/request/{token}" if token else None,
        "payments_enabled":paid_intros,
        "contact_credit_available":credit_available,
        "engagement_path":f"/s/m/engaged/{token}" if token else None,
        "checkout_path":f"/billing/contact/{token}" if token else None,
        "version":VERSION,
    }


def _pair_rows(token, ns):
    viewer_id,candidate_id=load_pair_token(token,ns["FLASK_SECRET"])
    if viewer_id==candidate_id: abort(404)
    a,b=ns["profile"](viewer_id),ns["profile"](candidate_id)
    if not a or not b: abort(404)
    if _age(_value(a,"birth_date")) is not None and _age(_value(a,"birth_date")) < 18: abort(404)
    if _age(_value(b,"birth_date")) is not None and _age(_value(b,"birth_date")) < 18: abort(404)
    allowed=ns.get("eligible")
    if callable(allowed) and not allowed(a,b): abort(404)
    try:
        user=ns.get("user")
        if callable(user):
            for uid in (viewer_id,candidate_id):
                u=user(uid)
                if not u or int(_value(u,"is_banned",0)): abort(404)
    except (ValueError,TypeError): abort(404)
    return a,b,viewer_id,candidate_id


def _response_headers(resp):
    resp.headers["Cache-Control"]="private, no-store"
    resp.headers["Referrer-Policy"]="no-referrer"
    resp.headers["X-Robots-Tag"]="noindex, nofollow, noarchive"
    resp.headers["X-Content-Type-Options"]="nosniff"
    return resp


def register_pair_motion(app,ns):
    @app.get("/s/m/health")
    def motion_health():
        return {"status":"ok" if (MOTION_DIST/"assets/motion.js").is_file() else "missing-build",
                "frontend":(MOTION_DIST/"assets/motion.js").is_file(),"version":VERSION}

    @app.get("/s/m/static/<path:filename>")
    def motion_static(filename):
        if not filename.startswith("assets/"): abort(404)
        res=send_from_directory(str(MOTION_DIST),filename)
        res.headers["Cache-Control"]="no-store, max-age=0"
        return res

    def render(data):
        # Escape all JS-script delimiters; no user text is interpreted as HTML.
        packed=json.dumps(data,ensure_ascii=False,separators=(",",":"),allow_nan=False)
        packed=(packed.replace("&",r"\u0026").replace("<",r"\u003c")
                      .replace(">",r"\u003e").replace("\u2028",r"\u2028")
                      .replace("\u2029",r"\u2029"))
        markup=(
            '<!doctype html><html lang="ru"><head>'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            '<meta name="theme-color" content="#fff8fb"><meta name="robots" content="noindex,nofollow">'
            '<title>Ваша пара · Совпали</title>'
            '<script src="https://telegram.org/js/telegram-web-app.js"></script>'
            '<link rel="stylesheet" href="/s/m/static/assets/motion.css?v=calendar-20261108-1">'
            '</head><body><div id="root"></div>'
            '<script>window.__SOVPALI_PAIR__='+packed+';</script>'
            '<script type="module" src="/s/m/static/assets/motion.js?v=calendar-20261108-1"></script>'
            '</body></html>'
        )
        return _response_headers(make_response(markup))

    @app.get("/s/mini/<token>")
    def miniapp_shell(token):
        # No personal data in the shell; Telegram signature is checked first.
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,2048}", token): abort(404)
        return render({"miniapp_auth_path": "/s/mini/auth/"+token})

    @app.post("/s/mini/auth/<token>")
    def miniapp_auth(token):
        from pair_miniapp import validate_init_data
        if (request.content_length or 0)>18000: abort(413)
        body=request.get_json(silent=True) or {}
        if not isinstance(body,dict): abort(400)
        try:
            telegram_id=validate_init_data(body.get("init_data",""), ns.get("TOKEN") or os.getenv("BOT_TOKEN",""))
        except (ValueError, TypeError, KeyError):
            return _response_headers(make_response({"message":"Открой разбор кнопкой в боте «Совпали»."},401))
        a,b,viewer,candidate=_pair_rows(token,ns)
        account=ns["user"](viewer)
        if int(_value(account,"tg_id",0))!=telegram_id:
            return _response_headers(make_response({"message":"Этот разбор предназначен другому человеку. Открой свою подборку в боте."},403))
        # Keep the existing view/engagement funnel semantics.
        try:
            if callable(ns.get("audit")): ns["audit"](viewer,"motion_pair_view",{"candidate_user_id":candidate})
            if callable(ns.get("mp_record_view")): ns["mp_record_view"](viewer,candidate)
        except Exception: pass
        from pair_cabinet import enrich_pair
        return _response_headers(make_response(enrich_pair(_data_for_pair(a,b,token,ns),ns,viewer,candidate)))

    from pair_cabinet import register_cabinet
    register_cabinet(app,ns,render)

    @app.get("/s/m/demo")
    def motion_demo():
        if request.args.get('preview')=='phone':
            return _response_headers(make_response('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Совпали · мобильный просмотр</title><style>body{margin:0;background:#e9e4e1;display:grid;place-items:center;min-height:100vh}iframe{width:390px;height:min(844px,96vh);border:1px solid #d8cbd2;border-radius:28px;box-shadow:0 15px 60px #59455222;background:#fff8fb}@media(max-width:420px){iframe{width:100vw;height:100dvh;border:0;border-radius:0}}</style><iframe title="Мини-приложение Совпали" src="/s/m/demo"></iframe></html>'))
        a={"user_id":1,"name":"Вы","birth_date":"05.01.1990","goal":"Серьёзные отношения",
           "priority":"Семья","city":"Владивосток"}
        b={"user_id":2,"name":"Анна","birth_date":"14.05.1993","goal":"Серьёзные отношения",
           "priority":"Семья","city":"Владивосток"}
        # The demo uses no actual users' data, no Telegram photo, and no payments.
        d=_data_for_pair(a,b,"",ns,demo=True)
        d["score"]=92
        d["reasons"]=["Оба выбрали серьёзные отношения","Совпадает важный ориентир — семья","Вы живёте в одном городе"]
        d["factors"][2]["score"]=91;d["factors"][3]["score"]=86
        return render(d)

    @app.get("/s/m/<token>")
    def motion_pair(token):
        a,b,viewer,candidate=_pair_rows(token,ns)
        try:
            if callable(ns.get("audit")):
                ns["audit"](viewer,"motion_pair_view",{"candidate_user_id":candidate})
        except Exception: pass
        try:
            view_hook=ns.get("mp_record_view")
            if callable(view_hook):
                view_hook(viewer,candidate)
        except Exception as exc:
            print("[match-push] website view marker "+type(exc).__name__,flush=True)
        return render(_data_for_pair(a,b,token,ns))



    @app.post("/s/m/request/<token>")
    def motion_request(token):
        """A site-initiated proposal. Consent approval goes to Telegram.

        Token links are signed, short-lived bearer capabilities. Without
        Telegram WebApp auth, forwarded links may permit proposing on behalf
        of a viewer; this is a test-only flow until account binding is added.
        No Telegram contact is disclosed unless the recipient accepts.
        """
        origin=request.headers.get("Origin","")
        site=request.headers.get("Sec-Fetch-Site","")
        if site and site not in ("same-origin","none"):abort(403)
        if origin:
            expected=urlsplit(request.host_url)
            supplied=urlsplit(origin)
            if supplied.scheme not in ("https","http") or supplied.netloc!=expected.netloc:abort(403)
        if request.content_length and request.content_length>1024:abort(413)
        a,b,viewer,candidate=_pair_rows(token,ns)
        switch=ns.get("web_contact_live")
        membership=ns.get("web_premium_active")
        pay_required=(bool(switch()) if callable(switch) else False) and not (
            bool(membership(viewer)) if callable(membership) else False)
        if pay_required:
            return _response_headers(make_response({
                "ok":False,"status":"payment_required",
                "message":"Оформите покупку на сайте перед отправкой запроса.",
                "checkout_url":"/billing/contact/"+token
            },402))
        get_existing=ns.get("cr_between")
        if not callable(get_existing):
            return _response_headers(make_response({"ok":False,"status":"error",
               "message":"Отправка запроса пока недоступна."},503))
        existing=get_existing(viewer,candidate)
        if existing:
            status=str(_value(existing,"status",""))
            if status=="accepted":
                return _response_headers(make_response({"ok":True,"status":"accepted",
                  "message":"Вы уже подтвердили взаимное знакомство."}))
            if status=="pending" and int(_value(existing,"requester_user_id",0))!=int(viewer):
                return _response_headers(make_response({"ok":True,"status":"incoming",
                  "message":"Этот человек уже прислал тебе запрос. Ответь на него в Telegram."}))
        if not ns.get("ready") or not ns["ready"].wait(timeout=3):
            return _response_headers(make_response({"ok":False,"status":"error",
                "message":"Бот временно недоступен. Попробуй ещё раз."},503))
        try:
            send=ns["cr_send_request"]
            loop=ns["loop"]
            bot=ns["bot"].bot
            future=__import__("asyncio").run_coroutine_threadsafe(
                send(SimpleNamespace(bot=bot),viewer,candidate,_number(ns["score"],a,b)),loop)
            status,request_id=future.result(timeout=18)
        except FutureTimeout:
            return _response_headers(make_response({"ok":False,"status":"error",
                "message":"Сервер не подтвердил отправку. Проверь статус позднее."},503))
        except Exception as exc:
            print("[web-request] request failure "+type(exc).__name__+": "+str(exc)[:120],flush=True)
            return _response_headers(make_response({"ok":False,"status":"error",
                "message":"Не получилось отправить запрос. Повтори позднее."},503))
        texts={
            "sent":"💌 Запрос отправлен! Ждём решения второго человека в Telegram.",
            "pending":"⏳ Запрос уже отправлен. Ждём ответ.",
            "accepted":"💞 Вы оба согласились на знакомство."
        }
        ok=status in texts
        return _response_headers(make_response({"ok":ok,"status":status if ok else "error",
            "message":texts.get(status,"Telegram не подтвердил доставку. Нажми ещё раз немного позже.")},
            200 if ok else 502))

    @app.post("/s/m/engaged/<token>")
    def motion_engaged(token):
        # Only a deliberate scroll to the actual compatibility details should
        # register reading. Opening the page or Telegram link preview alone
        # cannot schedule a reminder.
        site=request.headers.get("Sec-Fetch-Site","")
        if site and site not in ("same-origin","none"): abort(403)
        a,b,viewer,candidate=_pair_rows(token,ns)
        registered=False
        try:
            hook=ns.get("pair_followup_read")
            if callable(hook):registered=bool(hook(viewer,candidate))
        except Exception as exc:
            print("[pair-followup] engagement "+type(exc).__name__,flush=True)
        return _response_headers(make_response({"ok":True,"registered":registered}))

    @app.get("/s/m/checkout/<token>")
    def motion_checkout(token):
        # Legacy link from previously sent Telegram notifications/bookmarks.
        # In free QA mode there is NO checkout: send the user straight to the
        # consent request button on their actual signed compatibility page.
        a,b,viewer,candidate=_pair_rows(token,ns)
        try:
            # A person who reached the last step should not get a stale
            # "viewed but inactive" reminder about this same pair.
            hook=ns.get("pair_followup_checkout")
            if callable(hook):hook(viewer,candidate)
        except Exception as exc:
            print("[pair-followup] legacy checkout status "+type(exc).__name__,flush=True)
        response=redirect("/s/m/"+token+"#sx-start",code=302)
        return _response_headers(response)


    @app.get("/s/m/photo/<token>/<role>")
    def motion_photo(token,role):
        if role not in ("viewer","candidate"): abort(404)
        a,b,_,_=_pair_rows(token,ns)
        row=a if role=="viewer" else b
        photo_id=_value(row,"photo_file_id","")
        if not photo_id: abort(404)
        if photo_id=="local:portrait-v1":
            from photo_media import get_local
            photo=get_local(ns["db"],int(_value(row,"user_id",0)))
            if not photo:abort(404)
            body,mime=photo
            return _response_headers(Response(body,mimetype=mime))
        bot_token=ns.get("TOKEN") or os.getenv("BOT_TOKEN","")
        if not bot_token: abort(503)
        try:
            r=requests.get("https://api.telegram.org/bot"+bot_token+"/getFile",
                           params={"file_id":photo_id},timeout=7)
            r.raise_for_status()
            info=r.json()
            path=info.get("result",{}).get("file_path") if info.get("ok") else None
            if not path or path.startswith("/") or ".." in path: abort(404)
            r=requests.get("https://api.telegram.org/file/bot"+bot_token+"/"+path,
                           timeout=12)
            r.raise_for_status()
            content=r.content
            if len(content)>8*1024*1024: abort(413)
            # Telegram profile/photo uploads are JPEG, but accept a PNG signature too.
            ctype="image/png" if content.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
            return _response_headers(Response(content,mimetype=ctype))
        except requests.RequestException:
            abort(502)
