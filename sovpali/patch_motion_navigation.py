"""Make every real matchmaking surface hand off to the signed motion page.

Runs AFTER patch_pair_motion.py so the original app and all existing market,
onboarding, matching, exclusivity and payment patches stay intact.
"""
from pathlib import Path

p=Path("app.py")
s=p.read_text(encoding="utf-8")

def replace_once(old,new,tag):
    global s
    count=s.count(old)
    if count!=1:
        raise SystemExit(f"[build] motion-navigation: {tag} anchor count={count}")
    s=s.replace(old,new,1)

# Existing callbacks also reopen the same report in Telegram.
s=s.replace("InlineKeyboardButton('💞 Читать совместимость',url=url)",
            "pair_button('💞 Читать совместимость',url)")
s=s.replace('Открой совместимость на сайте, прочитай разбор',
            'Открой совместимость, прочитай разбор')

# The legacy "✨ Подбор" and old "💖 Мои пары" menu produce cand:* callbacks.
# Those buttons already sent to users must continue working after deployment.
import ast
start="    if data.startswith('cand:') and p:\n"
i=s.find(start)
if i<0:
    raise SystemExit("[build] motion-navigation: legacy cand handler not found")
source_line=s[:i].count("\n")+1
tree=ast.parse(s)
node=next((n for n in ast.walk(tree)
           if isinstance(n,ast.If) and n.lineno==source_line),None)
if node is None or node.end_lineno is None:
    raise SystemExit("[build] motion-navigation: cannot isolate cand callback safely")
lines=s.splitlines(keepends=True)
prefix="".join(lines[:node.lineno-1])
suffix="".join(lines[node.end_lineno:])

legacy="""    if data.startswith('cand:') and p:
        try:
            _, raw_cid, _old_score = data.split(':', 2)
            cid=int(raw_cid)
        except (ValueError, TypeError):
            await q.message.reply_text('Не удалось открыть анкету. Обнови подбор.')
            return
        c=profile(cid); uu=user(cid)
        if not c or not uu or int(uu['is_banned'] or 0) or not eligible(p,c):
            await q.message.reply_text('Анкета недоступна. Открой подбор ещё раз.')
            return
        # Other cities are allowed; only the actual eligibility gate applies.
        url=pair_link(PAIR_WEB_BASE_URL,int(u['id']),cid,FLASK_SECRET)
        if not url:
            await q.message.reply_text('Страница пары пока недоступна.')
            return
        score_value=int(score(p,c))
        age=_age(c['birth_date']) if '_age' in globals() else None
        label=html.escape(c['name'])
        caption=(f"💞 <b>{label} · {score_value}% совместимости</b>\\n"
                 f"{html.escape(c['city'])} · {html.escape(c['goal'])}\\n\\n"
                 "Персональный разбор, фотографии и причины совпадения теперь на сайте. "
                 "Нажми кнопку ниже — откроется страница именно вашей пары.")
        keyboard=InlineKeyboardMarkup([
            [pair_button('✨ Посмотреть совместимость',url)],
            [InlineKeyboardButton('💖 Вернуться к подбору',callback_data='mp:refresh:0')]
        ])
        try:
            audit(int(u['id']),'legacy_pair_open',{'candidate_user_id':cid,'score':score_value})
        except Exception: pass
        if c['photo_file_id']:
            try:
                await q.message.reply_photo(c['photo_file_id'],caption=caption,
                                             parse_mode=ParseMode.HTML,reply_markup=keyboard)
                return
            except Exception as exc:
                print(f'[motion-navigation] legacy photo unavailable: {exc}',flush=True)
        await q.message.reply_text(caption,parse_mode=ParseMode.HTML,reply_markup=keyboard)
        return
"""
s=prefix+legacy+suffix

# After each candidate selection in the newer "Моя пара" browser, show a
# short teaser. The full reasons/astro/numerology now live on the website.
entry="\nregister_pair_web(app, globals())\n"
if s.count(entry)!=1:
    raise SystemExit("[build] motion-navigation: route registration anchor missing")

override="""
from pair_miniapp import pair_button
import time as _sovpali_time
_sovpali_last_pair_list={}
# Both list buttons lead to the signed web page in ONE tap. The callback flow
# stays available for older messages and automatic offer status callbacks.
_motion_previous_mp_show_top3=mp_show_top3
async def mp_show_top3(message,u,p):
    uid=int(u['id'])
    tm=_sovpali_time.monotonic()
    if tm-_sovpali_last_pair_list.get(('my',uid),-100)>2:
        _sovpali_last_pair_list[('my',uid)]=tm
    else:
        return
    found=mp_candidates(uid,3)
    if not found:
        return await _motion_previous_mp_show_top3(message,u,p)
    intro=['💞 <b>Моя пара</b>','','Открой разбор в Telegram. Предложить общение можно после прочтения.']
    buttons=[]
    for idx,(sv,c) in enumerate(found,1):
        age=xm_age(c['birth_date'])
        person=c['name']+(f', {age}' if age else '')
        label=f'{idx}. {person} · {int(sv)}%'
        link=pair_link(PAIR_WEB_BASE_URL,int(u['id']),int(c['user_id']),FLASK_SECRET)
        if link:
            buttons.append([pair_button(label,link)])
        else:
            buttons.append([InlineKeyboardButton(label,callback_data=f'mp:view:{c["user_id"]}')])

    buttons.append([InlineKeyboardButton('🔄 Обновить подбор',callback_data='mp:refresh:0')])
    await message.reply_text('\\n'.join(intro),parse_mode=ParseMode.HTML,
                             reply_markup=InlineKeyboardMarkup(buttons))

_motion_previous_pairs_view=pairs_view
async def pairs_view(message,u,p,show_intro=False):
    # Reuse final directional selection; the old Bot "Мои пары" button
    # must not reveal reverse matches excluded from the Mini App.
    found=mp_candidates(int(u['id']),3)
    if not found:
        return await _motion_previous_pairs_view(message,u,p,show_intro)
    buttons=[]
    for idx,(sv,c) in enumerate(found,1):
        age=xm_age(c['birth_date'])
        person=c['name']+(f', {age}' if age else '')
        link=pair_link(PAIR_WEB_BASE_URL,int(u['id']),int(c['user_id']),FLASK_SECRET)
        label=f'{idx}. {person} · {sv}%'
        if link:
            buttons.append([pair_button(label,link)])
        else:
            buttons.append([InlineKeyboardButton(label,callback_data=f'cand:{c["user_id"]}:{sv}')])

    await message.reply_text('💞 <b>Подбор совместимости</b>\\n\\nПосмотри совместимость в Telegram, затем предложи общение там же.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(buttons))

# Brief summary only — same real score, while long report is available on the web.
def mp_card_text(viewer, candidate, score_value, rank=None):
    age=xm_age(candidate['birth_date'])
    name_age=html.escape(candidate['name'])+(f', {age}' if age else '')
    prefix=f'ТОП-{rank} · ' if rank else ''
    return (f'💖 <b>{prefix}{int(score_value)}% совместимости</b>\\n\\n'
            f'<b>{name_age}</b> · {html.escape(candidate["city"])}\\n'
            f'Цель: {html.escape(candidate["goal"])}\\n\\n'
            '✨ Подробные причины, совместимость по ценностям, астрологии и '
            'нумерологии — на вашей персональной странице.\\n\\n'
            'Персональный разбор доступен по ссылке: '
            +'<a href="'+html.escape(pair_link(PAIR_WEB_BASE_URL,int(viewer['user_id']),int(candidate['user_id']),FLASK_SECRET),quote=True)+'">✨ Смотреть совместимость на сайте</a>')

# Automatic offers also use the same compact presentation.
def xm_personal_copy(viewer, candidate, score_value):
    age=xm_age(candidate['birth_date'])
    name_age=html.escape(candidate['name'])+(f', {age}' if age else '')
    return (f'💞 <b>Совпадение · {int(score_value)}%</b>\\n\\n'
            f'<b>{name_age}</b> · {html.escape(candidate["city"])}\\n'
            f'Цель: {html.escape(candidate["goal"])}\\n\\n'
            '✨ Полный персональный разбор уже готов на сайте. '
            'Там есть причины совпадения и подробные расчёты.\\n\\n'
            'Ты сам решаешь, хочешь ли предложить знакомство.\\\n'
            +('<a href="'+html.escape(pair_link(PAIR_WEB_BASE_URL,int(viewer['user_id']),int(candidate['user_id']),FLASK_SECRET),quote=True)+'">✨ Смотреть разбор на сайте</a>'
              if PAIR_WEB_BASE_URL else ''))

def xm_interest_copy(subject, interested, score_value):
    age=xm_age(interested['birth_date'])
    name_age=html.escape(interested['name'])+(f', {age}' if age else '')
    return (f'💌 <b>{name_age} предлагает познакомиться</b>\\n'
            f'Индекс пары: <b>{int(score_value)}%</b>.\\n\\n'
            'На сайте доступен подробный разбор. '
            'Контакт не раскрывается без взаимного согласия.\\\n'
            +('<a href="'+html.escape(pair_link(PAIR_WEB_BASE_URL,int(subject['user_id']),int(interested['user_id']),FLASK_SECRET),quote=True)+'">✨ Смотреть разбор на сайте</a>'
              if PAIR_WEB_BASE_URL else ''))
"""
s=s.replace(entry,"\n"+override+entry,1)

# The last matching hook uses a bot proxy so all legacy layers can keep their
# own offer logic and concurrency controls. No source-string matching required.
proxy_override = """
class _MotionSendProxy:
    def __init__(self, delegate, viewer_uid, candidate_uid):
        self.delegate=delegate
        self.page_url=pair_link(PAIR_WEB_BASE_URL,viewer_uid,candidate_uid,FLASK_SECRET)

    def __getattr__(self,name):
        return getattr(self.delegate,name)

    def _attach(self, kwargs):
        if not self.page_url:
            return kwargs
        old=kwargs.get('reply_markup')
        rows=[[pair_button('✨ Посмотреть совместимость',self.page_url)]]
        if old is not None and hasattr(old,'inline_keyboard'):
            rows.extend([list(row) for row in old.inline_keyboard])
        kwargs['reply_markup']=InlineKeyboardMarkup(rows)
        return kwargs

    async def send_photo(self,*args,**kwargs):
        return await self.delegate.send_photo(*args,**self._attach(kwargs))

    async def send_message(self,*args,**kwargs):
        return await self.delegate.send_message(*args,**self._attach(kwargs))

_motion_old_send_candidate=xm_send_candidate
async def xm_send_candidate(bot_api, offer_id, viewer, candidate, score_value):
    proxy=_MotionSendProxy(bot_api,int(viewer['user_id']),int(candidate['user_id']))
    return await _motion_old_send_candidate(proxy,offer_id,viewer,candidate,score_value)

"""
s=s.replace(entry,"\n"+proxy_override+entry,1)

# The new "Моя пара" profile already has a link. Put it FIRST so it cannot be
# mistaken for an in-bot-only compatibility card.
old="""        pair_rows = [[main_button]]
        if web_url:
            pair_rows.append([InlineKeyboardButton('🌐 Открыть страницу пары', url=web_url)])
"""
new="""        pair_rows = []
        if web_url:
            pair_rows.append([pair_button('✨ Посмотреть совместимость',web_url)])
        pair_rows.append([main_button])
"""
if old in s:
    replace_once(old,new,"my-pair primary button")
else:
    at=s.find("Открыть страницу пары")
    print("[build] motion-navigation: web button already present or markup different; at="+str(at),flush=True)


# Diagnostic version marker used by /health to verify that the latest patches
# actually shipped, without revealing any private user profile.
s=s.replace("\nregister_pair_motion(app, globals())\n",
            "\nMOTION_BOT_NAV='nav2-all-flow-links'\nregister_pair_motion(app, globals())\n",1)

for symbol in ("async def mp_callback(", "async def xm_send_candidate(",
               "async def xm_callback(", "async def mp_show_top3(",
               "bot.add_handler(CallbackQueryHandler(mp_callback"):
    if symbol not in s:
        raise SystemExit("[build] motion-navigation: required matching handler lost: "+symbol)

p.write_text(s,encoding="utf-8")
print("[build] motion navigation v2: legacy, my-pair and auto offers linked",flush=True)
