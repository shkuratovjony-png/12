"""Wire voluntary friend bonuses after all historical patches are applied.

Build-only transformation. Existing 30% affiliate URLs remain untouched.
"""
from pathlib import Path

p = Path("app.py")
source = p.read_text(encoding="utf-8")

anchor = """    if ctx.args:
        try:
            from affiliate_program import register_start"""
assert source.count(anchor) == 1, "Expected existing /start affiliate link hook"

new_hook = """    if ctx.args:
        try:
            from friend_invites import claim_start as friend_claim_start
            friend_claim_start(db, u, ctx.args)
        except Exception as exc:
            print('[friends] first-touch deferred: '+type(exc).__name__, flush=True)
    if ctx.args:
        try:
            from affiliate_program import register_start"""
source = source.replace(anchor, new_hook, 1)

anchor = "if __name__=='__main__':"
assert source.count(anchor) == 1, "Expected one app startup anchor"
mount = """# User-created profile grants qualify only verified new friend invites.
from friend_invites import mount as mount_friend_invites
from friend_invites import profile_completed as friend_profile_completed
_friends_previous_save_profile = save_profile

def save_profile(uid, data):
    _friends_previous_save_profile(uid, data)
    try:
        friend_profile_completed(db, int(uid))
    except Exception as exc:
        # Do not discard a saved profile if optional bonus reconciliation fails.
        print('[friends] profile reward retry needed: '+type(exc).__name__, flush=True)

mount_friend_invites(app, globals())

"""
source = source.replace(anchor, mount + anchor, 1)
p.write_text(source, encoding="utf-8")
print("[build] voluntary three-friend bonus mounted; paid affiliates unchanged", flush=True)
