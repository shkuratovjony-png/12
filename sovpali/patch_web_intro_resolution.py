"""Connect declined/accepted real Telegram consent to verified web contact orders."""
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
        # Free old requests must not be affected if optional payment tables fail.
        print("[web-intro] resolution sync "+type(exc).__name__,flush=True)
        return False
"""
s=s.replace(anchor,"\n"+inject+anchor,1)
changes=(
    ('execute("UPDATE communication_requests SET status=\\'declined\\',responded_at=? WHERE id=?",(now(),req_id))',
     'execute("UPDATE communication_requests SET status=\\'declined\\',responded_at=? WHERE id=?",(now(),req_id))\n        web_contact_resolution(requester_uid,target_uid,False)'),
    ('execute("UPDATE communication_requests SET status=\\'accepted\\',responded_at=? WHERE id=?",(now(),req_id))',
     'execute("UPDATE communication_requests SET status=\\'accepted\\',responded_at=? WHERE id=?",(now(),req_id))\n        web_contact_resolution(requester_uid,target_uid,True)'),
)
for old,new in changes:
    if s.count(old)!=1:
        raise SystemExit("[build] expected exactly one consent status update for paid intro hook: "+old[:65])
    s=s.replace(old,new,1)
p.write_text(s,encoding="utf-8")
print("[build] web-paid introduction resolution & replacement credits hooked into Telegram consent",flush=True)
