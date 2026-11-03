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
PRICES={"reply_coach":900}
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


def _free_message(answers, viewer, candidate):
    """Ground the free first message in disclosed profile fields and user intent.

    This is transparent rule-based personalisation; AI followups will only
    become available after a real payment provider and model are integrated.
    Do not infer hidden desires from zodiac signs or numerology.
    """
    answers=answers or {}
    name=str(_row(candidate,"name",""))[:38].strip().split(" ")[0] or "привет"
    priority=str(_row(candidate,"priority",""))[:90].strip()
    goal=str(_row(candidate,"goal",""))[:90].strip()
    intent=answers.get("intent","talk")
    tempo=answers.get("tempo","week")
    tone=answers.get("tone","gentle")
    # Topic is grounded in what the profile actually says.
    topics={
        "семья":("семья","Что для тебя важнее всего в близких отношениях?"),
        "доверие":("доверие","Как ты понимаешь доверие между людьми?"),
        "честность":("честность","Что для тебя самое важное в искреннем общении?"),
        "верность":("верность","Что помогает тебе чувствовать уверенность в отношениях?"),
        "развитие":("развитие","Что сейчас тебя больше всего вдохновляет?"),
        "юмор":("юмор","Что способно рассмешить тебя даже после сложного дня?"),
        "уважение":("уважение","Что для тебя значит уважение в общении?"),
        "забота":("забота","Какие небольшие знаки внимания ты особенно ценишь?"),
        "поддержка":("поддержка","Что для тебя значит поддержка в отношениях?"),
    }
    topic=next((v for key,v in topics.items() if key in priority.casefold()),None)
    if topic:
        word,question=topic
        opening=f"Привет, {name}! Увидел, что тебе важно {word}."
    elif priority:
        # Don't turn unknown priority into an awkward or insensitive sentence.
        opening=f"Привет, {name}! В твоей анкете мне откликнулся твой взгляд на важные вещи."
        question="А что тебе особенно интересно узнать о человеке в начале знакомства?"
    else:
        opening=f"Привет, {name}! Рад знакомству."
        question="А что тебе обычно нравится в первом разговоре?"
    if tone=="direct":
        message=f"{name}, привет! Понравилось, что мы оба открыты к знакомству. {question}"
    elif tone=="playful":
        message=f"{opening} Кажется, у нас есть с чего начать знакомство 🙂 {question}"
    else:
        message=f"{opening} {question}"
    if tempo=="slow" and intent=="date":
        # Date is the stated goal, but don't pressure for a date immediately.
        message=f"{opening} {question}"
    reason=(f"В анкете {name} указан приоритет «{priority or 'не указан'}»"
            f" и цель «{goal or 'не указана'}». "
            "Мы использовали эти добровольные ответы и твой выбранный стиль, "
            "чтобы начать с открытого вопроса без давления. "
            "Астрология и нумерология могут служить творческим дополнением, "
            "но не раскрывают реальные мысли или желания другого человека.")
    return {"first_message":message,"why":reason,"engine":"profile-based-v1",
            "compliment":"Уважительный интерес к заявленным ценностям"}
    
    
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
        "price_reply":PRICES["reply_coach"],
        "prepare":"/coach/api/prepare/"+token if not demo else None,
        "model_ready":False,
        "payments_ready":False,
    }
    # Save/resume the free first message so users coming back with a reply
    # do not need to answer the three questions again.
    if not demo:
        load=ns.get("coach_load_answers")
        if callable(load):
            try:
                answers=load(v,c)
                if isinstance(answers,dict) and all(k in answers for k in ("intent","tempo","tone")):
                    base["saved_answers"]=answers
                    base["saved_plan"]=_free_message(answers,a,b)
            except Exception as exc:
                print("[coach] resume "+type(exc).__name__,flush=True)
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
       '<link rel="stylesheet" href="/coach/static/coach.css?v=2"></head><body>'
       '<div id="coach"></div><script>window.__COACH__='+_json_script(data)+'</script>'
       '<script defer src="/coach/static/coach.js?v=2"></script></body></html>'
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
            "intent":{"talk","date","relationship"},
            "tempo":{"soon","week","slow"},
            "tone":{"gentle","direct","playful"},
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
        plan=_free_message(data,a,b)
        return _headers(make_response({
            "ok":True,"paid":False,"first_free":True,
            "reply_price":PRICES["reply_coach"],
            "message":"Первое сообщение готово бесплатно.",
            **plan
        }))

    @app.post("/coach/api/chat/<token>")
    def coach_chat(token):
        # A paid conversation simulator can be added only after a verified
        # Prodamus webhook, AI-provider integration, and usage limits.
        _authorized(token,ns)
        return _headers(make_response({
            "ok":False,"reply_price":PRICES["reply_coach"],
            "error":"Продолжение переписки за 900 ₽ пока недоступно: оплата и AI ещё не подключены"
        },503))
