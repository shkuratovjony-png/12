from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
anchor = "bot=Application.builder().token(TOKEN).build()"
if anchor not in s:
    raise SystemExit('[build] city-normalization: bot anchor not found')

block = r"""
# --- City normalization + hub routing ---------------------------------------
# Keep the person's real city for display, but route matching/chats/analytics
# through a stable city hub. Common typos and aliases are normalized locally,
# with no paid geocoding API required.
import re as _cn_re
import difflib as _cn_difflib

_CN_SEEDS = [
    # hub_key, hub_display, canonical_city, aliases
    ('vladivostok', 'Владивосток', 'Владивосток', ['владивосток','владик','vladivostok','vladi']),
    ('vladivostok', 'Владивосток', 'Артём', ['артем','артём','artem']),
    ('vladivostok', 'Владивосток', 'Надеждинский район', ['надеждинский район','надеждинский','надеждинск','nadezhdinsky']),
    ('vladivostok', 'Владивосток', 'Вольно-Надеждинское', ['вольно-надеждинское','волно-надеждинское','вольное надеждинское','волно надеждинское']),
    ('vladivostok', 'Владивосток', 'Новый', ['новый']),
    ('vladivostok', 'Владивосток', 'Соловей-Ключ', ['соловей-ключ','соловей ключ']),
    ('vladivostok', 'Владивосток', 'Угловое', ['угловое']),
    ('vladivostok', 'Владивосток', 'Трудовое', ['трудовое']),
    ('vladivostok', 'Владивосток', 'Садгород', ['садгород']),
    ('vladivostok', 'Владивосток', 'Кипарисово', ['кипарисово']),
    ('vladivostok', 'Владивосток', 'Раздольное', ['раздольное']),
    ('vladivostok', 'Владивосток', 'Тавричанка', ['тавричанка']),
    ('vladivostok', 'Владивосток', 'Де-Фриз', ['де-фриз','де фриз']),
    ('khabarovsk', 'Хабаровск', 'Хабаровск', ['хабаровск','хабар','khabarovsk']),
]
_CN_ALIAS_CACHE = None
_CN_ALIAS_CACHE_AT = None


def cn_key(value):
    x = (value or '').strip().lower().replace('ё', 'е')
    x = _cn_re.sub(r'^(?:г\.?|город|пос\.?|поселок|пгт)\s+', '', x)
    x = x.replace('_', ' ')
    x = _cn_re.sub(r'[^a-zа-я0-9\- ]+', ' ', x)
    x = _cn_re.sub(r'\s+', ' ', x).strip(' -')
    return x


def cn_pretty_unknown(value):
    raw = _cn_re.sub(r'\s+', ' ', (value or '').strip())[:90]
    if not raw:
        return ''
    return raw[:1].upper() + raw[1:]


def cn_seed_rows():
    out = []
    for hub_key, hub_display, canonical, aliases in _CN_SEEDS:
        for alias in aliases:
            out.append((cn_key(alias), canonical, hub_key, hub_display))
    return out


def cn_alias_rows(force=False):
    global _CN_ALIAS_CACHE, _CN_ALIAS_CACHE_AT
    nowv = datetime.utcnow()
    if (not force and _CN_ALIAS_CACHE is not None and _CN_ALIAS_CACHE_AT is not None
            and (nowv - _CN_ALIAS_CACHE_AT).total_seconds() < 300):
        return _CN_ALIAS_CACHE
    rows = []
    try:
        dbrows = many('''SELECT a.alias_key,a.canonical_city,a.hub_key,h.display_name hub_display
                         FROM city_aliases a JOIN city_hubs h ON h.hub_key=a.hub_key
                         WHERE h.active=1''')
        for r in dbrows:
            rows.append((str(r['alias_key']), str(r['canonical_city']), str(r['hub_key']), str(r['hub_display'])))
    except Exception:
        rows = cn_seed_rows()
    if not rows:
        rows = cn_seed_rows()
    _CN_ALIAS_CACHE = rows
    _CN_ALIAS_CACHE_AT = nowv
    return rows


def cn_resolve(value):
    key = cn_key(value)
    if not key:
        return '', '', '', 0.0
    rows = cn_alias_rows()

    # Exact alias first.
    for alias, canonical, hub_key, hub_display in rows:
        if key == alias:
            return canonical, hub_key, hub_display, 1.0

    # Extra words such as "Артем Приморский край" should still resolve.
    for alias, canonical, hub_key, hub_display in rows:
        if len(alias) >= 5 and (f' {alias} ' in f' {key} ' or key.startswith(alias + ' ') or key.endswith(' ' + alias)):
            return canonical, hub_key, hub_display, 0.97

    # Conservative fuzzy matching for typos. Short names need a higher score.
    best = None
    best_ratio = 0.0
    for alias, canonical, hub_key, hub_display in rows:
        ratio = _cn_difflib.SequenceMatcher(None, key, alias).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = (canonical, hub_key, hub_display)
    threshold = 0.84 if len(key) >= 7 else 0.91
    if best and best_ratio >= threshold:
        return best[0], best[1], best[2], round(best_ratio, 3)

    # Unknown cities still form their own stable hub so identical city names match.
    pretty = cn_pretty_unknown(value)
    return pretty, 'city:' + key, pretty, 0.0


def cn_hub_key(value):
    return cn_resolve(value)[1]


def cn_init_tables():
    with db() as c:
        if USE_POSTGRES:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS city_hubs(
                hub_key TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                chat_setting_key TEXT,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS city_aliases(
                alias_key TEXT PRIMARY KEY,
                canonical_city TEXT NOT NULL,
                hub_key TEXT NOT NULL REFERENCES city_hubs(hub_key) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS profile_city_map(
                user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                raw_city TEXT NOT NULL,
                normalized_city TEXT NOT NULL,
                hub_key TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_profile_city_map_hub ON profile_city_map(hub_key);
            ''')
        else:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS city_hubs(
                hub_key TEXT PRIMARY KEY,display_name TEXT NOT NULL,chat_setting_key TEXT,active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS city_aliases(
                alias_key TEXT PRIMARY KEY,canonical_city TEXT NOT NULL,hub_key TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profile_city_map(
                user_id INTEGER PRIMARY KEY,raw_city TEXT NOT NULL,normalized_city TEXT NOT NULL,hub_key TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_profile_city_map_hub ON profile_city_map(hub_key);
            ''')
        c.execute("INSERT INTO city_hubs(hub_key,display_name,chat_setting_key,active) VALUES(?,?,?,1) ON CONFLICT(hub_key) DO UPDATE SET display_name=excluded.display_name,chat_setting_key=excluded.chat_setting_key,active=1",
                  ('vladivostok','Владивосток','chat_vladivostok_url'))
        c.execute("INSERT INTO city_hubs(hub_key,display_name,chat_setting_key,active) VALUES(?,?,?,1) ON CONFLICT(hub_key) DO UPDATE SET display_name=excluded.display_name,chat_setting_key=excluded.chat_setting_key,active=1",
                  ('khabarovsk','Хабаровск','chat_khabarovsk_url'))
        for hub_key, hub_display, canonical, aliases in _CN_SEEDS:
            for alias in aliases:
                c.execute('''INSERT INTO city_aliases(alias_key,canonical_city,hub_key) VALUES(?,?,?)
                             ON CONFLICT(alias_key) DO UPDATE SET canonical_city=excluded.canonical_city,hub_key=excluded.hub_key''',
                          (cn_key(alias), canonical, hub_key))

    cn_alias_rows(force=True)
    # Backfill existing profiles without changing their historical raw value.
    try:
        for pr in many('SELECT user_id,city FROM profiles'):
            canonical, hub_key, _, confidence = cn_resolve(pr['city'])
            execute('''INSERT INTO profile_city_map(user_id,raw_city,normalized_city,hub_key,confidence,updated_at)
                       VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                       raw_city=excluded.raw_city,normalized_city=excluded.normalized_city,hub_key=excluded.hub_key,
                       confidence=excluded.confidence,updated_at=excluded.updated_at''',
                    (int(pr['user_id']), str(pr['city']), canonical, hub_key, confidence, now()))
            if confidence > 0 and canonical and canonical != str(pr['city']):
                execute('UPDATE profiles SET city=? WHERE user_id=?', (canonical, int(pr['user_id'])))
    except Exception as exc:
        print(f'[city] backfill warning: {type(exc).__name__}: {exc}', flush=True)


_cn_old_init_db = init_db
def init_db():
    _cn_old_init_db()
    cn_init_tables()


_cn_old_save_profile = save_profile
def save_profile(uid, d):
    raw_city = str(d.get('city') or '').strip()[:90]
    canonical, hub_key, hub_display, confidence = cn_resolve(raw_city)
    clean = dict(d)
    clean['city'] = canonical or raw_city
    _cn_old_save_profile(uid, clean)
    try:
        execute('''INSERT INTO profile_city_map(user_id,raw_city,normalized_city,hub_key,confidence,updated_at)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                   raw_city=excluded.raw_city,normalized_city=excluded.normalized_city,hub_key=excluded.hub_key,
                   confidence=excluded.confidence,updated_at=excluded.updated_at''',
                (int(uid), raw_city, canonical or raw_city, hub_key, confidence, now()))
        audit(int(uid), 'city_normalized', {
            'raw_city': raw_city,
            'normalized_city': canonical or raw_city,
            'hub_key': hub_key,
            'hub_display': hub_display,
            'confidence': confidence,
        })
    except Exception as exc:
        print(f'[city] map save warning: {type(exc).__name__}: {exc}', flush=True)


# Every matching path now compares city hubs, not the raw spelling.
def xm_same_hub(a, b):
    try:
        return cn_hub_key(a) == cn_hub_key(b)
    except Exception:
        return cn_key(a) == cn_key(b)


# Route the chat by normalized hub as well.
def city_chat_info(city: str):
    canonical, hub_key, hub_display, _ = cn_resolve(city)
    if hub_key == 'vladivostok':
        return 'Владивостока', (setting('chat_vladivostok_url').strip() or setting('chat_url').strip())
    if hub_key == 'khabarovsk':
        return 'Хабаровска', setting('chat_khabarovsk_url').strip()
    return (hub_display or canonical or city or 'твоего города'), ''
# ---------------------------------------------------------------------------

"""

s = s.replace(anchor, block + anchor, 1)
p.write_text(s, encoding='utf-8')
print('[build] city typo normalization + hub routing applied', flush=True)
