"""Apply the BotFather-equivalent public profile copy at bot startup."""
from pathlib import Path

p=Path("app.py")
s=p.read_text(encoding="utf-8")
anchor="    ready.set()\n"
if s.count(anchor)!=1:
    raise SystemExit("Bot branding patch: ready marker not unique")
injection="""    try:
        from bot_branding import sync_bot_profile
        await sync_bot_profile(bot.bot)
    except Exception as exc:
        print("[bot-profile] profile update error: "+type(exc).__name__,flush=True)
"""
s=s.replace(anchor,injection+anchor,1)
p.write_text(s,encoding="utf-8")
print("[build] public BotFather fields sync connected",flush=True)
