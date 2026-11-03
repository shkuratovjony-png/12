"""Security contract for Ozon checkout preview.

No credit-card fields, bank secrets, checkout POST or charge endpoint can be
opened before a real acquiring integration is configured and independently
tested. Demo works with an offline Flask test client.
"""
import os
from flask import Flask
from unittest.mock import patch
from ozon_billing_preview import _bank_checkout_url
from ozon_billing_preview import register_ozon_billing_preview

app=Flask(__name__)
register_ozon_billing_preview(app,{})
c=app.test_client()
r=c.get("/billing/demo")
assert r.status_code==200,r.status_code
html=r.get_data(as_text=True)
for text in ("совпали","СБП","Картой","data-pay-method=\"sbp\"",
             "data-pay-method=\"card\"","ПЕРЕЙТИ К ОПЛАТЕ ЧЕРЕЗ СБП",
             "ПЕРЕЙТИ К ОПЛАТЕ КАРТОЙ",
             "900 ₽","100 ₽","1 200 ₽","ТЕСТ ЭКВАЙРИНГА · 100 ₽"):
    assert text in html,text
for s in ('name="card"', 'name="card_number"', 'autocomplete="cc-number"',
          'autocomplete="cc-exp"', 'autocomplete="cc-csc"',
          'type="password"', 'payment_intent', 'checkoutSession', 'window.location="http'):
    assert s not in html,"A forbidden live/credit card control is present: "+s
assert 'disabled aria-disabled="true"' in html
assert c.post("/billing/demo").status_code==405
assert "no-store" in r.headers["Cache-Control"]
assert r.headers["X-Robots-Tag"].startswith("noindex")
for route,needle in (("/billing/return/success","Проверяем оплату"),("/billing/return/fail","Оплата не завершена")):
    result=c.get(route)
    assert result.status_code==200,route
    content=result.get_data(as_text=True)
    assert needle in content
    assert "не подтверждение оплаты" in content
    assert "без" not in result.headers.get("Location","")
    assert c.post(route).status_code==405
    assert "no-store" in result.headers["Cache-Control"]
assert not any("/billing/return/success" in str(rule) and "POST" in rule.methods for rule in app.url_map.iter_rules())
assert "payment-method" in html and "chooseMethod(method)" in html
assert "Реквизиты карты здесь не вводятся" in html
assert html.count('aria-pressed="true"')>=2
assert html.count('aria-pressed="false"')>=3
# The real-payment link must be operator-provided, exact HTTPS and hosted
# only under an Ozon-controlled domain. No free-form redirect query params.
assert c.get("/billing/test-payment/100").status_code==503
assert c.post("/billing/test-payment/100").status_code==405
with patch.dict(os.environ, {"OZON_PAY_TEST_100_URL":"https://pay.ozon.ru/pay/example-100"}):
    assert _bank_checkout_url()=="https://pay.ozon.ru/pay/example-100"
    ready=c.get("/billing/demo")
    ready_html=ready.get_data(as_text=True)
    assert '<button class="cta" id="pay-button" type="button" >' in ready_html
    assert 'var bankReady=true;' in ready_html
    direct=c.get("/billing/test-payment/100")
    assert direct.status_code==303
    assert direct.headers["Location"]=="https://pay.ozon.ru/pay/example-100"
    assert direct.headers["Referrer-Policy"]=="no-referrer"
    assert "no-store" in direct.headers["Cache-Control"]
for invalid in (
  "http://pay.ozon.ru/pay/unsafe",
  "https://ozon.ru.evil.example/pay/100",
  "https://evil.example/pay/100",
  "https://pay.ozon.ru/",
  "https://user:password@pay.ozon.ru/pay/100",
  "https://pay.ozon.ru:444/pay/100",
  "javascript:alert(1)",
):
    with patch.dict(os.environ,{"OZON_PAY_TEST_100_URL":invalid}):
        assert _bank_checkout_url() is None, invalid
        assert c.get("/billing/test-payment/100").status_code==503

print("[test] Ozon bank-link checkout: only 100 RUB, Ozon HTTPS redirect, no secrets or auto-unlock PASS",flush=True)
