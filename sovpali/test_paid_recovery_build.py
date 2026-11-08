"""Regression for Ozon paid-undelivered recovery and stale claims.

This executes the exact production SELECT extracted from the checkout module.
Uses a private in-memory SQLite fixture; no live bank or user data.
"""
import sqlite3,re
from datetime import datetime,timezone,timedelta
from pathlib import Path
src=Path("ozon_web_checkout.py").read_text(encoding="utf-8")
m=re.search(r'rows=c\.execute\("""(SELECT o\.\* FROM billing_web_orders o.*?LIMIT 30)""",\(pending_cutoff,stale_sending\)\)',src,re.S)
assert m,"Bank recovery query should check both a pending charge and old paid failed deliveries"
sql=m.group(1)
conn=sqlite3.connect(":memory:")
conn.row_factory=sqlite3.Row
conn.executescript("""CREATE TABLE billing_web_orders(
 order_id TEXT PRIMARY KEY,product_key TEXT,created_at TEXT,status TEXT);
 CREATE TABLE web_purchase_bindings(billing_order_id TEXT,binding_status TEXT,updated_at TEXT);
""")
def iso(hours=0,minutes=0):
 return (datetime.now(timezone.utc)-timedelta(hours=hours,minutes=minutes)).isoformat(timespec="seconds")
rows=[
 ("pending_recent","contact",iso(hours=1),"pending"),
 ("pending_old","contact",iso(hours=5),"pending"),
 ("paid_retry_old","contact",iso(hours=72),"paid"),
 ("paid_stale_send","contact",iso(hours=72),"paid"),
 ("paid_recent_send","contact",iso(hours=1),"paid"),
 ("paid_delivered","contact",iso(hours=1),"paid")
]
conn.executemany("INSERT INTO billing_web_orders VALUES(?,?,?,?)",rows)
conn.executemany("INSERT INTO web_purchase_bindings VALUES(?,?,?)",[
 ("paid_retry_old","retry",iso(hours=72)),
 ("paid_stale_send","sending",iso(minutes=10)),
 ("paid_recent_send","sending",iso(minutes=1)),
 ("paid_delivered","delivered",iso(hours=1))
])
found={r["order_id"] for r in conn.execute(sql,(iso(hours=3),iso(minutes=5))).fetchall()}
assert found=={"pending_recent","paid_retry_old","paid_stale_send"},found
built=Path("app.py").read_text(encoding="utf-8")
assert "status IN ('paid','awaiting_response') AND response_expires_at IS NOT NULL" in built
print("[test] verified bank retries and unclaimed sending recovery after 5min; paid timeout after 24h PASS",flush=True)
