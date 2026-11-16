"""Offline checks: standby must not contact Telegram/Ozon or start workers."""
import base64
import importlib
import os
import tempfile
import unittest
from unittest.mock import patch

from werkzeug.test import Client
from werkzeug.wrappers import Response
from amvera_runner import StandbyGate


class StandbyTests(unittest.TestCase):
    def test_gateway_rejects_actions_before_application(self):
        calls = []

        def downstream(environ, start_response):
            calls.append(environ["PATH_INFO"])
            return Response("ok")(environ, start_response)

        password = "offline-test-password-32-characters"
        client = Client(StandbyGate(downstream, "preview", password), Response)
        headers = {"Authorization": "Basic " + base64.b64encode(
            ("preview:" + password).encode()).decode()}
        self.assertEqual(client.get("/health").status_code, 200)
        self.assertEqual(client.get("/s/app").status_code, 401)
        self.assertEqual(client.get("/s/app", headers=headers).status_code, 200)
        for path in ("/telegram/webhook", "/billing/ozon/notify", "/billing/create",
                     "/internal/project-admin/send", "/api/miniapp/profile"):
            self.assertEqual(client.post(path, headers=headers).status_code, 503)
        self.assertEqual(calls, ["/health", "/s/app"])

    def test_weak_or_missing_preview_password_fails_closed(self):
        for password in ("", "short"):
            with self.assertRaises(RuntimeError):
                StandbyGate(None, "preview", password)

    def test_bank_transport_blocked_even_with_live_configuration(self):
        import ozon_web_checkout
        with patch.dict(os.environ, {"SOVPALI_RUNTIME_MODE": "standby", "OZON_PAY_MODE": "live"}):
            with patch("requests.post") as post:
                with self.assertRaises(RuntimeError):
                    ozon_web_checkout._post("/v1/createPayment", {})
                post.assert_not_called()

    def test_built_application_initializes_without_network_or_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"SOVPALI_RUNTIME_MODE": "standby", "OZON_PAY_MODE": "disabled",
                   "BOT_TOKEN": "0:offline-test-token", "DATABASE_URL": "",
                   "DB_PATH": directory + "/empty.db", "ADMIN_PASSWORD": "offline-only",
                   "FLASK_SECRET": "offline-only-secret", "WEBHOOK_BASE_URL": "https://preview.invalid"}
            with patch.dict(os.environ, env), patch("threading.Thread.start") as start:
                with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
                    application = importlib.import_module("app")
                    application.init_db()
                    application.xm_init_db()
                    application.lf_init_db()
                    self.assertEqual(application.one("SELECT COUNT(*) AS n FROM users")["n"], 0)
                    self.assertFalse(application.ready.is_set())
                    start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
