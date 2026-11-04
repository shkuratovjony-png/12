"""Keep automatic Telegram matches from silently disappearing.

The live "Моя пара" browser is read-only and never reserves a pairing. This
patch fixes delivery *separately*: recent signups are prioritised, old browsing
locks are removed, night-time matches are retried in the next permitted window,
and safe aggregate diagnostics report why notifications were not delivered.

No forced messages at night, no payment changes, no duplicate notifications.
"""
from pathlib import Path

target=Path("app.py")
src=target.read_text(encoding="utf-8")
anchor="\nregister_pair_motion(app, globals())\n"
if src.count(anchor)!=1:
    raise SystemExit("[build] auto-recovery: registration anchor missing")

block=r'''
# --- Automatic matching recovery, independent of the My Pair browser --------
# Viewing a profile does not constitute an intent to reserve a contact.
# Remove legacy reservation locks created by read-only My Pair page visits.
def am_cleanup_legacy_browse_locks():
    try:
        execute("DELETE FROM pair_direction_locks WHERE source='my_pair'")
    except Exception as exc:
        print("[auto-match] browse-lock cleanup: "+type(exc).__name__,flush=True)

def am_possible_count():
    # Aggregates ONLY. Don't print names, dates of birth, Telegram IDs or tokens.
    rows=many("""SELECT p.*,u.is_banned
                 FROM profiles p JOIN users u ON u.id=p.user_id
                 WHERE u.is_banned=0""")
    same_city=same_goal=high=eligible_pairs=available=0
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            try:
                if not eligible(a,b):
                    continue
                eligible_pairs+=1
                if xm_same_hub(a['city'],b['city']):
                    same_city+=1
                if a['goal']!=b['goal']:
                    continue
                same_goal+=1
                sv=int(score(a,b))
                if sv<sm_int('auto_match_min_score',86) and a['priority']!=b['priority']:
                    continue
                high+=1
                if not xm_pair_seen(a['user_id'],b['user_id']) and not xm_busy(a['user_id']) and not xm_busy(b['user_id']):
                    available+=1
            except Exception as exc:
                print("[auto-match] aggregate check: "+type(exc).__name__,flush=True)
    return {
       "profiles":len(rows),
       "eligible_gender_pairs":eligible_pairs,
       "same_city_pairs":same_city,
       "same_goal_pairs":same_goal,
       "auto_eligible_pairs":high,
       "unoffered_free_pairs":available,
       "minimum_score":sm_int('auto_match_min_score',86),
       "quiet_hours":not (10 <= (sm_now()+timedelta(hours=5)).hour < 22),
    }

@ app.get('/admin/auto-match-status')
@ need
def am_admin_diagnostics():
    data=am_possible_count()
    body="<h1>Автоматический подбор — диагностика</h1><div class='card'><table>"
    labels=[
       ('profiles','Активных анкет'),
       ('eligible_gender_pairs','Пар по полу'),
       ('same_city_pairs','Пар с дополнительным бонусом за один город'),
       ('same_goal_pairs','Пар с одинаковыми целями (вся Россия)'),
       ('auto_eligible_pairs','Пар для автоуведомлений: высокий индекс или одинаковые цели и приоритеты'),
       ('unoffered_free_pairs','Пар без активного знакомства или старой истории'),
       ('minimum_score','Порог для автоуведомления, %'),
       ('quiet_hours','Ночное ограничение сейчас активно'),
    ]
    for key,label in labels:
        value=data[key]
        if isinstance(value,bool):value='да' if value else 'нет'
        body+='<tr><td>'+html.escape(label)+'</td><td>'+html.escape(str(value))+'</td></tr>'
    body+='</table></div><p>Только агрегированные числа. Личные данные не раскрываются.</p>'
    return page(body)

# Keep cleanup, 24-hour offer expiry and normal individual notification limit.
# The latest signup is checked first so its match goes to an existing person.
async def xm_maintenance(bot_api):
    await asyncio.sleep(12)
    first=True
    while True:
        try:
            am_cleanup_legacy_browse_locks()
            stamp=xm_iso()
            expired=many("""SELECT * FROM match_offers
                            WHERE status IN ('offered','interested')
                              AND expires_at IS NOT NULL AND expires_at<=?
                            ORDER BY id LIMIT 100""",(stamp,))
            released=set()
            for r in expired:
                execute("""UPDATE match_offers SET status='expired',closed_at=?
                           WHERE id=? AND status IN ('offered','interested')""",
                        (stamp,r['id']))
                released.add(int(r['subject_user_id']))
                released.add(int(r['recipient_user_id']))
                try:audit(int(r['recipient_user_id']),'match_expired',{'offer_id':r['id']})
                except Exception:pass
            if first:
                print("[auto-match] startup summary "+str(am_possible_count()),flush=True)
                first=False
            # Recent sign-ups should be sources; older compatible users receive
            # notification, but only during configured quiet-hour window.
            ids=[]
            rs=many("""SELECT user_id FROM profiles
                        ORDER BY completed_at DESC LIMIT 250""")
            for r in rs:
                uid=int(r['user_id'])
                if uid not in ids and not xm_busy(uid):
                    ids.append(uid)
                if len(ids)>=XM_BATCH_SIZE:
                    break
            for uid in released:
                if uid not in ids:
                    ids.insert(0,uid)
            sent=0
            for uid in ids:
                if sent>=XM_BATCH_SIZE: break
                try:
                    if await xm_try_offer(bot_api,uid):
                        sent+=1
                        await asyncio.sleep(.25)
                except Exception as exc:
                    print('[auto-match] retry failed: '+type(exc).__name__+': '+str(exc)[:100],flush=True)
            if sent:
                print('[auto-match] delivered offers='+str(sent),flush=True)
        except Exception as exc:
            print('[auto-match] maintenance error '+type(exc).__name__+': '+str(exc)[:140],flush=True)
        await asyncio.sleep(5*60)

MATCH_AUTO_REVISION="recovery-v1"
# -----------------------------------------------------------------------------
'''
# Normalize Python decorator style; @ app.get is legal but uncommon.
block=block.replace("@ app.get(","@app.get(").replace("@ need\n","@need\n")
src=src.replace(anchor,"\n"+block+anchor,1)
for name in ["async def xm_try_offer(","async def xm_profile_ready(","async def mp_show_top3(","async def xm_maintenance(","def sm_auto_recipient_allowed("]:
    if name not in src:
        raise SystemExit("[build] auto-recovery: missing "+name)
target.write_text(src,encoding="utf-8")
print("[build] automatic matching recovery installed; no nighttime pushes",flush=True)
