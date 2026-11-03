"""Test-drive navigation is honest and never creates a bank order on GET."""
from flask import Flask
from web_test_drive import register_test_drive
from unittest.mock import patch
import os

app=Flask(__name__)
app.secret_key="test-drive-no-charges"
ns={
    "web_contact_live":lambda:os.getenv("SOVPALI_WEB_CONTACTS_LIVE","0")=="1",
    "web_premium_live":lambda:os.getenv("SOVPALI_WEB_PREMIUM_LIVE","0")=="1",
    "web_coach_live":lambda:False,
}
register_test_drive(app,ns)
client=app.test_client()
with patch.dict(os.environ,{"SOVPALI_WEB_CONTACTS_LIVE":"0",
                              "SOVPALI_WEB_PREMIUM_LIVE":"0",
                              "OZON_PAY_MODE":"disabled"},clear=False):
    page=client.get("/test-drive")
    assert page.status_code==200
    body=page.get_data(as_text=True)
    assert "Аккаунт А" in body and "Аккаунт Б" in body
    assert "/coach/demo" in body and "/s/m/demo" in body
    assert "настоящие 100 ₽" in body
    assert "Списание 0" not in body
    assert not client.get("/test-drive/status").json["contacts_open"]
with patch.dict(os.environ,{"SOVPALI_WEB_CONTACTS_LIVE":"1"},clear=False):
    assert client.get("/test-drive/status").json["contacts_open"]
assert "/billing/create" not in app.view_functions
print("[test] test-drive guide, free dialogue demo and feature states PASS",flush=True)
