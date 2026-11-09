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
assert not PRODUCTS["test100"]["sellable"]
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
        assert "100 ₽" in html and "1 200 ₽" in html and "900 ₽" not in html and "500 ₽" not in html
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
        # Only the unit test simulates an already verified receipt system.
        # Production keeps this unset until real fiscal automation exists.
        "SOVPALI_FISCAL_RECEIPTS_ENABLED": "1",
        "SOVPALI_ENABLE_PAYMENT_TESTS": "1",
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
            # Fiscalization must be requested for a real card checkout.
            assert json["order"]["enableFiscalization"] is True
            assert json["redirectUrl"].startswith("https://one2-1o22.onrender.com/")
            return Response({"paymentDetails": {"paymentId": "fake-provider-id"},
                             "order": {"item": {"payLink": "https://checkout.ozon.ru/pay/123"}}})
        if url.endswith("/v1/getPaymentDetails"):
            assert json["requestSign"] == _sign(json.get("id") or json.get("extId"))
            return Response({"items": [{"status": "PAYMENT_COMPLETED",
                                        "amount": {"value": "10000", "currencyCode": "643"}}]})
        raise AssertionError("unexpected bank call")

    # Even with valid acquiring credentials, new sales MUST be blocked if
    # fiscal receipts aren't configured. Bank reconciliation stays available.
    no_receipts = dict(e)
    no_receipts["SOVPALI_FISCAL_RECEIPTS_ENABLED"] = "0"
    with patch.dict(os.environ, no_receipts):
        blocked = client.get("/billing/pay")
        assert blocked.status_code == 200
        assert "disabled" in blocked.get_data(as_text=True)
        with client.session_transaction() as sess:
            csrf = sess["billing_csrf"]
        assert client.post("/billing/create", data={
            "csrf": csrf, "sku": "test100", "method": "card"
        }).status_code == 503

    with patch.dict(os.environ, e), patch("ozon_web_checkout.requests.post", side_effect=post):
        response = client.get("/billing/pay")
        assert response.status_code == 200
        with client.session_transaction() as sess:
            csrf = sess["billing_csrf"]
        assert client.post("/billing/create", data={"csrf": "wrong", "sku": "test100", "method": "card"}).status_code == 403
        assert client.post("/billing/create", data={"csrf": csrf, "sku": "test100", "method": "card"}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.post("/billing/create", data={"csrf": csrf, "sku": "premium", "method": "card"}).status_code == 403
        # Reverse proxy serves HTTPS to browser but may use internal HTTP to Flask.
        r = client.post("/billing/create", data={"csrf": csrf, "sku": "test100", "method": "card"},
                        headers={"Origin": "https://one2-1o22.onrender.com"})
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

    # Regression: the direct Mini App uses a fiscalized createOrder instead
    # of the rejected createPayment/card method. No real Ozon API is called.
    import hashlib
    from ozon_web_checkout import _create_fiscal, _verify
    fiscal_oid="a"*32
    fiscal_amount=10000
    fiscal_url="https://checkout.ozon.ru/pay/fiscal-order"
    fiscal_ext="sovpali-order-"+fiscal_oid
    bank_state={"status":"STATUS_PAYMENT_PENDING","amount":{"currencyCode":"643","value":"10000"},"id":"bank-fiscal-123","extId":fiscal_ext}
    seen_fiscal=[]
    def fiscal_post(path,payload):
        seen_fiscal.append((path,payload))
        if path=="/v1/createOrder":
            assert payload["amount"]=={"currencyCode":"643","value":"10000"}
            assert payload["enableFiscalization"] is True
            assert payload["receiptEmail"]=="fiscal@example.ru"
            assert payload["extId"]==fiscal_ext
            assert payload["items"][0]["quantity"]==1
            assert payload["items"][0]["type"]=="TYPE_SERVICE"
            assert payload["items"][0]["price"]==payload["amount"]
            assert payload["mode"]=="MODE_FULL"
            expected_return="https://one2-1o22.onrender.com/billing/return?order="+fiscal_oid+"&mini=1"
            assert payload["successUrl"]==expected_return
            assert payload["failUrl"]==expected_return
            access=e["OZON_PAY_ACCESS_KEY"]
            secret=e["OZON_PAY_SECRET_KEY"]
            signed=(access+payload["expiresAt"]+payload["extId"]+
                    "FISCAL_TYPE_SINGLE"+"PAY_ALGO_SMS"+"643"+"10000"+secret)
            assert payload["requestSign"]==hashlib.sha256(signed.encode()).hexdigest()
            return {"order":{"id":"bank-fiscal-123","payLink":fiscal_url}}
        if path=="/v1/getOrderDetails":
            assert payload=={"accessKey":e["OZON_PAY_ACCESS_KEY"],"extId":fiscal_ext}
            return {"item":dict(bank_state)}
        raise AssertionError("Unexpected fiscal bank API path: "+path)
    with patch.dict(os.environ,{**e,"SOVPALI_BOT_USERNAME":"SovpaliTestBot"}), patch("ozon_web_checkout._post",side_effect=fiscal_post):
        bank_link, bank_id, ext_id=_create_fiscal(
            fiscal_oid,"contact",fiscal_amount,"https://one2-1o22.onrender.com","fiscal@example.ru")
        assert (bank_link,bank_id,ext_id)==(fiscal_url,"bank-fiscal-123",fiscal_ext)
        with db() as conn:
            conn.execute("""INSERT INTO billing_web_orders(
                order_id,browser_nonce,product_key,amount_kopecks,currency_code,
                method,status,checkout_url,provider_payment_id,provider_order_ext_id,
                created_at,updated_at)
                VALUES (?,?,?,?,?,'fiscal','pending',?,?,?,? ,?)""",
                (fiscal_oid,"fiscal-test","contact",fiscal_amount,"643",fiscal_url,
                 bank_id,ext_id,"2026-11-09T01:00:00+00:00","2026-11-09T01:00:00+00:00"))
            row=conn.execute("SELECT * FROM billing_web_orders WHERE order_id=?",(fiscal_oid,)).fetchone()
        # Navigation must not itself mark an order paid or require another
        # merchant results page; only a Telegram-authenticated app can verify.
        direct=client.get("/billing/return?order="+fiscal_oid+"&mini=1")
        assert direct.status_code==303,direct.get_data(as_text=True)[:200]
        assert direct.headers["Location"]=="https://t.me/SovpaliTestBot?startapp=payment_"+fiscal_oid
        assert "Проверяем платёж" not in direct.get_data(as_text=True)
        assert _verify(row,db)=="pending"
        bank_state["status"]="STATUS_PAID"
        bank_state["amount"]={"currencyCode":"643","value":"120000"}
        assert _verify(row,db)=="mismatch","Incorrect bank amount must not unlock"
        bank_state["amount"]={"currencyCode":"643","value":"10000"}
        bank_state["id"]="another-bank-id"
        assert _verify(row,db)=="checking","Mismatched provider order must not unlock"
        bank_state["id"]="bank-fiscal-123"
        assert _verify(row,db)=="paid"
        with db() as conn:
            assert conn.execute("SELECT status FROM billing_web_orders WHERE order_id=?",
                                (fiscal_oid,)).fetchone()["status"]=="paid"
    assert [x[0] for x in seen_fiscal].count("/v1/createOrder")==1

print("[test] Ozon live checkout contract: amount, signatures, CSRF, idempotency, verified status PASS", flush=True)
