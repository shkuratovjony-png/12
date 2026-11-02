from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
anchor = "bot=Application.builder().token(TOKEN).build()"
if anchor not in s:
    raise SystemExit('[build] yekaterinburg-hub: bot anchor not found')

block = r'''
# --- Yekaterinburg primary commercial hub -----------------------------------
# Road-accessible satellite towns/settlements are routed to one dating hub.
# Unknown typo variants are additionally handled by the fuzzy matcher from
# patch_city_normalization.py, so we only seed common spellings/aliases here.
_YK_SEEDS = [
    ('Екатеринбург', ['екатеринбург','екатеренбург','екатиринбург','екатаринбург','екатеринбурк','екатеринбур','екб','екбург','е-бург','ебург','екат','ekaterinburg','yekaterinburg','ekb','yekb','sverdlovsk','свердловск']),
    ('Верхняя Пышма', ['верхняя пышма','верхняяпышма','верх пышма','в пышма','в.пышма','впышма','пышма','verkhnyaya pyshma','verkhnaya pyshma']),
    ('Берёзовский', ['березовский','берёзовский','березовск','березовый','berezovsky','berezovskiy']),
    ('Среднеуральск', ['среднеуральск','средне уральск','среднеуралск','sredneuralsk']),
    ('Арамиль', ['арамиль','арамил','арамел','aramil']),
    ('Первоуральск', ['первоуральск','перво уральск','первоуралск','первоуральс','pervouralsk']),
    ('Ревда', ['ревда','ревде','revda']),
    ('Дегтярск', ['дегтярск','дегтярьск','дегтярс','degtyarsk']),
    ('Полевской', ['полевской','полевскои','полевскый','polevskoy']),
    ('Сысерть', ['сысерть','сысерт','сисерть','sysert']),
    ('Заречный', ['заречный','заречныи','заречны','zarechny']),
    ('Белоярский', ['белоярский','белоярск','белоярка','beloyarsky','beloyarskiy']),
    ('Верхнее Дуброво', ['верхнее дуброво','верхнее-дуброво','верх дуброво','verkhnee dubrovo']),
    ('Большой Исток', ['большой исток','большои исток','б исток','bolshoy istok']),
    ('Косулино', ['косулино','косулина','kosulino']),
    ('Патруши', ['патруши','патруш','patrushi']),
    ('Бобровский', ['бобровский','бобровскии','bobrovsky']),
    ('Уральский', ['уральский','зато уральский','уральскии','uralsky']),
    ('Исток', ['исток','поселок исток','п исток']),
    ('Прохладный', ['прохладный','прохладныи','prokhladny']),
    ('Рассоха', ['рассоха','рассоха свердловская','rassokha']),
    ('Балтым', ['балтым','балтим','baltym']),
    ('Решеты', ['решеты','решёты','reshety']),
    ('Шабровский', ['шабровский','шабровскии','shabrovsky']),
    ('Горный Щит', ['горный щит','горныи щит','gorny shchit']),
]

_yk_old_cn_init_tables = cn_init_tables
def cn_init_tables():
    _yk_old_cn_init_tables()
    with db() as c:
        c.execute("INSERT INTO city_hubs(hub_key,display_name,chat_setting_key,active) VALUES(?,?,?,1) ON CONFLICT(hub_key) DO UPDATE SET display_name=excluded.display_name,chat_setting_key=excluded.chat_setting_key,active=1",
                  ('yekaterinburg','Екатеринбург','chat_yekaterinburg_url'))
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING", ('chat_yekaterinburg_url',''))
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ('primary_hub_key','yekaterinburg'))
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ('primary_hub_display','Екатеринбург'))
        for canonical, aliases in _YK_SEEDS:
            for alias in aliases:
                c.execute('''INSERT INTO city_aliases(alias_key,canonical_city,hub_key) VALUES(?,?,?)
                             ON CONFLICT(alias_key) DO UPDATE SET canonical_city=excluded.canonical_city,hub_key=excluded.hub_key''',
                          (cn_key(alias), canonical, 'yekaterinburg'))
    cn_alias_rows(force=True)

    # Re-resolve all existing profiles after adding the Yekaterinburg dictionary.
    try:
        for pr in many('SELECT user_id,city FROM profiles'):
            canonical, hub_key, _, confidence = cn_resolve(pr['city'])
            execute('''INSERT INTO profile_city_map(user_id,raw_city,normalized_city,hub_key,confidence,updated_at)
                       VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                       raw_city=excluded.raw_city,normalized_city=excluded.normalized_city,hub_key=excluded.hub_key,
                       confidence=excluded.confidence,updated_at=excluded.updated_at''',
                    (int(pr['user_id']), str(pr['city']), canonical or str(pr['city']), hub_key, confidence, now()))
            if hub_key == 'yekaterinburg' and confidence > 0 and canonical and canonical != str(pr['city']):
                execute('UPDATE profiles SET city=? WHERE user_id=?', (canonical, int(pr['user_id'])))
    except Exception as exc:
        print(f'[yekaterinburg-hub] backfill warning: {type(exc).__name__}: {exc}', flush=True)


_yk_old_city_chat_info = city_chat_info
def city_chat_info(city: str):
    canonical, hub_key, hub_display, _ = cn_resolve(city)
    if hub_key == 'yekaterinburg':
        return 'Екатеринбурга', setting('chat_yekaterinburg_url').strip()
    return _yk_old_city_chat_info(city)


def yk_hub_city(value):
    """Stable helper for analytics/admin: returns hub display for a user city."""
    canonical, hub_key, hub_display, _ = cn_resolve(value)
    return hub_display or canonical or value or ''
# ---------------------------------------------------------------------------

'''

s = s.replace(anchor, block + anchor, 1)
p.write_text(s, encoding='utf-8')
print('[build] Yekaterinburg primary hub + nearby 70km aliases applied', flush=True)
