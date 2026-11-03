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
for text in ("совпали","СБП","ОПЛАТИТЬ ЧЕРЕЗ СБП",
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
print("[test] Ozon Pay checkout preview: SBP only, no cards, no charges, mobile PASS",flush=True)
