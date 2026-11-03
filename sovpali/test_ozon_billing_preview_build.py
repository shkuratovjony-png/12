"""Security contract for Ozon checkout preview.

No credit-card fields, bank secrets, checkout POST or charge endpoint can be
opened before a real acquiring integration is configured and independently
tested. Demo works with an offline Flask test client.
"""
from flask import Flask
from ozon_billing_preview import register_ozon_billing_preview

app=Flask(__name__)
register_ozon_billing_preview(app,{})
c=app.test_client()
r=c.get("/billing/demo")
assert r.status_code==200,r.status_code
html=r.get_data(as_text=True)
for text in ("совпали","СБП","Картой","data-pay-method=\"sbp\"",
             "data-pay-method=\"card\"","ОПЛАТИТЬ ЧЕРЕЗ СБП",
             "ОПЛАТИТЬ БАНКОВСКОЙ КАРТОЙ",
             "900 ₽","100 ₽","1 200 ₽","ДЕМО · БЕЗ СПИСАНИЙ"):
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
print("[test] Ozon Pay card+SBP bank-hosted selection, no collection, no charges, safe returns PASS",flush=True)
