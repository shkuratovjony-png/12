"""Build-time contract test for the post-contact coaching funnel.

Mock profiles in temporary SQLite, Flask test client, and a fake Telegram bot.
No network, payment, third-party AI or real user identifiers.
"""
import asyncio
import ast
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from flask import Flask

from coach_web import register_coach,coach_link,_approved_pair,_free_message
from coach_offers import CoachOffers

with TemporaryDirectory() as folder:
    p=str(Path(folder)/"coach.sqlite")
    @contextmanager
    def db():
        c=sqlite3.connect(p)
        c.row_factory=sqlite3.Row
        try:
            yield c;c.commit()
        except Exception:
            c.rollback();raise
        finally:c.close()
    def one(sql,args=()):
        with db() as c:return c.execute(sql,args).fetchone()
    def execute(sql,args=()):
        with db() as c:c.execute(sql,args)
    def many(sql,args=()):
        with db() as c:return c.execute(sql,args).fetchall()
    with db() as c:
        c.executescript("""
        CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER,is_banned INTEGER DEFAULT 0);
        CREATE TABLE profiles(user_id INTEGER PRIMARY KEY,name TEXT,city TEXT,goal TEXT,
                 priority TEXT,birth_date TEXT,gender TEXT);
        CREATE TABLE communication_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,requester_user_id INTEGER,target_user_id INTEGER,status TEXT);
        CREATE TABLE match_offers(recipient_user_id INTEGER,subject_user_id INTEGER,status TEXT);
        CREATE TABLE intro_orders(buyer_user_id INTEGER,target_user_id INTEGER,status TEXT,paid_at TEXT);
        CREATE TABLE lifecycle_prefs(user_id INTEGER,promo_enabled INTEGER);
        """)
        c.executemany("INSERT INTO users(id,tg_id,is_banned) VALUES(?,?,0)",[(1,101),(2,202)])
        c.executemany("INSERT INTO profiles VALUES(?,?,?,?,?,?,?)",[
            (1,"Михаил","Екатеринбург","Серьёзные отношения","Семья","05.01.1990","Мужчина"),
            (2,"Анна","Москва","Серьёзные отношения","Семья","14.05.1993","Женщина"),
        ])
    namespace={
       "db":db,"one":one,"many":many,"execute":execute,
       "USE_POSTGRES":False,
       "profile":lambda u:one("SELECT * FROM profiles WHERE user_id=?",(int(u),)),
       "user":lambda u:one("SELECT * FROM users WHERE id=?",(int(u),)),
       "score":lambda a,b:92,
       "reasons":lambda a,b:["Общая цель отношений","Совпадающие приоритеты"],
       "eligible":lambda a,b:a["gender"]!=b["gender"],
       "FLASK_SECRET":"test-secret-only","PAIR_WEB_BASE_URL":"https://example.test",
    }
    app=Flask("coach-test")
    register_coach(app,namespace)
    browser=app.test_client()
    signed=coach_link(namespace["PAIR_WEB_BASE_URL"],1,2,namespace["FLASK_SECRET"])
    assert "/coach/t/" in signed
    path=signed.replace("https://example.test","",1)
    assert browser.get("/coach/demo").status_code==200
    assert "Анна" in browser.get("/coach/demo").get_data(as_text=True)
    assert browser.get(path).status_code==404,"unaccepted contact must not open private coach"
    assert not _approved_pair(1,2,namespace)
    execute("INSERT INTO communication_requests(requester_user_id,target_user_id,status) VALUES(1,2,'accepted')")
    assert _approved_pair(1,2,namespace)
    assert not _approved_pair(2,1,namespace),"only initiator may receive invitation"
    result=browser.get(path)
    assert result.status_code==200
    assert "goal" in result.get_data(as_text=True)
    assert "Серьёзные отношения" in result.get_data(as_text=True)
    assert "СБП" not in result.get_data(as_text=True)
    assert browser.get("/coach/static/coach.css").status_code==200
    assert browser.get("/coach/static/coach.js").status_code==200
    assert browser.get("/coach/static/../../app.py").status_code==404
    path_api=path.replace("/coach/t/","/coach/api/prepare/",1)
    answers={"intent":"date","tempo":"week","tone":"gentle"}
    # Answers and first message are free in QA mode; no checkout is built.
    offers=CoachOffers(namespace)
    namespace["coach_store_answers"]=offers.save
    reply=browser.post(path_api,json=answers)
    assert reply.status_code==200,reply.data
    assert reply.json["test_mode"] is True and reply.json["first_free"] is True
    assert not any(k in reply.json for k in ("reply_price","paid","pro","starter"))
    assert "Анна" in reply.json["first_message"]
    assert "Семья" in reply.json["why"]
    assert not any(k in reply.json for k in ("starter","pro"))
    assert "первое сообщение" in reply.json["message"].lower()
    candidate=namespace["profile"](2)
    viewer=namespace["profile"](1)
    direct=_free_message({"intent":"talk","tempo":"week","tone":"direct"},viewer,candidate)
    warm=_free_message({"intent":"talk","tempo":"week","tone":"gentle"},viewer,candidate)
    dating=_free_message({"intent":"date","tempo":"soon","tone":"gentle"},viewer,candidate)
    slowly=_free_message({"intent":"date","tempo":"slow","tone":"gentle"},viewer,candidate)
    assert direct["first_message"]!=warm["first_message"],"tone must change the opening"
    assert dating["first_message"]!=slowly["first_message"],"tempo must change the opening"
    assert "Семья" in dating["why"],"candidate priorities must be used"
    assert "99%" not in dating["why"],"no fictitious guarantee"
    row=one("SELECT answers_json FROM coach_quizzes WHERE buyer_user_id=1 AND candidate_user_id=2")
    assert row and "gentle" in row["answers_json"]
    namespace["coach_load_answers"]=offers.load
    resumed=browser.get(path)
    assert resumed.status_code==200
    assert "saved_plan" in resumed.get_data(as_text=True)
    assert browser.post(path_api,json={**answers,"tone":"manipulative"}).status_code==400
    assert browser.post(path_api,json={**answers,"experience":"new"}).status_code==200
    assert browser.post(path_api,json={k:v for k,v in answers.items() if k!="tempo"}).status_code==400
    chat=browser.post(path.replace("/coach/t/","/coach/api/chat/",1),json={"text":"Привет"})
    assert chat.status_code==503,"unpaid AI service must be locked"
    class FakeBot:
        def __init__(self):self.sent=[]
        async def send_message(self,chat_id,text,**kwargs):self.sent.append((chat_id,text,kwargs))
    bot=FakeBot()
    assert asyncio.run(offers.offer(bot,1,2)) is True
    assert len(bot.sent)==1
    assert bot.sent[0][0]==101
    assert "Не спеши" in bot.sent[0][1]
    assert "три коротких вопроса" in bot.sent[0][1]
    assert "900 ₽" not in bot.sent[0][1]
    assert "2 900" not in bot.sent[0][1]
    assert "500 ₽" in bot.sent[0][1] and "разовая оплата" in bot.sent[0][1]
    assert "coach/t/" in str(bot.sent[0][2]["reply_markup"])
    assert asyncio.run(offers.offer(bot,1,2)) is False
    assert len(bot.sent)==1,"only one automatic after-contact invite"
    # /coachtest deliberately replays the same exact text to the initiating
    # account; it never resends to the other person nor mutates automatic dedupe.
    assert asyncio.run(offers.preview_for(bot,1)) is True
    assert len(bot.sent)==2
    assert bot.sent[1][0]==101 and bot.sent[1][1]==bot.sent[0][1]
    assert str(bot.sent[1][2]["reply_markup"])==str(bot.sent[0][2]["reply_markup"])
    assert asyncio.run(offers.preview_for(bot,2)) is False
    execute("INSERT INTO lifecycle_prefs VALUES(2,0)")
    assert asyncio.run(offers.offer(bot,2,1)) is False
    # Fail closed if mutual consent was revoked or partnership expired.
    execute("UPDATE communication_requests SET status='declined'")
    assert browser.get(path).status_code==404

src=Path("app.py").read_text(encoding="utf-8")
ast.parse(src)
assert "await coach_after_contact(ctx.bot, requester_uid, target_uid)" in src
assert "await coach_after_contact(ctx.bot, recipient_uid, subject_uid)" in src
assert "register_coach(app,globals())" in src
assert "register_pair_motion(app, globals())" in src
assert "async def cr_send_request(" in src
assert Path("pair_motion.py").read_text(encoding="utf-8").find('@app.post("/s/m/request/<token>")')>=0, (
    "The real Motion website, not Telegram, must initiate the free consent request"
)
frontend=Path("coach_static/coach.js").read_text(encoding="utf-8")
for term in ('data-choice','cc-reply-form','replyDraft','copyReply','cc-building',
             'cc-first','cc-unlock','first_message','СКОПИРОВАТЬ СООБЩЕНИЕ','localPlan'):
    assert term in frontend,term
# The existing free demo must remain free. New 900-RUB AI UI is behind
# paid_ai_available and a verified browser purchase, never shown in demo.
for forbidden in ('price_pro||2900','price_start||900','price_reply||900','cc-chat-form','cc-plans','2 900'):
    assert forbidden not in frontend,"legacy misleading plan UI: "+forbidden
assert 'c.paid_ai_available&&c.paid_checkout_path' in frontend
assert 'paid_reply_ready' in frontend and 'requestAiReport' in frontend
demo_html=browser.get("/coach/demo").get_data(as_text=True)
assert '"paid_ai_available":false' in demo_html or '"paid_ai_available": false' in demo_html
assert 'questions=[' in frontend and frontend.count('key:"')==3
assert 'state.screen="building"' in frontend
assert 'window.__COACH__' in frontend
assert "navigator.clipboard" in frontend
assert "coachtest_command" in src and "CommandHandler('coachtest',coachtest_command)" in src
print("[test] coaching funnel: mutual contact -> free invite -> free first + free reply preview PASS",flush=True)
