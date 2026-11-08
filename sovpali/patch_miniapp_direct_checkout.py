"""Mount direct Mini App -> Ozon payment creation alongside existing routes."""
from pathlib import Path
p=Path("app.py")
s=p.read_text(encoding="utf-8")
anchor="if __name__=='__main__':"
if s.count(anchor)!=1:raise SystemExit("[build] mini checkout: app entry anchor not found")
s=s.replace(anchor,"from miniapp_direct_checkout import register_miniapp_checkout\nregister_miniapp_checkout(app, globals())\n\n"+anchor,1)
p.write_text(s,encoding="utf-8")
print("[build] direct Mini App Ozon checkout mounted",flush=True)
