"""Install the SBP-only Ozon checkout demonstration without touching live bot.

Leave all purchases disabled until Ozon Pay is fully approved, provider test
credentials are configured via Render Secrets and an authenticated callback is
implemented and tested. User-facing view is deliberately in no-charge mode.
"""
from pathlib import Path
p=Path("app.py")
s=p.read_text(encoding="utf-8")
anchor="\nregister_pair_motion(app, globals())\n"
if s.count(anchor)!=1:
    raise SystemExit("[build] billing preview: motion registration anchor missing")
insert="\nfrom ozon_billing_preview import register_ozon_billing_preview\nregister_ozon_billing_preview(app, globals())\n"
s=s.replace(anchor,insert+anchor)
p.write_text(s,encoding="utf-8")
print("[build] Ozon Pay SBP-only checkout preview installed; real charges disabled",flush=True)
