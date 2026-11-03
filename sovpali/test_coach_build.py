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

from coach_web import register_coach,coach_link,_approved_pair
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
    with db() as c:
        c.executescript("""
        CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER,is_banned INTEGER DEFAULT 0);
        CREATE TABLE profiles(user_id INTEGER PRIMARY KEY,name TEXT,city TEXT,goal TEXT,
                 priority TEXT,birth_date TEXT,gender TEXT);
        CREATE TABLE communication_requests(requester_user_id INTEGER,target_user_id INTEGER,status TEXT);
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
       "db":db,"one":one,"execute":execute,
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
    execute("INSERT INTO communication_requests VALUES(1,2,'accepted')")
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
    answers={"intent":"date","tempo":"week","tone":"gentle","experience":"new"}
    # Until a workshop store hook exists, quiz still returns the honest
    # paywall state. With the hook, responses are persisted.
    offers=CoachOffers(namespace)
    namespace["coach_store_answers"]=offers.save
    reply=browser.post(path_api,json=answers)
    assert reply.status_code==200,reply.data
    assert reply.json["starter"]==900 and reply.json["pro"]==2900
    assert reply.json["paid"] is False
    row=one("SELECT answers_json FROM coach_quizzes WHERE buyer_user_id=1 AND candidate_user_id=2")
    assert row and "gentle" in row["answers_json"]
    assert browser.post(path_api,json={**answers,"tone":"manipulative"}).status_code==400
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
    assert "coach/t/" in str(bot.sent[0][2]["reply_markup"])
    assert asyncio.run(offers.offer(bot,1,2)) is False
    assert len(bot.sent)==1,"only one after-contact invite"
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
frontend=Path("coach_static/coach.js").read_text(encoding="utf-8")
for term in ('data-choice','cc-chat-form','price_pro||2900','price_start||900','cc-ready','cc-sim'):
    assert term in frontend,term
print("[test] coaching funnel: consent, quiz, signed privacy, demo, contact upsell, no charge PASS",flush=True)
