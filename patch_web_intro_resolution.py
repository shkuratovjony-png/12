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
