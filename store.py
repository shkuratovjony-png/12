"""Isolated key/value research storage. No writes outside smart_trader_ai."""
import os, json, sqlite3
from contextlib import contextmanager

URL = os.getenv("DATABASE_URL", "")
LOCAL = os.getenv("LOCAL_DB", "/tmp/smart-trader-ai.sqlite3")
TABLE = "smart_trader_ai.state" if URL else "state"

@contextmanager
def connection():
    if URL:
        import psycopg
        c = psycopg.connect(URL, connect_timeout=10)
    else:
        c = sqlite3.connect(LOCAL, timeout=30)
    try:
        yield c
        c.commit()
    finally:
        c.close()

def init():
    with connection() as c:
        if URL:
            c.execute("CREATE SCHEMA IF NOT EXISTS smart_trader_ai")
        c.execute(f"CREATE TABLE IF NOT EXISTS {TABLE} (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

def get(key, default=None):
    p = "%s" if URL else "?"
    with connection() as c:
        row = c.execute(f"SELECT value FROM {TABLE} WHERE key={p}", (key,)).fetchone()
    return json.loads(row[0]) if row else default

def put(key, value):
    p = "%s" if URL else "?"
    with connection() as c:
        c.execute(f"INSERT INTO {TABLE} (key,value) VALUES ({p},{p}) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key,json.dumps(value,allow_nan=False,separators=(",",":"))))
