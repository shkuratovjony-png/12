"""Hook conversion reminder into the real Telegram bot and motion server.

Executed after patch_match_push_v2.py and all original matching/payment patches.
"""
from pathlib import Path

path=Path("app.py")
src=path.read_text(encoding="utf-8")

anchor="\nregister_pair_motion(app, globals())\n"
if src.count(anchor)!=1:
    raise SystemExit("[build] pair-followup: motion registration anchor missing")

block=r'''
# --- Real engaged reads -> one honest 30-minute conversion follow-up ----------
from pair_conversion import PairConversion
PAIR_CONVERSION=PairConversion(globals())

def pair_followup_read(viewer_uid,candidate_uid):
    return PAIR_CONVERSION.record(viewer_uid,candidate_uid)

def pair_followup_checkout(viewer_uid,candidate_uid):
    return PAIR_CONVERSION.mark_checkout(viewer_uid,candidate_uid)

PAIR_FOLLOWUP_REVISION="read30-checkout-v1"
# -----------------------------------------------------------------------------
'''
src=src.replace(anchor,"\n"+block+anchor,1)

old="asyncio.create_task(lf_maintenance(bot.bot))"
new=old+"; asyncio.create_task(PAIR_CONVERSION.maintain(bot.bot))"
if src.count(old)!=1:
    raise SystemExit("[build] pair-followup: startup scheduler anchor missing")
src=src.replace(old,new,1)

for required in [
    "async def xm_profile_ready(", "async def xm_maintenance(",
    "async def lf_maintenance(", "async def mp_callback(",
    "bot.add_handler(CallbackQueryHandler(xm_callback",
    "bot.add_handler(CallbackQueryHandler(lf_callback",
    "register_pair_motion(app, globals())",
]:
    if required not in src:
        raise SystemExit("[build] pair-followup: existing handler lost "+required)
path.write_text(src,encoding="utf-8")
print("[build] pair follow-up: read -> 30 minutes -> short checkout; no fake expiry",flush=True)
