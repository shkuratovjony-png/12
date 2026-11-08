"""Connect recipient consent to the matching bank-verified web introduction."""
from pathlib import Path
p=Path("app.py")
s=p.read_text(encoding="utf-8")
anchor="\nregister_pair_motion(app, globals())\n"
if s.count(anchor)!=1:
    raise SystemExit("[build] web intro resolution anchor missing")
inject="""
from web_intro_fulfillment import resolve_intro as _resolve_web_intro
def web_contact_resolution(buyer,target,accepted):
    try:
        return _resolve_web_intro(globals(),buyer,target,accepted)
    except Exception as exc:
        print("[web-intro] resolution sync "+type(exc).__name__,flush=True)
        return False
"""
s=s.replace(anchor,"\n"+inject+anchor,1)
# Protect consent and bank-paid entitlements from stale button clicks.
# An unanswered request expires after 24 hours; the original Telegram
# buttons might still be visible long afterwards.
reply_guard="""    if str(row['status']) == 'pending':
        try:
            ip_cleanup_expired()
            row = one('SELECT * FROM communication_requests WHERE id=?',(req_id,)) or row
            sent_at = datetime.fromisoformat(str(row['created_at']).replace('Z','+00:00')).replace(tzinfo=None)
            if datetime.utcnow() - sent_at >= timedelta(hours=24):
                execute("UPDATE communication_requests SET status='expired',responded_at=? WHERE id=? AND status='pending'",(now(),req_id))
                row = one('SELECT * FROM communication_requests WHERE id=?',(req_id,)) or row
        except Exception as exc:
            print('[communication] response deadline check '+type(exc).__name__,flush=True)
            await q.message.reply_text('Не получилось проверить срок запроса. Попробуй чуть позже.')
            return
"""
target="""    if str(row['status']) != 'pending':
        await q.message.reply_text('На этот запрос уже был дан ответ.')"""
if s.count(target)!=1:raise SystemExit("Reply deadline guard anchor missing or duplicated")
s=s.replace(target,reply_guard+target,1)

decline="""execute("UPDATE communication_requests SET status='declined',responded_at=? WHERE id=?",(now(),req_id))"""
accept="""execute("UPDATE communication_requests SET status='accepted',responded_at=? WHERE id=?",(now(),req_id))"""
for old, new, result in (
    (decline, "web_contact_resolution(requester_uid,target_uid,False)", "decline"),
    (accept, "web_contact_resolution(requester_uid,target_uid,True)", "accept"),
):
    if s.count(old)!=1:
        raise SystemExit("[build] expected one Telegram "+result+" update")
    s=s.replace(old,old+"\n        "+new,1)
p.write_text(s,encoding="utf-8")
print("[build] paid web introduction resolution linked to Telegram reply",flush=True)
