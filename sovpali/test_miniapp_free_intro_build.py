"""Mini App Premium/paid-repeat introductions never need a merchant page or bank charge."""
import os,sqlite3,tempfile,threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime
from flask import Flask
from miniapp_direct_checkout import register_miniapp_checkout

with tempfile.TemporaryDirectory() as folder:
 path=folder+"/free-intro.sqlite3"
 @contextmanager
 def db():
  c=sqlite3.connect(path);c.row_factory=sqlite3.Row
  try:
   yield c;c.commit()
  except: c.rollback();raise
  finally:c.close()
 with db() as c:
  c.executescript("""
   CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER,is_banned INTEGER);
   INSERT INTO users VALUES(1,101,0);
   CREATE TABLE intro_orders(id INTEGER PRIMARY KEY,status TEXT,reservation_expires_at TEXT,response_expires_at TEXT);
  """)
 def one(q,args=()):
  with db() as c:return c.execute(q,args).fetchone()
 def execute(q,args=()):
  with db() as c:c.execute(q,args)
 ready=threading.Event();ready.set()
 state={"premium":False,"credit":False,"request":None,"limit":False,"calls":0}
 def reserve(uid,cid,amount):
  if state["limit"]:return "daily_cap",None
  with db() as c:c.execute("INSERT INTO intro_orders VALUES(91,'reserved',NULL,NULL)")
  return "reserved",{"id":91}
 async def send(ctx,uid,cid,score):
  state["calls"]+=1
  state["request"]={"status":"pending"}
  return "sent",11
 ns={"db":db,"one":one,"TOKEN":"fake",
     "mp_candidates":lambda uid,limit:[(93,{"user_id":2})],
     "web_premium_active":lambda uid:state["premium"],
     "web_contact_credit_available":lambda uid:state["credit"],
     "cr_between":lambda a,b:state["request"],
     "ip_reserve_intro":reserve,
     "ip_close":lambda i:None,
     "ready":ready,"bot":SimpleNamespace(bot=object()),"loop":object(),
     "profile":lambda i:{"user_id":i},
     "score":lambda a,b:93,
     "cr_send_request":send,
     "ip_iso":lambda dt:dt.isoformat(timespec="seconds"),
     "ip_now":datetime.utcnow,
     "execute":execute,
     "audit":lambda *a:None}
 app=Flask(__name__)
 register_miniapp_checkout(app,ns)
 client=app.test_client()
 payload={"candidate_id":2}
 def scheduler(coro,loop):
  coro.close()
  return SimpleNamespace(result=lambda timeout:("sent",11))
 with patch("miniapp_direct_checkout.validate_init_data",return_value=101),\
      patch("pair_cabinet.history_ids",return_value=[]),\
      patch("pair_cabinet.can_open",return_value=True),\
      patch("asyncio.run_coroutine_threadsafe",side_effect=scheduler):
  no_access=client.post("/s/app/api/checkout/redeem",json=payload)
  assert no_access.status_code==402,no_access.get_json()
  state["premium"]=True
  state["limit"]=True
  limit=client.post("/s/app/api/checkout/redeem",json=payload)
  assert limit.status_code==409 and "3 запроса" in limit.json["message"],limit.get_json()
  state["limit"]=False
  ok=client.post("/s/app/api/checkout/redeem",json=payload)
  assert ok.status_code==200,ok.get_json()
  assert ok.json["status"]=="pending"
  assert "url" not in ok.json,"This must never send user to website or Ozon"
  with db() as c:
   intro=c.execute("SELECT * FROM intro_orders WHERE id=91").fetchone()
   assert intro["status"]=="awaiting_response"
  assert state["request"]=={"status":"pending"}
  # A repeated press cannot send the same request twice.
  again=client.post("/s/app/api/checkout/redeem",json=payload)
  assert again.status_code==409 and state["request"]["status"]=="pending"
  state["credit"]=True;state["premium"]=False
  # Reuse a different ID to test existing paid voucher without Ozon.
  state["request"]=None
  def credit_reserve(uid,cid,amount):
   with db() as c:c.execute("INSERT INTO intro_orders VALUES(92,'reserved',NULL,NULL)")
   return "reserved",{"id":92}
  ns["ip_reserve_intro"]=credit_reserve
  with patch("web_product_access.redeem_intro_credit",return_value="original-100"):
   retry=client.post("/s/app/api/checkout/redeem",json=payload)
  assert retry.status_code==200,retry.get_json()
  assert "url" not in retry.json
 with patch("miniapp_direct_checkout.validate_init_data",side_effect=ValueError("signature")):
  assert client.post("/s/app/api/checkout/redeem",json=payload).status_code==401
print("[test] Premium/paid-repeat requests sent inside Mini App, 3/day quota, no duplicate send or extra web page PASS",flush=True)
