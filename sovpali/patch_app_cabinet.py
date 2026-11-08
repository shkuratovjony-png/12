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
p.write_text(s)
print('[build] Mini App cabinet menu added')
