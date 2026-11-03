"""Switch matchmaking notifications to recipient-local schedule.

Injection runs last, after all historical patches. Existing XM buttons/paid
agreements remain intact, but the *automatic notification* path no longer
creates 24h exclusive offers or uses Yekaterinburg's fixed clock.
"""
from pathlib import Path

target=Path("app.py")
source=target.read_text(encoding="utf-8")
anchor="\nregister_pair_motion(app, globals())\n"
if source.count(anchor)!=1:
    raise SystemExit("[build] match-push: route registration anchor missing")

block=r'''
# --- First-ever match instant; later notifications use recipient-local slots ---
from match_push_engine import MatchPushEngine
from match_localtime import infer_zone

MATCH_PUSH_ENGINE=MatchPushEngine(globals())

def mp_record_view(uid,candidate):
    # Also called by the signed mobile page when a user opens the real report.
    try:MATCH_PUSH_ENGINE.mark_view(uid,candidate)
    except Exception as exc:print('[match-push] view marker '+type(exc).__name__,flush=True)

async def xm_profile_ready(ctx,uid):
    # On completed registration, offer the newcomer to ONE older recipient first.
    # Never notify both accounts about each other. Newcomer can receive OTHER
    # candidates. A person's first delivered match bypasses local quiet hours.
    try:await MATCH_PUSH_ENGINE.new_profile(ctx.bot,uid)
    except Exception as exc:
        print('[match-push] onboarding hook '+type(exc).__name__+': '+str(exc)[:100],flush=True)

async def xm_try_offer(bot_api,subject_uid):
    # Old call sites (lifecycle, decline/expiry callbacks) reuse the *new*
    # read-only recommendation engine. Historical active offers remain valid.
    return await MATCH_PUSH_ENGINE.suggest(bot_api,subject_uid)

async def xm_maintenance(bot_api):
    return await MATCH_PUSH_ENGINE.maintain(bot_api)

def sm_auto_recipient_allowed(uid):
    # Important: this is no longer hard-coded to UTC+5 / Yekaterinburg.
    try:return MATCH_PUSH_ENGINE.desired_slot(uid) is not None
    except Exception:return False

def sm_auto_today(uid):
    try:return MATCH_PUSH_ENGINE.daily_stats(uid)[1]
    except Exception:return 0

async def mp_timezone_command(update,ctx):
    if not update.effective_message:return
    current=upsert_user(update.effective_user)
    uid=int(current['id'])
    p=profile(uid)
    if not p:
        await update.effective_message.reply_text('Сначала создай анкету через /start.')
        return
    clock,zone=MATCH_PUSH_ENGINE.zone(uid,p)
    guessed,reliable=infer_zone(p['city'])
    kind='автоматически определён по городу' if reliable and guessed==zone else 'настроен вручную' if guessed!=zone else 'ориентировочный'
    choices=MATCH_PUSH_ENGINE.timezone_choices()
    rows=[]
    row=[]
    for code,iana in choices.items():
        row.append(InlineKeyboardButton('UTC+'+code,callback_data='mtz:'+code))
        if len(row)==4:
            rows.append(row);row=[]
    if row:rows.append(row)
    await update.effective_message.reply_text(
        '🕒 <b>Часовой пояс уведомлений</b>\n\n'
        f'Город анкеты: {html.escape(str(p["city"]))}\n'
        f'Сейчас для тебя: <b>{clock:%H:%M}</b>\n'
        f'Часовой пояс: <code>{html.escape(zone)}</code> ({kind}).\n\n'
        'Если время неверное, выбери свой пояс. '
        'Если пар ещё не было — первая подходящая анкета приходит сразу, даже ночью. '
        'После первого совпадения рассылки идут по времени города: днём и вечером. '
        'Не более двух за сутки.',
        parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(rows))

async def mp_timezone_callback(update,ctx):
    q=update.callback_query
    await q.answer()
    u=upsert_user(update.effective_user)
    key=(q.data or '').partition(':')[2]
    choices=MATCH_PUSH_ENGINE.timezone_choices()
    zone=choices.get(key)
    if not zone or not MATCH_PUSH_ENGINE.set_timezone(int(u['id']),zone):
        await q.message.reply_text('Не удалось выбрать часовой пояс.')
        return
    clock,zone=MATCH_PUSH_ENGINE.zone(int(u['id']))
    await q.message.reply_text(
        f'✅ Часовой пояс установлен: UTC+{key}. '
        f'Сейчас у тебя {clock:%H:%M}. '
        'Буду учитывать это время при автоматическом подборе.')

bot.add_handler(CommandHandler('timezone',mp_timezone_command))
bot.add_handler(CallbackQueryHandler(mp_timezone_callback,pattern=r'^mtz:'))

MATCH_PUSH_REVISION="first-ever-immediate-v3"
# -----------------------------------------------------------------------------
'''
source=source.replace(anchor,"\n"+block+anchor,1)
# Double-check key handlers remain available for paid introductions and legacy
# mutual-consent callbacks; this patch changes ONLY the auto notification path.
for symbol in ["async def xm_callback(", "async def mp_callback(",
               "async def xm_profile_ready(", "async def xm_try_offer(",
               "async def xm_maintenance(", "bot.add_handler(CallbackQueryHandler(xm_callback",
               "bot.add_handler(CallbackQueryHandler(mp_callback"]:
    if symbol not in source:
        raise SystemExit("[build] match-push: required callback missing "+symbol)
target.write_text(source,encoding="utf-8")
print("[build] one-way match distribution: first-ever immediate, later local schedule; no reciprocal notifications",flush=True)
