"""Wire standalone Ozon checkout to the website, keeping Telegram untouched."""
from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")
anchor = "\nregister_pair_motion(app, globals())\n"
if s.count(anchor) != 1:
    raise SystemExit("[build] Ozon web checkout: pair motion registration missing or duplicated")
inject = """
from web_contact_checkout import register_contact_product
register_contact_product(app, globals())
from web_checkout_auth import register_web_checkout_auth
register_web_checkout_auth(app, globals())
from web_premium_checkout import register_web_premium
register_web_premium(app, globals())
from web_coach_checkout import register_web_coach
register_web_coach(app, globals())
from web_workshop import register_workshop
register_workshop(app, globals())
from ozon_web_checkout import register_ozon_web_checkout
register_ozon_web_checkout(app, globals())
from web_test_drive import register_test_drive
register_test_drive(app, globals())
"""
if "register_ozon_web_checkout(app, globals())" in s:
    raise SystemExit("[build] Ozon web checkout registered twice")
s = s.replace(anchor, "\n" + inject + anchor, 1)
p.write_text(s, encoding="utf-8")
print("[build] standalone Ozon web checkout connected without modifying Telegram", flush=True)
