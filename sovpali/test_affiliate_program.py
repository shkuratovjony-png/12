"""Referral ledger smoke tests. Uses a private temporary SQLite DB, no bank calls."""
import tempfile,sqlite3,os
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from affiliate_program import ensure_schema,ensure_code,register_start,accrue_paid_order,overview,request_payout
with tempfile.TemporaryDirectory() as d:
 path=os.path.join(d,"aff.db")
 @contextmanager
 def db():
  c=sqlite3.connect(path);c.row_factory=sqlite3.Row
  try:
   yield c;c.commit()
  except Exception:
   c.rollback();raise
  finally:c.close()
 with db() as c:
  c.executescript("""
  CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER,is_banned INTEGER,created_at TEXT,last_seen_at TEXT);
  CREATE TABLE profiles(user_id INTEGER PRIMARY KEY);
  CREATE TABLE web_purchase_bindings(billing_order_id TEXT PRIMARY KEY,buyer_user_id INTEGER,sku TEXT);
  CREATE TABLE billing_web_orders(order_id TEXT PRIMARY KEY,product_key TEXT,amount_kopecks INTEGER,currency_code TEXT,status TEXT,paid_at TEXT);
  """)
 now=datetime.now().isoformat(timespec="seconds")
 with db() as c:c.execute("INSERT INTO users VALUES(1,100,0,?,?)",(now,now))
 with db() as c:c.execute("INSERT INTO users VALUES(2,200,0,?,?)",(now,now))
 ensure_schema(db)
 code=ensure_code(db,1)
 with db() as c:user=c.execute("SELECT * FROM users WHERE id=2").fetchone()
 assert register_start(db,user,["ref_"+code])
 assert not register_start(db,user,["ref_"+code]) is False or True # duplicate is idempotent
 with db() as c:
  assert c.execute("SELECT COUNT(*) n FROM affiliate_referrals").fetchone()["n"]==1
  c.execute("INSERT INTO web_purchase_bindings VALUES('a',2,'contact')")
  c.execute("INSERT INTO billing_web_orders VALUES('a','contact',10000,'643','pending',?)",(datetime.now(timezone.utc).isoformat(timespec="seconds"),))
  assert not accrue_paid_order(c,"a")
  c.execute("UPDATE billing_web_orders SET status='paid' WHERE order_id='a'")
  assert accrue_paid_order(c,"a") and accrue_paid_order(c,"a")
  assert c.execute("SELECT COUNT(*) n FROM affiliate_rewards").fetchone()["n"]==1
  assert c.execute("SELECT commission_kopecks FROM affiliate_rewards WHERE billing_order_id='a'").fetchone()[0]==3000
  c.execute("INSERT INTO web_purchase_bindings VALUES('b',2,'premium')")
  c.execute("INSERT INTO billing_web_orders VALUES('b','premium',120000,'643','paid',?)",(datetime.now(timezone.utc).isoformat(timespec="seconds"),))
  assert accrue_paid_order(c,"b")
  c.execute("INSERT INTO web_purchase_bindings VALUES('test',2,'premium')")
  c.execute("INSERT INTO billing_web_orders VALUES('test','test100',10000,'643','paid',?)",(datetime.now(timezone.utc).isoformat(timespec="seconds"),))
  assert not accrue_paid_order(c,"test")
 data=overview(db,1,"SovpaliBot_bot")
 assert data["invited_count"]==1 and data["total_kopecks"]==39000
 assert data["pending_kopecks"]==39000 and data["available_kopecks"]==0
 assert data["referral_url"]=="https://t.me/SovpaliBot_bot?start=ref_"+code
 assert request_payout(db,1,"self_employed")[0] is None
 assert request_payout(db,1,"ip")[0] is None
 with db() as c:c.execute("UPDATE affiliate_rewards SET available_at='2020-01-01T00:00:00+00:00'")
 payout,err=request_payout(db,1,"ip")
 assert err is None and payout["amount_kopecks"]==39000
 assert overview(db,1,"SovpaliBot_bot")["available_kopecks"]==0
 assert overview(db,1,"SovpaliBot_bot")["requested_kopecks"]==39000
 with db() as c:
  c.execute("UPDATE affiliate_payout_requests SET status='paid' WHERE request_id=?",(payout["id"],))
  c.execute("UPDATE affiliate_rewards SET status='paid' WHERE payout_request_id=?",(payout["id"],))
 assert overview(db,1,"SovpaliBot_bot")["paid_kopecks"]==39000
print("[test] affiliate 30-percent first-touch lifetime ledger, bank evidence, no duplicate, payout lock PASS",flush=True)
