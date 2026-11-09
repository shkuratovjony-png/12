"""Read-only browsing respects permanent automatic pair direction.

A new pair is not reserved merely by viewing a listing, but once profile B
has been auto-delivered to A, the reverse B->A is excluded from B's top-three.
Payment/communication locks do not hide other unassigned candidates.
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
def mp_candidates(uid,limit=3,excluded_ids=None):
    viewer=profile(int(uid))
    if not viewer:
        return []
    # User-initiated skips affect only the Mini App shortlist, never the
    # automatic delivery engine, existing paid requests or reciprocal rules.
    excluded={int(cid) for cid in (excluded_ids or ())}
    candidates=many("""SELECT p.*,u.tg_id,u.username,u.is_banned
                        FROM profiles p JOIN users u ON u.id=p.user_id
                        WHERE p.user_id<>? AND u.is_banned=0""",(int(uid),))
    strict,fallback=[],[]
    for c in candidates:
        try:
            if int(c['user_id']) in excluded:
                continue
            if not eligible(viewer,c):
                continue
            # The direction of an already-sent automatic match is permanent.
            # A sees B if the offer was sent to A. B must see OTHER people,
            # not the same A in reverse. Browsing itself does not claim pairs.
            engine=globals().get("MATCH_PUSH_ENGINE")
            if engine is not None:
                owner=engine.pair_owner(uid,c['user_id'])
                if owner is not None and int(owner)!=int(uid):
                    continue
                active_guard=getattr(engine,"target_in_active_request",None)
                if callable(active_guard) and active_guard(int(c["user_id"])):
                    # A buyer cannot initiate an introduction to a person
                    # waiting on a different paid/free consent request.
                    continue
            # Regional preference is optional, not a visibility gate.
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
        if not opposite:
            reason=('Другие анкеты есть, но они не проходят фильтр пола. '
                    'В текущей версии подбор работает между мужчиной и женщиной. '
                    'Для проверки зарегистрируй один мужской и один женский профиль.')
        else:
            reason=('Подходящие люди есть, но часть пар уже была отправлена '
                    'в одном направлении другим пользователям. '
                    'Когда появится новая подходящая анкета, бот сообщит.')
            print('[match-visibility] unexpected empty result after filters',flush=True)
    await message.reply_text(
        '💖 <b>Моя пара</b>\n\n'+reason+'\n\n'
        'Один и тот же человек не появляется в обратной рассылке, '
        'если ваша анкета уже была предложена ему.',
        parse_mode=ParseMode.HTML,reply_markup=MENU)

MATCH_BROWSER_REVISION='directional-browse-v2'
# ---------------------------------------------------------------------------
'''
app=app.replace(anchor,"\n"+block+anchor,1)
for needle in ["async def mp_show_top3(","async def mp_callback(","async def cabinet(","def mp_candidates(","def sm_claim_direction(","register_pair_motion(app, globals())"]:
    if needle not in app:
        raise SystemExit("[build] match-visibility: missing handler "+needle)
path.write_text(app,encoding="utf-8")
print("[build] match visibility: one-way auto-assignment respected in top-three",flush=True)
