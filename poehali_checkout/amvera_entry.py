"""Private Amvera preview. Activation requires an explicit deployment change."""
import os
from preview_gate import StandbyGate
mode = os.environ.setdefault("POEHALI_RUNTIME_MODE", "standby")
if mode not in ("standby", "active"):
    raise RuntimeError("Invalid POEHALI_RUNTIME_MODE")
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("Amvera PostgreSQL is required")
if mode == "standby":
    gate = StandbyGate(None, os.getenv("STANDBY_USERNAME", "preview"), os.getenv("STANDBY_PASSWORD", ""))
    os.environ.update(OZON_PAY_MODE="disabled", POEHALI_SELLING_ENABLED="0", POEHALI_SMTP_ENABLED="0")
    for key in list(os.environ):
        if key.startswith("POEHALI_") and any(x in key for x in ("PROBE", "DIAG_RUN", "RECOVERY_RUN")):
            os.environ.pop(key, None)
from app import app, conn, DB_OK
if not DB_OK:
    raise RuntimeError("Database initialization failed")
if mode == "standby":
    def health():
        from contextlib import closing
        with closing(conn()) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        return {"ok": True, "database": True, "mode": "standby", "bot": False, "payments": False}
    app.view_functions["health"] = health
    gate.application = app.wsgi_app
    app.wsgi_app = gate
