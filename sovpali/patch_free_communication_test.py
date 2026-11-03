from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
anchor = "bot=Application.builder().token(TOKEN).build()"
if anchor not in s:
    raise SystemExit('[build] free-communication: bot anchor not found')

block = r'''
# --- Free communication test + professional compatibility explanation -------
# Payments are intentionally hidden during product validation. Users can send
# a real communication request and the second side explicitly accepts/declines.

def pc_num_pct(a, b):
    try:
        la, lb = lifepath(a['birth_date']), lifepath(b['birth_date'])
        if la == lb:
            return 96
        if abs(la-lb) in (1, 3):
            return 88
        if abs(la-lb) in (2, 4):
            return 79
        return 71
    except Exception:
        return 70


def pc_astro_pct(a, b):
    try:
        za, zb = zodiac(a['birth_date']), zodiac(b['birth_date'])
        ea, eb = ELEMENT[za], ELEMENT[zb]
        return 93 if eb in GOOD[ea] else 76
    except Exception:
        return 74


def pc_priority_pct(a, b):
    return 97 if str(a['priority']) == str(b['priority']) else 72


def pc_goal_pct(a, b):
    return 98 if str(a['goal']) == str(b['goal']) else 62


def pc_num_copy(a, b):
    try:
        la, lb = lifepath(a['birth_date']), lifepath(b['birth_date'])
        pct = pc_num_pct(a, b)
        if la == lb:
            body = 'Числа жизненного пути совпадают. В нашей модели это означает похожий темп решений, эмоциональных реакций и жизненных приоритетов.'
        elif abs(la-lb) in (1, 3):
            body = 'Числа жизненного пути разные, но хорошо дополняют друг друга: один ритм добавляет движение, второй — баланс.'
        elif abs(la-lb) in (2, 4):
            body = 'Нумерологические ритмы не одинаковые, но совместимы: различия скорее дополняют, чем конфликтуют.'
        else:
            body = 'Нумерологические ритмы заметно различаются. Это не минус само по себе, но здесь важнее совпадение целей и ценностей.'
        return f'🔢 <b>Нумерология — {pct}%</b>\nЧисла жизненного пути: <b>{la}</b> и <b>{lb}</b>. {body}'
    except Exception:
        return '🔢 <b>Нумерология</b>\nНедостаточно данных для уверенного расчёта.'


def pc_astro_copy(a, b):
    try:
        za, zb = zodiac(a['birth_date']), zodiac(b['birth_date'])
        ea, eb = ELEMENT[za], ELEMENT[zb]
        pct = pc_astro_pct(a, b)
        if eb in GOOD[ea]:
            body = f'Связка <b>{html.escape(ea)} + {html.escape(eb)}</b> считается гармоничной в нашей астрологической модели: темпераменты легче поддерживают друг друга.'
        else:
            body = f'Связка <b>{html.escape(ea)} + {html.escape(eb)}</b> контрастная: притяжение возможно, но больше зависит от целей, ценностей и способа общения.'
        return (f'✨ <b>Базовый натальный слой — {pct}%</b>\n'
                f'{html.escape(za)} ({html.escape(ea)}) + {html.escape(zb)} ({html.escape(eb)}). {body}\n'
                '<i>Расчёт по дате рождения; без точного времени мы не заявляем дома, Асцендент и аспекты как полноценную натальную карту.</i>')
    except Exception:
        return '✨ <b>Базовый натальный слой</b>\nНедостаточно данных для расчёта.'


def pc_priority_copy(a, b):
    pr = str(a['priority'] or '').strip()
    pct = pc_priority_pct(a, b)
    same = str(a['priority']) == str(b['priority'])
    if same:
        bodies = {
            'Страсть': 'Вы оба поставили на первое место химию, притяжение и эмоциональную интенсивность. Это сильный сигнал именно по тому критерию, который ты выбрал сам.',
            'Семья': 'Вы оба ставите семью и долгосрочную устойчивость выше случайного знакомства. Намерение строить отношения совпадает.',
            'Любовь': 'Для вас обоих важна эмоциональная близость и ощущение настоящих чувств, а не только удобство или формальный статус.',
            'Ценности': 'Вы оба считаете совпадение взглядов и внутренних ориентиров главным фундаментом отношений.',
            'Опора': 'Вы оба ищете надёжность, спокойствие и человека, на которого можно опереться.'
        }
        body = bodies.get(pr, 'Ваш главный критерий отношений совпадает — это один из самых весомых факторов модели.')
    else:
        body = f'Для тебя главное — «{html.escape(pr)}», а у второго человека приоритет другой. Поэтому этот блок снижает итоговый балл и требует больше внимания при знакомстве.'
    return f'💎 <b>Главный критерий — {pct}%</b>\n{body}'


def pc_goal_copy(a, b):
    pct = pc_goal_pct(a, b)
    if str(a['goal']) == str(b['goal']):
        return f'🎯 <b>Цель отношений — {pct}%</b>\nВы оба выбрали: <b>{html.escape(str(a["goal"]))}</b>. Это важнее случайной симпатии: вы изначально ищете похожий формат отношений.'
    return (f'🎯 <b>Цель отношений — {pct}%</b>\n'
            f'Твоя цель: <b>{html.escape(str(a["goal"]))}</b>. У второго человека: <b>{html.escape(str(b["goal"]))}</b>. Здесь есть расхождение намерений.')


def pc_location_copy(a, b):
    same_city = str(a['city']).strip().lower().replace('ё','е') == str(b['city']).strip().lower().replace('ё','е')
    if same_city:
        return f'📍 <b>Встреча рядом</b>\\nВы оба указали <b>{html.escape(str(a["city"]))}</b>. Жить в одном городе — приятный дополнительный плюс к знакомству.'
    # Do not invent a shared regional hub or frame long-distance as a defect.
    # Actual cities remain visible in each profile.
    return ''


def pc_match_analysis(a, b, score_value=None):
    total = int(score_value if score_value is not None else score(a, b))
    if total >= 94:
        verdict = 'Система видит очень сильное сочетание сразу по нескольким независимым слоям. Это не один случайный признак, а сумма намерений, главного критерия, астрологического и нумерологического профиля.'
    elif total >= 86:
        verdict = 'Совпадение сильное: основные отношения и дополнительные расчётные слои поддерживают друг друга.'
    else:
        verdict = 'Совместимость заметная, но есть параметры, которые лучше проверить уже в живом общении.'
    return (pc_goal_copy(a,b) + '\n\n' +
            pc_priority_copy(a,b) + '\n\n' +
            pc_astro_copy(a,b) + '\n\n' +
            pc_num_copy(a,b) + '\n\n' +
            pc_location_copy(a,b) + '\n\n' +
            f'🧩 <b>Итог модели — {total}%</b>\n{verdict}')


# Make every existing personalization surface use the professional breakdown.
def pn_match_block(viewer, candidate):
    return pc_match_analysis(viewer, candidate)


def xm_personal_copy(viewer, candidate, score_value):
    age = xm_age(candidate['birth_date'])
    name_age = html.escape(candidate['name']) + (f', {age}' if age else '')
    lead = 'Очень сильное совпадение' if score_value >= 92 else ('Сильное совпадение' if score_value >= 86 else 'Совпадение')
    return (f'💖 <b>{lead} · {score_value}%</b>\n\n'
            f'<b>{name_age}</b> · {html.escape(candidate["city"])}\n\n'
            'Система поставила эту анкету высоко не из-за одного признака. Вот из чего складывается расчёт:\n\n'
            f'{pc_match_analysis(viewer, candidate, score_value)}\n\n'
            'Если человек тебе откликается, можно предложить общение — без оплаты.')


def xm_interest_copy(subject, interested, score_value):
    age = xm_age(interested['birth_date'])
    name_age = html.escape(interested['name']) + (f', {age}' if age else '')
    return (f'💌 <b>{name_age} предлагает начать общение</b>\n\n'
            f'Совместимость по нашей модели: <b>{score_value}%</b>\n\n'
            f'{pc_match_analysis(subject, interested, score_value)}\n\n'
            'Если тебе тоже интересно — подтверди. Контакт откроется только после взаимного согласия.')


# Free communication request storage.
_pc_old_init_db = init_db
def init_db():
    _pc_old_init_db()
    with db() as c:
        if USE_POSTGRES:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS communication_requests(
                id BIGSERIAL PRIMARY KEY,
                pair_low BIGINT NOT NULL,
                pair_high BIGINT NOT NULL,
                requester_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                target_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                score INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                responded_at TEXT,
                UNIQUE(pair_low,pair_high)
            );
            CREATE INDEX IF NOT EXISTS idx_communication_requests_requester ON communication_requests(requester_user_id);
            CREATE INDEX IF NOT EXISTS idx_communication_requests_target ON communication_requests(target_user_id);
            CREATE INDEX IF NOT EXISTS idx_communication_requests_status ON communication_requests(status);
            """)
        else:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS communication_requests(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair_low INTEGER NOT NULL,
                pair_high INTEGER NOT NULL,
                requester_user_id INTEGER NOT NULL,
                target_user_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                responded_at TEXT,
                UNIQUE(pair_low,pair_high)
            );
            CREATE INDEX IF NOT EXISTS idx_communication_requests_requester ON communication_requests(requester_user_id);
            CREATE INDEX IF NOT EXISTS idx_communication_requests_target ON communication_requests(target_user_id);
            CREATE INDEX IF NOT EXISTS idx_communication_requests_status ON communication_requests(status);
            """)
    try:
        set_setting('payments_live','0')
    except Exception:
        pass


def cr_between(a, b):
    lo, hi = sorted((int(a), int(b)))
    return one('SELECT * FROM communication_requests WHERE pair_low=? AND pair_high=? ORDER BY id DESC LIMIT 1', (lo,hi))


def cr_contact(uid):
    u = user(uid); p = profile(uid)
    if not u or not p:
        return ''
    name = html.escape(str(p['name']))
    return f'<a href="tg://user?id={int(u["tg_id"])}">{name}</a>'


async def cr_send_request(ctx, requester_uid, target_uid, score_value):
    requester_uid, target_uid = int(requester_uid), int(target_uid)
    existing = cr_between(requester_uid, target_uid)
    if existing:
        if str(existing['status']) == 'pending':
            return 'pending', int(existing['id'])
        if str(existing['status']) == 'accepted':
            return 'accepted', int(existing['id'])
        execute('DELETE FROM communication_requests WHERE id=?', (int(existing['id']),))
    lo, hi = sorted((requester_uid, target_uid))
    with db() as c:
        cur = c.execute('''INSERT INTO communication_requests(pair_low,pair_high,requester_user_id,target_user_id,score,status,created_at)
                           VALUES(?,?,?,?,?,'pending',?) RETURNING id''',
                        (lo,hi,requester_uid,target_uid,int(score_value),now()))
        req_id = int(cur.fetchone()['id'])
    requester = profile(requester_uid); target = profile(target_uid); tg_target = user(target_uid)
    if not requester or not target or not tg_target:
        return 'failed', req_id
    age = xm_age(requester['birth_date'])
    title = html.escape(requester['name']) + (f', {age}' if age else '')
    text = (f'💌 <b>{title} предлагает начать общение</b>\n\n'
            f'Совместимость: <b>{int(score_value)}%</b>\n\n'
            f'{pc_match_analysis(target, requester, int(score_value))}\n\n'
            'Это бесплатный запрос. Ничего не откроется без твоего решения.')
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton('💬 Да, хочу общаться', callback_data=f'cr:accept:{req_id}'),
        InlineKeyboardButton('Не сейчас', callback_data=f'cr:decline:{req_id}')
    ]])
    if requester['photo_file_id']:
        await ctx.bot.send_photo(tg_target['tg_id'], requester['photo_file_id'], caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await ctx.bot.send_message(tg_target['tg_id'], text, parse_mode=ParseMode.HTML, reply_markup=kb)
    try: audit(requester_uid,'communication_request_sent',{'request_id':req_id,'target_user_id':target_uid,'score':int(score_value)})
    except Exception: pass
    return 'sent', req_id


async def cr_callback(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = upsert_user(update.effective_user)
    try:
        _, action, raw = q.data.split(':',2); req_id = int(raw)
    except Exception:
        return
    row = one('SELECT * FROM communication_requests WHERE id=?',(req_id,))
    if not row:
        await q.message.reply_text('Этот запрос уже недоступен.')
        return
    if int(row['target_user_id']) != int(u['id']):
        return
    if str(row['status']) != 'pending':
        await q.message.reply_text('На этот запрос уже был дан ответ.')
        return
    requester_uid = int(row['requester_user_id']); target_uid = int(row['target_user_id'])
    requester = profile(requester_uid); target = profile(target_uid)
    if action == 'decline':
        execute("UPDATE communication_requests SET status='declined',responded_at=? WHERE id=?",(now(),req_id))
        try: await q.edit_message_reply_markup(reply_markup=None)
        except Exception: pass
        await q.message.reply_text('Хорошо. Запрос отклонён — контакт не раскрывался.')
        try: audit(target_uid,'communication_request_declined',{'request_id':req_id,'requester_user_id':requester_uid})
        except Exception: pass
        return
    if action == 'accept':
        execute("UPDATE communication_requests SET status='accepted',responded_at=? WHERE id=?",(now(),req_id))
        try: await q.edit_message_reply_markup(reply_markup=None)
        except Exception: pass
        requester_link = cr_contact(requester_uid); target_link = cr_contact(target_uid)
        await q.message.reply_text(
            f'💞 <b>Взаимный интерес!</b>\n\n{requester_link} тоже хочет общаться. Нажми на имя, чтобы открыть Telegram.',
            parse_mode=ParseMode.HTML,
        )
        ru = user(requester_uid)
        if ru:
            await ctx.bot.send_message(
                ru['tg_id'],
                f'💞 <b>{html.escape(target["name"])} принял(а) твой запрос</b>\n\n{target_link} — нажми на имя, чтобы открыть Telegram и написать.',
                parse_mode=ParseMode.HTML,
            )
        try:
            audit(target_uid,'communication_request_accepted',{'request_id':req_id,'requester_user_id':requester_uid})
            audit(requester_uid,'communication_request_mutual',{'request_id':req_id,'target_user_id':target_uid})
        except Exception: pass
        return


# Professional My Pair card, no payment language.
def mp_card_text(viewer, candidate, score_value, rank=None):
    age = xm_age(candidate['birth_date'])
    name_age = html.escape(candidate['name']) + (f', {age}' if age else '')
    rank_line = f'ТОП-{rank} · ' if rank else ''
    return (f'💖 <b>{rank_line}{score_value}% совместимости</b>\n\n'
            f'<b>{name_age}</b> · {html.escape(candidate["city"])}\n\n'
            f'{pc_match_analysis(viewer, candidate, score_value)}\n\n'
            'Хочешь проверить совпадение в реальном общении? Отправь бесплатный запрос — второй человек сам решит, отвечать или нет.')


async def mp_callback(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = upsert_user(update.effective_user)
    viewer = profile(u['id'])
    if not viewer:
        await q.message.reply_text('Сначала заполни профиль — нажми /start.')
        return
    try:
        _, action, raw = q.data.split(':', 2)
    except Exception:
        return
    if action == 'refresh':
        await mp_show_top3(q.message, u, viewer); return
    try: cid = int(raw)
    except Exception: return
    candidate = profile(cid)
    if not candidate or not eligible(viewer,candidate):
        # City is never a hard limit: the public pairing is nationwide.
        await q.message.reply_text('Эта анкета уже недоступна. Обновляю подбор.')
        await mp_show_top3(q.message,u,viewer); return
    # Old Telegram cards retain their inline callbacks. Never start the
    # introduction from Telegram: direct users to the full website instead.
    if action in ('view','connect','buy'):
        url=pair_link(PAIR_WEB_BASE_URL,int(u['id']),cid,FLASK_SECRET)
        if not url:
            await q.message.reply_text('Страница пары временно недоступна. Попробуй позже.')
            return
        await q.message.reply_text(
            '✨ Открой совместимость на сайте, прочитай разбор и затем нажми '
            '«Предложить общение». Второй человек получит личный запрос в Telegram.',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton('💞 Читать совместимость',url=url)
            ]]))
        return
    found = {int(c['user_id']):(sv,c) for sv,c in mp_candidates(int(u['id']),3)}
    if action == 'view':
        if cid not in found:
            await q.message.reply_text('Анкета сейчас недоступна для нового знакомства. Покажу актуальный ТОП-3.')
            await mp_show_top3(q.message,u,viewer); return
        sv,candidate = found[cid]
        cr = cr_between(int(u['id']),cid)
        xm = mp_active_offer_between(int(u['id']),cid)
        if cr and str(cr['status']) == 'accepted':
            main = InlineKeyboardButton('💞 Общение подтверждено', callback_data=f'mp:status:{cid}')
        elif cr and str(cr['status']) == 'pending':
            if int(cr['requester_user_id']) == int(u['id']):
                main = InlineKeyboardButton('⏳ Запрос уже отправлен', callback_data=f'mp:status:{cid}')
            else:
                main = InlineKeyboardButton('💌 Ответить на запрос', callback_data=f'cr:accept:{int(cr["id"])}')
        elif xm and str(xm['status']) == 'interested' and int(xm['subject_user_id']) == int(u['id']):
            main = InlineKeyboardButton('💬 Подтвердить общение', callback_data=f'xm:accept:{int(xm["id"])}')
        elif xm and str(xm['status']) == 'interested':
            main = InlineKeyboardButton('⏳ Ждём ответ', callback_data=f'mp:status:{cid}')
        elif xm and str(xm['status']) == 'offered' and int(xm['recipient_user_id']) == int(u['id']):
            main = InlineKeyboardButton('💬 Предложить общение', callback_data=f'xm:interest:{int(xm["id"])}')
        elif xm and str(xm['status']) == 'accepted':
            main = InlineKeyboardButton('💞 Взаимный интерес', callback_data=f'mp:status:{cid}')
        else:
            main = InlineKeyboardButton('💬 Предложить общение', callback_data=f'mp:connect:{cid}')
        kb=InlineKeyboardMarkup([[main],[InlineKeyboardButton('← К ТОП-3',callback_data='mp:refresh:0')]])
        text=mp_card_text(viewer,candidate,sv)
        try: audit(int(u['id']),'my_pair_candidate_open',{'candidate_user_id':cid,'score':sv})
        except Exception: pass
        if candidate['photo_file_id']:
            await q.message.reply_photo(candidate['photo_file_id'],caption=text,parse_mode=ParseMode.HTML,reply_markup=kb)
        else:
            await q.message.reply_text(text,parse_mode=ParseMode.HTML,reply_markup=kb)
        return
    if action in ('connect','buy'):
        # Old already-sent payment buttons are treated as a free communication request.
        if cid not in found:
            await q.message.reply_text('Анкета уже вышла из актуального ТОП-3. Обновляю подбор.')
            await mp_show_top3(q.message,u,viewer); return
        sv,candidate = found[cid]
        state, req_id = await cr_send_request(ctx,int(u['id']),cid,sv)
        if state == 'sent':
            await q.message.reply_text(f'💌 Запрос отправлен {html.escape(candidate["name"])}. Теперь решение за второй стороной.',parse_mode=ParseMode.HTML)
        elif state == 'pending':
            await q.message.reply_text('⏳ Запрос уже отправлен. Ждём ответ второй стороны.')
        elif state == 'accepted':
            await q.message.reply_text('💞 Вы уже подтвердили взаимный интерес.')
        else:
            await q.message.reply_text('Не получилось отправить запрос. Попробуй ещё раз чуть позже.')
        return
    if action == 'status':
        cr=cr_between(int(u['id']),cid)
        if cr:
            st=str(cr['status'])
            if st=='pending': await q.message.reply_text('⏳ Запрос на общение отправлен. Ждём ответ.')
            elif st=='accepted': await q.message.reply_text('💞 Общение уже подтверждено с обеих сторон.')
            else: await q.message.reply_text('Этот запрос завершён. Можно обновить подбор.')
            return
        xm=mp_active_offer_between(int(u['id']),cid)
        if xm:
            st=str(xm['status'])
            if st=='offered': await q.message.reply_text('⏳ Совпадение активно. Можно предложить общение.')
            elif st=='interested': await q.message.reply_text('❤️ Один человек уже проявил интерес. Ждём второй ответ.')
            else: await q.message.reply_text('💞 У вас взаимный интерес.')
            return
        await q.message.reply_text('Активного запроса по этой паре сейчас нет.')
        return
# ---------------------------------------------------------------------------
'''

s = s.replace(anchor, block + anchor, 1)
handler = "bot.add_handler(CallbackQueryHandler(mp_callback,pattern=r'^mp:'))\n"
if handler in s and "pattern=r'^cr:'" not in s:
    s = s.replace(handler, handler + "bot.add_handler(CallbackQueryHandler(cr_callback,pattern=r'^cr:'))\n", 1)

# Remove payment wording from the automatic mutual-interest flow as well.
s = s.replace(
    'Совпадение закреплено за вами двумя. Контакт не раскрывается автоматически — это оставляет нам безопасный шаг для платного открытия контакта.',
    'Совпадение подтверждено с обеих сторон. Теперь можно переходить к общению.'
)
s = s.replace(
    'Вторая сторона тоже хочет познакомиться. Совпадение закреплено за вами двумя.',
    'Вторая сторона тоже хочет общаться. Совпадение подтверждено с обеих сторон.'
)

p.write_text(s, encoding='utf-8')
print('[build] free communication requests + professional compatibility analysis applied', flush=True)
