"""Final repair of the full website -> Telegram approval journey.

Runs AFTER legacy patches to avoid stale city gates, paid stubs, or overlong
Telegram messages. A request can only be initiated from a signed website
capability after the person visits the real pair page. Refusals and the
existing mutual consent/contact handlers remain untouched.
"""
from pathlib import Path

p=Path("app.py")
s=p.read_text(encoding="utf-8")
anchor="\nregister_pair_motion(app, globals())\n"
if s.count(anchor)!=1:
    raise SystemExit("[build] web-request-fix: motion registration anchor not found")
block=r'''
# --- Website-only introduction; bot sends recipient consent card -------------
import asyncio as _site_asyncio

_site_previous_init_db=init_db
def init_db():
    _site_previous_init_db()
    with db() as conn:
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS communication_request_deliveries(
            request_id BIGINT PRIMARY KEY,
            sent_at TEXT NOT NULL
          );
        """)

_SITE_CR_LOCK=_site_asyncio.Lock()

async def cr_send_request(ctx,requester_uid,target_uid,score_value):
    requester_uid,target_uid=int(requester_uid),int(target_uid)
    if requester_uid==target_uid:return ('failed',None)
    async with _SITE_CR_LOCK:
        requester=profile(requester_uid)
        target=profile(target_uid)
        target_user=user(target_uid)
        if (not requester or not target or not target_user
            or int(target_user['is_banned'] or 0)
            or not eligible(requester,target)):
            return ('failed',None)

        existing=cr_between(requester_uid,target_uid)
        req_id=None
        if existing:
            req_id=int(existing['id'])
            status=str(existing['status'])
            if status=='accepted':return ('accepted',req_id)
            if status=='pending':
                sent=one('SELECT 1 FROM communication_request_deliveries WHERE request_id=?',(req_id,))
                if sent:return ('pending',req_id)
            else:
                execute('DELETE FROM communication_requests WHERE id=?',(req_id,))
                req_id=None

        if req_id is None:
            lo,hi=sorted((requester_uid,target_uid))
            try:
                with db() as conn:
                    cur=conn.execute("""INSERT INTO communication_requests(
                        pair_low,pair_high,requester_user_id,target_user_id,
                        score,status,created_at)
                        VALUES(?,?,?,?,?,'pending',?) RETURNING id""",
                        (lo,hi,requester_uid,target_uid,int(score_value),now()))
                    req_id=int(cur.fetchone()['id'])
            except Exception as exc:
                existing=cr_between(requester_uid,target_uid)
                if not existing:return ('failed',None)
                req_id=int(existing['id'])
                if str(existing['status'])=='accepted':return ('accepted',req_id)
                if one('SELECT 1 FROM communication_request_deliveries WHERE request_id=?',(req_id,)):
                    return ('pending',req_id)
                print('[web-request] retrying previously unconfirmed delivery: '+type(exc).__name__,flush=True)

        name=html.escape(str(requester['name'])[:90])
        city=html.escape(str(requester['city'])[:90])
        text=(f'💌 <b>{name} предлагает тебе познакомиться</b>\n\n'
              f'Совместимость по анкетам: <b>{int(score_value)}%</b>\n'
              f'{city}\n\n'
              'Человек уже посмотрел вашу совместимость и хочет начать общение. '
              'Твой контакт не раскроется без согласия.\n\n'
              'Как ты ответишь?')
        kb=InlineKeyboardMarkup([[
          InlineKeyboardButton('❤️ Да, хочу общаться',callback_data=f'cr:accept:{req_id}'),
          InlineKeyboardButton('Не сейчас',callback_data=f'cr:decline:{req_id}')
        ]])
        try:
            await ctx.bot.send_message(target_user['tg_id'],text,
                                       parse_mode=ParseMode.HTML,reply_markup=kb,
                                       disable_web_page_preview=True)
        except Exception as exc:
            print('[web-request] Telegram delivery failed: '+type(exc).__name__+': '+str(exc)[:120],flush=True)
            return ('failed',req_id)
        try:
            execute("""INSERT INTO communication_request_deliveries(request_id,sent_at)
                   VALUES(?,?) ON CONFLICT(request_id) DO NOTHING""",(req_id,now()))
            audit(requester_uid,'communication_request_sent',{
                'request_id':req_id,'target_user_id':target_uid,'source':'website'
            })
        except Exception as exc:
            print('[web-request] delivery recording failed: '+type(exc).__name__,flush=True)
        print('[web-request] delivered approval request',flush=True)
        return ('sent',req_id)

SITE_INTROS_REVISION='site-first-nationwide-v1'
# ---------------------------------------------------------------------------
'''
s=s.replace(anchor,"\n"+block+anchor,1)
for symbol in ["async def cr_send_request(", "def cr_between(",
               "async def cr_callback(", "bot.add_handler(CallbackQueryHandler(cr_callback",
               "register_pair_motion(app, globals())"]:
    if symbol not in s:raise SystemExit("[build] web-request-fix: required handler missing "+symbol)
p.write_text(s,encoding="utf-8")
print("[build] website-only consent request, concise Telegram delivery and safe repeat handling",flush=True)
