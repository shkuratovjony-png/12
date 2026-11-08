from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
anchor = "bot=Application.builder().token(TOKEN).build()"
if anchor not in s:
    raise SystemExit('[build] growth-knowledge: bot anchor not found')

block = r'''
# --- Knowledge-driven compatibility + gentle conversion funnel --------------
from compat_knowledge import NUMBER_KB, SIGN_KB, MODE_TEXT, PAIR_NUMBER_TEXT, number_info, sign_info, element_pair_text

# Keep the bot focused on the paid matching product. The public dating-chat
# button is intentionally removed; old typed commands can remain harmless.
MENU = ReplyKeyboardMarkup([
    [KeyboardButton('💖 Моя пара'), KeyboardButton('👤 Мой профиль')],
    [KeyboardButton('✨ Подбор'), KeyboardButton('⚙️ Ещё')],
], resize_keyboard=True, is_persistent=True)


def kg_number_relation(a, b):
    a, b = int(a), int(b)
    if a == b:
        return 'Вы похожи по внутреннему темпу: многие решения и реакции могут быть понятны друг другу без долгой настройки.'
    aa = 2 if a in (11, 22, 33) else a
    bb = 2 if b in (11, 22, 33) else b
    d = abs(aa - bb)
    if d in (1, 3):
        return 'Ритмы разные, но хорошо дополняются: один чаще запускает движение, другой добавляет баланс или глубину.'
    if d in (2, 4):
        return 'У вас разные способы принимать решения. Это сочетание лучше раскрывается, когда ожидания проговариваются прямо.'
    return 'Контраст заметный, поэтому особенно ценны уважение к разному темпу, ясные договорённости и отсутствие попыток переделать друг друга.'


def pc_num_pct(a, b):
    try:
        la, lb = lifepath(a['birth_date']), lifepath(b['birth_date'])
        da, db = pc_birth_day_number(a['birth_date']), pc_birth_day_number(b['birth_date'])
        score_num = 70
        if la == lb:
            score_num += 18
        elif abs((2 if la in (11,22,33) else la) - (2 if lb in (11,22,33) else lb)) in (1,3):
            score_num += 12
        elif abs((2 if la in (11,22,33) else la) - (2 if lb in (11,22,33) else lb)) in (2,4):
            score_num += 7
        if da == db:
            score_num += 6
        elif abs(da-db) <= 2:
            score_num += 3
        return min(97, score_num)
    except Exception:
        return 74


def pc_astro_pct(a, b):
    try:
        za, zb = zodiac(a['birth_date']), zodiac(b['birth_date'])
        ia, ib = sign_info(za), sign_info(zb)
        pct = 74
        if ia['element'] == ib['element']:
            pct += 13
        elif ib['element'] in GOOD.get(ia['element'], set()):
            pct += 10
        else:
            pct += 3
        if ia['mode'] == ib['mode']:
            pct += 5
        else:
            pct += 2
        return min(96, pct)
    except Exception:
        return 74


def pc_num_copy(a, b):
    try:
        la, lb = lifepath(a['birth_date']), lifepath(b['birth_date'])
        da, db = pc_birth_day_number(a['birth_date']), pc_birth_day_number(b['birth_date'])
        pair = pc_pair_number(a, b)
        ai, bi = number_info(la), number_info(lb)
        dai, dbi = number_info(da), number_info(db)
        pair_text = PAIR_NUMBER_TEXT.get(pair, 'у пары формируется собственный совместный ритм, который лучше всего раскрывается через честные договорённости')
        return (
            f'🔢 <b>Нумерология — {pc_num_pct(a,b)}%</b>\n'
            f'<b>Жизненный путь:</b> {la} + {lb}. {kg_number_relation(la, lb)}\n\n'
            f'<b>Твой ритм {la}:</b> {ai["core"]}. В любви — {ai["love"]}. '
            f'Сильная сторона: {ai["strength"]}; точка внимания: {ai["risk"]}.\n\n'
            f'<b>Ритм партнёра {lb}:</b> {bi["core"]}. В любви — {bi["love"]}. '
            f'Сильная сторона: {bi["strength"]}; точка внимания: {bi["risk"]}.\n\n'
            f'<b>Числа дня рождения:</b> {da} и {db}. '
            f'У тебя в повседневном проявлении сильнее читается {dai["core"]}; у партнёра — {dbi["core"]}.\n\n'
            f'<b>Число пары — {pair}.</b> {pair_text}.'
        )
    except Exception:
        return '🔢 <b>Нумерология</b>\nДаты рождения дают индивидуальный и парный ритм; система учтёт его в следующем пересчёте.'


def pc_astro_copy(a, b):
    try:
        za, zb = zodiac(a['birth_date']), zodiac(b['birth_date'])
        ai, bi = sign_info(za), sign_info(zb)
        rel_name, rel_text = element_pair_text(ai['element'], bi['element'])
        if ai['mode'] == bi['mode']:
            mode_text = f'По динамике вы оба относитесь к типу «{ai["mode"]}»: {MODE_TEXT.get(ai["mode"], "темп действий похож")}.'
        else:
            mode_text = (f'По динамике вы разные: {za} — {ai["mode"].lower()}, {zb} — {bi["mode"].lower()}. '
                         'Это добавляет паре разные способы двигаться к одной цели.')
        return (
            f'✨ <b>Астрологический профиль — {pc_astro_pct(a,b)}%</b>\n'
            f'<b>{html.escape(za)}</b> · {ai["element"]} · {ai["mode"]}. {ai["love"].capitalize()}.\n'
            f'<b>{html.escape(zb)}</b> · {bi["element"]} · {bi["mode"]}. {bi["love"].capitalize()}.\n\n'
            f'<b>Связка стихий — {rel_name}:</b> {rel_text}.\n'
            f'{mode_text}\n\n'
            f'<b>Сильная сторона пары:</b> {ai["strength"]}; со стороны партнёра — {bi["strength"]}. '
            f'<b>Что важно учитывать:</b> {ai["risk"]}; у партнёра — {bi["risk"]}.'
        )
    except Exception:
        return '✨ <b>Астрологический профиль</b>\nЗнаки, стихии и динамика пары учитываются в общем разборе совместимости.'


# ---- Gentle warm-up funnel --------------------------------------------------
GF_WARMUP_WEEKDAYS = (1, 3, 6)  # Tue / Thu / Sun in Yekaterinburg local time.


def gf_local_now(uid=None):
    # Use the member's own city/timezone, never fixed UTC+5.
    engine=globals().get('MATCH_PUSH_ENGINE')
    if uid is not None and engine:
        try:return engine.zone(int(uid))[0].replace(tzinfo=None)
        except Exception:pass
    return datetime.utcnow().replace(microsecond=0)+timedelta(hours=5)


def gf_week_bounds(uid):
    engine=globals().get('MATCH_PUSH_ENGINE')
    if engine:
        try:
            from zoneinfo import ZoneInfo
            from datetime import timezone,time
            local,zone=engine.zone(int(uid))
            monday=local.date()-timedelta(days=local.weekday())
            monday_utc=datetime.combine(monday,time.min,tzinfo=ZoneInfo(zone)).astimezone(timezone.utc).replace(tzinfo=None)
            return monday_utc,monday_utc+timedelta(days=7)
        except Exception:pass
    local=gf_local_now(uid)
    monday_local=datetime(local.year,local.month,local.day)-timedelta(days=local.weekday())
    start_utc=monday_local-timedelta(hours=5)
    return start_utc,start_utc+timedelta(days=7)


def gf_warmup_week_count(uid):
    start, end = gf_week_bounds(uid)
    r = one("SELECT COUNT(*) c FROM lifecycle_sends WHERE user_id=? AND segment='growth_warmup' AND created_at>=? AND created_at<?",
            (int(uid), sm_iso(start), sm_iso(end)))
    return int(r['c'] or 0) if r else 0


def gf_last_warmup(uid):
    r = one("SELECT created_at FROM lifecycle_sends WHERE user_id=? AND segment='growth_warmup' ORDER BY id DESC LIMIT 1", (int(uid),))
    return sm_parse(r['created_at']) if r and r['created_at'] else None


def gf_has_service_event_today(uid):
    start, end = sm_local_day_bounds()
    event_filter = "(event_type='profile_saved' OR event_type LIKE 'match_%' OR event_type LIKE 'communication_%' OR event_type LIKE 'intro_%' OR event_type LIKE 'payment_%')"
    try:
        if USE_POSTGRES:
            r = one("SELECT COUNT(*) c FROM audit_events WHERE user_id=? AND created_at>=?::timestamptz AND created_at<?::timestamptz AND " + event_filter,
                    (int(uid), sm_iso(start) + 'Z', sm_iso(end) + 'Z'))
        else:
            r = one("SELECT COUNT(*) c FROM audit_events WHERE user_id=? AND created_at>=? AND created_at<? AND " + event_filter,
                    (int(uid), sm_iso(start), sm_iso(end)))
        return bool(r and int(r['c'] or 0) > 0)
    except Exception:
        return False


def gf_has_live_request(uid):
    uid = int(uid)
    try:
        if one("SELECT id FROM communication_requests WHERE status='pending' AND (requester_user_id=? OR target_user_id=?) LIMIT 1", (uid, uid)):
            return True
    except Exception:
        pass
    try:
        if one("SELECT id FROM intro_orders WHERE status IN ('reserved','payment_pending','paid','awaiting_response','accepted') AND (buyer_user_id=? OR target_user_id=?) LIMIT 1", (uid, uid)):
            return True
    except Exception:
        pass
    return False


def gf_preview_candidates(uid):
    try:
        fn = globals().get('_sm_old_mp_candidates')
        rows = fn(int(uid), 3) if fn else mp_candidates(int(uid), 3)
        return list(rows or [])[:3]
    except Exception:
        return []


def gf_warmup_allowed(uid):
    uid = int(uid)
    local = gf_local_now(uid)
    if local.weekday() not in GF_WARMUP_WEEKDAYS:
        return False
    if local.hour < 10 or local.hour >= 21:
        return False
    if gf_warmup_week_count(uid) >= 3:
        return False
    last = gf_last_warmup(uid)
    if last and (datetime.utcnow().replace(microsecond=0) - last).total_seconds() < 48 * 3600:
        return False
    if sm_marketing_today(uid) > 0:
        return False
    if gf_has_service_event_today(uid):
        return False
    if lf_active_offer(uid) or gf_has_live_request(uid):
        return False
    return True


def gf_warmup_text(uid, found):
    p = profile(int(uid))
    if not p or not found:
        return ''
    best_score = int(found[0][0])
    count = len(found)
    lp = lifepath(p['birth_date'])
    ni = number_info(lp)
    sign = zodiac(p['birth_date'])
    si = sign_info(sign)
    variant = (int(uid) + gf_local_now(uid).isocalendar().week + gf_local_now(uid).weekday()) % 3
    if variant == 0:
        return (f'💖 <b>Подбор обновился</b>\n\nСейчас для тебя доступны <b>{count}</b> сильные анкеты. '
                f'Лучшее совпадение в текущем ТОПе — <b>{best_score}%</b>.\n\n'
                'Я не буду присылать их одну за другой — открой подбор, когда удобно, и посмотри, кто действительно откликается.')
    if variant == 1:
        return (f'🔢 <b>Небольшая деталь про твой профиль</b>\n\nТвоё число жизненного пути — <b>{lp}</b>: {ni["core"]}. '
                f'В отношениях {ni["love"]}.\n\nСейчас в «Моей паре» есть <b>{count}</b> доступные анкеты; '
                f'самое сильное совпадение — <b>{best_score}%</b>.')
    return (f'✨ <b>{html.escape(sign)} · {si["element"]}</b>\n\n{si["love"].capitalize()}. '
            f'Поэтому в подборе особенно важны не только проценты, но и совпадение целей и главного приоритета.\n\n'
            f'Сейчас доступны <b>{count}</b> анкеты, лучший текущий результат — <b>{best_score}%</b>.')


_gf_old_lf_process_user = lf_process_user
async def lf_process_user(bot_api, uid):
    uid = int(uid)
    sent = await _gf_old_lf_process_user(bot_api, uid)
    if sent:
        return True
    if not gf_warmup_allowed(uid):
        return False
    found = gf_preview_candidates(uid)
    if not found:
        return False
    text = gf_warmup_text(uid, found)
    if not text:
        return False
    local = gf_local_now()
    key = f'growth:{local.isocalendar().year}:{local.isocalendar().week}:{local.weekday()}'
    base=str(globals().get('PAIR_WEB_BASE_URL') or '').rstrip('/')
    if base.startswith('https://'):
        from telegram import WebAppInfo
        open_button=InlineKeyboardButton('💖 Сделать подборку',web_app=WebAppInfo(url=base+'/s/app'))
    else:
        open_button=InlineKeyboardButton('💖 Сделать подборку',callback_data='mp:refresh:0')
    kb = InlineKeyboardMarkup([
        [open_button],
        [InlineKeyboardButton('Не присылать такие сообщения', callback_data='lf:optout')],
    ])
    return await lf_send(bot_api, uid, 'growth_warmup', key, text, kb)
# ---------------------------------------------------------------------------

'''

s = s.replace(anchor, block + anchor, 1)
p.write_text(s, encoding='utf-8')
print('[build] knowledge engine + chat removal + gentle conversion funnel applied', flush=True)
