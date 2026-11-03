"""Register coach website and add a follow-up after confirmed contact delivery.

The old free/manual and exclusive/automatic acceptance callbacks are modified
at the exact success send point. Contact delivery remains first; subsequent
optional product invitation cannot prevent the actual contact being delivered.
"""
from pathlib import Path
p=Path("app.py")
s=p.read_text(encoding="utf-8")
anchor="\nregister_pair_motion(app, globals())\n"
if s.count(anchor)!=1:
    raise SystemExit("[build] coach: pair motion registration not unique")
block=r'''
# --- Post-consent personalized Conversation Workshop ------------------------
from coach_web import register_coach,coach_link
from coach_offers import CoachOffers
COACH_OFFERS=CoachOffers(globals())
async def coach_after_contact(bot_api,buyer_uid,target_uid):
    try:
        return await COACH_OFFERS.offer(bot_api,buyer_uid,target_uid)
    except Exception as exc:
        print("[coach] optional invitation error "+type(exc).__name__,flush=True)
        return False

def coach_store_answers(buyer_uid,target_uid,answers):
    return COACH_OFFERS.save(buyer_uid,target_uid,answers)

def coach_load_answers(buyer_uid,target_uid):
    return COACH_OFFERS.load(buyer_uid,target_uid)

COACH_REVISION="free-first-reply900-v2"
register_coach(app,globals())
# ---------------------------------------------------------------------------
'''
s=s.replace(anchor,"\n"+block+anchor,1)

# The current manual communication flow calls this after the requester is
# notified of mutual consent and sent a "write in Telegram" button.
manual="""                reply_markup=ioc_contact_keyboard(target_uid),
            )
"""
if s.count(manual)!=1:
    raise SystemExit("[build] coach: initiator manual contact release marker missing/duplicated")
s=s.replace(manual,manual+"            await coach_after_contact(ctx.bot, requester_uid, target_uid)\n",1)

# The current exclusive matching flow reveals contacts to RECIPIENT (initiator)
# after subject accepts. Send the upsell only after this message succeeds.
auto="reply_markup=ar_contact_keyboard(subject_uid, offer_id))"
if s.count(auto)!=1:
    raise SystemExit("[build] coach: initiator exclusive contact marker missing/duplicated")
s=s.replace(auto,auto+"; await coach_after_contact(ctx.bot, recipient_uid, subject_uid)",1)

# Fail the build if we somehow touch an outbound request or accept branch
# incorrectly, instead of compromising users' existing contact flow.
for required in [
    "async def coach_after_contact(",
    "async def cr_callback(",
    "async def xm_callback(",
    "async def mp_callback(",
    "register_coach(app,globals())",
    "bot.add_handler(CallbackQueryHandler(cr_callback",
    "bot.add_handler(CallbackQueryHandler(xm_callback",
    "coach_after_contact(ctx.bot, requester_uid, target_uid)",
    "coach_after_contact(ctx.bot, recipient_uid, subject_uid)",
]:
    if required not in s:
        raise SystemExit("[build] coach: missing validated handler "+required)
p.write_text(s,encoding="utf-8")
print("[build] coach: website, quiz, demo and post-contact invite attached",flush=True)
