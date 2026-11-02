from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

repls = {
"""    if p:\n        await send_card(update.effective_message,'welcome',f\"✨ <b>С возвращением в «Совпали»</b>\\n\\n{html.escape(p['name'])}, твой профиль готов. Открой «Мои пары» или запусти новый подбор.\",MENU)\n        return ConversationHandler.END\n""":
"""    if p:\n        await update.effective_message.reply_text(f\"✨ <b>С возвращением в «Совпали»</b>\\n\\n{html.escape(p['name'])}, твой профиль готов. Открой «Мои пары» или запусти новый подбор.\",parse_mode=ParseMode.HTML,reply_markup=MENU)\n        return ConversationHandler.END\n""",

"""    await send_card(message,'matching','✨ <b>Профиль готов</b>\\n\\nТеперь «Совпали» сравнивает не один признак, а сразу несколько слоёв: намерение, главный ориентир в отношениях, город, нумерологию и базовую астрологическую совместимость.\\n\\nОткрой <b>«Мои пары»</b> в нижнем меню.',MENU)\n""":
"""    await message.reply_text('✨ <b>Профиль готов</b>\\n\\nТеперь «Совпали» сравнивает не один признак, а сразу несколько слоёв: намерение, главный ориентир в отношениях, город, нумерологию и базовую астрологическую совместимость.\\n\\nОткрой <b>«Мои пары»</b> в нижнем меню.',parse_mode=ParseMode.HTML,reply_markup=MENU)\n""",

"""        await send_card(message,'matching','✨ <b>Ищу сильные совпадения</b>\\n\\nСначала отсеиваю неподходящие анкеты по полу и цели отношений, затем сравниваю ценности, город, нумерологические и базовые астрологические параметры.')\n""":
"""        await message.reply_text('✨ <b>Ищу сильные совпадения</b>\\n\\nСначала отсеиваю неподходящие анкеты по полу и цели отношений, затем сравниваю ценности, город, нумерологические и базовые астрологические параметры.',parse_mode=ParseMode.HTML)\n""",

"""        await send_card(message,'pairs','💖 <b>Твои пары</b>\\n\\nПока недостаточно подходящих анкет для качественного результата. Как только появятся совместимые люди противоположного пола, лучшие совпадения будут здесь.',MENU)\n""":
"""        await message.reply_text('💖 <b>Твои пары</b>\\n\\nПока недостаточно подходящих анкет для качественного результата. Как только появятся совместимые люди противоположного пола, лучшие совпадения будут здесь.',parse_mode=ParseMode.HTML,reply_markup=MENU)\n""",

"""    await send_card(message,'pairs','\\n'.join(lines),ik(rows))\n""":
"""    await message.reply_text('\\n'.join(lines),parse_mode=ParseMode.HTML,reply_markup=ik(rows))\n""",

"""        await send_card(msg,'profile',cap,ik([[('🔄 Обновить профиль','profile:reset')]]))\n""":
"""        await msg.reply_text(cap,parse_mode=ParseMode.HTML,reply_markup=ik([[('🔄 Обновить профиль','profile:reset')]]))\n""",

"""            await send_card(msg,'chats','💬 <b>Чаты «Совпали»</b>\\n\\nЗдесь можно перейти в городской чат и познакомиться с участниками напрямую.',InlineKeyboardMarkup([[InlineKeyboardButton('Открыть городской чат',url=url)]]))\n""":
"""            await msg.reply_text('💬 <b>Чаты «Совпали»</b>\\n\\nЗдесь можно перейти в городской чат и познакомиться с участниками напрямую.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Открыть городской чат',url=url)]]))\n""",

"""            await send_card(msg,'chats','💬 <b>Чаты «Совпали»</b>\\n\\nГородской чат скоро появится здесь. Пока сосредоточимся на персональном подборе.',MENU)\n""":
"""            await msg.reply_text('💬 <b>Чаты «Совпали»</b>\\n\\nГородской чат скоро появится здесь. Пока сосредоточимся на персональном подборе.',parse_mode=ParseMode.HTML,reply_markup=MENU)\n""",

"""        await send_card(msg,'more','⚙️ <b>Ещё</b>\\n\\nНастройки профиля и информация о сервисе.',ik(rows))\n""":
"""        await msg.reply_text('⚙️ <b>Ещё</b>\\n\\nНастройки профиля и информация о сервисе.',parse_mode=ParseMode.HTML,reply_markup=ik(rows))\n""",

"""            await send_card(q.message,'pairs',cap)\n""":
"""            await q.message.reply_text(cap,parse_mode=ParseMode.HTML)\n""",
}

changed = 0
for old, new in repls.items():
    if old in s:
        s = s.replace(old, new)
        changed += 1
    else:
        print('[build] menu-image patch target not found:', old.splitlines()[0], flush=True)

p.write_text(s, encoding='utf-8')
print(f'[build] removed decorative menu images: {changed}/{len(repls)}', flush=True)
