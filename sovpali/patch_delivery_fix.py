from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
anchor = "bot=Application.builder().token(TOKEN).build()"
if anchor not in s:
    raise SystemExit('[build] delivery-fix: bot anchor not found')

# Telegram photo captions are limited. Detailed compatibility analysis is sent
# as a separate text message after a short photo card.
s = s.replace(
"""    if candidate['photo_file_id']:\n        await bot_api.send_photo(target['tg_id'], candidate['photo_file_id'], caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)\n    else:\n        await bot_api.send_message(target['tg_id'], text, parse_mode=ParseMode.HTML, reply_markup=kb)\n""",
"""    if candidate['photo_file_id']:\n        await bot_api.send_photo(target['tg_id'], candidate['photo_file_id'], caption=f'💖 {html.escape(candidate[\"name\"])} · {score_value}% совместимости', parse_mode=ParseMode.HTML)\n    await bot_api.send_message(target['tg_id'], text, parse_mode=ParseMode.HTML, reply_markup=kb)\n""",
1)

s = s.replace(
"""            if recipient['photo_file_id']:\n                await ctx.bot.send_photo(target['tg_id'], recipient['photo_file_id'], caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)\n            else:\n                await ctx.bot.send_message(target['tg_id'], text, parse_mode=ParseMode.HTML, reply_markup=kb)\n""",
"""            if recipient['photo_file_id']:\n                await ctx.bot.send_photo(target['tg_id'], recipient['photo_file_id'], caption=f'💌 {html.escape(recipient[\"name\"])} · {int(row[\"score\"])}% совместимости', parse_mode=ParseMode.HTML)\n            await ctx.bot.send_message(target['tg_id'], text, parse_mode=ParseMode.HTML, reply_markup=kb)\n""",
1)

# My Pair detailed card: photo first, analysis second.
s = s.replace(
"""        if candidate['photo_file_id']:\n            await q.message.reply_photo(candidate['photo_file_id'],caption=text,parse_mode=ParseMode.HTML,reply_markup=kb)\n        else:\n            await q.message.reply_text(text,parse_mode=ParseMode.HTML,reply_markup=kb)\n""",
"""        if candidate['photo_file_id']:\n            await q.message.reply_photo(candidate['photo_file_id'],caption=f'💖 {html.escape(candidate[\"name\"])} · {sv}% совместимости',parse_mode=ParseMode.HTML)\n        await q.message.reply_text(text,parse_mode=ParseMode.HTML,reply_markup=kb)\n""",
1)

block = r'''
# --- Delivery reliability fix -----------------------------------------------
async def cr_send_request(ctx, requester_uid, target_uid, score_value):
    requester_uid, target_uid = int(requester_uid), int(target_uid)
    existing = cr_between(requester_uid, target_uid)
    req_id = None
    if existing:
        st = str(existing['status'])
        if st == 'accepted':
            return 'accepted', int(existing['id'])
        if st == 'pending':
            # A previous Telegram delivery may have failed after the DB row was
            # created. Reuse the same request and try delivery again.
            req_id = int(existing['id'])
        else:
            execute('DELETE FROM communication_requests WHERE id=?', (int(existing['id']),))
    if req_id is None:
        lo, hi = sorted((requester_uid, target_uid))
        with db() as c:
            cur = c.execute("INSERT INTO communication_requests(pair_low,pair_high,requester_user_id,target_user_id,score,status,created_at) VALUES(?,?,?,?,?,'pending',?) RETURNING id",
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
    try:
        if requester['photo_file_id']:
            await ctx.bot.send_photo(
                tg_target['tg_id'], requester['photo_file_id'],
                caption=f'💌 {title} · {int(score_value)}% совместимости',
                parse_mode=ParseMode.HTML,
            )
        await ctx.bot.send_message(tg_target['tg_id'], text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception as exc:
        print(f'[communication] delivery failed request={req_id}: {type(exc).__name__}: {exc}', flush=True)
        return 'failed', req_id
    try:
        audit(requester_uid,'communication_request_sent',{'request_id':req_id,'target_user_id':target_uid,'score':int(score_value)})
    except Exception:
        pass
    return 'sent', req_id
# ---------------------------------------------------------------------------

'''

s = s.replace(anchor, block + anchor, 1)
p.write_text(s, encoding='utf-8')
print('[build] Telegram long-caption split + pending request retry applied', flush=True)
