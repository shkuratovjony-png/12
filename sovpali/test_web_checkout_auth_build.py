"""Check frictionless bot-signed checkout URL (no Telegram OTP).

Offline tests, no real people, bank charges or Telegram API access.
"""
import sqlite3
import tempfile
from contextlib import contextmanager
from unittest.mock import patch
from flask import Flask
from pair_web import _ser
from web_contact_checkout import register_contact_product
from web_checkout_auth import register_web_checkout_auth

with tempfile.TemporaryDirectory() as directory:
    db_path = directory + "/auth.sqlite"

    @contextmanager
    def db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    app = Flask(__name__)
    app.secret_key = "sign-browser-session"
    profiles = {
        1: {"user_id": 1, "name": "Мужчина", "city": "Владивосток"},
        2: {"user_id": 2, "name": "Женщина", "city": "Москва"}
    }
    ns = {
        "db": db,
        "FLASK_SECRET": "bot-signature-secret",
        "profile": lambda user_id: profiles.get(user_id),
        "user": lambda user_id: {"is_banned": 0, "tg_id": 1000 + user_id},
        "eligible": lambda a, b: True,
        "web_checkout_ready": lambda: True,
        "cr_between": lambda buyer, target: None
    }
    register_contact_product(app, ns)
    register_web_checkout_auth(app, ns)

    @app.get("/__probe")
    def probe():
        return {
            "owner1": ns["web_owner_verified"](1),
            "owner2": ns["web_owner_verified"](2)
        }

    client = app.test_client()
    token1 = _ser(ns["FLASK_SECRET"]).dumps({"v": 1, "c": 2})
    token2 = _ser(ns["FLASK_SECRET"]).dumps({"v": 2, "c": 1})

    assert client.get("/__probe").json == {"owner1": False, "owner2": False}
    assert client.get("/billing/contact/invalid-token").status_code == 404

    with patch.dict("os.environ", {"SOVPALI_WEB_CONTACTS_LIVE": "1"}):
        page = client.get("/billing/contact/" + token1)
        markup = page.get_data(as_text=True)
        assert page.status_code == 200, page.status_code
        assert "Женщина" in markup and "100 ₽" in markup
        assert "Оплатить 100 ₽" in markup
        assert "Код из Telegram" not in markup
        assert "Подтвердить через Telegram" not in markup
        assert "/billing/auth/" not in markup
        assert client.get("/__probe").json == {"owner1": True, "owner2": False}
        with client.session_transaction() as sess:
            assert sess["billing_signed_viewer"] == 1
            assert sess["billing_signed_pair"]
            assert sess["billing_signed_until"]
            assert sess["billing_csrf"] and sess["billing_nonce"]
            assert "billing_authenticated_uid" not in sess
            assert "web_auth_last_sent" not in sess

        # A different signed token cannot inherit the first token's session.
        with client.session_transaction() as sess:
            sess["billing_pair_token"] = token2
        assert client.get("/__probe").json == {"owner1": False, "owner2": False}

        # A valid second personal link can establish its own browser identity.
        second = client.get("/billing/contact/" + token2)
        assert second.status_code == 200
        assert client.get("/__probe").json == {"owner1": False, "owner2": True}

        # A forged signature is rejected regardless of the browser session.
        forged = _ser("incorrect-bot-secret").dumps({"v": 2, "c": 1})
        assert client.get("/billing/contact/" + forged).status_code == 404

    # No legacy OTP handlers should be registered at all.
    routes = {rule.rule for rule in app.url_map.iter_rules()}
    assert not any(route.startswith("/billing/auth/") for route in routes)

print("[test] signed checkout: direct 100-RUB page, no OTP, scoped browser owner, forged and swapped links blocked PASS", flush=True)
