from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
anchor = "bot=Application.builder().token(TOKEN).build()"
if anchor not in s:
    raise SystemExit('[build] initiator-only-contact: bot anchor not found')

block = r'''
# --- Initiator-only contact handoff -----------------------------------------
def ioc_name(uid):
    p = profile(int(uid))
    u = user(int(uid))
    return html.escape(str((p['name'] if p else None) or (u['first_name'] if u else None) or 'человека'))


def ioc_contact_keyboard(uid):
    url = ar_contact_url(int(uid)) if 'ar_contact_url' in globals() else ''
    if not url:
        u = user(int(uid))
        if u:
            username = str(u['username'] or '').strip().lstrip('@')
            url = ('https://t.me/' + username) if username else f'tg://user?id={int(u["tg_id"])}'
    if not url:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton('💬 Написать в Telegram', url=url)]])
# ---------------------------------------------------------------------------

'''
s = s.replace(anchor, block + anchor, 1)

# Manual communication request: accepter gets only confirmation; requester gets contact button.
old_cr = """        requester_link = cr_contact(requester_uid); target_link = cr_contact(target_uid)\n        await q.message.reply_text(\n            f'💞 <b>Взаимный интерес!</b>\\n\\n{requester_link} тоже хочет общаться. Нажми на имя, чтобы открыть Telegram.',\n            parse_mode=ParseMode.HTML,\n        )\n        ru = user(requester_uid)\n        if ru:\n            await ctx.bot.send_message(\n                ru['tg_id'],\n                f'💞 <b>{html.escape(target[\"name\"])} принял(а) твой запрос</b>\\n\\n{target_link} — нажми на имя, чтобы открыть Telegram и написать.',\n                parse_mode=ParseMode.HTML,\n            )\n"""
new_cr = """        await q.message.reply_text(\n            f'💞 <b>Готово!</b>\\n\\nМы сообщили {ioc_name(requester_uid)}, что ты согласился(ась) на знакомство. Контакт открыт только ему — жди от него сообщения в Telegram 🙂',\n            parse_mode=ParseMode.HTML,\n        )\n        ru = user(requester_uid)\n        if ru:\n            await ctx.bot.send_message(\n                ru['tg_id'],\n                f'💞 <b>{html.escape(target[\"name\"])} принял(а) твой запрос</b>\\n\\nТеперь можешь написать первым.',\n                parse_mode=ParseMode.HTML,\n                reply_markup=ioc_contact_keyboard(target_uid),\n            )\n"""
if old_cr not in s:
    raise SystemExit('[build] initiator-only-contact: communication accept block not found')
s = s.replace(old_cr, new_cr, 1)

# Exclusive automatic match: subject is the accepter, recipient is the original initiator.
old_subject = "await q.message.reply_text(f'💞 <b>Взаимный интерес!</b>\\n\\n{ar_contact_link(recipient_uid)} тоже хочет общаться. Нажми на контакт или кнопку ниже и напиши прямо в Telegram.', parse_mode=ParseMode.HTML, reply_markup=ar_contact_keyboard(recipient_uid, offer_id))"
new_subject = "await q.message.reply_text(f'💞 <b>Готово!</b>\\n\\nМы сообщили {ioc_name(recipient_uid)}, что ты согласился(ась) на знакомство. Контакт открыт только ему — жди от него сообщения в Telegram 🙂', parse_mode=ParseMode.HTML)"
if old_subject not in s:
    raise SystemExit('[build] initiator-only-contact: exclusive accepter block not found')
s = s.replace(old_subject, new_subject, 1)

old_initiator = "await ctx.bot.send_message(other['tg_id'], f'💞 <b>Взаимный интерес!</b>\\n\\n{ar_contact_link(subject_uid)} тоже хочет общаться. Нажми на контакт или кнопку ниже и напиши прямо в Telegram.', parse_mode=ParseMode.HTML, reply_markup=ar_contact_keyboard(subject_uid, offer_id))"
new_initiator = "await ctx.bot.send_message(other['tg_id'], f'💞 <b>{ioc_name(subject_uid)} согласился(ась) на знакомство</b>\\n\\nТеперь можешь написать первым.', parse_mode=ParseMode.HTML, reply_markup=ar_contact_keyboard(subject_uid, offer_id))"
if old_initiator not in s:
    raise SystemExit('[build] initiator-only-contact: exclusive initiator block not found')
s = s.replace(old_initiator, new_initiator, 1)

p.write_text(s, encoding='utf-8')
print('[build] initiator-only contact handoff applied', flush=True)
