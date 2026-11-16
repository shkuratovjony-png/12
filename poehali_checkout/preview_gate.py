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
        if request.path.startswith(("/funnel/", "/internal/")) or request.path == "/ozon/notify":
            return Response("Standby: integration inactive", status=503)(environ, start_response)
        auth = request.authorization
        if not (auth and auth.type == "basic"
                and hmac.compare_digest((auth.username or "").encode(), self.username.encode())
                and hmac.compare_digest((auth.password or "").encode(), self.password.encode())):
            return Response("Private deployment preview", status=401,
                            headers={"WWW-Authenticate": 'Basic realm="Poehali preview"'})(environ, start_response)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            return Response("Standby: writes disabled", status=503)(environ, start_response)
        return self.application(environ, start_response)

