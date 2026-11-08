from pathlib import Path

p=Path('app.py')
s=p.read_text(encoding='utf-8')
anchor="bot=Application.builder().token(TOKEN).build()"
if anchor not in s: raise SystemExit('[build] lifecycle: bot anchor not found')

block=r"""
# --- Lifecycle CRM: rule-based, no paid AI ----------------------------------
LF_DAILY_CAP=int(os.getenv('LIFECYCLE_DAILY_CAP','1'))
LF_BATCH_SIZE=int(os.getenv('LIFECYCLE_BATCH_SIZE','120'))
LF_RUN_EVERY_MIN=int(os.getenv('LIFECYCLE_RUN_EVERY_MIN','30'))
LF_SEND_START_UTC=int(os.getenv('LIFECYCLE_SEND_START_UTC','6'))
LF_SEND_END_UTC=int(os.getenv('LIFECYCLE_SEND_END_UTC','13'))
LF_LOCK=threading.Lock()

def lf_now(): return datetime.utcnow().replace(microsecond=0)
def lf_iso(dt=None): return (dt or lf_now()).isoformat()
def lf_parse(v):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace('Z','+00:00')).replace(tzinfo=None)
    except Exception: return None

def lf_init_db():
    with db() as c:
        if USE_POSTGRES:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS lifecycle_prefs(
              user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
              promo_enabled INTEGER NOT NULL DEFAULT 1,last_promo_at TEXT,last_segment TEXT,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS lifecycle_sends(
              id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              segment TEXT NOT NULL,dedupe_key TEXT NOT NULL,variant INTEGER NOT NULL DEFAULT 0,
              related_offer_id BIGINT,created_at TEXT NOT NULL,UNIQUE(user_id,dedupe_key));
            CREATE INDEX IF NOT EXISTS idx_lifecycle_sends_user ON lifecycle_sends(user_id);
            CREATE INDEX IF NOT EXISTS idx_lifecycle_sends_created ON lifecycle_sends(created_at);
            CREATE INDEX IF NOT EXISTS idx_lifecycle_sends_segment ON lifecycle_sends(segment);
            ''')
        else:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS lifecycle_prefs(
              user_id INTEGER PRIMARY KEY,promo_enabled INTEGER NOT NULL DEFAULT 1,last_promo_at TEXT,last_segment TEXT,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS lifecycle_sends(
              id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,segment TEXT NOT NULL,dedupe_key TEXT NOT NULL,
              variant INTEGER NOT NULL DEFAULT 0,related_offer_id INTEGER,created_at TEXT NOT NULL,UNIQUE(user_id,dedupe_key));
            CREATE INDEX IF NOT EXISTS idx_lifecycle_sends_user ON lifecycle_sends(user_id);
            CREATE INDEX IF NOT EXISTS idx_lifecycle_sends_created ON lifecycle_sends(created_at);
            CREATE INDEX IF NOT EXISTS idx_lifecycle_sends_segment ON lifecycle_sends(segment);
            ''')
    for k,v in [('lifecycle_enabled','1'),('payments_live','0'),('unlock_price_rub','100')]:
        try:
            if not one('SELECT key FROM settings WHERE key=?',(k,)): set_setting(k,v)
        except Exception: pass

def lf_pref(uid):
    r=one('SELECT * FROM lifecycle_prefs WHERE user_id=?',(uid,))
    if r: return r
    execute('INSERT INTO lifecycle_prefs(user_id,promo_enabled,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO NOTHING',(uid,1,lf_iso()))
    return one('SELECT * FROM lifecycle_prefs WHERE user_id=?',(uid,))

def lf_today_count(uid):
    r=one('SELECT COUNT(*) c FROM lifecycle_sends WHERE user_id=? AND created_at LIKE ?',(uid,lf_now().date().isoformat()+'%'))
    return int(r['c'] or 0) if r else 0

def lf_sent(uid,key): return bool(one('SELECT id FROM lifecycle_sends WHERE user_id=? AND dedupe_key=?',(uid,key)))
def lf_variant(uid,segment,n=3): return sum(ord(x) for x in f'{uid}:{segment}:{lf_now().date()}')%n

def lf_record(uid,segment,key,offer_id=None):
    execute('''INSERT INTO lifecycle_sends(user_id,segment,dedupe_key,variant,related_offer_id,created_at)
               VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,dedupe_key) DO NOTHING''',(uid,segment,key,lf_variant(uid,segment),offer_id,lf_iso()))
    execute('''INSERT INTO lifecycle_prefs(user_id,promo_enabled,last_promo_at,last_segment,updated_at) VALUES(?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET last_promo_at=excluded.last_promo_at,last_segment=excluded.last_segment,updated_at=excluded.updated_at''',
            (uid,1,lf_iso(),segment,lf_iso()))
    try: audit(uid,'lifecycle_sent',{'segment':segment,'dedupe_key':key,'offer_id':offer_id})
    except Exception: pass

def lf_last_paid(uid):
    r=one('''SELECT * FROM payments WHERE user_id=? AND LOWER(status) IN ('paid','success','succeeded','completed')
             ORDER BY COALESCE(paid_at,created_at) DESC LIMIT 1''',(uid,))
    return lf_parse(r['paid_at'] or r['created_at']) if r else None

def lf_pending_payment(uid):
    return one('''SELECT * FROM payments WHERE user_id=?
                  AND LOWER(status) NOT IN ('paid','success','succeeded','completed','failed','cancelled','canceled')
                  ORDER BY created_at DESC LIMIT 1''',(uid,))

def lf_active_offer(uid):
    return one('''SELECT * FROM match_offers WHERE status IN ('offered','interested','accepted')
                  AND (subject_user_id=? OR recipient_user_id=?) ORDER BY id DESC LIMIT 1''',(uid,uid))

def lf_other(offer,uid):
    if not offer: return None
    oid=int(offer['recipient_user_id']) if int(uid)==int(offer['subject_user_id']) else int(offer['subject_user_id'])
    return profile(oid)

def lf_age(p):
    try:
        a=xm_age(p['birth_date']); return f', {a}' if a else ''
    except Exception: return ''

def lf_left(offer):
    ex=lf_parse(offer['expires_at'])
    return max(0,int((ex-lf_now()).total_seconds()//3600)) if ex else None

def lf_offer_text(uid,o,c):
    name=html.escape(c['name']); age=lf_age(c); sc=int(o['score']); left=lf_left(o); tail=f' Ещё примерно {left} ч.' if left is not None else ''
    vv=[
      f'💖 Напомню один раз: у тебя всё ещё открыто сильное совпадение — <b>{name}{age}</b>, {sc}%.\n\nПока ты не ответил, я не передаю эту анкету дальше.{tail}',
      f'Кажется, ты не успел посмотреть совпадение.\n\n<b>{name}{age}</b> · {sc}% совместимости. Анкета всё ещё ждёт твоего решения.{tail}\n\nЕсли не откликается — просто откажись, и я продолжу подбор.',
      f'💌 У тебя осталось незавершённое знакомство с <b>{name}{age}</b>. Совместимость — <b>{sc}%</b>.\n\nЯ пока не подсовываю новое: сначала лучше решить с этим совпадением.{tail}'
    ]
    return vv[lf_variant(uid,'offer_reminder',len(vv))]

def lf_interest_text(uid,o,c):
    name=html.escape(c['name']); age=lf_age(c); sc=int(o['score'])
    vv=[
      f'💌 <b>{name}{age}</b> уже хочет познакомиться с тобой.\n\nУ вас {sc}% совместимости. Нужен только твой ответ — да или нет.',
      f'Тут решение за тобой 🙂\n\n<b>{name}{age}</b> отправил(а) запрос на знакомство. Совместимость — <b>{sc}%</b>. Пока ты не ответишь, эта пара остаётся закреплённой.',
      f'Напомню про один важный запрос: <b>{name}{age}</b> выбрал(а) знакомство с тобой.\n\n{sc}% совместимости. Если интересно — подтверди, если нет — я сразу продолжу подбор.'
    ]
    return vv[lf_variant(uid,'interest_reminder',len(vv))]

def lf_unlock_text(uid,o,c):
    name=html.escape(c['name']); age=lf_age(c); price=int(setting('unlock_price_rub','100') or 100)
    vv=[
      f'💞 У вас с <b>{name}{age}</b> взаимный интерес.\n\nСамое сложное уже случилось: вы оба сказали «да». Контакт пока закрыт.\n\nОткрыть контакт — <b>{price} ₽</b>.',
      f'Вы с <b>{name}{age}</b> выбрали друг друга.\n\nМожно не терять момент: контакт готов к открытию за <b>{price} ₽</b>.',
      f'❤️ Взаимность подтверждена с <b>{name}{age}</b>.\n\nЕсли хочешь перейти от подбора к общению, открой контакт за <b>{price} ₽</b>.'
    ]
    return vv[lf_variant(uid,'accepted_unpaid',len(vv))]

def lf_checkout_text(uid,p):
    amount=html.escape(str(p['amount_rub'] or setting('unlock_price_rub','100')))
    vv=[
      f'Похоже, оплата на <b>{amount} ₽</b> не завершилась.\n\nЕсли просто отвлёкся — можно продолжить с того же места.',
      f'Я сохранил незавершённый шаг с оплатой. Ничего заново искать не нужно.\n\nСумма — <b>{amount} ₽</b>.',
      f'Небольшое напоминание: открытие контакта осталось на шаге оплаты — <b>{amount} ₽</b>.\n\nЕсли передумал, просто проигнорируй сообщение.'
    ]
    return vv[lf_variant(uid,'checkout_abandoned',len(vv))]

async def lf_send(bot_api,uid,segment,key,text,kb=None,offer_id=None):
    if lf_sent(uid,key) or lf_today_count(uid)>=LF_DAILY_CAP: return False
    pref=lf_pref(uid)
    if pref and int(pref['promo_enabled'] or 0)!=1: return False
    target=user(uid)
    if not target: return False
    try:
        await bot_api.send_message(target['tg_id'],text,parse_mode=ParseMode.HTML,reply_markup=kb)
        lf_record(uid,segment,key,offer_id); return True
    except Exception as e:
        print(f'[lifecycle] send failed uid={uid}: {type(e).__name__}: {e}',flush=True); return False

async def lf_process_user(bot_api,uid):
    uid=int(uid)
    if setting('lifecycle_enabled','1')!='1' or lf_today_count(uid)>=LF_DAILY_CAP: return False
    pref=lf_pref(uid)
    if pref and int(pref['promo_enabled'] or 0)!=1: return False
    nowv=lf_now(); offer=lf_active_offer(uid)

    pending=lf_pending_payment(uid)
    if setting('payments_live','0')=='1' and pending:
        created=lf_parse(pending['created_at'])
        if created and (nowv-created).total_seconds()>=3600:
            key=f"checkout:{pending['id']}:d1"
            kb=InlineKeyboardMarkup([[InlineKeyboardButton('Продолжить оплату',callback_data=f"lf:pay:{pending['id']}")],[InlineKeyboardButton('Не присылать такие сообщения',callback_data='lf:optout')]])
            return await lf_send(bot_api,uid,'checkout_abandoned',key,lf_checkout_text(uid,pending),kb)

    if offer:
        st=str(offer['status']); other=lf_other(offer,uid)
        if st=='accepted' and other and setting('payments_live','0')=='1' and lf_last_paid(uid) is None:
            key=f"accepted:{offer['id']}:{nowv.date()}"
            kb=InlineKeyboardMarkup([[InlineKeyboardButton(f"Открыть контакт · {setting('unlock_price_rub','100')} ₽",callback_data=f"lf:unlock:{offer['id']}")],[InlineKeyboardButton('Не присылать напоминания',callback_data='lf:optout')]])
            return await lf_send(bot_api,uid,'accepted_unpaid',key,lf_unlock_text(uid,offer,other),kb,offer['id'])
        started=lf_parse(offer['offered_at'] or offer['created_at']) or nowv
        ageh=(nowv-started).total_seconds()/3600
        if st=='offered' and int(offer['recipient_user_id'])==uid and other and ageh>=6:
            key=f"offer-reminder:{offer['id']}"
            kb=InlineKeyboardMarkup([[InlineKeyboardButton('❤️ Хочу познакомиться',callback_data=f"xm:interest:{offer['id']}"),InlineKeyboardButton('Не сейчас',callback_data=f"xm:skip:{offer['id']}")],[InlineKeyboardButton('Не присылать напоминания',callback_data='lf:optout')]])
            return await lf_send(bot_api,uid,'offer_reminder',key,lf_offer_text(uid,offer,other),kb,offer['id'])
        if st=='interested' and int(offer['subject_user_id'])==uid and other:
            responded=lf_parse(offer['responded_at']) or started
            if (nowv-responded).total_seconds()>=6*3600:
                key=f"interest-reminder:{offer['id']}"
                kb=InlineKeyboardMarkup([[InlineKeyboardButton('❤️ Да, познакомиться',callback_data=f"xm:accept:{offer['id']}"),InlineKeyboardButton('Не сейчас',callback_data=f"xm:decline:{offer['id']}")],[InlineKeyboardButton('Не присылать напоминания',callback_data='lf:optout')]])
                return await lf_send(bot_api,uid,'interest_reminder',key,lf_interest_text(uid,offer,other),kb,offer['id'])
        return False

    last=lf_last_paid(uid)
    if last is None or (nowv-last).days>=7:
        try: return bool(await xm_try_offer(bot_api,uid))
        except Exception as e: print(f'[lifecycle] fresh-match warning uid={uid}: {type(e).__name__}: {e}',flush=True)
    return False

async def lf_run_once(bot_api):
    if not LF_LOCK.acquire(blocking=False): return 0
    sent=0
    try:
        rows=many('''SELECT p.user_id FROM profiles p JOIN users u ON u.id=p.user_id WHERE u.is_banned=0 ORDER BY u.last_seen_at DESC LIMIT 2500''')
        for r in rows:
            if sent>=LF_BATCH_SIZE: break
            try:
                if await lf_process_user(bot_api,int(r['user_id'])):
                    sent+=1; await asyncio.sleep(.12)
            except Exception as e: print(f'[lifecycle] user warning: {type(e).__name__}: {e}',flush=True)
        if sent: print(f'[lifecycle] run complete: sent={sent}',flush=True)
        return sent
    finally: LF_LOCK.release()

async def lf_maintenance(bot_api):
    await asyncio.sleep(55)
    while True:
        try:
            if LF_SEND_START_UTC<=lf_now().hour<LF_SEND_END_UTC: await lf_run_once(bot_api)
        except Exception as e: print(f'[lifecycle] maintenance warning: {type(e).__name__}: {e}',flush=True)
        await asyncio.sleep(max(10,LF_RUN_EVERY_MIN)*60)

async def lf_callback(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); u=upsert_user(update.effective_user); uid=int(u['id']); data=q.data or ''
    if data=='lf:optout':
        execute('''INSERT INTO lifecycle_prefs(user_id,promo_enabled,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET promo_enabled=0,updated_at=excluded.updated_at''',(uid,0,lf_iso()))
        await q.message.reply_text('Хорошо. Автоматические рекомендации и напоминания отключены. Сам бот и «Мои пары» продолжат работать.')
        try: await q.edit_message_reply_markup(reply_markup=None)
        except Exception: pass
        return
    if data=='lf:optin':
        execute('''INSERT INTO lifecycle_prefs(user_id,promo_enabled,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET promo_enabled=1,updated_at=excluded.updated_at''',(uid,1,lf_iso()))
        await q.message.reply_text('Готово. Буду присылать только сильные совпадения и важные напоминания.'); return
    if data.startswith('lf:unlock:'):
        await q.message.reply_text('Это старая кнопка. Открой Mini App «Совпали» через меню бота, зайди в «Подбор» и выбери человека для знакомства. Оплата доступна через Ozon.'); return
    if data.startswith('lf:pay:'):
        await q.message.reply_text('Это старое напоминание. Если уже платил, не оплачивай повторно. Открой Mini App «Совпали» и проверь статус знакомства или покупки.'); return

@app.get('/internal/lifecycle-run')
def lifecycle_wake():
    auth=request.headers.get('Authorization','').strip(); token=auth[7:].strip() if auth.lower().startswith('bearer ') else ''
    try:
        from backup_secure import verify_github_oidc
        verify_github_oidc(token)
        if not ready.wait(15): return ({'ok':False,'reason':'bot-not-ready'},503)
        asyncio.run_coroutine_threadsafe(lf_run_once(bot.bot),loop)
        return {'ok':True,'scheduled':True}
    except Exception as e:
        print(f'[lifecycle] wake denied/failed: {type(e).__name__}: {e}',flush=True); return ('not found',404)

@app.get('/admin/lifecycle')
@need
def admin_lifecycle():
    today=lf_now().date().isoformat()+'%'
    sent=one('SELECT COUNT(*) c FROM lifecycle_sends WHERE created_at LIKE ?',(today,))['c']; total=one('SELECT COUNT(*) c FROM lifecycle_sends')['c']; opt=one('SELECT COUNT(*) c FROM lifecycle_prefs WHERE promo_enabled=0')['c']
    segs=many('SELECT segment,COUNT(*) c FROM lifecycle_sends GROUP BY segment ORDER BY c DESC')
    seg_html=''.join(f"<tr><td>{html.escape(r['segment'])}</td><td>{r['c']}</td></tr>" for r in segs)
    rs=many('''SELECT l.*,p.name FROM lifecycle_sends l LEFT JOIN profiles p ON p.user_id=l.user_id ORDER BY l.id DESC LIMIT 100''')
    recent=''.join(f"<tr><td>{r['id']}</td><td>{html.escape(r['name'] or '—')}</td><td>{html.escape(r['segment'])}</td><td>{html.escape(r['created_at'])}</td></tr>" for r in rs)
    state='включены' if setting('payments_live','0')=='1' else 'готовы, но ждут подключения Prodamus'
    return page(f"<h1>Воронки</h1><div class='grid'><div class='card'><div class='muted'>Сегодня</div><div class='big'>{sent}</div></div><div class='card'><div class='muted'>Всего касаний</div><div class='big'>{total}</div></div><div class='card'><div class='muted'>Отключили</div><div class='big'>{opt}</div></div></div><div class='card'><b>Продажные CTA:</b> {state}. Лимит: {LF_DAILY_CAP} сообщение в день на пользователя.</div><div class='card'><h3>Блоки</h3><table><tr><th>Блок</th><th>Отправлено</th></tr>{seg_html}</table></div><div class='card'><h3>Последние касания</h3><table><tr><th>ID</th><th>Пользователь</th><th>Блок</th><th>UTC</th></tr>{recent}</table></div>")
# -----------------------------------------------------------------------------
"""

s=s.replace(anchor,block+'\n'+anchor,1)
xm="bot.add_handler(CallbackQueryHandler(xm_callback,pattern=r'^xm:'))"
if xm not in s: raise SystemExit('[build] lifecycle: xm handler anchor not found')
s=s.replace(xm,xm+"\nbot.add_handler(CallbackQueryHandler(lf_callback,pattern=r'^lf:'))",1)
startup="await bot.initialize(); await bot.start(); xm_init_db(); asyncio.create_task(xm_maintenance(bot.bot))"
if startup not in s: raise SystemExit('[build] lifecycle: startup anchor not found')
s=s.replace(startup,startup+"; lf_init_db(); asyncio.create_task(lf_maintenance(bot.bot))",1)
for nav in ["<a href='/admin/matches'>Знакомства</a>","<a href='/admin/payments'>Оплаты</a>","<a href='/admin/settings'>Настройки</a>"]:
    if nav in s and "href='/admin/lifecycle'" not in s:
        s=s.replace(nav,nav+"<a href='/admin/lifecycle'>Воронки</a>",1); break
p.write_text(s,encoding='utf-8')
print('[build] lifecycle CRM funnels + daily wake endpoint applied',flush=True)
