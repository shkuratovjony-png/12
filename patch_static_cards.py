from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
old = """async def send_card(message,theme,caption,reply_markup=None,animated=False):\n    if animated:\n        await message.reply_animation(as_file(animation(theme),f'{theme}.gif'),caption=caption,parse_mode=ParseMode.HTML,reply_markup=reply_markup)\n    else:\n        await message.reply_photo(as_file(visual(theme),f'{theme}.jpg'),caption=caption,parse_mode=ParseMode.HTML,reply_markup=reply_markup)\n"""
new = """async def send_card(message,theme,caption,reply_markup=None,animated=False):\n    # В версии 2.1 всегда отправляем статичную премиальную фотографию.\n    await message.reply_photo(as_file(visual(theme),f'{theme}.jpg'),caption=caption,parse_mode=ParseMode.HTML,reply_markup=reply_markup)\n"""
if old not in s:
    raise SystemExit('send_card block not found; update patch_static_cards.py')
s = s.replace(old, new)
s = s.replace("from visuals import visual, animation, as_file", "from visuals import visual, as_file")
p.write_text(s, encoding='utf-8')
print('Static premium photo cards enabled')
