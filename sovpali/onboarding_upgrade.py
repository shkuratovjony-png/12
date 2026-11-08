"""Onboarding API for Telegram Mini App. Shares existing profile and matching lifecycle."""
import asyncio
from datetime import datetime
from flask import request, abort
from pair_miniapp import validate_init_data

GOALS={"Серьёзные отношения","Любовь и семья","Общение и знакомство","Пока присматриваюсь"}
PRIORITIES={"Семья","Любовь","Ценности","Страсть","Опора"}

def attach(app,ns):
    def identify():
        try:
            tid=validate_init_data(request.headers.get("X-Telegram-Init-Data",""),ns["TOKEN"])
        except (ValueError,KeyError,TypeError):
            abort(401)
        u=ns["one"]("SELECT * FROM users WHERE tg_id=?",(tid,))
        if not u or int(u["is_banned"] or 0):abort(403)
        return u
    def schema():
        with ns["db"]() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS onboarding_drafts (
                user_id BIGINT PRIMARY KEY, data_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS natal_profile_data (
                user_id BIGINT PRIMARY KEY, birth_time TEXT,
                birth_time_known INTEGER NOT NULL DEFAULT 0,
                lifestyle TEXT, relationship_style TEXT,
                family_plan TEXT, completed_at TEXT);
            """)
    def respond(obj,code=200):return obj,code
    @app.post("/s/app/api/onboarding")
    def onboarding_data():
        u=identify(); uid=int(u["id"])
        old=ns["profile"](uid)
        if old:return respond({"completed":True})
        schema()
        import json
        record=ns["one"]("SELECT data_json FROM onboarding_drafts WHERE user_id=?",(uid,))
        draft={}
        if record:
            try:draft=json.loads(record["data_json"])
            except (TypeError,ValueError):pass
        return respond({"completed":False,"draft":draft,"telegram_name":str(u["first_name"] or "")[:60]})
    @app.post("/s/app/api/onboarding/save")
    def onboarding_save():
        u=identify();uid=int(u["id"])
        if ns["profile"](uid):return respond({"completed":True})
        obj=request.get_json(silent=True)
        if not isinstance(obj,dict) or len(str(obj))>5000:return respond({"message":"Неверные данные анкеты"},400)
        safe={}
        fields={"name","gender","birth_date","birth_place","birth_time","city","goal","priority","lifestyle","relationship_style","family_plan"}
        for k,v in obj.items():
            if k not in fields or not isinstance(v,str) or len(v)>90:return respond({"message":"Неверное поле анкеты"},400)
            safe[k]=v.strip()
        import json
        schema()
        now=datetime.utcnow().isoformat()
        ns["execute"]("""INSERT INTO onboarding_drafts(user_id,data_json,updated_at)
            VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at""",
            (uid,json.dumps(safe,ensure_ascii=False),now))
        return respond({"saved":True})
    @app.post("/s/app/api/onboarding/finish")
    def onboarding_finish():
        u=identify();uid=int(u["id"])
        if ns["profile"](uid):return respond({"completed":True})
        schema()
        import json
        # Last step submits the complete form in one request to avoid a draft write
        # followed by a second round-trip and a costly cabinet fetch.
        inline=request.get_json(silent=True)
        if isinstance(inline,dict) and inline:
            fields={"name","gender","birth_date","birth_place","birth_time","city","goal","priority","lifestyle","relationship_style","family_plan"}
            if (len(str(inline))>5000 or set(inline)-fields
                    or any(not isinstance(v,str) or len(v)>90 for v in inline.values())):
                return respond({"message":"Неверные данные анкеты"},400)
            p={k:v.strip() for k,v in inline.items()}
        else:
            r=ns["one"]("SELECT data_json FROM onboarding_drafts WHERE user_id=?",(uid,))
            if not r:return respond({"message":"Заполни анкету"},400)
            try:p=json.loads(r["data_json"])
            except (ValueError,TypeError):return respond({"message":"Данные анкеты повреждены"},400)
        required=["name","gender","birth_date","birth_place","city","goal","priority","lifestyle","relationship_style","family_plan"]
        if any(not isinstance(p.get(k),str) or not p[k].strip() for k in required):
            return respond({"message":"Ответь на все вопросы"},400)
        if p["gender"] not in ("Мужчина","Женщина") or p["goal"] not in GOALS or p["priority"] not in PRIORITIES:
            return respond({"message":"Проверь ответы"},400)
        if p["lifestyle"] not in ("Активный","Домашний","Баланс") or p["relationship_style"] not in ("Обсуждаю сразу","Нужно время","Спокойный диалог") or p["family_plan"] not in ("Хочу семью и детей","Семья без детей","Пока не решил"):
            return respond({"message":"Проверь ответы"},400)
        try:
            birthday=datetime.strptime(p["birth_date"],"%d.%m.%Y").date()
            now=datetime.utcnow().date()
            years=now.year-birthday.year-((now.month,now.day)<(birthday.month,birthday.day))
            if not 18<=years<=100:raise ValueError()
            if p.get("birth_time") and datetime.strptime(p["birth_time"],"%H:%M"):
                pass
        except (ValueError,TypeError):return respond({"message":"Проверь дату и время рождения. Сервис только для 18+"},400)
        if any(len(p[k])>90 for k in required):return respond({"message":"Ответ слишком длинный"},400)
        d={k:p[k] for k in ("name","gender","birth_date","birth_place","city","goal","priority")}
        d["looking_for"]="Женщину" if d["gender"]=="Мужчина" else "Мужчину"
        d["photo"]=None
        ns["save_profile"](uid,d)
        ns["execute"]("""INSERT INTO natal_profile_data
            (user_id,birth_time,birth_time_known,lifestyle,relationship_style,family_plan,completed_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET birth_time=excluded.birth_time,birth_time_known=excluded.birth_time_known,
            lifestyle=excluded.lifestyle,relationship_style=excluded.relationship_style,family_plan=excluded.family_plan,
            completed_at=excluded.completed_at""",
            (uid,p.get("birth_time") or None,1 if p.get("birth_time") else 0,
             p["lifestyle"],p["relationship_style"],p["family_plan"],datetime.utcnow().isoformat()))
        ns["execute"]("DELETE FROM onboarding_drafts WHERE user_id=?",(uid,))
        # Existing notifications, direction/exclusivity and payments remain untouched.
        try:
            cb=ns.get("xm_profile_ready"); loop=ns.get("loop"); bot=ns.get("bot")
            if cb and loop and bot:
                class Context:pass
                ctx=Context();ctx.bot=bot.bot
                asyncio.run_coroutine_threadsafe(cb(ctx,uid),loop)
        except Exception as exc:
            print("[onboarding] matching trigger "+type(exc).__name__,flush=True)
        return respond({"completed":True})

    @app.post("/s/app/api/natal-extra")
    def natal_extra():
        u=identify();uid=int(u["id"])
        if not ns["profile"](uid):return respond({"message":"Сначала создай профиль"},409)
        schema()
        obj=request.get_json(silent=True) or {}
        if not isinstance(obj,dict):return respond({"message":"Неверные данные"},400)
        if not obj:
            r=ns["one"]("SELECT * FROM natal_profile_data WHERE user_id=?",(uid,))
            return respond({"values":({k:(r[k] or "") for k in ("birth_time","lifestyle","relationship_style","family_plan")} if r else {})})
        required={"birth_time","lifestyle","relationship_style","family_plan"}
        if set(obj)!=required or any(not isinstance(x,str) or len(x)>90 for x in obj.values()):
            return respond({"message":"Проверь ответы"},400)
        if obj["birth_time"]:
            try:datetime.strptime(obj["birth_time"],"%H:%M")
            except ValueError:return respond({"message":"Время в формате 08:35"},400)
        if obj["lifestyle"] not in ("Активный","Домашний","Баланс") or obj["relationship_style"] not in ("Обсуждаю сразу","Нужно время","Спокойный диалог") or obj["family_plan"] not in ("Хочу семью и детей","Семья без детей","Пока не решил"):
            return respond({"message":"Выбери варианты из списка"},400)
        ns["execute"]("""INSERT INTO natal_profile_data
          (user_id,birth_time,birth_time_known,lifestyle,relationship_style,family_plan,completed_at)
          VALUES(?,?,?,?,?,?,?)
          ON CONFLICT(user_id) DO UPDATE SET birth_time=excluded.birth_time,
          birth_time_known=excluded.birth_time_known,lifestyle=excluded.lifestyle,
          relationship_style=excluded.relationship_style,
          family_plan=excluded.family_plan,completed_at=excluded.completed_at""",
          (uid,obj["birth_time"] or None,1 if obj["birth_time"] else 0,
           obj["lifestyle"],obj["relationship_style"],obj["family_plan"],datetime.utcnow().isoformat()))
        return respond({"saved":True})
