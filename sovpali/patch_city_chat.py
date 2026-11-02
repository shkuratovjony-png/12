from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

old_menu = """MENU=ReplyKeyboardMarkup([\n    [KeyboardButton('💖 Мои пары'),KeyboardButton('👤 Мой профиль')],\n    [KeyboardButton('✨ Подбор'),KeyboardButton('💬 Чаты')],\n    [KeyboardButton('⚙️ Ещё')]\n],resize_keyboard=True,is_persistent=True)\n"""
new_menu = """def city_chat_info(city: str):\n    c=(city or '').strip().lower().replace('ё','е')\n    # Один крупный чат на городской хаб. Мелкие населённые пункты\n    # направляются в ближайший крупный город.\n    vlad_hub=('владивосток','артем','надeждин','надеждин','новый','соловей-ключ','соловей ключ','угловое','трудовое','садгород','кипарисово','раздольное','тавричанка','волно-надеждинское')\n    if any(x in c for x in vlad_hub):\n        return 'Владивостока', (setting('chat_vladivostok_url').strip() or setting('chat_url').strip())\n    if 'хабаровск' in c:\n        return 'Хабаровска', setting('chat_khabarovsk_url').strip()\n    # Для нового города сначала создаём чат и добавляем его в эту таблицу.\n    return (city or 'твоего города').strip(), ''\n\ndef menu_for(p=None):\n    return ReplyKeyboardMarkup([\n        [KeyboardButton('💖 Мои пары'),KeyboardButton('👤 Мой профиль')],\n        [KeyboardButton('✨ Подбор'),KeyboardButton('💬 Чат знакомств')],\n        [KeyboardButton('⚙️ Ещё')]\n    ],resize_keyboard=True,is_persistent=True)\n\nMENU=menu_for()\n"""
if old_menu in s:
    s=s.replace(old_menu,new_menu)
else:
    print('[build] city-chat: menu target not found', flush=True)

# After the no-menu-images patch, keyboards are plain text; make them profile-aware
# while keeping the visible button name identical for every city.
s=s.replace("reply_markup=MENU)", "reply_markup=menu_for(p))")

old_chat="""    elif text=='💬 Чаты':\n        url=setting('chat_url').strip()\n        if url:\n            await msg.reply_text('💬 <b>Чаты «Совпали»</b>\\n\\nЗдесь можно перейти в городской чат и познакомиться с участниками напрямую.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Открыть городской чат',url=url)]]))\n        else:\n            await msg.reply_text('💬 <b>Чаты «Совпали»</b>\\n\\nГородской чат скоро появится здесь. Пока сосредоточимся на персональном подборе.',parse_mode=ParseMode.HTML,reply_markup=menu_for(p))\n"""
new_chat="""    elif text=='💬 Чат знакомств':\n        hub_name,url=city_chat_info(p['city'])\n        if url:\n            await msg.reply_text(f'💬 <b>Чат знакомств · {html.escape(hub_name)}</b>\\n\\nПереходи в городской чат и знакомься с людьми рядом.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Открыть чат знакомств',url=url)]]))\n        else:\n            await msg.reply_text(f'💬 <b>Чат знакомств</b>\\n\\nДля города <b>{html.escape(p["city"])}</b> чат пока готовится. Как только в городе наберётся аудитория, он появится здесь автоматически.',parse_mode=ParseMode.HTML,reply_markup=menu_for(p))\n"""
if old_chat in s:
    s=s.replace(old_chat,new_chat)
else:
    # Fallback for source before no-menu-images patch.
    s=s.replace("elif text=='💬 Чаты':", "elif text=='💬 Чат знакомств':")
    print('[build] city-chat: exact cabinet block not found; fallback applied', flush=True)

s=s.replace("filters.Regex(r'^(💖 Мои пары|👤 Мой профиль|✨ Подбор|💬 Чаты|⚙️ Ещё)$')", "filters.Regex(r'^(💖 Мои пары|👤 Мой профиль|✨ Подбор|💬 Чат знакомств|⚙️ Ещё)$')")

# finish_profile has no p variable in the original source; fetch it before menu_for(p).
needle="""async def finish_profile(update,ctx,message):\n    u=upsert_user(update.effective_user); save_profile(u['id'],ctx.user_data['p'])\n"""
repl="""async def finish_profile(update,ctx,message):\n    u=upsert_user(update.effective_user); save_profile(u['id'],ctx.user_data['p']); p=profile(u['id'])\n"""
if needle in s:
    s=s.replace(needle,repl)

p.write_text(s, encoding='utf-8')
print('[build] generic city chat routing applied', flush=True)
