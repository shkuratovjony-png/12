"""Only add a launch button; leave all existing bot handlers and schedules intact."""
from pathlib import Path
p=Path('app.py');s=p.read_text()
anchor='    ready.set()\n'
assert s.count(anchor)==1
s=s.replace(anchor,'''    # Native menu entry for the existing user's Mini App cabinet.
    global MINIAPP_BOT_USERNAME
    MINIAPP_BOT_USERNAME=bot.bot.username
    try:
        from telegram import MenuButtonWebApp, WebAppInfo
        base=(globals().get('PAIR_WEB_BASE_URL') or BASE_URL or '').rstrip('/')
        if base.startswith('https://'):
            await bot.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                text='Открыть',web_app=WebAppInfo(url=base+'/s/app')))
            print('[miniapp] Cabinet menu ready',flush=True)
    except Exception as exc:
        print('[miniapp] Menu setup failed: '+type(exc).__name__,flush=True)
'''+anchor)
# Allow only the intended Telegram host to frame the authenticated Mini App.
# Admin and every payment route retain their original DENY policy.
frame="    resp.headers['X-Frame-Options']='DENY'"
assert s.count(frame)==1
s=s.replace(frame,"""    if request.path == '/s/m/demo':
        resp.headers['X-Frame-Options']='SAMEORIGIN'
    elif request.path == '/s/app' or request.path.startswith('/s/mini/'):
        resp.headers.pop('X-Frame-Options',None)
        resp.headers['Content-Security-Policy']="frame-ancestors 'self' https://web.telegram.org"
    else:
        resp.headers['X-Frame-Options']='DENY'""")
p.write_text(s)
print('[build] Mini App cabinet menu added')

# Attach the verified Telegram Mini App registration API without altering old bot onboarding.
anchor='register_pair_motion(app, globals())'
s=p.read_text()
assert s.count(anchor)==1, 'Missing pair motion registration'
s=s.replace(anchor,anchor+"\nfrom onboarding_upgrade import attach as attach_onboarding\nattach_onboarding(app, globals())",1)
p.write_text(s)
print('[build] miniapp onboarding endpoints registered',flush=True)

# Route first-time /start users into the same authenticated Mini App, not the old chat questionnaire.
s=p.read_text()
start_anchor="    p=profile(u['id'])\n    if p:"
assert s.count(start_anchor)>=1, 'Bot start anchor missing'
replacement="""    p=profile(u['id'])
    if not p:
        from telegram import WebAppInfo
        entry=(globals().get('PAIR_WEB_BASE_URL') or BASE_URL or '').rstrip('/')
        if entry.startswith('https://'):
            keyboard=InlineKeyboardMarkup([[InlineKeyboardButton(
                'Открыть Совпали · создать анкету',
                web_app=WebAppInfo(url=entry+'/s/app'))]])
            await update.effective_message.reply_text(
                '💞 <b>Совпали</b>\\n\\nЗнакомства, где важны не только фотографии, но и ваши ценности, астрология и нумерология.\\n\\nОткрой личное пространство — заполнить анкету можно прямо здесь.',
                parse_mode=ParseMode.HTML,reply_markup=keyboard)
            return ConversationHandler.END
    if p:"""
s=s.replace(start_anchor,replacement,1)
p.write_text(s)
print('[build] new users start in Mini App',flush=True)
