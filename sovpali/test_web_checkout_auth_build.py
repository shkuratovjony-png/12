"""Offline 6-digit Telegram OTP gate: no bank or Telegram API calls."""
import asyncio
import os
import re
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask
from pair_web import _ser
from web_contact_checkout import register_contact_product
from web_checkout_auth import register_web_checkout_auth

with tempfile.TemporaryDirectory() as t:
    path=t+"/auth.sqlite"
    @contextmanager
    def db():
        c=sqlite3.connect(path)
        c.row_factory=sqlite3.Row
        try:
            yield c;c.commit()
        except Exception:
            c.rollback();raise
        finally:c.close()
    loop=asyncio.new_event_loop()
    thread=threading.Thread(target=lambda:(asyncio.set_event_loop(loop),loop.run_forever()),daemon=True)
    thread.start()
    ready=threading.Event();ready.set()
    delivered=[]
    class FakeBot:
        async def send_message(self,tid,msg,parse_mode="HTML"):
            delivered.append((tid,msg))
    app=Flask(__name__);app.secret_key="test-cookie-secret"
    profiles={1:{"user_id":1,"name":"Покупатель","city":"Москва"},2:{"user_id":2,"name":"Кандидат","city":"Москва"}}
    ns={"db":db,"FLASK_SECRET":"auth-test-secret",
        "profile":lambda uid:profiles.get(uid),"user":lambda uid:{"tg_id":1000+uid,"is_banned":0},
        "eligible":lambda a,b:True,"web_checkout_ready":lambda:True,
        "cr_between":lambda a,b:None,
        "ready":ready,"loop":loop,"bot":SimpleNamespace(bot=FakeBot())}
    register_contact_product(app,ns)
    register_web_checkout_auth(app,ns)
    client=app.test_client()
    token=_ser("auth-test-secret").dumps({"v":1,"c":2})
    with patch.dict(os.environ,{"SOVPALI_WEB_CONTACTS_LIVE":"1"}):
        res=client.get("/billing/contact/"+token)
        assert res.status_code==200 and "Подтвердить через Telegram" in res.get_data(as_text=True) and "100 ₽" in res.get_data(as_text=True)
        with client.session_transaction() as sess: csrf=sess["billing_csrf"]
        assert client.post("/billing/auth/start/"+token,data={"csrf":"bad"}).status_code==403
        res=client.post("/billing/auth/start/"+token,data={"csrf":csrf})
        assert res.status_code==303,res.status_code
        assert len(delivered)==1
        assert delivered[0][0]==1001
        otp_page=client.get("/billing/contact/"+token)
        assert otp_page.status_code==200
        assert "Код из Telegram" in otp_page.get_data(as_text=True)
        assert "Первый шаг" in otp_page.get_data(as_text=True)
        match=re.search(r"\b\d{6}\b",delivered[0][1])
        assert match
        code=match.group(0)
        assert client.post("/billing/auth/verify/"+token,data={"csrf":csrf,"code":"111111" if code!="111111" else "222222"}).status_code==403
        assert client.post("/billing/auth/verify/"+token,data={"csrf":csrf,"code":code}).status_code==303
        page=client.get("/billing/contact/"+token)
        assert page.status_code==200
        assert "Оплатить 100 ₽" in page.get_data(as_text=True)
        with client.session_transaction() as sess:
            assert sess["billing_authenticated_uid"]==1
            assert sess["billing_auth_until"]
    loop.call_soon_threadsafe(loop.stop);thread.join(1);loop.close()
print("[test] checkout OTP: wrong code and CSRF blocked; verified Telegram owner may access payment PASS",flush=True)
