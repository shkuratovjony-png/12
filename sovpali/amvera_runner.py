"""Amvera entrypoint: standby unless explicitly activated after cutover approval."""
import hmac
import os
import runpy

from werkzeug.wrappers import Request, Response


class StandbyGate:
    """Protect the preview before any application hook can perform an action."""

    def __init__(self, application, username, password):
        if not username or len(password) < 24:
            raise RuntimeError("Standby requires a username and a 24+ character password")
        self.application = application
        self.username = username
        self.password = password

    def __call__(self, environ, start_response):
        request = Request(environ)
        if request.path == "/health" and request.method in ("GET", "HEAD"):
            return self.application(environ, start_response)
        if request.path.startswith(("/telegram/", "/internal/")) or request.path == "/billing/ozon/notify":
            return Response("Standby: integration inactive", status=503)(environ, start_response)
        auth = request.authorization
        if not (auth and auth.type == "basic"
                and hmac.compare_digest((auth.username or "").encode(), self.username.encode())
                and hmac.compare_digest((auth.password or "").encode(), self.password.encode())):
            return Response("Private deployment preview", status=401,
                            headers={"WWW-Authenticate": 'Basic realm="Sovpali preview"'})(environ, start_response)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            return Response("Standby: writes disabled", status=503)(environ, start_response)
        return self.application(environ, start_response)


def main():
    mode = os.environ.setdefault("SOVPALI_RUNTIME_MODE", "standby")
    if mode not in ("active", "standby"):
        raise RuntimeError("Invalid SOVPALI_RUNTIME_MODE")
    if not os.getenv("DATABASE_URL", "").strip():
        raise RuntimeError("Amvera requires its own PostgreSQL DATABASE_URL")
    if mode == "active":
        runpy.run_path("setup_runner.py", run_name="__main__")
        return

    # Validate protection before importing modules that initialize database tables.
    gate = StandbyGate(None, os.getenv("STANDBY_USERNAME", "preview"),
                       os.getenv("STANDBY_PASSWORD", ""))
    os.environ["OZON_PAY_MODE"] = "disabled"
    os.environ["SOVPALI_FISCAL_RECEIPTS_ENABLED"] = "0"
    # Keep stored credentials intact, but never construct a production Telegram
    # client in standby. Authenticated Mini App testing belongs to cutover testing.
    os.environ["BOT_TOKEN"] = "0:standby-placeholder-not-a-real-token"
    import app as application
    application.init_db()
    application.xm_init_db()
    application.lf_init_db()

    def health():
        with application.db() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"ok": True, "database": True, "mode": "standby",
                "bot": False, "payments": False}

    application.app.view_functions["health"] = health
    gate.application = application.app.wsgi_app
    application.app.wsgi_app = gate
    from waitress import serve
    serve(application.app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")), threads=8)


if __name__ == "__main__":
    main()
