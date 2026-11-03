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

# The legacy "✨ Подбор" and old "💖 Мои пары" menu produce cand:* callbacks.
# Those buttons already sent to users must continue working after deployment.
start="    if data.startswith('cand:') and p:\n"
end="\n\nbot=Application.builder().token(TOKEN).build()"
i=s.find(start)
j=s.find(end,i)
if i<0 or j<i:
    raise SystemExit("[build] motion-navigation: legacy cand handler missing")

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
        if 'xm_same_hub' in globals() and not xm_same_hub(p['city'], c['city']):
            await q.message.reply_text('Анкета находится вне твоего региона. Обнови подбор.')
            return
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
            [InlineKeyboardButton('✨ Смотреть совместимость на сайте',url=url)],
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
s=s[:i]+legacy+s[j:]

# After each candidate selection in the newer "Моя пара" browser, show a
# short teaser. The full reasons/astro/numerology now live on the website.
entry="\nregister_pair_web(app, globals())\n"
if s.count(entry)!=1:
    raise SystemExit("[build] motion-navigation: route registration anchor missing")

override="""
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
            'Нажми <b>«Смотреть совместимость на сайте»</b> ниже. '
            'Первый шаг к знакомству остаётся добровольным.')

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
        rows=[[InlineKeyboardButton('✨ Смотреть совместимость на сайте',url=self.page_url)]]
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
s=s.replace(entry,"\n"+override+proxy_override+entry,1)

# The new "Моя пара" profile already has a link. Put it FIRST so it cannot be
# mistaken for an in-bot-only compatibility card.
old="""        pair_rows = [[main_button]]
        if web_url:
            pair_rows.append([InlineKeyboardButton('🌐 Открыть страницу пары', url=web_url)])
"""
new="""        pair_rows = []
        if web_url:
            pair_rows.append([InlineKeyboardButton('✨ Смотреть совместимость на сайте', url=web_url)])
        pair_rows.append([main_button])
"""
replace_once(old,new,"my-pair primary button")

# Diagnostic version marker used by /health to verify that the latest patches
# actually shipped, without revealing any private user profile.
s=s.replace("\nregister_pair_motion(app, globals())\n",
            "\nMOTION_BOT_NAV='nav2-all-flow-links'\nregister_pair_motion(app, globals())\n",1)

p.write_text(s,encoding="utf-8")
print("[build] motion navigation v2: legacy, my-pair and auto offers linked",flush=True)
