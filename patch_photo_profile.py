from pathlib import Path

p=Path('app.py')
s=p.read_text(encoding='utf-8')

old_priority="""async def priority(update,ctx):\n    q=update.callback_query; await q.answer(); ctx.user_data['p']['priority']=q.data.split(':',1)[1]\n    await send_card(q.message,'photo','📸 <b>Последний штрих</b>\\n\\nМожешь добавить одну фотографию. Она <b>не влияет на расчёт совместимости</b>, но помогает сильному совпадению превратиться в настоящее знакомство.\\n\\nЕсли не хочешь сейчас — просто пропусти.',ik([[('Пропустить пока','photo:skip')]]))\n    return PHOTO\n\nasync def photo(update,ctx):\n"""
new_priority="""async def priority(update,ctx):\n    q=update.callback_query; await q.answer(); ctx.user_data['p']['priority']=q.data.split(':',1)[1]\n    await send_card(q.message,'photo','📸 <b>Последний штрих</b>\\n\\nДобавь фотографию для анкеты. Можно взять текущую фотографию профиля Telegram или загрузить другую.\\n\\nФото не влияет на расчёт совместимости — оно нужно, чтобы после совпадения люди могли увидеть друг друга.',ik([[('📷 Взять из Telegram','photo:telegram')],[('⬆️ Загрузить новую','photo:upload')],[('Пропустить пока','photo:skip')]]))\n    return PHOTO\n\nasync def photo_from_telegram(update,ctx):\n    q=update.callback_query; await q.answer()\n    try:\n        photos=await ctx.bot.get_user_profile_photos(update.effective_user.id,limit=1)\n        if photos.total_count and photos.photos:\n            ctx.user_data['p']['photo']=photos.photos[0][-1].file_id\n            return await finish_profile(update,ctx,q.message)\n    except Exception as e:\n        print(f'[profile-photo] telegram: {e}',flush=True)\n    await q.message.reply_text('В профиле Telegram не нашёл доступную фотографию. Пришли фото сообщением — я поставлю его в анкету.')\n    return PHOTO\n\nasync def photo_upload(update,ctx):\n    q=update.callback_query; await q.answer()\n    await q.message.reply_text('Пришли сюда фотографию одним сообщением.')\n    return PHOTO\n\nasync def photo(update,ctx):\n"""
if old_priority in s:
    s=s.replace(old_priority,new_priority)
else:
    print('[build] photo patch: priority target not found',flush=True)

old_state="""        PHOTO:[MessageHandler(filters.PHOTO,photo),CallbackQueryHandler(photo_skip,pattern=r'^photo:skip$')],\n"""
new_state="""        PHOTO:[MessageHandler(filters.PHOTO,photo),CallbackQueryHandler(photo_from_telegram,pattern=r'^photo:telegram$'),CallbackQueryHandler(photo_upload,pattern=r'^photo:upload$'),CallbackQueryHandler(photo_skip,pattern=r'^photo:skip$')],\n"""
if old_state in s:
    s=s.replace(old_state,new_state)
else:
    print('[build] photo patch: PHOTO state target not found',flush=True)

# In My Profile show the user's real chosen photo if it exists. Decorative menu images
# have already been removed by patch_no_menu_images.py.
old_profile="""        await msg.reply_text(cap,parse_mode=ParseMode.HTML,reply_markup=ik([[('🔄 Обновить профиль','profile:reset')]]))\n"""
new_profile="""        profile_markup=ik([[('🔄 Обновить профиль','profile:reset')]])\n        if p['photo_file_id']:\n            await msg.reply_photo(p['photo_file_id'],caption=cap,parse_mode=ParseMode.HTML,reply_markup=profile_markup)\n        else:\n            await msg.reply_text(cap,parse_mode=ParseMode.HTML,reply_markup=profile_markup)\n"""
if old_profile in s:
    s=s.replace(old_profile,new_profile)
else:
    print('[build] photo patch: profile display target not found',flush=True)

p.write_text(s,encoding='utf-8')
print('[build] telegram profile photo choice applied',flush=True)
