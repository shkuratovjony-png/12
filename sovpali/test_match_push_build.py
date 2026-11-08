"""Build-time integration checks for recipient-local, 2/day matching.

Offline SQLite + fake Telegram Bot. No live accounts, user data or network calls.
"""
import asyncio
import sqlite3
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from match_localtime import infer_zone,local_now
from match_push_engine import MatchPushEngine

assert infer_zone("Екатеринбург")[0]=="Asia/Yekaterinburg"
assert infer_zone("Москва")[0]=="Europe/Moscow"
assert infer_zone("Владивосток")[0]=="Asia/Vladivostok"
assert infer_zone("Южно-Сахалинск")[0]=="Asia/Sakhalin"
assert local_now("Владивосток",now_utc=datetime(2026,11,3,12,tzinfo=timezone.utc))[0].hour==22

class FakeBot:
    def __init__(self):self.sent=[]
    async def send_message(self,chat_id,text,**kwargs):
        self.sent.append((chat_id,text,kwargs))
    async def send_photo(self,chat_id,photo,**kwargs):
        self.sent.append((chat_id,kwargs.get("caption",""),kwargs))

with TemporaryDirectory() as folder:
    dbfile=str(Path(folder)/"test.sqlite3")
    @contextmanager
    def db():
        conn=sqlite3.connect(dbfile,check_same_thread=False)
        conn.row_factory=sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:conn.close()
    def one(sql,args=()):
        with db() as c:return c.execute(sql,args).fetchone()
    def many(sql,args=()):
        with db() as c:return c.execute(sql,args).fetchall()
    def execute(sql,args=()):
        with db() as c:c.execute(sql,args)
    with db() as c:
        c.executescript("""
        CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER,is_banned INTEGER DEFAULT 0,
                           last_seen_at TEXT);
        CREATE TABLE profiles(user_id INTEGER PRIMARY KEY,name TEXT,gender TEXT,
                              city TEXT,goal TEXT,priority TEXT,birth_date TEXT,
                              photo_file_id TEXT,completed_at TEXT);
        CREATE TABLE match_offers(recipient_user_id INTEGER,pair_low INTEGER,pair_high INTEGER,
                                  offered_at TEXT,status TEXT);
        CREATE TABLE audit_events(id INTEGER PRIMARY KEY,user_id INTEGER,event_type TEXT,payload TEXT);
        CREATE TABLE lifecycle_prefs(user_id INTEGER,promo_enabled INTEGER);
        CREATE TABLE lifecycle_sends(user_id INTEGER,created_at TEXT);
        CREATE TABLE intro_orders(id INTEGER PRIMARY KEY,target_user_id INTEGER,status TEXT,
                  reservation_expires_at TEXT,response_expires_at TEXT);
        CREATE TABLE communication_requests(target_user_id INTEGER,status TEXT,created_at TEXT);
        """)
        c.executemany("INSERT INTO users(id,tg_id,is_banned,last_seen_at) VALUES(?,?,0,'2026-11-03')",
                      [(1,1001),(2,1002),(3,1003),(4,1004)])
        c.executemany("""INSERT INTO profiles(
            user_id,name,gender,city,goal,priority,birth_date,photo_file_id,completed_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",[
            (1,"А","Женщина","Екатеринбург","Серьёзные отношения","Семья","01.01.1990",None,"2026-11-01"),
            (2,"Б","Мужчина","Москва","Серьёзные отношения","Семья","01.01.1991",None,"2026-11-02"),
            (3,"В","Мужчина","Санкт-Петербург","Серьёзные отношения","Семья","01.01.1992",None,"2026-11-03"),
            (4,"Г","Мужчина","Владивосток","Серьёзные отношения","Семья","01.01.1993",None,"2026-10-29"),
        ])
    ns=dict(
      db=db,one=one,many=many,execute=execute,
      profile=lambda uid:one("SELECT * FROM profiles WHERE user_id=?",(uid,)),
      user=lambda uid:one("SELECT * FROM users WHERE id=?",(uid,)),
      eligible=lambda x,y:x["gender"]!=y["gender"],
      score=lambda x,y:93,
      sm_int=lambda k,default:default,
      xm_age=lambda d:30,
      cn_key=lambda city:city.casefold(),
      pair_link=lambda base,uid,cid,secret:f"{base}/s/m/test_{uid}_{cid}",
      PAIR_WEB_BASE_URL="https://example.test",FLASK_SECRET="fake",
      USE_POSTGRES=False
    )
    engine=MatchPushEngine(ns)
    bot=FakeBot()
    now=[datetime(2026,11,3,5,0,tzinfo=timezone.utc)] # 10 AM Ekb
    engine.now=lambda:now[0]
    assert engine.desired_slot(1)=="first"
    assert engine.desired_slot(2)=="first","Moscow 08:00: never-matched account must receive a match immediately"
    assert engine.desired_slot(4)=="first","Vladivostok local 15:00"
    assert asyncio.run(engine.suggest(bot,1)) is True
    assert len(bot.sent)==1
    assert "test_1_3" in str(bot.sent[0][2]),"Newest candidate first"
    assert engine.desired_slot(1) is None,"After first send, next must wait until evening"
    # No duplicate, even if an old match remains open or reopened.
    engine.mark_view(1,3)
    assert engine.viewed(1,3)
    now[0]=datetime(2026,11,3,13,30,tzinfo=timezone.utc) # 18:30 Ekb
    assert engine.desired_slot(1)=="evening"
    assert asyncio.run(engine.suggest(bot,1)) is True
    assert len(bot.sent)==2
    assert "test_1_2" in str(bot.sent[1][2]),"Next eligible, not previously seen"
    assert engine.desired_slot(1) is None,"Third notification blocked"
    assert asyncio.run(engine.suggest(bot,1)) is False
    assert len(bot.sent)==2
    # Vladivostok 23:30: first-ever push is allowed; only follow-ups respect quiet time.
    assert engine.desired_slot(4)=="first"
    assert asyncio.run(engine.suggest(bot,4)) is True
    assert engine.desired_slot(4) is None,"After first touch, Vladivostok 23:30 is quiet"
    assert engine.desired_slot(2)=="first","Moscow first match also immediate"
    # Personal manual timezone correction is persistent.
    assert engine.set_timezone(1,"Asia/Vladivostok")
    assert engine.zone(1)[1]=="Asia/Vladivostok"
    # A new local date opens a new daily allowance.
    now[0]=datetime(2026,11,4,1,0,tzinfo=timezone.utc)
    assert engine.desired_slot(1)=="first"
    # Keep opt-out of automatic promotional notifications respected.
    execute("INSERT INTO lifecycle_prefs(user_id,promo_enabled) VALUES(?,?)",(1,0))
    assert engine.disabled(1)
    assert asyncio.run(engine.suggest(bot,1)) is False
    # A real contact request temporarily removes its target from unsolicited
    # candidate pushes; releasing or expiring it restores availability.
    later=engine.naive_iso(now[0]+timedelta(hours=23))
    execute("INSERT INTO intro_orders(id,target_user_id,status,response_expires_at) VALUES(11,1,'awaiting_response',?)",(later,))
    assert engine.target_in_active_request(1),"Active paid request must suppress other introductions"
    execute("UPDATE intro_orders SET status='declined' WHERE id=11")
    assert not engine.target_in_active_request(1),"Declined request must release target"
    execute("INSERT INTO communication_requests VALUES(3,'pending',?)",(engine.naive_iso(now[0]),))
    assert engine.target_in_active_request(3),"A fresh free request must hold the target"
    execute("UPDATE communication_requests SET created_at=? WHERE target_user_id=3",(engine.naive_iso(now[0]-timedelta(hours=25)),))
    assert not engine.target_in_active_request(3),"Stale requests do not block indefinitely"

    # A lifecycle warm-up is part of the same 2/day limit as push/follow-up.
    execute("INSERT INTO lifecycle_sends VALUES(1,?)",(engine.naive_iso(now[0]),))
    assert engine.daily_stats(1)[1]==1
    execute("INSERT INTO lifecycle_sends VALUES(1,?)",(engine.naive_iso(now[0]+timedelta(minutes=1)),))
    assert engine.daily_stats(1)[1]==2
    assert engine.desired_slot(1) is None,"Two marketing notifications should block a third automatic push"


print("[test] match push: first-ever immediate including night, then schedule, max 2/day PASS",flush=True)
