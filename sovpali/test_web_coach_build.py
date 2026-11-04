"""Offline paid coaching security/fulfillment contract tests.

Uses fake API, never Ozon/OpenAI network or actual charge.
"""
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from unittest.mock import patch
from flask import Flask
from itsdangerous import URLSafeTimedSerializer
from web_product_access import ensure_schema,bind_order
from web_coach_checkout import register_web_coach

with tempfile.TemporaryDirectory() as temp:
    path=temp+"/coach.sqlite"
    @contextmanager
    def db():
        c=sqlite3.connect(path)
        c.row_factory=sqlite3.Row
        try:
            yield c;c.commit()
        except Exception:
            c.rollback();raise
        finally:c.close()
    with db() as c:
        c.execute("""CREATE TABLE billing_web_orders(
        order_id TEXT PRIMARY KEY,product_key TEXT,amount_kopecks INTEGER,
        currency_code TEXT,status TEXT,created_at TEXT)""")
    ensure_schema(db)
    app=Flask(__name__)
    app.secret_key="secret-coach-cookie"
    profiles={1:{"name":"Владелец","goal":"Серьёзные отношения","priority":"Семья"},
              2:{"name":"Получатель","goal":"Серьёзные отношения","priority":"Семья"}}
    ns={"db":db,"FLASK_SECRET":"secret-for-pair",
        "profile":lambda uid: profiles.get(uid),
        "user":lambda uid:{"is_banned":0,"tg_id":1000+uid},
        "one":lambda query,params:{"value":1},
        "web_owner_verified":lambda uid:uid==1,
        "web_owner_claim":lambda uid:uid==1,
        "web_checkout_ready":lambda:True}
    register_web_coach(app,ns)
    client=app.test_client()
    token=URLSafeTimedSerializer("secret-for-pair",salt="sovpali-coach-v1").dumps({"v":1,"c":2})
    with patch.dict(os.environ,{"SOVPALI_WEB_COACH_LIVE":"0","OPENAI_API_KEY":""}):
        checkout=client.get("/billing/coach/"+token)
        assert checkout.status_code==200
        assert "<button disabled>" in checkout.get_data(as_text=True)
        assert client.post("/coach/api/ai/"+token,json={"consent":True,"reply":"Привет"}).status_code==503
    env={"SOVPALI_WEB_COACH_LIVE":"1","OPENAI_API_KEY":"fake-offline-test",
         "OZON_PAY_MODE":"live"}
    class MockResponse:
        def raise_for_status(self):pass
        def json(self):
            return {"status":"completed","output":[{
              "type":"message","content":[{"type":"output_text",
              "text":"Собеседник ответил кратко и дружелюбно. Спокойно спроси о её увлечениях. Вариант первый: рад, что ответила! Вариант второй: расскажи, что тебя радует. Если просьба прекратить общение — остановись."}]}]}
    requests_made=[]
    def fake_post(url,headers,json,timeout):
        requests_made.append((url,json))
        assert url=="https://api.openai.com/v1/responses"
        assert json["store"] is False
        assert "OPENAI_API_KEY" not in str(json)
        return MockResponse()
    with patch.dict(os.environ,env),patch("web_coach_checkout.requests.post",side_effect=fake_post):
        page=client.get("/billing/coach/"+token)
        assert page.status_code==200
        assert "<button >Оплатить 900 ₽</button>" in page.get_data(as_text=True)
        with client.session_transaction() as sess:csrf=sess["billing_csrf"]
        no_bank=client.post("/coach/api/ai/"+token,json={
            "csrf":csrf,"consent":True,"reply":"Спасибо за твой ответ!"})
        assert no_bank.status_code==402
        bind_order(db,"coach-one",1,"coach",target_id=2)
        with db() as c:
            c.execute("INSERT INTO billing_web_orders VALUES('coach-one','coach',90000,'643','paid','now')")
        assert ns["web_coach_unspent"](1,2)
        wrong=client.post("/coach/api/ai/"+token,json={
            "csrf":"wrong","consent":True,"reply":"Спасибо!"})
        assert wrong.status_code==403
        no_consent=client.post("/coach/api/ai/"+token,json={"csrf":csrf,"reply":"Спасибо!"})
        assert no_consent.status_code==400
        result=client.post("/coach/api/ai/"+token,json={
            "csrf":csrf,"consent":True,"reply":"Спасибо! Люблю путешествия и кино."})
        assert result.status_code==200,(result.status_code,result.get_data(as_text=True))
        assert result.json["ok"] and len(result.json["report"])>40
        assert len(requests_made)==1
        assert not ns["web_coach_unspent"](1,2)
        with db() as c:
            stored=c.execute("SELECT encrypted_report FROM web_coach_reports").fetchone()["encrypted_report"]
            assert "Собеседник ответил" not in stored
            assert c.execute("SELECT COUNT(*) AS n FROM web_product_grants WHERE sku='coach'").fetchone()["n"]==1
        report=client.get("/coach/api/report/"+token)
        assert report.status_code==200
        assert report.json["report"]==result.json["report"]
        retry=client.post("/coach/api/ai/"+token,json={
            "csrf":csrf,"consent":True,"reply":"Другое сообщение"})
        assert retry.status_code==402
        assert len(requests_made)==1
print("[test] coach: 900 RUB bank grant, explicit consent, AI call once, encrypted report, no double delivery PASS",flush=True)
