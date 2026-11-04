from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
start = s.find('async def send_card(')
if start < 0:
    raise SystemExit('send_card not found')
end = s.find('\n\nAGE', start)
if end < 0:
    raise SystemExit('state marker not found')
new = '''async def send_card(message,theme,caption,reply_markup=None,animated=False):\n    # Версия 3.1: только статичные горизонтальные фото.\n    await message.reply_photo(\n        as_file(visual(theme),f'{theme}.jpg'),\n        caption=caption,\n        parse_mode=ParseMode.HTML,\n        reply_markup=reply_markup,\n    )\n'''
s = s[:start] + new + s[end:]
p.write_text(s, encoding='utf-8')
print('[patch] static landscape photos enabled', flush=True)
