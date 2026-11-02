from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
anchor = "bot=Application.builder().token(TOKEN).build()"
if anchor not in s:
    raise SystemExit('[build] my-pair: bot anchor not found')

block = r"""
# --- My Pair: user-initiated top-3 browser ----------------------------------
def mp_candidates(uid, limit=3):
    viewer = profile(uid)
    if not viewer:
        return []
    rows = many('''SELECT p.*,u.tg_id,u.username,u.is_banned
                   FROM profiles p JOIN users u ON u.id=p.user_id
                   WHERE p.user_id<>? AND u.is_banned=0''', (uid,))
    strict, fallback = [], []
    for c in rows:
        try:
            if not eligible(viewer, c):
                continue
            if not xm_same_hub(viewer['city'], c['city']):
                continue
            if xm_busy(c['user_id']):
                continue
            if xm_pair_seen(uid, c['user_id']):
                continue
            sv = int(score(viewer, c))
            item = (sv, c)
            if viewer['goal'] == c['goal']:
                strict.append(item)
            else:
                fallback.append(item)
        except Exception as exc:
            print(f'[my-pair] candidate skipped: {type(exc).__name__}: {exc}', flush=True)
    strict.sort(key=lambda x: x[0], reverse=True)
    fallback.sort(key=lambda x: x[0], reverse=True)
    return (strict + fallback)[:limit]


def mp_card_text(viewer, candidate, score_value, rank=None):
    age = xm_age(candidate['birth_date'])
    name_age = html.escape(candidate['name']) + (f', {age}' if age else '')
    rank_line = f'ТОП-{rank} твоего подбора · ' if rank else ''
    return (
        f'💖 <b>{rank_line}{score_value}% совместимости</b>\n\n'
        f'<b>{name_age}</b> · {html.escape(candidate["city"])}\n'
        f'Цель: {html.escape(candidate["goal"])}\n\n'
        f'{pn_match_block(viewer, candidate)}\n\n'
        'Если человек тебе откликается, можно сразу открыть знакомство. '
        'После оплаты второй стороне уйдёт приоритетный запрос; контакт откроется только после взаимного согласия.'
    )


async def mp_show_top3(message, u, p):
    found = mp_candidates(int(u['id']), 3)
    if not found:
        await message.reply_text(
            '💖 <b>Моя пара</b>\n\nСейчас в твоём городе нет свободных подходящих анкет для ТОП-3. '
            'Я продолжу искать автоматически и сообщу, когда появится сильное совпадение.',
            parse_mode=ParseMode.HTML,
            reply_markup=MENU,
        )
        return
    lines = ['💖 <b>Моя пара · твой ТОП-3</b>', '', 'Выбери человека — покажу подробный разбор совместимости:']
    buttons = []
    for idx, (sv, c) in enumerate(found, 1):
        age = xm_age(c['birth_date'])
        label = html.escape(c['name']) + (f', {age}' if age else '')
        lines.append(f'{idx}. <b>{label}</b> — {sv}%')
        buttons.append([InlineKeyboardButton(f'{idx}. {c["name"]} · {sv}%', callback_data=f'mp:view:{c["user_id"]}')])
    buttons.append([InlineKeyboardButton('🔄 Обновить подбор', callback_data='mp:refresh:0')])
    try:
        audit(int(u['id']), 'my_pair_top3_view', {'count': len(found), 'candidates': [int(c['user_id']) for _, c in found]})
    except Exception:
        pass
    await message.reply_text('\n'.join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


_mp_old_cabinet = cabinet
async def cabinet(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or '').strip() if update.effective_message else ''
    if text in ('💖 Моя пара', '💖 Мои пары'):
        u = upsert_user(update.effective_user)
        p = profile(u['id'])
        if not p:
            await update.effective_message.reply_text('Сначала создай профиль — нажми /start', reply_markup=ReplyKeyboardRemove())
            return
        await mp_show_top3(update.effective_message, u, p)
        return
    return await _mp_old_cabinet(update, ctx)


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
        await mp_show_top3(q.message, u, viewer)
        return
    try:
        cid = int(raw)
    except Exception:
        return
    candidate = profile(cid)
    if not candidate or not eligible(viewer, candidate) or not xm_same_hub(viewer['city'], candidate['city']):
        await q.message.reply_text('Эта анкета уже недоступна. Обновляю подбор.')
        await mp_show_top3(q.message, u, viewer)
        return

    current = {int(c['user_id']): (sv, c) for sv, c in mp_candidates(int(u['id']), 3)}
    if action == 'view':
        if cid not in current:
            await q.message.reply_text('Эта анкета уже занята другим активным знакомством. Покажу актуальный ТОП-3.')
            await mp_show_top3(q.message, u, viewer)
            return
        sv, candidate = current[cid]
        price = int(setting('unlock_price_rub', '100') or 100)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f'❤️ Открыть знакомство · {price} ₽', callback_data=f'mp:buy:{cid}')],
            [InlineKeyboardButton('← К ТОП-3', callback_data='mp:refresh:0')],
        ])
        text = mp_card_text(viewer, candidate, sv)
        try:
            audit(int(u['id']), 'my_pair_candidate_open', {'candidate_user_id': cid, 'score': sv})
        except Exception:
            pass
        if candidate['photo_file_id']:
            await q.message.reply_photo(candidate['photo_file_id'], caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if action == 'buy':
        if xm_busy(int(u['id'])):
            await q.message.reply_text('У тебя уже есть активное знакомство. Сначала заверши его, чтобы не вести несколько эксклюзивных знакомств одновременно.')
            return
        if xm_busy(cid):
            await q.message.reply_text('Эту анкету уже выбрали для другого активного знакомства. Деньги не списывались — обновляю подбор.')
            await mp_show_top3(q.message, u, viewer)
            return
        found = mp_candidates(int(u['id']), 3)
        by_id = {int(c['user_id']): (sv, c) for sv, c in found}
        if cid not in by_id:
            await q.message.reply_text('Анкета уже вышла из актуального ТОП-3. Деньги не списывались — обновляю подбор.')
            await mp_show_top3(q.message, u, viewer)
            return
        sv, candidate = by_id[cid]
        price = int(setting('unlock_price_rub', '100') or 100)
        created = now()
        intent_id = f'my-pair-{int(u["id"])}-{cid}-{int(datetime.utcnow().timestamp())}'
        try:
            execute('''INSERT INTO payments(user_id,provider,provider_payment_id,product,amount_rub,status,created_at,paid_at)
                       VALUES(?,?,?,?,?,?,?,NULL)''',
                    (int(u['id']), 'prodamus', intent_id, f'my_pair_intro:{cid}', price, 'intent', created))
        except Exception as exc:
            print(f'[my-pair] payment intent warning: {type(exc).__name__}: {exc}', flush=True)
        try:
            audit(int(u['id']), 'my_pair_buy_click', {'candidate_user_id': cid, 'score': sv, 'price_rub': price})
        except Exception:
            pass
        if setting('payments_live', '0') != '1':
            await q.message.reply_text(
                f'💳 <b>Открыть знакомство с {html.escape(candidate["name"])}</b> · {price} ₽\n\n'
                'Покупка уже учитывается в воронке, но платёжный шлюз пока не включён, поэтому <b>деньги не списаны</b>. '
                'После подключения Prodamus эта же кнопка будет сразу переводить к оплате.',
                parse_mode=ParseMode.HTML,
            )
            return
        await q.message.reply_text('Платёжный режим включён, но ссылка провайдера для этого продукта ещё не настроена. Деньги не списаны.')
        return
# ---------------------------------------------------------------------------

"""

s = s.replace(anchor, block + anchor, 1)
s = s.replace("KeyboardButton('💖 Мои пары')", "KeyboardButton('💖 Моя пара')")
s = s.replace('Открой «Мои пары»', 'Открой «Моя пара»')

handler_anchor = "bot.add_handler(conv)\n"
if handler_anchor not in s:
    raise SystemExit('[build] my-pair: handler anchor not found')
s = s.replace(
    handler_anchor,
    handler_anchor
    + "bot.add_handler(CallbackQueryHandler(mp_callback,pattern=r'^mp:'))\n"
    + "bot.add_handler(MessageHandler(filters.Regex(r'^(💖 Моя пара|💖 Мои пары)$'),cabinet))\n",
    1,
)

p.write_text(s, encoding='utf-8')
print('[build] My Pair top-3 browser + purchase intent applied', flush=True)
