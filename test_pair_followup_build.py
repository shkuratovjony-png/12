"""Isolated build test for engaged-read followups and short checkout links.

Fake Telegram bot + temporary SQLite. No production profiles or network calls.
"""
import asyncio
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from pair_conversion import PairConversion
from match_push_engine import MatchPushEngine

with TemporaryDirectory() as root:
    filename=str(Path(root)/"test.sqlite")
    @contextmanager
    def db():
        c=sqlite3.connect(filename,check_same_thread=False)
        c.row_factory=sqlite3.Row
        try:
            yield c;c.commit()
        except Exception:
            c.rollback();raise
        finally:c.close()
    def one(sql,p=()):
        with db() as c:return c.execute(sql,p).fetchone()
    def many(sql,p=()):
        with db() as c:return c.execute(sql,p).fetchall()
    def execute(sql,p=()):
        with db() as c:c.execute(sql,p)
    with db() as c:
        c.executescript("""
            CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER,is_banned INTEGER DEFAULT 0);
            CREATE TABLE profiles(user_id INTEGER PRIMARY KEY,name TEXT,city TEXT,gender TEXT,
                   goal TEXT,priority TEXT,birth_date TEXT,completed_at TEXT,photo_file_id TEXT);
            CREATE TABLE match_offers(recipient_user_id INTEGER,pair_low INTEGER,pair_high INTEGER,
                    offered_at TEXT,status TEXT);
            CREATE TABLE communication_requests(requester_user_id INTEGER,target_user_id INTEGER,status TEXT);
            CREATE TABLE intro_orders(pair_low INTEGER,pair_high INTEGER,status TEXT);
            CREATE TABLE lifecycle_prefs(user_id INTEGER,promo_enabled INTEGER);
            CREATE TABLE lifecycle_sends(user_id INTEGER,created_at TEXT);
        """)
        c.executemany("INSERT INTO users(id,tg_id,is_banned) VALUES(?,?,0)",
                      [(1,111),(2,222),(3,333),(4,444)])
        c.executemany("""INSERT INTO profiles(
          user_id,name,city,gender,goal,priority,birth_date,completed_at,photo_file_id)
          VALUES(?,?,?,?,?,?,?,?,NULL)""",[
          (1,"Саша","Екатеринбург","Мужчина","Серьёзные отношения","Семья","01.01.1990","2026-11-01"),
          (2,"Анна","Москва","Женщина","Серьёзные отношения","Семья","02.01.1990","2026-11-02"),
          (3,"Ольга","Москва","Женщина","Серьёзные отношения","Семья","03.01.1990","2026-11-03"),
          (4,"Мария","Москва","Женщина","Серьёзные отношения","Семья","04.01.1990","2026-11-04"),
        ])
    n=datetime(2026,11,3,6,0,tzinfo=timezone.utc)  # 11 AM Yekaterinburg
    current=[n]
    ns={
      "db":db,"one":one,"many":many,"execute":execute,"USE_POSTGRES":False,
      "profile":lambda uid:one("SELECT * FROM profiles WHERE user_id=?",(int(uid),)),
      "user":lambda uid:one("SELECT * FROM users WHERE id=?",(int(uid),)),
      "eligible":lambda a,b:a["gender"]!=b["gender"],
      "pair_link":lambda base,u,c,secret:f"{base}/s/m/{u}_{c}_token",
      "PAIR_WEB_BASE_URL":"https://example.test",
      "FLASK_SECRET":"mock-secret"
    }
    engine=MatchPushEngine(ns)
    engine.now=lambda:current[0]
    engine.init_db()
    ns["MATCH_PUSH_ENGINE"]=engine
    reminder=PairConversion(ns)
    reminder.now=lambda:current[0]

    class FakeBot:
        def __init__(self):self.messages=[]
        async def send_message(self,chat_id,text,**kwargs):
            self.messages.append((chat_id,text,kwargs))

    bot=FakeBot()
    assert reminder.record(1,2)
    assert one("SELECT status FROM pair_read_followups WHERE viewer_user_id=1 AND candidate_user_id=2")["status"]=="pending"
    assert asyncio.run(reminder.process(bot))==0,"premature reminder"
    current[0]+=timedelta(minutes=31)
    assert asyncio.run(reminder.process(bot))==1,"one reminder after 30 minutes"
    assert len(bot.messages)==1
    chat,text,kw=bot.messages[0]
    assert chat==111
    assert "Анна" in text
    assert "через 30 минут" not in text.lower(),"fake timer"
    assert "/s/m/1_2_token" in str(kw["reply_markup"]),"reminder must open the free match page"
    assert "lf:optout" in str(kw["reply_markup"]),"opt-out missing"
    assert reminder.record(1,2) and asyncio.run(reminder.process(bot))==0,"one reminder per pair"
    # Viewer clicking the checkout suppresses their pending followup.
    assert reminder.record(1,3)
    reminder.mark_checkout(1,3)
    current[0]+=timedelta(minutes=40)
    assert asyncio.run(reminder.process(bot))==0,"checkout started; no upsell"
    assert one("SELECT status FROM pair_read_followups WHERE viewer_user_id=1 AND candidate_user_id=3")["status"]=="checkout_started"
    # Starting a communication request also blocks reminders.
    assert reminder.record(1,4)
    execute("INSERT INTO communication_requests VALUES(1,4,'pending')")
    current[0]+=timedelta(minutes=40)
    assert asyncio.run(reminder.process(bot))==0,"contact request started"
    assert one("SELECT status FROM pair_read_followups WHERE viewer_user_id=1 AND candidate_user_id=4")["status"]=="already_started"
    # Successful reminder consumes exactly one of the day's two proactive messages.
    assert engine.daily_stats(1)[1]==1,"followup must count toward 2/day cap"
    execute("INSERT INTO lifecycle_prefs VALUES(2,0)")
    assert reminder.optout(2)

front=Path("motion_site/src/Premium.tsx").read_text(encoding="utf-8")
assert "IntersectionObserver" in front and "pair.engagement_path" in front
assert 'method: "POST"' in front
assert "pair.request_path" in front
back=Path("pair_motion.py").read_text(encoding="utf-8")
assert '@app.post("/s/m/engaged/<token>")' in back
assert '@app.get("/s/m/checkout/<token>")' in back
assert 'redirect("/s/m/"+token+"#sx-start",code=302)' in back
assert "100 ₽" not in back and "Оплата пока недоступна" not in back, (
    "checkout legacy route must never display payment during QA"
)
print("[test] viewed-pair followup: 30min later opens free pair page, no duplicates, optout, daily cap PASS",flush=True)
