from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

s = s.replace(
    "import asyncio, html, os, sqlite3, threading",
    "import asyncio, html, os, sqlite3, threading, json\nimport psycopg\nfrom psycopg.rows import dict_row",
    1,
)

start = s.index("DB_PATH=os.getenv('DB_PATH','/tmp/sovpali_v3.db')")
end = s.index("\nZODIAC=")

block = r"""DATABASE_URL=os.getenv('DATABASE_URL','').strip()
DB_PATH=os.getenv('DB_PATH','/tmp/sovpali_v3.db')
USE_POSTGRES=bool(DATABASE_URL)

app=Flask(__name__); app.secret_key=FLASK_SECRET

class DBConn:
    def __init__(self, raw, pg=False):
        self.raw=raw
        self.pg=pg
    def _sql(self, q):
        if not self.pg:
            return q
        q=q.replace('?', '%s')
        if q.strip().startswith('INSERT OR IGNORE INTO settings'):
            q=q.replace('INSERT OR IGNORE INTO settings(key,value) VALUES(%s,%s)',
                        'INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT (key) DO NOTHING')
        return q
    def execute(self, q, p=()):
        return self.raw.execute(self._sql(q), p)
    def executescript(self, script):
        if not self.pg:
            return self.raw.executescript(script)
        for stmt in [x.strip() for x in script.split(';') if x.strip()]:
            self.raw.execute(stmt)

@contextmanager
def db():
    if USE_POSTGRES:
        c=psycopg.connect(DATABASE_URL,row_factory=dict_row,connect_timeout=10)
        try:
            yield DBConn(c,True)
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
    else:
        c=sqlite3.connect(DB_PATH,timeout=30,check_same_thread=False); c.row_factory=sqlite3.Row
        try:
            yield DBConn(c,False)
            c.commit()
        finally:
            c.close()

def init_db():
    with db() as c:
        if USE_POSTGRES:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS users(
                id BIGSERIAL PRIMARY KEY,
                tg_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                is_banned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profiles(
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                gender TEXT NOT NULL,
                looking_for TEXT NOT NULL,
                birth_date TEXT NOT NULL,
                birth_time TEXT,
                birth_place TEXT NOT NULL,
                city TEXT NOT NULL,
                goal TEXT NOT NULL,
                priority TEXT NOT NULL,
                photo_file_id TEXT,
                completed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profile_history(
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                snapshot JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_profile_history_user_id ON profile_history(user_id);
            CREATE TABLE IF NOT EXISTS audit_events(
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT,
                event_type TEXT NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_audit_events_user_id ON audit_events(user_id);
            CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at);
            ''')
        else:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,tg_id INTEGER UNIQUE NOT NULL,username TEXT,first_name TEXT,is_banned INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,last_seen_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS profiles(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER UNIQUE NOT NULL,name TEXT NOT NULL,gender TEXT NOT NULL,looking_for TEXT NOT NULL,birth_date TEXT NOT NULL,birth_time TEXT,birth_place TEXT NOT NULL,city TEXT NOT NULL,goal TEXT NOT NULL,priority TEXT NOT NULL,photo_file_id TEXT,completed_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS profile_history(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,snapshot TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,event_type TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
            ''')
        defaults={
            'project_name':'Совпали',
            'chat_url':'',
            'support_username':'',
            'welcome_text':'Мы не ищем пару по одному признаку. «Совпали» сравнивает цели отношений, жизненные ценности, город, нумерологические и базовые астрологические параметры, чтобы среди случайных знакомств показать тех, с кем совпадение действительно сильнее.'
        }
        for k,v in defaults.items(): c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',(k,v))

def now(): return datetime.now().isoformat(timespec='seconds')
def one(sql,p=()):
    with db() as c: return c.execute(sql,p).fetchone()
def many(sql,p=()):
    with db() as c: return c.execute(sql,p).fetchall()
def execute(sql,p=()):
    with db() as c: c.execute(sql,p)
def setting(k,default=''):
    r=one('SELECT value FROM settings WHERE key=?',(k,)); return r['value'] if r else default
def set_setting(k,v): execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,v))
def audit(user_id,event_type,payload=None):
    payload=payload or {}
    if USE_POSTGRES:
        execute('INSERT INTO audit_events(user_id,event_type,payload) VALUES(?,?,?::jsonb)',(user_id,event_type,json.dumps(payload,ensure_ascii=False)))
    else:
        execute('INSERT INTO audit_events(user_id,event_type,payload,created_at) VALUES(?,?,?,?)',(user_id,event_type,json.dumps(payload,ensure_ascii=False),now()))
def upsert_user(tg):
    t=now()
    with db() as c:
        c.execute('''INSERT INTO users(tg_id,username,first_name,created_at,last_seen_at) VALUES(?,?,?,?,?) ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,last_seen_at=excluded.last_seen_at''',(tg.id,tg.username,tg.first_name,t,t))
        row=c.execute('SELECT * FROM users WHERE tg_id=?',(tg.id,)).fetchone()
    return row
def profile(uid): return one('SELECT * FROM profiles WHERE user_id=?',(uid,))
def user(uid): return one('SELECT * FROM users WHERE id=?',(uid,))
def _snapshot_profile(row):
    if not row: return None
    return {k: row[k] for k in row.keys()}
def save_profile(uid,d):
    old=profile(uid)
    if old:
        snap=_snapshot_profile(old)
        if USE_POSTGRES:
            execute('INSERT INTO profile_history(user_id,snapshot) VALUES(?,?::jsonb)',(uid,json.dumps(snap,ensure_ascii=False)))
        else:
            execute('INSERT INTO profile_history(user_id,snapshot,created_at) VALUES(?,?,?)',(uid,json.dumps(snap,ensure_ascii=False),now()))
    vals=(uid,d['name'],d['gender'],d['looking_for'],d['birth_date'],None,d['birth_place'],d['city'],d['goal'],d['priority'],d.get('photo'),now())
    execute('''INSERT INTO profiles(user_id,name,gender,looking_for,birth_date,birth_time,birth_place,city,goal,priority,photo_file_id,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name,gender=excluded.gender,looking_for=excluded.looking_for,birth_date=excluded.birth_date,birth_time=NULL,birth_place=excluded.birth_place,city=excluded.city,goal=excluded.goal,priority=excluded.priority,photo_file_id=excluded.photo_file_id,completed_at=excluded.completed_at''',vals)
    audit(uid,'profile_saved',{'city':d.get('city'),'goal':d.get('goal'),'priority':d.get('priority')})
"""

s = s[:start] + block + s[end:]
p.write_text(s, encoding='utf-8')
print('[build] postgres backend + profile history + audit log applied', flush=True)
