"""Server-side bridge between Telegram profiles and Sovpali Motion UI.

No Telegram bot token or Telegram file_id is sent to the browser. A signed pair
link is a bearer capability; images are proxied only for that pair. Payments
are intentionally disabled until acquiring and legal compliance are reviewed.
"""
from datetime import datetime
from pathlib import Path
import html
import json
import os
import re

import requests
from flask import Response, abort, make_response, send_from_directory
from pair_web import _load as load_pair_token


MOTION_DIST = Path(__file__).with_name("motion_site") / "dist"
VERSION = "motion-live-01"


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
    price = 100
    try: price = int(ns.get("setting",lambda k,d:d)("unlock_price_rub","100") or "100")
    except Exception: pass
    return {
        "demo":bool(demo),"score":score,"reasons":reasons,
        "viewer":person(a,viewer_id,"viewer"),
        "candidate":person(b,candidate_id,"candidate"),
        "factors":factors,"astro":astro_text,"numerology":num_text,
        "same_city":hub_same,"price":price,
        "payments_enabled":False,
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
        res.headers["Cache-Control"]="public, max-age=3600"
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
            '<meta name="theme-color" content="#121113"><meta name="robots" content="noindex,nofollow">'
            '<title>Ваша пара · Совпали</title>'
            '<link rel="stylesheet" href="/s/m/static/assets/motion.css">'
            '</head><body><div id="root"></div>'
            '<script>window.__SOVPALI_PAIR__='+packed+';</script>'
            '<script type="module" src="/s/m/static/assets/motion.js"></script>'
            '</body></html>'
        )
        return _response_headers(make_response(markup))

    @app.get("/s/m/demo")
    def motion_demo():
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

    @app.get("/s/m/photo/<token>/<role>")
    def motion_photo(token,role):
        if role not in ("viewer","candidate"): abort(404)
        a,b,_,_=_pair_rows(token,ns)
        row=a if role=="viewer" else b
        photo_id=_value(row,"photo_file_id","")
        if not photo_id: abort(404)
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
