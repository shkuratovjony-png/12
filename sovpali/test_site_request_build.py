"""Regression: site-only request button, Telegram approval and duplicate safety.

All tests run offline with fake accounts, SQLite, the actual generated bot
sender and Flask routes. No production account, Telegram network or payments.
"""
import ast
import asyncio
import html
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from pair_web import pair_link,register_pair_web
from pair_miniapp import pair_button
from pair_motion import register_pair_motion

source=Path("app.py").read_text(encoding="utf-8")
tree=ast.parse(source)
func=lambda name:[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
assert func("cr_send_request"),"missing request sender"
sender=func("cr_send_request")[-1]
assert "communication_request_deliveries" in ast.get_source_segment(source,sender)
callback=func("mp_callback")[-1]
callback_src=ast.get_source_segment(source,callback)
assert "if action in ('view','connect','buy')" in callback_src,"old Telegram buttons must redirect to the website"
assert "not xm_same_hub(viewer['city'],candidate['city'])" not in callback_src,"city gate must not reject nationwide matches"

with __import__("tempfile").TemporaryDirectory() as folder:
    path=str(Path(folder)/"test.sqlite")
    @contextmanager
    def db():
        conn=sqlite3.connect(path,timeout=10,check_same_thread=False)
        conn.row_factory=sqlite3.Row
        try:
            yield conn;conn.commit()
        except Exception:
            conn.rollback();raise
        finally:
            conn.close()
    def one(query,args=()):
        with db() as c:return c.execute(query,args).fetchone()
    def execute(query,args=()):
        with db() as c:c.execute(query,args)
    with db() as c:
        c.executescript("""
        CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER,is_banned INTEGER DEFAULT 0);
        CREATE TABLE profiles(user_id INTEGER PRIMARY KEY,name TEXT,gender TEXT,city TEXT,
               goal TEXT,priority TEXT,birth_date TEXT,photo_file_id TEXT,completed_at TEXT);
        CREATE TABLE communication_requests(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          pair_low INTEGER,pair_high INTEGER,requester_user_id INTEGER,target_user_id INTEGER,
          score INTEGER,status TEXT,created_at TEXT,responded_at TEXT,UNIQUE(pair_low,pair_high)
        );
        CREATE TABLE communication_request_deliveries(request_id INTEGER PRIMARY KEY,sent_at TEXT);
        """)
        c.executemany("INSERT INTO users(id,tg_id,is_banned) VALUES(?,?,0)",[(11,1011),(22,2022)])
        c.executemany("""INSERT INTO profiles(
             user_id,name,gender,city,goal,priority,birth_date,photo_file_id,completed_at)
             VALUES(?,?,?,?,?,?,?,?,?)""",[
             (11,"Ирина","Женщина","Екатеринбург","Серьёзные отношения","Семья","05.01.1990",None,"2026-11-03"),
             (22,"Джон","Мужчина","Москва","Серьёзные отношения","Семья","14.05.1993",None,"2026-11-03"),
        ])
    def profile(uid):return one("SELECT * FROM profiles WHERE user_id=?",(int(uid),))
    def user(uid):return one("SELECT * FROM users WHERE id=?",(int(uid),))
    def between(a,b):
        lo,hi=sorted([int(a),int(b)])
        return one("SELECT * FROM communication_requests WHERE pair_low=? AND pair_high=?",(lo,hi))
    class FakeBot:
        def __init__(self):self.sent=[]
        async def send_message(self,chat_id,text,**kwargs):
            self.sent.append((chat_id,text,kwargs))
    bot=FakeBot()
    loop=asyncio.new_event_loop()
    started=threading.Event()
    def runner():
        asyncio.set_event_loop(loop);started.set();loop.run_forever()
    worker=threading.Thread(target=runner,daemon=True);worker.start()
    assert started.wait(2)
    ready=threading.Event();ready.set()
    space={
      "db":db,"one":one,"execute":execute,"profile":profile,"user":user,
      "cr_between":between,"eligible":lambda a,b:a["gender"]!=b["gender"],
      "now":lambda:datetime.now().isoformat(timespec="seconds"),
      "audit":lambda *args:None,"_SITE_CR_LOCK":asyncio.Lock(),
      "html":html,"ParseMode":ParseMode,
      "InlineKeyboardMarkup":InlineKeyboardMarkup,
      "InlineKeyboardButton":InlineKeyboardButton,
      "FLASK_SECRET":"test-web-pair-secret",
      "PAIR_WEB_BASE_URL":"https://example.test",
    }
    exec(compile(ast.Module(body=[sender],type_ignores=[]),"app.py","exec"),space)
    ns={
      **space,"FLASK_SECRET":"test-web-pair-secret",
      "score":lambda a,b:88,"reasons":lambda a,b:["Общие цели","Общие ценности"],
      "ready":ready,"loop":loop,"bot":SimpleNamespace(bot=bot),
    }
    app=Flask("pair_request_qa")
    register_pair_motion(app,ns)
    register_pair_web(app,ns)
    client=app.test_client()
    url=pair_link("https://example.test",11,22,ns["FLASK_SECRET"])
    pair_path=url.replace("https://example.test","")
    page=client.get(pair_path)
    assert page.status_code==200,page.data[:200]
    doc=page.get_data(as_text=True)
    assert '"request_path"' in doc
    assert "Джон" in doc and '"score":88' in doc
    assert '"request_status":"ready"' in doc
    # All previously sent payment links must now land on the FREE contact
    # request at the bottom of the signed, personalized compatibility page.
    for legacy in ("/s/m/checkout/","/s/pay/"):
        old_link=pair_path.replace("/s/m/",legacy,1)
        redirect_response=client.get(old_link)
        assert redirect_response.status_code==302,(legacy,redirect_response.data[:160])
        assert redirect_response.headers["Location"]==pair_path+"#sx-start"
        assert "100" not in redirect_response.get_data(as_text=True)

    assert client.post(pair_path.replace("/s/m/","/s/m/request/",1),
         json={},headers={"Origin":"https://evil.example"}).status_code==403
    result=client.post(pair_path.replace("/s/m/","/s/m/request/",1),json={})
    assert result.status_code==200,(result.status_code,result.data)
    assert result.json["status"]=="sent",result.json
    assert len(bot.sent)==1,"exactly one incoming request"
    assert bot.sent[0][0]==2022,"send to John, not requester"
    assert "Ирина" in bot.sent[0][1] and "88%" in bot.sent[0][1]
    buttons=bot.sent[0][2]["reply_markup"].inline_keyboard[0]
    assert len(buttons)==1,"one Mini App review button, not premature consent buttons"
    assert buttons[0].web_app is not None
    assert buttons[0].callback_data is None
    assert buttons[0].web_app.url.startswith("https://example.test/s/mini/")
    assert "Посмотреть совместимость" in buttons[0].text
    again=client.post(pair_path.replace("/s/m/","/s/m/request/",1),json={})
    assert again.json["status"]=="pending",again.data
    assert len(bot.sent)==1,"repeat must not notify target again"
    reverse=pair_link("https://example.test",22,11,ns["FLASK_SECRET"])
    reverse_path=reverse.replace("https://example.test","")
    incoming=client.post(reverse_path.replace("/s/m/","/s/m/request/",1),json={})
    assert incoming.json["status"]=="incoming",incoming.data
    assert len(bot.sent)==1,"opposite person cannot send a second crossing request"
    status=client.get(pair_path).get_data(as_text=True)
    assert '"request_status":"pending"' in status
    # Simulate the old bug: the pending DB row exists, but Telegram
    # never confirmed delivery, so the web button must allow a retry.
    execute("DELETE FROM communication_request_deliveries")
    retry_page=client.get(pair_path).get_data(as_text=True)
    assert '"request_status":"ready"' in retry_page, (
        "undelivered pending requests must not disable the free action"
    )
    resent=client.post(pair_path.replace("/s/m/","/s/m/request/",1),json={})
    assert resent.json["status"]=="sent",resent.data
    assert len(bot.sent)==2,"one explicit retry after missing delivery receipt"
    assert '"request_status":"pending"' in client.get(pair_path).get_data(as_text=True)
    execute("UPDATE communication_requests SET status='accepted'")
    accepted=client.post(pair_path.replace("/s/m/","/s/m/request/",1),json={})
    assert accepted.json["status"]=="accepted"
    assert len(bot.sent)==2
    loop.call_soon_threadsafe(loop.stop);worker.join(timeout=2);loop.close()

front=Path("motion_site/src/Premium.tsx").read_text(encoding="utf-8")
assert 'ПРЕДЛОЖИТЬ ОБЩЕНИЕ' in front
assert 'pair.request_path' in front and 'method:"POST"' in front
assert 'pair.price} ₽' not in front
assert 'ПРОДОЛЖИТЬ <ArrowUpRight' not in front
assert "requestStatus" in front
assert "ПОДРОБНЫЙ РАЗБОР" in front

print("[test] website-only CTA, nationwide pair, Telegram approval, no double sends PASS",flush=True)
