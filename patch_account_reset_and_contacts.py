from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# We need private-chat block/unblock updates from Telegram.
s = s.replace(
    'from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters',
    'from telegram.ext import Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters',
    1,
)

anchor = "bot=Application.builder().token(TOKEN).build()"
if anchor not in s:
    raise SystemExit('[build] account-reset: bot anchor not found')

block = r"""
# --- Account reset on bot stop + direct mutual-contact handoff --------------
def ar_contact_url(uid):
    u = user(int(uid))
    if not u:
        return ''
    username = str(u['username'] or '').strip().lstrip('@')
    if username:
        return 'https://t.me/' + username
    return f'tg://user?id={int(u["tg_id"])}'


def ar_contact_link(uid):
    u = user(int(uid)); p = profile(int(uid))
    if not u:
        return ''
    label = html.escape(str((p['name'] if p else None) or u['first_name'] or 'Открыть Telegram'))
    username = str(u['username'] or '').strip().lstrip('@')
    if username:
        safe_username = html.escape(username)
        return f'<a href="https://t.me/{safe_username}">@{safe_username}</a>'
    return f'<a href="tg://user?id={int(u["tg_id"])}">{label}</a>'


def ar_contact_keyboard(other_uid, offer_id):
    url = ar_contact_url(other_uid)
    rows = []
    if url:
        rows.append([InlineKeyboardButton('💬 Написать в Telegram', url=url)])
    rows.append([InlineKeyboardButton('Завершить знакомство', callback_data=f'xm:close:{int(offer_id)}')])
    return InlineKeyboardMarkup(rows)


def ar_purge_user_by_tg_id(tg_id):
    row = one('SELECT id FROM users WHERE tg_id=?', (int(tg_id),))
    if not row:
        return False
    uid = int(row['id'])
    user_cols = ('user_id','subject_user_id','recipient_user_id','requester_user_id','target_user_id')
    with db() as c:
        if USE_POSTGRES:
            rows = c.execute(
                "SELECT table_name,column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND column_name IN (%s,%s,%s,%s,%s)",
                user_cols,
            ).fetchall()
            grouped = {}
            for r in rows:
                table = str(r['table_name'])
                if table == 'users':
                    continue
                grouped.setdefault(table, []).append(str(r['column_name']))
            for table, cols in grouped.items():
                safe_table = table.replace('"','""')
                safe_cols = [x.replace('"','""') for x in cols]
                where = ' OR '.join(f'"{col}"=?' for col in safe_cols)
                c.execute(f'DELETE FROM "{safe_table}" WHERE {where}', tuple(uid for _ in safe_cols))
        else:
            tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for tr in tables:
                table = str(tr['name'])
                if table == 'users' or not table.replace('_','').isalnum():
                    continue
                cols = c.execute(f'PRAGMA table_info("{table}")').fetchall()
                names = [str(x['name']) for x in cols if str(x['name']) in user_cols]
                if not names:
                    continue
                where = ' OR '.join(f'"{col}"=?' for col in names)
                c.execute(f'DELETE FROM "{table}" WHERE {where}', tuple(uid for _ in names))
        c.execute('DELETE FROM users WHERE id=?', (uid,))
    print('[account] user data purged after bot stop', flush=True)
    return True


async def ar_my_chat_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cm = update.my_chat_member
    if not cm or str(cm.chat.type) != 'private':
        return
    status = str(cm.new_chat_member.status)
    if status in ('kicked', 'left'):
        try:
            ar_purge_user_by_tg_id(cm.chat.id)
        finally:
            try:
                ctx.user_data.clear()
            except Exception:
                pass
# ---------------------------------------------------------------------------

"""
s = s.replace(anchor, block + anchor, 1)

# Register the private-chat bot-status handler before ordinary conversation work.
s = s.replace(
    anchor,
    anchor + "\nbot.add_handler(ChatMemberHandler(ar_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER), group=-1)",
    1,
)

# Make sure Telegram actually sends private my_chat_member updates to this webhook.
s = s.replace(
    "kw={'url':BASE_URL+'/telegram/webhook','drop_pending_updates':False}",
    "kw={'url':BASE_URL+'/telegram/webhook','drop_pending_updates':False,'allowed_updates':['message','callback_query','my_chat_member']}",
    1,
)

# Automatic exclusive-matching mutual-interest branch: reveal real contacts to BOTH sides.
old_subject = "await q.message.reply_text('💞 <b>Взаимный интерес!</b>\\n\\nСовпадение подтверждено с обеих сторон. Теперь можно переходить к общению.', parse_mode=ParseMode.HTML, reply_markup=close_kb)"
new_subject = "await q.message.reply_text(f'💞 <b>Взаимный интерес!</b>\\n\\n{ar_contact_link(recipient_uid)} тоже хочет общаться. Нажми на контакт или кнопку ниже и напиши прямо в Telegram.', parse_mode=ParseMode.HTML, reply_markup=ar_contact_keyboard(recipient_uid, offer_id))"
s = s.replace(old_subject, new_subject, 1)

old_other = "await ctx.bot.send_message(other['tg_id'], '💞 <b>Взаимный интерес!</b>\\n\\nВторая сторона тоже хочет общаться. Совпадение подтверждено с обеих сторон.', parse_mode=ParseMode.HTML, reply_markup=close_kb)"
new_other = "await ctx.bot.send_message(other['tg_id'], f'💞 <b>Взаимный интерес!</b>\\n\\n{ar_contact_link(subject_uid)} тоже хочет общаться. Нажми на контакт или кнопку ниже и напиши прямо в Telegram.', parse_mode=ParseMode.HTML, reply_markup=ar_contact_keyboard(subject_uid, offer_id))"
s = s.replace(old_other, new_other, 1)

if old_subject in s or old_other in s:
    raise SystemExit('[build] account-reset: mutual contact replacement incomplete')

p.write_text(s, encoding='utf-8')
print('[build] account reset on bot stop + mutual contact links applied', flush=True)
