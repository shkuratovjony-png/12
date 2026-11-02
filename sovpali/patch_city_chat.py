from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

old_menu = """MENU=ReplyKeyboardMarkup([\n    [KeyboardButton('💖 Мои пары'),KeyboardButton('👤 Мой профиль')],\n    [KeyboardButton('✨ Подбор'),KeyboardButton('💬 Чаты')],\n    [KeyboardButton('⚙️ Ещё')]\n],resize_keyboard=True,is_persistent=True)\n"""
new_menu = """def chat_hub(city: str) -> str:\n    c=(city or '').strip().lower().replace('ё','е')\n    vlad_hub=('владивосток','артем','надеждин','новый','соловей-ключ','соловей ключ','угловое','трудовое','садгород','кипарисово','раздольное','тавpичанка','тавричанка')\n    if any(x in c for x in vlad_hub):\n        return 'Владивостока'\n    return ''\n\ndef menu_for(p=None):\n    hub=chat_hub(p['city'] if p else '')\n    chat_label=f'💬 Чат {hub}' if hub else '💬 Чат'\n    return ReplyKeyboardMarkup([\n        [KeyboardButton('💖 Мои пары'),KeyboardButton('👤 Мой профиль')],\n        [KeyboardButton('✨ Подбор'),KeyboardButton(chat_label)],\n        [KeyboardButton('⚙️ Ещё')]\n    ],resize_keyboard=True,is_persistent=True)\n\nMENU=menu_for()\n"""
if old_menu in s:
    s=s.replace(old_menu,new_menu)
else:
    print('[build] city-chat: menu target not found', flush=True)

repls={
"reply_markup=MENU)":"reply_markup=menu_for(p))",
"elif text=='💬 Чаты':":"elif text.startswith('💬 Чат'):",
"'💬 <b>Чаты «Совпали»</b>\\n\\nЗдесь можно перейти в городской чат и познакомиться с участниками напрямую.'":"f'💬 <b>{html.escape(text.replace(chr(128172)+chr(32), chr(128172)+chr(32)))}</b>\\n\\nЗдесь можно перейти в общий чат твоего городского хаба и познакомиться с участниками напрямую.'",
"'💬 <b>Чаты «Совпали»</b>\\n\\nГородской чат скоро появится здесь. Пока сосредоточимся на персональном подборе.'":"f'💬 <b>{html.escape(text)}</b>\\n\\nЧат этого городского хаба скоро появится здесь. Пока сосредоточимся на персональном подборе.'",
"filters.Regex(r'^(💖 Мои пары|👤 Мой профиль|✨ Подбор|💬 Чаты|⚙️ Ещё)$')":"filters.Regex(r'^(💖 Мои пары|👤 Мой профиль|✨ Подбор|💬 Чат.*|⚙️ Ещё)$')",
}
for old,new in repls.items():
    if old in s:
        s=s.replace(old,new)
    else:
        print('[build] city-chat target not found:', old[:80], flush=True)

# Context-specific dynamic keyboards.
s=s.replace("await update.effective_message.reply_text(f\"✨ <b>С возвращением в «Совпали»</b>\\n\\n{html.escape(p['name'])}, твой профиль готов. Открой «Мои пары» или запусти новый подбор.\",parse_mode=ParseMode.HTML,reply_markup=menu_for(p))", "await update.effective_message.reply_text(f\"✨ <b>С возвращением в «Совпали»</b>\\n\\n{html.escape(p['name'])}, твой профиль готов. Открой «Мои пары» или запусти новый подбор.\",parse_mode=ParseMode.HTML,reply_markup=menu_for(p))")

# finish_profile has no p variable yet; fetch it before showing keyboard.
needle="""async def finish_profile(update,ctx,message):\n    u=upsert_user(update.effective_user); save_profile(u['id'],ctx.user_data['p'])\n"""
repl="""async def finish_profile(update,ctx,message):\n    u=upsert_user(update.effective_user); save_profile(u['id'],ctx.user_data['p']); p=profile(u['id'])\n"""
if needle in s:
    s=s.replace(needle,repl)

p.write_text(s, encoding='utf-8')
print('[build] city chat hubs applied', flush=True)
