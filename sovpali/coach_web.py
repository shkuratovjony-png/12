"""Совпали · Conversation Workshop.

An optional coaching tool offered only AFTER verified mutual consent/contact
handoff. No predictions of another person's private thoughts or '99% success'.
Public demo uses fabricated profiles. Production checkout and AI require an
actual signed provider payment event and configured API credentials.
"""
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import abort, make_response, request

TTL=14*24*3600
PRICES={"starter":900, "pro":2900}
STATIC=Path(__file__).with_name("coach_static")


def coach_link(base, buyer, candidate, secret):
    base=str(base or "").strip().rstrip("/")
    if not base:return ""
    token=URLSafeTimedSerializer(secret,salt="sovpali-coach-v1").dumps({"v":int(buyer),"c":int(candidate)})
    return base+"/coach/t/"+token


def _ids(token,secret):
    try:
        data=URLSafeTimedSerializer(secret,salt="sovpali-coach-v1").loads(token,max_age=TTL)
        v,c=int(data["v"]),int(data["c"])
        if v==c:abort(404)
        return v,c
    except (BadSignature,SignatureExpired,KeyError,TypeError,ValueError):
        abort(404)


def _row(row,key,default=""):
    try:
        v=row[key]
        return v if v is not None else default
    except (TypeError,IndexError,KeyError):
        return default


def _approved_pair(v,c,ns):
    """Contact was actually disclosed following mutual consent.

    Accepted communication request: only its INITIATOR gets the follow-up.
    Accepted old automatic match: only RECIPIENT (initiator) gets it.
    Paid intro: buyer only after confirmed mutual acceptance, never at reserve.
    """
    look=ns["one"]
    try:
        if look("""SELECT 1 FROM communication_requests WHERE
          requester_user_id=? AND target_user_id=? AND status='accepted'
          LIMIT 1""",(v,c)):return True
    except Exception:pass
    try:
        if look("""SELECT 1 FROM match_offers WHERE
          recipient_user_id=? AND subject_user_id=? AND status='accepted'
          LIMIT 1""",(v,c)):return True
    except Exception:pass
    try:
        if look("""SELECT 1 FROM intro_orders WHERE
          buyer_user_id=? AND target_user_id=? AND
          status='accepted' AND paid_at IS NOT NULL LIMIT 1""",(v,c)):return True
    except Exception:pass
    return False


def _authorized(token,ns):
    v,c=_ids(token,ns["FLASK_SECRET"])
    a,b=ns["profile"](v),ns["profile"](c)
    if not a or not b or not _approved_pair(v,c,ns):
        abort(404)
    for uid in (v,c):
        u=ns["user"](uid)
        if not u or int(_row(u,"is_banned",0)):
            abort(404)
    return v,c,a,b


def _clean(text):
    return html.unescape(re.sub(r"<[^>]+>","",str(text or ""))).strip()


def _data(v,c,a,b,ns,token="",demo=False):
    reason=[]
    try:
        reason=[str(s)[:210] for s in ns["reasons"](a,b)][:4]
    except Exception:pass
    base={
        "demo":demo,
        "viewer":str(_row(a,"name","Вы"))[:80],
        "candidate":str(_row(b,"name","Пара"))[:80],
        "city":str(_row(b,"city",""))[:90],
        "goal":str(_row(b,"goal",""))[:90],
        "priority":str(_row(b,"priority",""))[:90],
        "score":max(0,min(100,int(ns["score"](a,b)))) if not demo else 92,
        "reasons":reason,
        "price_start":PRICES["starter"],
        "price_pro":PRICES["pro"],
        "prepare":"/coach/api/prepare/"+token if not demo else None,
        "model_ready":bool(os.getenv("OPENAI_API_KEY")),
        "payments_ready":False,
    }
    # These are cultural/entertainment interpretations only, NOT inferred
    # wishes, behavioural psychology or guarantees of reciprocal interest.
    return base


def _json_script(data):
    s=json.dumps(data,ensure_ascii=False,separators=(",",":"))
    return (s.replace("&",r"\u0026").replace("<",r"\u003c")
             .replace(">",r"\u003e").replace("\u2028",r"\u2028")
             .replace("\u2029",r"\u2029"))


def _headers(response):
    response.headers["Cache-Control"]="private,no-store"
    response.headers["X-Robots-Tag"]="noindex,nofollow,noarchive"
    response.headers["Referrer-Policy"]="no-referrer"
    response.headers["X-Content-Type-Options"]="nosniff"
    return response


def _page(data):
    return _headers(make_response(
       '<!doctype html><html lang="ru"><head><meta charset="UTF-8">'
       '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
       '<meta name="theme-color" content="#121115"><meta name="robots" content="noindex,nofollow">'
       '<title>Конструктор общения · Совпали</title>'
       '<link rel="stylesheet" href="/coach/static/coach.css?v=1"></head><body>'
       '<div id="coach"></div><script>window.__COACH__='+_json_script(data)+'</script>'
       '<script defer src="/coach/static/coach.js?v=1"></script></body></html>'
    ))


def register_coach(app,ns):
    @app.get("/coach/static/<name>")
    def coach_assets(name):
        if name not in ("coach.css","coach.js"):abort(404)
        from flask import send_from_directory
        res=send_from_directory(STATIC,name)
        res.headers["Cache-Control"]="public,max-age=600"
        return res

    @app.get("/coach/demo")
    def coach_demo():
        a={"name":"Вы","city":"Москва","goal":"Серьёзные отношения",
           "priority":"Близость","birth_date":"05.01.1990"}
        b={"name":"Анна","city":"Екатеринбург","goal":"Серьёзные отношения",
           "priority":"Семья","birth_date":"14.05.1993"}
        d=_data(1,2,a,b,ns,demo=True)
        d["reasons"]=["Оба обозначили серьёзную цель отношений","Для партнёра важны семейные ценности"]
        return _page(d)

    @app.get("/coach/t/<token>")
    def coach_personal(token):
        v,c,a,b=_authorized(token,ns)
        try:
            if callable(ns.get("audit")):
                ns["audit"](v,"coach_open",{"candidate_user_id":c})
        except Exception:pass
        return _page(_data(v,c,a,b,ns,token=token))

    @app.post("/coach/api/prepare/<token>")
    def coach_prepare(token):
        # A signed URL is a bearer capability. Browser requests only from our
        # origin; external forms and scripts cannot prepare sessions.
        site=request.headers.get("Sec-Fetch-Site","")
        if site and site not in ("same-origin","none"):abort(403)
        v,c,a,b=_authorized(token,ns)
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict):abort(400)
        if request.content_length and request.content_length>8000:abort(413)
        choices={
            "intent":{"talk","date","friendship","relationship"},
            "tempo":{"soon","week","slow"},
            "tone":{"gentle","direct","playful"},
            "experience":{"new","already_chatted","awkward"},
        }
        data={}
        for key,options in choices.items():
            value=payload.get(key)
            if value not in options:abort(400)
            data[key]=value
        # No speculative psychological diagnoses are persisted. Only the
        # buyer's stated intent/tone is stored, never the candidate's messages.
        try:
            store=ns.get("coach_store_answers")
            if callable(store):store(v,c,data)
        except Exception as exc:
            print("[coach] storing answers "+type(exc).__name__,flush=True)
        return _headers(make_response({
            "ok":True,"starter":900,"pro":2900,"paid":False,
            "message":"Конструктор подготовлен. Оплата пока не подключена."
        }))

    @app.post("/coach/api/chat/<token>")
    def coach_chat(token):
        # A paid conversation simulator can be added only after a verified
        # Prodamus webhook, AI-provider integration, and usage limits.
        _authorized(token,ns)
        return _headers(make_response({
            "ok":False,
            "error":"AI-тренажёр пока недоступен: оплата и модель не подключены"
        },503))
