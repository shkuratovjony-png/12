from pathlib import Path

p=Path('app.py')
s=p.read_text(encoding='utf-8')

imp="from visuals import visual, as_file\n"
if imp not in s:
    raise SystemExit('[build] pair-web: import anchor not found')
if 'from pair_web import pair_link, register_pair_web' not in s:
    s=s.replace(imp,imp+'from pair_web import pair_link, register_pair_web\n',1)

port="PORT=int(os.getenv('PORT','10000'))\n"
if port not in s:
    raise SystemExit('[build] pair-web: port anchor not found')
if 'PAIR_WEB_BASE_URL=' not in s:
    s=s.replace(port,port+"PAIR_WEB_BASE_URL=(os.getenv('PUBLIC_URL','').strip().rstrip('/') or BASE_URL or 'https://one2-1o22.onrender.com')\n",1)

old="""        kb = InlineKeyboardMarkup([\n            [main_button],\n            [InlineKeyboardButton('← К ТОП-3', callback_data='mp:refresh:0')],\n        ])\n"""
new="""        web_url = pair_link(PAIR_WEB_BASE_URL, int(u['id']), cid, FLASK_SECRET)\n        pair_rows = [[main_button]]\n        if web_url:\n            pair_rows.append([InlineKeyboardButton('🌐 Открыть страницу пары', url=web_url)])\n        pair_rows.append([InlineKeyboardButton('← К ТОП-3', callback_data='mp:refresh:0')])\n        kb = InlineKeyboardMarkup(pair_rows)\n"""
if old in s:
    s=s.replace(old,new,1)
elif '🌐 Открыть страницу пары' not in s:
    raise SystemExit('[build] pair-web: My Pair keyboard anchor not found')

main="\nif __name__=='__main__':\n"
if main not in s:
    raise SystemExit('[build] pair-web: main anchor not found')
if 'register_pair_web(app, globals())' not in s:
    s=s.replace(main,"\nregister_pair_web(app, globals())\n"+main,1)

p.write_text(s,encoding='utf-8')
print('[build] pair web portal + bot link applied',flush=True)
