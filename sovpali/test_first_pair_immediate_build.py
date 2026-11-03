"""Regression: first match delivered ONCE, never reciprocally.

Man A registers first with no partner; woman B registers later in another
city outside local daytime. Only MAN A receives WOMAN B immediately.
Woman B will receive a DIFFERENT suitable man C on his registration.
No real Telegram, database, payments or user information is accessed.
"""
import asyncio
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from match_push_engine import MatchPushEngine

class FakeBot:
    def __init__(self):
        self.sent=[]
    async def send_message(self,chat_id,text,**kw):
        self.sent.append((int(chat_id),str(text)))
    async def send_photo(self,chat_id,photo,**kw):
        self.sent.append((int(chat_id),str(kw.get("caption",""))))

with TemporaryDirectory() as folder:
    path=str(Path(folder)/"db.sqlite")
    @contextmanager
    def db():
        c=sqlite3.connect(path)
        c.row_factory=sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:c.close()
    def one(sql,args=()):
        with db() as c:return c.execute(sql,args).fetchone()
    def many(sql,args=()):
        with db() as c:return c.execute(sql,args).fetchall()
    def execute(sql,args=()):
        with db() as c:c.execute(sql,args)
    with db() as c:
        c.executescript("""
        CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER,is_banned INTEGER DEFAULT 0,last_seen_at TEXT);
        CREATE TABLE profiles(user_id INTEGER PRIMARY KEY,name TEXT,gender TEXT,city TEXT,
            goal TEXT,priority TEXT,birth_date TEXT,photo_file_id TEXT,completed_at TEXT);
        CREATE TABLE match_offers(recipient_user_id INTEGER,pair_low INTEGER,pair_high INTEGER,
            offered_at TEXT,status TEXT);
        CREATE TABLE audit_events(id INTEGER PRIMARY KEY,user_id INTEGER,event_type TEXT,payload TEXT);
        CREATE TABLE lifecycle_prefs(user_id INTEGER,promo_enabled INTEGER);
        """)
        c.executemany("INSERT INTO users(id,tg_id,is_banned,last_seen_at) VALUES(?,?,0,'2026-11-04')",
                      [(1,1001),(2,1002),(3,1003)])
        c.execute("""INSERT INTO profiles VALUES(
                1,'Мужчина','Мужчина','Москва','Серьёзные отношения','Семья',
                '1990-01-01',NULL,'2026-11-04T00:10:00')""")
    ns=dict(db=db,one=one,many=many,execute=execute,
        profile=lambda uid:one("SELECT * FROM profiles WHERE user_id=?",(uid,)),
        user=lambda uid:one("SELECT * FROM users WHERE id=?",(uid,)),
        eligible=lambda a,b:a["gender"]!=b["gender"],
        score=lambda a,b:83,  # below 86, but equal priorities => suitable
        sm_int=lambda k,default:default,
        xm_age=lambda d:30,
        cn_key=lambda city:city.casefold(),
        pair_link=lambda base,uid,cid,secret:f"{base}/s/m/test_{uid}_{cid}",
        PAIR_WEB_BASE_URL="https://example.test",FLASK_SECRET="fake",USE_POSTGRES=False)
    engine=MatchPushEngine(ns)
    now=[datetime(2026,11,3,22,0,tzinfo=timezone.utc)]
    engine.now=lambda:now[0]
    bot=FakeBot()
    # First user has no possible pair: nobody receives a random suggestion.
    asyncio.run(engine.new_profile(bot,1))
    assert not bot.sent
    assert engine.desired_slot(1)=="first"  # Moscow 01:00, never matched

    # Second signup: compatible across cities; local Moscow 01:00, Vladivostok 08:00.
    execute("""INSERT INTO profiles VALUES(
          2,'Женщина','Женщина','Владивосток','Серьёзные отношения','Семья',
          '1992-02-02',NULL,'2026-11-04T00:12:00')""")
    assert engine.desired_slot(2)=="first"
    asyncio.run(engine.new_profile(bot,2))
    assert len(bot.sent)==1,bot.sent
    assert bot.sent[0][0]==1001,"The older man must receive the newer woman"
    assert engine.pair_owner(1,2)==1,"Pair is owned by the man, never the woman"
    assert not engine.candidates(2,only_candidate=1),"No reciprocal candidate"
    assert engine.desired_slot(1) is None,"Moscow after first touch obeys night"
    assert engine.desired_slot(2)=="first","Woman has not received her first match yet"
    asyncio.run(engine.new_profile(bot,2))
    assert len(bot.sent)==1,"Repeated registration event must not duplicate a match"

    # Third signup: a DIFFERENT man arrives while Vladivostok is still 08:00.
    # The waiting woman must receive man C immediately; C must not receive B.
    execute("""INSERT INTO profiles VALUES(
          3,'Другой мужчина','Мужчина','Санкт-Петербург','Серьёзные отношения','Семья',
          '1993-03-03',NULL,'2026-11-04T00:15:00')""")
    asyncio.run(engine.new_profile(bot,3))
    assert len(bot.sent)==2,bot.sent
    assert bot.sent[-1][0]==1002,"The woman must get a DIFFERENT man"
    assert engine.pair_owner(2,3)==2
    assert not engine.candidates(3,only_candidate=2),"No reverse offer to the new man"
    assert engine.desired_slot(2) is None,"After her first contact, followup waits for schedule"
    assert engine.desired_slot(3)=="first","New man has not received a match"
    assert engine.pair_owner(1,2)==1
    assert engine.pair_owner(2,3)==2
print("[test] first matches: A receives B, B receives another C; reverse directions blocked PASS",flush=True)
