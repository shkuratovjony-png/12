from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

marker = '# === SOVPALI_PROMO_ALLOWLIST ==='
if marker in s:
    print('promo allowlist patch already applied')
    raise SystemExit(0)

# 1) Add imports used by the promo handler.
s = s.replace(
    'import asyncio, html, os, sqlite3, threading',
    'import asyncio, html, os, sqlite3, threading, random, time',
    1,
)

# 2) Add configuration. The feature is OFF unless explicitly enabled.
config_anchor = "PORT=int(os.getenv('PORT','10000'))\n"
config_block = r'''PORT=int(os.getenv('PORT','10000'))

# === SOVPALI_PROMO_ALLOWLIST ===
def _parse_int_set(raw):
    out=set()
    for part in (raw or '').split(','):
        part=part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            print(f'[promo] ignored invalid chat id: {part!r}', flush=True)
    return out

PROMO_ENABLED=os.getenv('PROMO_ENABLED','0').strip().lower() in {'1','true','yes','on'}
PROMO_APPROVED_CHAT_IDS=_parse_int_set(os.getenv('PROMO_APPROVED_CHAT_IDS',''))
PROMO_COOLDOWN_SEC=max(300,int(os.getenv('PROMO_COOLDOWN_SEC','7200')))
PROMO_DAILY_LIMIT=max(1,int(os.getenv('PROMO_DAILY_LIMIT','3')))
PROMO_MIN_MESSAGE_LEN=max(8,int(os.getenv('PROMO_MIN_MESSAGE_LEN','16')))
PROMO_TRIGGER_WORDS=tuple(x.strip().lower() for x in os.getenv(
    'PROMO_TRIGGER_WORDS',
    'знакомств,знакомиться,познакомиться,отношени,любов,пара,совместим,натальн,астролог,гороскоп,свидани,одиноч'
).split(',') if x.strip())

_promo_last_sent={}
_promo_daily_count={}

PROMO_REPLIES=(
    'Я бот «Совпали». Мы как раз подбираем знакомства не только по анкетам, а ещё по целям, ценностям и базовой совместимости. Если интересно — можно открыть мой профиль.',
    'Я из «Совпали» 🙂 У нас идея как раз про знакомства по совместимости: сначала цели и ценности, потом базовые астрологические параметры. Подробности есть в моём профиле.',
    'Тема прямо про «Совпали» 🙂 Я бот проекта знакомств, где пары сравниваются по целям отношений, ценностям и базовой совместимости. Можно посмотреть через мой профиль.',
)
'''
if config_anchor not in s:
    raise SystemExit('promo patch: PORT anchor not found')
s = s.replace(config_anchor, config_block, 1)

# 3) Add a transparent, rate-limited contextual responder.
handler_anchor = "bot=Application.builder().token(TOKEN).build()\n"
handler_block = r'''async def promo_context_reply(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    """Auto-reply only in explicitly approved chats.

    The bot does not DM users, does not post links, and does not operate in chats
    outside PROMO_APPROVED_CHAT_IDS. Replies are deliberately transparent that
    the sender is the «Совпали» bot.
    """
    if not PROMO_ENABLED or not PROMO_APPROVED_CHAT_IDS:
        return
    msg=update.effective_message
    chat=update.effective_chat
    usr=update.effective_user
    if not msg or not chat or not usr or usr.is_bot:
        return
    if chat.id not in PROMO_APPROVED_CHAT_IDS:
        return
    text=(msg.text or msg.caption or '').strip()
    if len(text)<PROMO_MIN_MESSAGE_LEN:
        return
    low=text.lower()
    if not any(word in low for word in PROMO_TRIGGER_WORDS):
        return

    now_ts=time.time()
    day=datetime.now().date().isoformat()
    day_key=(chat.id,day)
    if _promo_daily_count.get(day_key,0)>=PROMO_DAILY_LIMIT:
        return
    if now_ts-_promo_last_sent.get(chat.id,0)<PROMO_COOLDOWN_SEC:
        return

    # Reserve the slot before sending, so simultaneous updates cannot flood a chat.
    _promo_last_sent[chat.id]=now_ts
    _promo_daily_count[day_key]=_promo_daily_count.get(day_key,0)+1
    try:
        await msg.reply_text(random.choice(PROMO_REPLIES), disable_web_page_preview=True)
        print(f'[promo] replied in approved chat {chat.id}', flush=True)
    except Exception as e:
        # Roll back daily quota on failed sends.
        _promo_daily_count[day_key]=max(0,_promo_daily_count.get(day_key,1)-1)
        print(f'[promo] send failed in chat {chat.id}: {e}', flush=True)

bot=Application.builder().token(TOKEN).build()
'''
if handler_anchor not in s:
    raise SystemExit('promo patch: bot builder anchor not found')
s = s.replace(handler_anchor, handler_block, 1)

# 4) Register in a late handler group so normal product conversations keep priority.
register_anchor = "bot.add_handler(MessageHandler(filters.Regex(r'^(💖 Мои пары|👤 Мой профиль|✨ Подбор|💬 Чаты|⚙️ Ещё)$'),cabinet))\n"
register_block = register_anchor + "bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,promo_context_reply),group=50)\n"
if register_anchor not in s:
    raise SystemExit('promo patch: handler registration anchor not found')
s = s.replace(register_anchor, register_block, 1)

p.write_text(s, encoding='utf-8')
print('promo allowlist patch applied')
