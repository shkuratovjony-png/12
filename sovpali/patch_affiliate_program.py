"""Wire referral capture on /start and register private affiliate/admin routes."""
from pathlib import Path
p=Path("app.py")
s=p.read_text(encoding="utf-8")
anchor="    u=upsert_user(update.effective_user)\n    if u['is_banned']:"
if s.count(anchor)!=1:raise SystemExit("Referrals: /start handler not found")
s=s.replace(anchor,"""    u=upsert_user(update.effective_user)
    if ctx.args:
        try:
            from affiliate_program import register_start
            register_start(db,u,ctx.args)
        except Exception as exc:
            print('[affiliate] referral capture deferred: '+type(exc).__name__,flush=True)
    if u['is_banned']:""",1)
marker="if __name__=='__main__':"
if s.count(marker)!=1:raise SystemExit("Referrals: app entry not found")
s=s.replace(marker,"""from affiliate_program import mount as mount_affiliates
mount_affiliates(app,globals())

"""+marker,1)
p.write_text(s,encoding="utf-8")
print("[build] referral deep links and Mini App affiliate APIs installed",flush=True)
