"""Fix pair-browser visibility without mutating exclusive matching state.

Browsing is READ-ONLY: direction ownership, payment holds, and pending offers
must never silently hide otherwise compatible profiles. They only gate actual
requests/transactions. Adds useful diagnostic messages for two-account tests.
This patch executes last, AFTER all previous matchmaking and motion patches.
"""
from pathlib import Path

path=Path("app.py")
app=path.read_text(encoding="utf-8")
anchor="\nregister_pair_motion(app, globals())\n"
if app.count(anchor)!=1:
    raise SystemExit("[build] match-visibility: motion registration anchor missing")

block=r'''
# --- Browse compatibility independently of relationship reservations --------
# Auto-match and purchase rules remain unchanged. This function is for listing
# profile previews and signed compatibility pages, never making a transaction.
def mp_candidates(uid,limit=3):
    viewer=profile(int(uid))
    if not viewer:
        return []
    candidates=many("""SELECT p.*,u.tg_id,u.username,u.is_banned
                        FROM profiles p JOIN users u ON u.id=p.user_id
                        WHERE p.user_id<>? AND u.is_banned=0""",(int(uid),))
    strict,fallback=[],[]
    for c in candidates:
        try:
            if not eligible(viewer,c):
                continue
            if not xm_same_hub(viewer['city'],c['city']):
                continue
            item=(int(score(viewer,c)),c)
            if viewer['goal']==c['goal']:
                strict.append(item)
            else:
                fallback.append(item)
        except Exception as exc:
            print('[match-visibility] candidate error: '+type(exc).__name__+': '+str(exc)[:180],flush=True)
    strict.sort(key=lambda x:x[0],reverse=True)
    fallback.sort(key=lambda x:x[0],reverse=True)
    return (strict+fallback)[:max(1,int(limit))]

_mv_previous_mp_show_top3=mp_show_top3
async def mp_show_top3(message,u,p):
    found=mp_candidates(int(u['id']),3)
    if found:
        return await _mv_previous_mp_show_top3(message,u,p)
    rows=many("""SELECT p.gender,p.city,p.goal
                 FROM profiles p JOIN users u ON u.id=p.user_id
                 WHERE p.user_id<>? AND u.is_banned=0""",(int(u['id']),))
    if not rows:
        reason='В базе пока нет других заполненных анкет.'
    else:
        opposite=[c for c in rows if eligible(p,c)]
        local=[c for c in opposite if xm_same_hub(p['city'],c['city'])]
        if not opposite:
            reason=('Другие анкеты есть, но они не проходят фильтр пола. '
                    'В текущей версии подбор работает между мужчиной и женщиной. '
                    'Для проверки зарегистрируй один мужской и один женский профиль.')
        elif not local:
            reason=('Анкеты подходящего пола есть, но они в других городах '
                    'или система не распознала одинаковый город. '
                    'Проверь написание города в обоих профилях.')
        else:
            reason=('Анкеты подходящего пола и города найдены, но подбор не смог '
                    'подготовить карточку. Попробуй ещё раз и сообщи в поддержку.')
            print('[match-visibility] unexpected empty result after filters',flush=True)
    await message.reply_text(
        '💖 <b>Моя пара</b>\n\n'+reason+'\n\n'
        'При обычном просмотре анкеты не скрываются из-за уже '
        'отправленных предложений или ожидания ответа.',
        parse_mode=ParseMode.HTML,reply_markup=MENU)

MATCH_BROWSER_REVISION='read-only-browse-v1'
# ---------------------------------------------------------------------------
'''
app=app.replace(anchor,"\n"+block+anchor,1)
for needle in ["async def mp_show_top3(","async def mp_callback(","async def cabinet(","def mp_candidates(","def sm_claim_direction(","register_pair_motion(app, globals())"]:
    if needle not in app:
        raise SystemExit("[build] match-visibility: missing handler "+needle)
path.write_text(app,encoding="utf-8")
print("[build] match visibility corrected: reciprocal previews, diagnostics",flush=True)
