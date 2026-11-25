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

def get_many(keys):
    keys=list(dict.fromkeys(keys))
    if not keys:return {}
    p="%s" if URL else "?"
    placeholders=",".join([p]*len(keys))
    with connection() as c:
        rows=c.execute(f"SELECT key,value FROM {TABLE} WHERE key IN ({placeholders})",tuple(keys)).fetchall()
    return {k:json.loads(v) for k,v in rows}

# Hold a session advisory lock for the entire lifetime of the worker process.
# HTTP health can start before this lock, allowing Render's old instance to exit.
def acquire_worker_lock():
    import time,logging
    if URL:
        import psycopg
        c=psycopg.connect(URL,connect_timeout=10,autocommit=True)
        try:
            while not c.execute("SELECT pg_try_advisory_lock(%s)",(71423518019,)).fetchone()[0]:
                time.sleep(2)
            return c
        except BaseException:
            c.close();raise
    import fcntl
    c=open(LOCAL+".worker.lock","a")
    fcntl.flock(c,fcntl.LOCK_EX)
    return c

def monitor_worker_lock(c):
    import time,logging
    while True:
        time.sleep(2)
        if URL:
            try:c.execute("SELECT 1").fetchone()
            except Exception:
                logging.exception("Worker lock connection lost; fail-stop")
                os._exit(1)

def save_forward(snapshot,retired):
    # Archive model state and publish current snapshot atomically.
    p="%s" if URL else "?"
    sql=f"INSERT INTO {TABLE} (key,value) VALUES ({p},{p}) ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    with connection() as c:
        for k,a in retired.items():
            c.execute(sql,("forward_archive:"+k,json.dumps(a,allow_nan=False,separators=(",",":"))))
        c.execute(sql,("forward_lab",json.dumps(snapshot,allow_nan=False,separators=(",",":"))))
