"""Offline checkout security/contract tests: no bank charges or secrets required."""
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import urlsplit

from flask import Flask
from ozon_web_checkout import _html, _hosted, _sign, PRODUCTS, register_ozon_web_checkout

assert PRODUCTS["test100"]["price"] == 100
assert not PRODUCTS["coach"]["sellable"]
assert not PRODUCTS["premium"]["sellable"]
assert _hosted("https://checkout.ozon.ru/pay/test")
assert _hosted("https://qr.nspk.ru/1234")
assert not _hosted("https://checkout.ozon.ru.evil.example/test")
assert not _hosted("https://evil.example/test")

with tempfile.TemporaryDirectory() as tempdir:
    dbpath = tempdir + "/billing.db"
    @contextmanager
    def db():
        c = sqlite3.connect(dbpath)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    app = Flask(__name__)
    app.secret_key = "offline-test-secret"
    register_ozon_web_checkout(app, {"db": db})
    client = app.test_client()

    with patch.dict(os.environ, {"OZON_PAY_MODE": "disabled"}, clear=False):
        response = client.get("/billing/pay")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "100 ₽" in html and "900 ₽" in html and "1 200 ₽" in html
        assert "disabled" in html
        with client.session_transaction() as sess:
            csrf = sess["billing_csrf"]
        assert client.post("/billing/create", data={"csrf": csrf, "sku": "test100", "method": "card"}).status_code == 503

    e = {
        "OZON_PAY_MODE": "live",
        "OZON_PAY_API_URL": "https://payapi.ozon.ru",
        "OZON_PAY_ACCESS_KEY": "fake-test-id",
        "OZON_PAY_SECRET_KEY": "fake-test-secret",
        "WEBHOOK_BASE_URL": "https://one2-1o22.onrender.com",
        "OZON_PAY_NOTIFICATION_SECRET_KEY": "fake-test-notify",
    }
    calls = []
    class Response:
        def __init__(self, value):
            self.value = value
        def raise_for_status(self): pass
        def json(self): return self.value

    def post(url, json, timeout, headers=None):
        calls.append((url, json))
        if url.endswith("/v1/createPayment"):
            assert json["accessKey"] == e["OZON_PAY_ACCESS_KEY"]
            assert json["requestSign"] == _sign(json["extId"])
            assert json["amount"] == {"currencyCode": "643", "value": "10000"}
            assert json["redirectUrl"].startswith("https://one2-1o22.onrender.com/")
            return Response({"paymentDetails": {"paymentId": "fake-provider-id"},
                             "order": {"item": {"payLink": "https://checkout.ozon.ru/pay/123"}}})
        if url.endswith("/v1/getPaymentDetails"):
            assert json["requestSign"] == _sign(json.get("id") or json.get("extId"))
            return Response({"items": [{"status": "PAYMENT_COMPLETED",
                                        "amount": {"value": "10000", "currencyCode": "643"}}]})
        raise AssertionError("unexpected bank call")

    with patch.dict(os.environ, e), patch("ozon_web_checkout.requests.post", side_effect=post):
        response = client.get("/billing/pay")
        assert response.status_code == 200
        with client.session_transaction() as sess:
            csrf = sess["billing_csrf"]
        assert client.post("/billing/create", data={"csrf": "wrong", "sku": "test100", "method": "card"}).status_code == 403
        assert client.post("/billing/create", data={"csrf": csrf, "sku": "premium", "method": "card"}).status_code == 400
        r = client.post("/billing/create", data={"csrf": csrf, "sku": "test100", "method": "card"})
        assert r.status_code == 303, (r.status_code, r.get_data(as_text=True)[:300])
        assert r.headers["Location"] == "https://checkout.ozon.ru/pay/123"
        assert len([x for x in calls if x[0].endswith("/v1/createPayment")]) == 1
        repeat = client.post("/billing/create", data={"csrf": csrf, "sku": "test100", "method": "card"})
        assert repeat.status_code == 303
        assert len([x for x in calls if x[0].endswith("/v1/createPayment")]) == 1
        with db() as c:
            record = c.execute("SELECT * FROM billing_web_orders").fetchone()
        assert record["status"] == "pending"
        paid = client.get("/billing/status/" + record["order_id"])
        assert paid.status_code == 200
        assert paid.json["status"] == "paid"
        with db() as c:
            record = c.execute("SELECT * FROM billing_web_orders").fetchone()
            assert record["paid_at"]
        assert client.post("/billing/ozon/notify", json={"requestSign": "invalid"}).status_code == 403
        assert client.get("/billing/status/" + ("0" * 32)).status_code == 404

print("[test] Ozon live checkout contract: amount, signatures, CSRF, idempotency, verified status PASS", flush=True)
