from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# Needed for offer expiration timestamps.
s = s.replace('from datetime import datetime\n', 'from datetime import datetime, timedelta\n', 1)

anchor = "bot=Application.builder().token(TOKEN).build()"
if anchor not in s:
    raise SystemExit('[build] exclusive matching: bot anchor not found')

block = r'''
# --- Exclusive sequential matchmaking ---------------------------------------
# One person can participate in only one active introduction at a time.
# Compatibility is calculated locally and deterministically; no paid AI API is
# required. Personalized copy is generated from the actual matching factors.
XM_MIN_SCORE = int(os.getenv('MATCH_MIN_SCORE', '80'))
XM_OFFER_HOURS = int(os.getenv('MATCH_OFFER_HOURS', '24'))
XM_BATCH_SIZE = int(os.getenv('MATCH_BATCH_SIZE', '20'))
XM_LOCK = threading.Lock()
XM_ACTIVE = ('offered', 'interested', 'accepted')


def xm_utcnow():
    return datetime.utcnow().replace(microsecond=0)


def xm_iso(dt=None):
    return (dt or xm_utcnow()).isoformat()


def xm_init_db():
    with db() as c:
        if USE_POSTGRES:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS match_offers(
                id BIGSERIAL PRIMARY KEY,
                pair_low BIGINT NOT NULL,
                pair_high BIGINT NOT NULL,
                subject_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                recipient_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                score INTEGER NOT NULL,
                reasons TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'offered',
                created_at TEXT NOT NULL,
                offered_at TEXT,
                expires_at TEXT,
                responded_at TEXT,
                closed_at TEXT,
                UNIQUE(pair_low,pair_high)
            );
            CREATE INDEX IF NOT EXISTS idx_match_offers_subject ON match_offers(subject_user_id);
            CREATE INDEX IF NOT EXISTS idx_match_offers_recipient ON match_offers(recipient_user_id);
            CREATE INDEX IF NOT EXISTS idx_match_offers_status ON match_offers(status);
            ''')
        else:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS match_offers(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair_low INTEGER NOT NULL,
                pair_high INTEGER NOT NULL,
                subject_user_id INTEGER NOT NULL,
                recipient_user_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                reasons TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'offered',
                created_at TEXT NOT NULL,
                offered_at TEXT,
                expires_at TEXT,
                responded_at TEXT,
                closed_at TEXT,
                UNIQUE(pair_low,pair_high)
            );
            CREATE INDEX IF NOT EXISTS idx_match_offers_subject ON match_offers(subject_user_id);
            CREATE INDEX IF NOT EXISTS idx_match_offers_recipient ON match_offers(recipient_user_id);
            CREATE INDEX IF NOT EXISTS idx_match_offers_status ON match_offers(status);
            ''')


def xm_busy(uid):
    marks = ','.join('?' for _ in XM_ACTIVE)
    r = one(
        f'''SELECT id FROM match_offers
            WHERE status IN ({marks})
              AND (subject_user_id=? OR recipient_user_id=?)
            LIMIT 1''',
        tuple(XM_ACTIVE) + (uid, uid),
    )
    return bool(r)


def xm_pair_seen(a, b):
    lo, hi = sorted((int(a), int(b)))
    return bool(one('SELECT id FROM match_offers WHERE pair_low=? AND pair_high=? LIMIT 1', (lo, hi)))


def xm_same_hub(a, b):
    try:
        ah = city_chat_info(a)[0].strip().lower().replace('ё', 'е')
        bh = city_chat_info(b)[0].strip().lower().replace('ё', 'е')
        return ah == bh
    except Exception:
        return (a or '').strip().lower().replace('ё', 'е') == (b or '').strip().lower().replace('ё', 'е')


def xm_age(birth_date):
    try:
        d = datetime.strptime(birth_date, '%d.%m.%Y')
        t = datetime.now()
        return t.year - d.year - ((t.month, t.day) < (d.month, d.day))
    except Exception:
        return None


def xm_reason_lines(a, b):
    rr = reasons(a, b)
    clean = []
    for r in rr:
        r = str(r).strip()
        if r and r not in clean:
            clean.append(r)
    return clean[:3]


def xm_offer_caption(subject, score_value):
    age = xm_age(subject['birth_date'])
    title = html.escape(subject['name'])
    if age:
        title += f', {age}'
    rs = xm_reason_lines(subject, subject)  # overwritten below by caller when needed
    return title, rs


def xm_personal_copy(viewer, candidate, score_value):
    age = xm_age(candidate['birth_date'])
    name_age = html.escape(candidate['name']) + (f', {age}' if age else '')
    rs = xm_reason_lines(viewer, candidate)
    bullets = '\n'.join('• ' + html.escape(x) for x in rs)
    if score_value >= 92:
        lead = 'Очень сильное совпадение'
    elif score_value >= 86:
        lead = 'Сильное совпадение'
    else:
        lead = 'Хорошее совпадение'
    return (
        f'💖 <b>{lead} · {score_value}%</b>\n\n'
        f'<b>{name_age}</b> · {html.escape(candidate["city"])}\n'
        f'Цель: {html.escape(candidate["goal"])}\n\n'
        f'<b>Почему система выбрала именно эту анкету:</b>\n{bullets}\n\n'
        'Сейчас эта анкета предложена <b>только тебе</b>. '
        'Если знакомство не начнётся, система передаст её следующему сильному совпадению.'
    )


def xm_interest_copy(subject, interested, score_value):
    age = xm_age(interested['birth_date'])
    name_age = html.escape(interested['name']) + (f', {age}' if age else '')
    rs = xm_reason_lines(subject, interested)
    bullets = '\n'.join('• ' + html.escape(x) for x in rs)
    return (
        f'💌 <b>Тебе отправили запрос на знакомство</b>\n\n'
        f'<b>{name_age}</b> · {html.escape(interested["city"])}\n'
        f'Совместимость: <b>{score_value}%</b>\n\n'
        f'{bullets}\n\n'
        'Сейчас это знакомство закреплено только за вами двумя. '
        'Контакт не раскрывается без твоего согласия.'
    )


def xm_candidates_for(subject_uid):
    subject = profile(subject_uid)
    if not subject:
        return []
    rows = many('''SELECT p.*,u.tg_id,u.username,u.is_banned
                   FROM profiles p JOIN users u ON u.id=p.user_id
                   WHERE p.user_id<>? AND u.is_banned=0''', (subject_uid,))
    out = []
    for c in rows:
        try:
            if not eligible(subject, c):
                continue
            if not xm_same_hub(subject['city'], c['city']):
                continue
            # Intent is a hard compatibility gate for proactive introductions.
            if subject['goal'] != c['goal']:
                continue
            if xm_pair_seen(subject_uid, c['user_id']):
                continue
            if xm_busy(c['user_id']):
                continue
            sv = score(subject, c)
            if sv < XM_MIN_SCORE:
                continue
            out.append((sv, c))
        except Exception as exc:
            print(f'[match] candidate skipped: {type(exc).__name__}: {exc}', flush=True)
    out.sort(key=lambda x: x[0], reverse=True)
    return out


async def xm_send_candidate(bot_api, offer_id, viewer, candidate, score_value):
    text = xm_personal_copy(viewer, candidate, score_value)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton('❤️ Хочу познакомиться', callback_data=f'xm:interest:{offer_id}'),
        InlineKeyboardButton('Не сейчас', callback_data=f'xm:skip:{offer_id}')
    ]])
    target = user(viewer['user_id'])
    if not target:
        raise RuntimeError('viewer user missing')
    if candidate['photo_file_id']:
        await bot_api.send_photo(target['tg_id'], candidate['photo_file_id'], caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await bot_api.send_message(target['tg_id'], text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def xm_try_offer(bot_api, subject_uid):
    subject_uid = int(subject_uid)
    with XM_LOCK:
        if xm_busy(subject_uid):
            return False
        subject = profile(subject_uid)
        if not subject:
            return False
        candidates = xm_candidates_for(subject_uid)
        if not candidates:
            return False
        sv, recipient = candidates[0]
        recipient_uid = int(recipient['user_id'])
        if xm_busy(recipient_uid):
            return False
        lo, hi = sorted((subject_uid, recipient_uid))
        created = xm_iso()
        expires = xm_iso(xm_utcnow() + timedelta(hours=XM_OFFER_HOURS))
        rr = json.dumps(xm_reason_lines(subject, recipient), ensure_ascii=False)
        try:
            with db() as c:
                cur = c.execute('''INSERT INTO match_offers(
                    pair_low,pair_high,subject_user_id,recipient_user_id,score,reasons,status,
                    created_at,offered_at,expires_at)
                    VALUES(?,?,?,?,?,?,?, ?,?,?) RETURNING id''',
                    (lo,hi,subject_uid,recipient_uid,sv,rr,'offered',created,created,expires))
                offer_id = int(cur.fetchone()['id'])
        except Exception as exc:
            print(f'[match] reserve failed: {type(exc).__name__}: {exc}', flush=True)
            return False

    try:
        await xm_send_candidate(bot_api, offer_id, recipient, subject, sv)
        try: audit(recipient_uid, 'match_offer_sent', {'offer_id':offer_id,'subject_user_id':subject_uid,'score':sv})
        except Exception: pass
        return True
    except Exception as exc:
        print(f'[match] send failed: {type(exc).__name__}: {exc}', flush=True)
        execute("UPDATE match_offers SET status='send_failed',closed_at=? WHERE id=?", (xm_iso(), offer_id))
        return await xm_try_offer(bot_api, subject_uid)


async def xm_profile_ready(ctx, uid):
    try:
        # New profile enters the exclusive queue immediately. If either side is
        # already in an active introduction, the scheduler will pick it up later.
        await xm_try_offer(ctx.bot, uid)
    except Exception as exc:
        print(f'[match] profile-ready warning: {type(exc).__name__}: {exc}', flush=True)


async def xm_callback(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = upsert_user(update.effective_user)
    try:
        _, action, raw_id = q.data.split(':', 2)
        offer_id = int(raw_id)
    except Exception:
        return
    row = one('SELECT * FROM match_offers WHERE id=?', (offer_id,))
    if not row:
        await q.message.reply_text('Это знакомство уже недоступно.')
        return
    subject_uid = int(row['subject_user_id'])
    recipient_uid = int(row['recipient_user_id'])
    subject = profile(subject_uid)
    recipient = profile(recipient_uid)
    if not subject or not recipient:
        return

    if action == 'interest':
        if int(u['id']) != recipient_uid or row['status'] != 'offered':
            return
        expires = xm_iso(xm_utcnow() + timedelta(hours=XM_OFFER_HOURS))
        execute("UPDATE match_offers SET status='interested',responded_at=?,expires_at=? WHERE id=? AND status='offered'",
                (xm_iso(), expires, offer_id))
        try: audit(recipient_uid, 'match_interest', {'offer_id':offer_id,'subject_user_id':subject_uid,'score':row['score']})
        except Exception: pass
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await q.message.reply_text('❤️ Запрос отправлен. Теперь решение за второй стороной — пара пока закреплена за вами двумя.')
        target = user(subject_uid)
        if target:
            text = xm_interest_copy(subject, recipient, int(row['score']))
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton('❤️ Да, познакомиться', callback_data=f'xm:accept:{offer_id}'),
                InlineKeyboardButton('Не сейчас', callback_data=f'xm:decline:{offer_id}')
            ]])
            if recipient['photo_file_id']:
                await ctx.bot.send_photo(target['tg_id'], recipient['photo_file_id'], caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await ctx.bot.send_message(target['tg_id'], text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if action == 'skip':
        if int(u['id']) != recipient_uid or row['status'] != 'offered':
            return
        execute("UPDATE match_offers SET status='skipped',responded_at=?,closed_at=? WHERE id=?", (xm_iso(), xm_iso(), offer_id))
        try: audit(recipient_uid, 'match_skipped', {'offer_id':offer_id})
        except Exception: pass
        try: await q.edit_message_reply_markup(reply_markup=None)
        except Exception: pass
        await q.message.reply_text('Понял. Эту анкету больше тебе не покажу — ищу следующее сильное совпадение.')
        await xm_try_offer(ctx.bot, subject_uid)
        await xm_try_offer(ctx.bot, recipient_uid)
        return

    if action == 'accept':
        if int(u['id']) != subject_uid or row['status'] != 'interested':
            return
        execute("UPDATE match_offers SET status='accepted',responded_at=?,expires_at=NULL WHERE id=?", (xm_iso(), offer_id))
        try:
            audit(subject_uid, 'match_accepted', {'offer_id':offer_id,'other_user_id':recipient_uid,'score':row['score']})
            audit(recipient_uid, 'match_mutual', {'offer_id':offer_id,'other_user_id':subject_uid,'score':row['score']})
        except Exception: pass
        try: await q.edit_message_reply_markup(reply_markup=None)
        except Exception: pass
        close_kb = InlineKeyboardMarkup([[InlineKeyboardButton('Завершить это знакомство', callback_data=f'xm:close:{offer_id}')]])
        await q.message.reply_text('💞 <b>Взаимный интерес!</b>\n\nСовпадение закреплено за вами двумя. Контакт не раскрывается автоматически — это оставляет нам безопасный шаг для платного открытия контакта.', parse_mode=ParseMode.HTML, reply_markup=close_kb)
        other = user(recipient_uid)
        if other:
            await ctx.bot.send_message(other['tg_id'], '💞 <b>Взаимный интерес!</b>\n\nВторая сторона тоже хочет познакомиться. Совпадение закреплено за вами двумя.', parse_mode=ParseMode.HTML, reply_markup=close_kb)
        return

    if action == 'decline':
        if int(u['id']) != subject_uid or row['status'] != 'interested':
            return
        execute("UPDATE match_offers SET status='declined',responded_at=?,closed_at=? WHERE id=?", (xm_iso(), xm_iso(), offer_id))
        try: audit(subject_uid, 'match_declined', {'offer_id':offer_id})
        except Exception: pass
        try: await q.edit_message_reply_markup(reply_markup=None)
        except Exception: pass
        await q.message.reply_text('Хорошо. Контакт не раскрыт. Продолжаю подбор.')
        other = user(recipient_uid)
        if other:
            await ctx.bot.send_message(other['tg_id'], 'Спасибо за отклик. В этот раз взаимного знакомства не получилось — система продолжит искать для тебя сильное совпадение.')
        await xm_try_offer(ctx.bot, subject_uid)
        await xm_try_offer(ctx.bot, recipient_uid)
        return

    if action == 'close':
        if int(u['id']) not in (subject_uid, recipient_uid) or row['status'] != 'accepted':
            return
        execute("UPDATE match_offers SET status='closed',closed_at=? WHERE id=?", (xm_iso(), offer_id))
        try: audit(int(u['id']), 'match_closed', {'offer_id':offer_id})
        except Exception: pass
        await q.message.reply_text('Знакомство завершено. Оба профиля снова доступны для нового подбора.')
        other_uid = recipient_uid if int(u['id']) == subject_uid else subject_uid
        other = user(other_uid)
        if other:
            try: await ctx.bot.send_message(other['tg_id'], 'Это знакомство завершено. Твой профиль снова участвует в подборе.')
            except Exception: pass
        await xm_try_offer(ctx.bot, subject_uid)
        await xm_try_offer(ctx.bot, recipient_uid)


async def xm_maintenance(bot_api):
    await asyncio.sleep(35)
    while True:
        try:
            stamp = xm_iso()
            expired = many("SELECT * FROM match_offers WHERE status IN ('offered','interested') AND expires_at IS NOT NULL AND expires_at<=? ORDER BY id LIMIT 100", (stamp,))
            released = set()
            for r in expired:
                execute("UPDATE match_offers SET status='expired',closed_at=? WHERE id=? AND status IN ('offered','interested')", (stamp, r['id']))
                released.add(int(r['subject_user_id'])); released.add(int(r['recipient_user_id']))
                try: audit(int(r['recipient_user_id']), 'match_expired', {'offer_id':r['id']})
                except Exception: pass
            # First requeue people released by expiration, then a small fair batch
            # of currently free profiles. This avoids mass-spamming the whole city.
            ids = list(released)
            rows = many('SELECT user_id FROM profiles ORDER BY completed_at ASC LIMIT 250')
            for r in rows:
                uid = int(r['user_id'])
                if uid not in ids and not xm_busy(uid):
                    ids.append(uid)
                if len(ids) >= XM_BATCH_SIZE:
                    break
            sent = 0
            for uid in ids:
                if sent >= XM_BATCH_SIZE:
                    break
                if await xm_try_offer(bot_api, uid):
                    sent += 1
                    await asyncio.sleep(0.25)
        except Exception as exc:
            print(f'[match] maintenance warning: {type(exc).__name__}: {exc}', flush=True)
        await asyncio.sleep(15 * 60)
# ---------------------------------------------------------------------------

'''

s = s.replace(anchor, block + anchor, 1)

# Start automatic matching immediately after a newly completed profile is saved.
needle = "u=upsert_user(update.effective_user); save_profile(u['id'],ctx.user_data['p']); p=profile(u['id'])"
if needle in s:
    s = s.replace(needle, needle + "\n    try: await xm_profile_ready(ctx,u['id'])\n    except Exception as e: print(f'[match] onboarding hook warning: {type(e).__name__}: {e}',flush=True)", 1)
else:
    needle2 = "u=upsert_user(update.effective_user); save_profile(u['id'],ctx.user_data['p'])"
    if needle2 in s:
        s = s.replace(needle2, needle2 + "\n    try: await xm_profile_ready(ctx,u['id'])\n    except Exception as e: print(f'[match] onboarding hook warning: {type(e).__name__}: {e}',flush=True)", 1)
    else:
        raise SystemExit('[build] exclusive matching: finish_profile hook not found')

# Register the exclusive-matching callback before the generic callback handler.
handler_anchor = "bot.add_handler(conv)"
if handler_anchor not in s:
    raise SystemExit('[build] exclusive matching: handler anchor not found')
s = s.replace(handler_anchor, handler_anchor + "\nbot.add_handler(CallbackQueryHandler(xm_callback,pattern=r'^xm:'))", 1)

# Start the lightweight maintenance queue with the Telegram application.
start_anchor = "await bot.initialize(); await bot.start()"
if start_anchor not in s:
    raise SystemExit('[build] exclusive matching: start_bot anchor not found')
s = s.replace(start_anchor, start_anchor + "; asyncio.create_task(xm_maintenance(bot.bot))", 1)

# Ensure DB tables are available before the bot starts.
main_anchor = "init_db(); threading.Thread(target=bot_thread,daemon=True).start()"
if main_anchor not in s:
    raise SystemExit('[build] exclusive matching: main startup anchor not found')
s = s.replace(main_anchor, "init_db(); xm_init_db(); threading.Thread(target=bot_thread,daemon=True).start()", 1)

# Add a simple admin view for queue health and conversion.
admin_anchor = "@app.get('/health')"
admin_block = r'''
@app.get('/admin/matches')
@need
def admin_matches():
    total=one('SELECT COUNT(*) c FROM match_offers')['c']
    offered=one("SELECT COUNT(*) c FROM match_offers WHERE status='offered'")['c']
    interested=one("SELECT COUNT(*) c FROM match_offers WHERE status='interested'")['c']
    accepted=one("SELECT COUNT(*) c FROM match_offers WHERE status='accepted'")['c']
    rs=many('''SELECT m.*,ps.name subject_name,pr.name recipient_name
               FROM match_offers m
               LEFT JOIN profiles ps ON ps.user_id=m.subject_user_id
               LEFT JOIN profiles pr ON pr.user_id=m.recipient_user_id
               ORDER BY m.id DESC LIMIT 100''')
    rows=''.join(
        f"<tr><td>{r['id']}</td><td>{html.escape(r['subject_name'] or '—')}</td><td>{html.escape(r['recipient_name'] or '—')}</td><td>{r['score']}%</td><td>{html.escape(r['status'])}</td><td>{html.escape(r['created_at'])}</td></tr>"
        for r in rs
    )
    body=(f"<h1>Знакомства</h1><div class='grid'>"
          f"<div class='card'><div class='muted'>Всего попыток</div><div class='big'>{total}</div></div>"
          f"<div class='card'><div class='muted'>Сейчас предложено</div><div class='big'>{offered}</div></div>"
          f"<div class='card'><div class='muted'>Ждут ответа второй стороны</div><div class='big'>{interested}</div></div>"
          f"<div class='card'><div class='muted'>Активные взаимные</div><div class='big'>{accepted}</div></div></div>"
          "<div class='card'><h3>Последние знакомства</h3><table><tr><th>ID</th><th>Анкета</th><th>Кому предложена</th><th>Совпадение</th><th>Статус</th><th>Создано</th></tr>"+rows+"</table></div>")
    return page(body)

'''
if admin_anchor in s:
    s = s.replace(admin_anchor, admin_block + admin_anchor, 1)

# Try to add the navigation link regardless of whether the expanded analytics nav is present.
for nav_piece in [
    "<a href='/admin/payments'>Оплаты</a>",
    "<a href='/admin/settings'>Настройки</a>",
]:
    if nav_piece in s and "href='/admin/matches'" not in s:
        s = s.replace(nav_piece, nav_piece + "<a href='/admin/matches'>Знакомства</a>", 1)
        break

p.write_text(s, encoding='utf-8')
print('[build] exclusive sequential matchmaking + free personalized copy applied', flush=True)
